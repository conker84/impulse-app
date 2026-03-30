import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import Plot from "react-plotly.js";
import type { TimeSeriesContainer, TimeSeriesSignal, TimeSeriesPoint } from "../types";
import {
  listCatalogs,
  listSchemas,
  fetchTimeSeriesContainers,
  fetchTimeSeriesSignals,
  fetchTimeSeriesData,
} from "../api";
import { PALETTE, BASE_CONFIG, mergeLayout } from "../plotlyTheme";

interface Props {
  onBack: () => void;
  initialCatalog?: string;
  initialSchema?: string;
  settingsButton?: React.ReactNode;
}

interface TraceData {
  channelId: number;
  channelName: string;
  unit: string;
  points: TimeSeriesPoint[];
  totalPoints: number;
}

type ViewMode = "line" | "daily" | "hourly" | "minutely";

function toISOTimestamps(points: TimeSeriesPoint[], baseMs: number): string[] {
  return points.map((p) => new Date(baseMs + p.t * 1000).toISOString());
}

function bucketBoxPlots(
  points: TimeSeriesPoint[],
  baseMs: number,
  mode: "daily" | "hourly" | "minutely",
): { x: string[]; low: number[]; q1: number[]; median: number[]; q3: number[]; high: number[] } {
  const buckets = new Map<string, number[]>();

  for (const p of points) {
    const d = new Date(baseMs + p.t * 1000);
    let key: string;
    if (mode === "daily") {
      key = d.toISOString().slice(0, 10); // YYYY-MM-DD
    } else if (mode === "hourly") {
      key = d.toISOString().slice(0, 13) + ":00"; // YYYY-MM-DDTHH:00
    } else {
      key = d.toISOString().slice(0, 16); // YYYY-MM-DDTHH:MM
    }
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(p.v);
  }

  const x: string[] = [];
  const low: number[] = [];
  const q1: number[] = [];
  const median: number[] = [];
  const q3: number[] = [];
  const high: number[] = [];

  const sorted = Array.from(buckets.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  for (const [key, vals] of sorted) {
    if (vals.length === 0) continue;
    vals.sort((a, b) => a - b);
    const pct = (p: number) => {
      const idx = (p / 100) * (vals.length - 1);
      const lo = Math.floor(idx);
      const hi = Math.ceil(idx);
      return lo === hi ? vals[lo] : vals[lo] + (vals[hi] - vals[lo]) * (idx - lo);
    };
    x.push(key);
    low.push(vals[0]);
    q1.push(pct(25));
    median.push(pct(50));
    q3.push(pct(75));
    high.push(vals[vals.length - 1]);
  }

  return { x, low, q1, median, q3, high };
}

export default function TimeSeriesView({ onBack, initialCatalog, initialSchema, settingsButton }: Props) {
  // UC browser
  const [catalogs, setCatalogs] = useState<string[]>([]);
  const [schemas, setSchemas] = useState<string[]>([]);
  const [catalog, setCatalog] = useState(initialCatalog || "");
  const [schema, setSchema] = useState(initialSchema || "");

  // Container / signal selection
  const [containers, setContainers] = useState<TimeSeriesContainer[]>([]);
  const [selectedContainer, setSelectedContainer] = useState<number | null>(null);
  const [signals, setSignals] = useState<TimeSeriesSignal[]>([]);
  const [selectedSignals, setSelectedSignals] = useState<Set<number>>(new Set());

  // Chart data
  const [traces, setTraces] = useState<TraceData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("line");

  // Debounce zoom/pan
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resolve container start_dt for timestamp conversion
  const activeContainer = useMemo(
    () => containers.find((c) => c.container_id === selectedContainer),
    [containers, selectedContainer],
  );
  const baseMs = useMemo(
    () => (activeContainer?.start_dt ? new Date(activeContainer.start_dt).getTime() : 0),
    [activeContainer],
  );

  // Load catalogs on mount
  useEffect(() => {
    listCatalogs()
      .then((r) => setCatalogs(r.catalogs.map((c) => c.name)))
      .catch(() => {});
  }, []);

  // Load schemas when catalog changes
  useEffect(() => {
    if (!catalog) { setSchemas([]); return; }
    listSchemas(catalog)
      .then((r) => setSchemas(r.schemas.map((s) => s.name)))
      .catch(() => setSchemas([]));
  }, [catalog]);

  // Load containers when schema changes
  useEffect(() => {
    if (!catalog || !schema) { setContainers([]); return; }
    setError(null);
    fetchTimeSeriesContainers(catalog, schema)
      .then((r) => setContainers(r.containers))
      .catch((e) => {
        setContainers([]);
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("404")) setError("No ingested data found for this catalog/schema.");
        else setError(`Failed to load containers: ${msg}`);
      });
  }, [catalog, schema]);

  // Load signals when container changes
  useEffect(() => {
    if (!catalog || !schema || selectedContainer == null) { setSignals([]); return; }
    fetchTimeSeriesSignals(catalog, schema, selectedContainer)
      .then((r) => setSignals(r.signals))
      .catch(() => setSignals([]));
  }, [catalog, schema, selectedContainer]);

  const toggleSignal = (channelId: number) => {
    setSelectedSignals((prev) => {
      const next = new Set(prev);
      if (next.has(channelId)) next.delete(channelId);
      else next.add(channelId);
      return next;
    });
  };

  // Fetch data for selected signals
  const fetchDataInner = useCallback(async (xMin?: number, xMax?: number) => {
    if (!catalog || !schema || selectedContainer == null || selectedSignals.size === 0) return;
    setLoading(true);
    setError(null);

    // Convert seconds back to nanoseconds for the API
    const xMinNs = xMin != null ? Math.round(xMin * 1e9) : undefined;
    const xMaxNs = xMax != null ? Math.round(xMax * 1e9) : undefined;

    try {
      const results = await Promise.all(
        Array.from(selectedSignals).map(async (channelId) => {
          const sig = signals.find((s) => s.channel_id === channelId);
          const resp = await fetchTimeSeriesData(catalog, schema, selectedContainer!, channelId, xMinNs, xMaxNs);
          return {
            channelId,
            channelName: sig?.channel_name || `ch_${channelId}`,
            unit: sig?.unit || "",
            points: resp.data,
            totalPoints: resp.total_points,
          };
        }),
      );
      setTraces(results);
    } catch (e) {
      setError(`Failed to load data: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [catalog, schema, selectedContainer, selectedSignals, signals]);

  const handleShow = () => fetchDataInner();

  // Handle zoom/pan — debounce refetch (line chart only, box plots don't zoom-refetch)
  const handleRelayout = useCallback((event: Record<string, any>) => {
    if (viewMode !== "line") return;
    // When x-axis is type: "date", Plotly sends date strings for ranges
    const xMinRaw = event["xaxis.range[0]"];
    const xMaxRaw = event["xaxis.range[1]"];
    if (xMinRaw == null || xMaxRaw == null) return;

    // Convert date strings back to epoch seconds for the API
    const xMinSec = (new Date(xMinRaw).getTime() - baseMs) / 1000;
    const xMaxSec = (new Date(xMaxRaw).getTime() - baseMs) / 1000;
    if (isNaN(xMinSec) || isNaN(xMaxSec)) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchDataInner(xMinSec, xMaxSec);
    }, 400);
  }, [fetchDataInner, viewMode, baseMs]);

  // Build Plotly traces
  const units = new Set(traces.map((t) => t.unit).filter(Boolean));
  const unitList = Array.from(units);
  const useDualAxis = unitList.length === 2;

  const plotlyTraces = useMemo(() => {
    if (viewMode === "line") {
      return traces.map((trace, i) => {
        const yAxisIdx = useDualAxis && trace.unit === unitList[1] ? 2 : 1;
        const xDates = toISOTimestamps(trace.points, baseMs);
        return {
          x: xDates,
          y: trace.points.map((p) => p.v),
          name: `${trace.channelName}${trace.unit ? ` (${trace.unit})` : ""}`,
          type: "scattergl" as const,
          mode: "lines" as const,
          line: { color: PALETTE[i % PALETTE.length], width: 1.5 },
          yaxis: yAxisIdx === 2 ? ("y2" as const) : ("y" as const),
          hovertemplate: `<b>${trace.channelName}</b><br>%{x}<br>%{y:.4f} ${trace.unit}<extra></extra>`,
        };
      });
    }

    // Box plot mode
    const boxMode = viewMode as "daily" | "hourly" | "minutely";
    return traces.flatMap((trace, i) => {
      const yAxisIdx = useDualAxis && trace.unit === unitList[1] ? 2 : 1;
      const box = bucketBoxPlots(trace.points, baseMs, boxMode);
      const color = PALETTE[i % PALETTE.length];
      const name = `${trace.channelName}${trace.unit ? ` (${trace.unit})` : ""}`;

      // Use candlestick-like box rendering: median line + q1-q3 filled area + whiskers
      return [
        // IQR box (q1 to q3)
        {
          x: [...box.x, ...box.x.slice().reverse()],
          y: [...box.q3, ...box.q1.slice().reverse()],
          fill: "toself" as const,
          fillcolor: color + "30",
          line: { color, width: 1 },
          name,
          type: "scatter" as const,
          mode: "lines" as const,
          yaxis: yAxisIdx === 2 ? ("y2" as const) : ("y" as const),
          showlegend: true,
          hoverinfo: "skip" as const,
        },
        // Median line
        {
          x: box.x,
          y: box.median,
          type: "scatter" as const,
          mode: "lines+markers" as const,
          line: { color, width: 2 },
          marker: { size: 4, color },
          name: `${name} median`,
          yaxis: yAxisIdx === 2 ? ("y2" as const) : ("y" as const),
          showlegend: false,
          hovertemplate: `<b>${trace.channelName}</b><br>%{x}<br>median: %{y:.4f} ${trace.unit}<extra></extra>`,
        },
        // Whiskers (min-max)
        {
          x: [...box.x, ...box.x.slice().reverse()],
          y: [...box.high, ...box.low.slice().reverse()],
          fill: "toself" as const,
          fillcolor: color + "10",
          line: { color, width: 0.5, dash: "dot" as const },
          name: `${name} range`,
          type: "scatter" as const,
          mode: "lines" as const,
          yaxis: yAxisIdx === 2 ? ("y2" as const) : ("y" as const),
          showlegend: false,
          hoverinfo: "skip" as const,
        },
      ];
    });
  }, [traces, viewMode, baseMs, useDualAxis, unitList]);

  const layout = mergeLayout({
    xaxis: {
      title: "Time",
      type: "date" as const,
    },
    yaxis: { title: useDualAxis ? unitList[0] : (unitList[0] || "value") },
    ...(useDualAxis ? {
      yaxis2: {
        title: unitList[1],
        overlaying: "y" as const,
        side: "right" as const,
        gridcolor: "rgba(128,128,128,0.08)",
        tickfont: { size: 10 },
      },
    } : {}),
    showlegend: traces.length > 1,
    legend: { orientation: "h" as const, y: -0.15, font: { size: 10 } },
    margin: { t: 8, r: useDualAxis ? 56 : 16, b: 56, l: 56 },
  });

  return (
    <div className="visualize-layout">
      <div className="visualize-sidebar">
        <div className="viz-sidebar-header">
          <button className="action-btn" onClick={onBack} title="Back to Home">Home</button>
          <span className="viz-report-name">Explore Time Series</span>
          {settingsButton}
        </div>

        {/* Catalog / Schema pickers */}
        <div className="viz-section">
          <div className="viz-section-title">Data Source</div>
          <div className="viz-filter-row">
            <label className="form-label">Catalog</label>
            <select
              className="form-input"
              value={catalog}
              onChange={(e) => { setCatalog(e.target.value); setSchema(""); setContainers([]); setSelectedContainer(null); setSignals([]); setSelectedSignals(new Set()); setTraces([]); }}
            >
              <option value="">Select catalog...</option>
              {catalogs.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="viz-filter-row">
            <label className="form-label">Schema</label>
            <select
              className="form-input"
              value={schema}
              onChange={(e) => { setSchema(e.target.value); setSelectedContainer(null); setSignals([]); setSelectedSignals(new Set()); setTraces([]); }}
              disabled={!catalog}
            >
              <option value="">Select schema...</option>
              {schemas.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>

        {/* Container picker */}
        {containers.length > 0 && (
          <div className="viz-section">
            <div className="viz-section-title">Container</div>
            <div className="viz-checkbox-list" style={{ maxHeight: 180 }}>
              {containers.map((c) => (
                <label key={c.container_id} className="viz-checkbox-row">
                  <input
                    type="radio"
                    name="ts-container"
                    checked={selectedContainer === c.container_id}
                    onChange={() => { setSelectedContainer(c.container_id); setSelectedSignals(new Set()); setTraces([]); }}
                  />
                  <div className="viz-hist-info">
                    <span className="viz-checkbox-label">{c.filename}</span>
                    <span className="viz-hist-desc">
                      {c.vehicle_key && `${c.vehicle_key} · `}
                      {c.num_channels} ch
                      {c.duration_ms ? ` · ${(c.duration_ms / 1000).toFixed(0)}s` : ""}
                    </span>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Signal selector */}
        {signals.length > 0 && (
          <div className="viz-section">
            <div className="viz-section-title">
              Signals
              <span className="viz-hint" style={{ marginLeft: "auto" }}>
                {selectedSignals.size} selected
              </span>
            </div>
            <div className="viz-checkbox-list" style={{ maxHeight: 240 }}>
              {signals.map((s) => (
                <label key={s.channel_id} className="viz-checkbox-row">
                  <input
                    type="checkbox"
                    checked={selectedSignals.has(s.channel_id)}
                    onChange={() => toggleSignal(s.channel_id)}
                  />
                  <div className="viz-hist-info">
                    <span className="viz-checkbox-label">{s.channel_name}</span>
                    <span className="viz-hist-desc">
                      {s.unit && `${s.unit} · `}
                      {s.sample_count} samples
                      {s.min_value != null ? ` · ${s.min_value.toFixed(1)}–${s.max_value?.toFixed(1)}` : ""}
                    </span>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        <button
          className="action-btn primary viz-apply-btn"
          disabled={selectedSignals.size === 0 || loading}
          onClick={handleShow}
        >
          {loading ? (
            <><span className="spinner" style={{ width: 14, height: 14, marginRight: 6 }} />Loading...</>
          ) : (
            `Show ${selectedSignals.size} Signal${selectedSignals.size !== 1 ? "s" : ""}`
          )}
        </button>
      </div>

      <div className="visualize-main">
        {error && <div className="viz-error-banner">{error}</div>}

        {traces.length === 0 && !loading && (
          <div className="visualize-empty">
            <div className="visualize-empty-icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <rect x="4" y="4" width="40" height="40" rx="6" fill="var(--accent-bg)" stroke="var(--accent)" strokeWidth="1.5" />
                <polyline points="10,34 18,22 26,28 34,14 40,18" stroke="var(--accent)" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="visualize-empty-text">
              Select a catalog, schema, container, and signals, then click <strong>Show</strong>.
            </div>
          </div>
        )}

        {traces.length > 0 && (
          <div className="chart-card" style={{ flex: 1, minHeight: 500 }}>
            <div className="chart-card-header">
              <span className="chart-card-title">
                {traces.map((t) => t.channelName).join(", ")}
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto", flexShrink: 0 }}>
                {(["line", "daily", "hourly", "minutely"] as ViewMode[]).map((m) => (
                  <button
                    key={m}
                    className={`action-btn${viewMode === m ? " primary" : ""}`}
                    style={{ padding: "2px 8px", fontSize: 11 }}
                    onClick={() => setViewMode(m)}
                  >
                    {m === "line" ? "Line" : m.charAt(0).toUpperCase() + m.slice(1)}
                  </button>
                ))}
                <span className="viz-hint" style={{ marginLeft: 8 }}>
                  {traces.reduce((sum, t) => sum + t.totalPoints, 0).toLocaleString()} pts
                </span>
              </div>
            </div>
            <Plot
              data={plotlyTraces}
              layout={layout}
              config={BASE_CONFIG}
              useResizeHandler
              style={{ width: "100%", height: "100%" }}
              onRelayout={handleRelayout}
            />
          </div>
        )}
      </div>
    </div>
  );
}
