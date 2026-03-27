import { useState, useEffect, useCallback, useRef } from "react";
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
}

interface TraceData {
  channelId: number;
  channelName: string;
  unit: string;
  points: TimeSeriesPoint[];
  totalPoints: number;
}

export default function TimeSeriesView({ onBack, initialCatalog, initialSchema }: Props) {
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

  // Debounce zoom/pan
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
  const fetchData = useCallback(async (xMin?: number, xMax?: number) => {
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

  const handleShow = () => fetchData();

  // Handle zoom/pan — debounce refetch
  const handleRelayout = useCallback((event: Record<string, any>) => {
    const xMin = event["xaxis.range[0]"] as number | undefined;
    const xMax = event["xaxis.range[1]"] as number | undefined;
    if (xMin == null || xMax == null) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchData(xMin, xMax);
    }, 400);
  }, [fetchData]);

  // Build Plotly traces
  const units = new Set(traces.map((t) => t.unit).filter(Boolean));
  const unitList = Array.from(units);
  const useDualAxis = unitList.length === 2;

  const plotlyTraces = traces.map((trace, i) => {
    const yAxisIdx = useDualAxis && trace.unit === unitList[1] ? 2 : 1;
    return {
      x: trace.points.map((p) => p.t),
      y: trace.points.map((p) => p.v),
      name: `${trace.channelName}${trace.unit ? ` (${trace.unit})` : ""}`,
      type: "scattergl" as const,
      mode: "lines" as const,
      line: { color: PALETTE[i % PALETTE.length], width: 1.5 },
      yaxis: yAxisIdx === 2 ? "y2" : "y",
      hovertemplate: `<b>${trace.channelName}</b><br>t=%{x:.3f}s<br>v=%{y:.4f} ${trace.unit}<extra></extra>`,
    };
  });

  const layout = mergeLayout({
    xaxis: { title: "Time (s)" },
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
              <span className="viz-hint" style={{ flexShrink: 0, marginLeft: 8 }}>
                {traces.reduce((sum, t) => sum + t.totalPoints, 0).toLocaleString()} total pts
              </span>
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
