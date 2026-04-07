import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import Plot from "react-plotly.js";
import type {
  TimeSeriesContainer,
  TimeSeriesSignal,
  TimeSeriesLoadChannel,
  TimeSeriesResampleTrace,
} from "../types";
import {
  listCatalogs,
  listSchemas,
  fetchTimeSeriesContainers,
  fetchTimeSeriesSignals,
  loadTimeSeriesChannels,
  resampleTimeSeries,
} from "../api";
import { PALETTE, BASE_CONFIG, mergeLayout } from "../plotlyTheme";

interface Props {
  onBack: () => void;
  initialCatalog?: string;
  initialSchema?: string;
  settingsButton?: React.ReactNode;
}

/** Loaded channel metadata from /load response */
interface LoadedChannel {
  channelId: number;
  cacheKey: string;
  totalPoints: number;
  tMinNs: number;
  tMaxNs: number;
}

/** Trace data from /resample response */
interface TraceData {
  cacheKey: string;
  channelId: number;
  channelName: string;
  unit: string;
  data: { t: number; v: number; v_raw?: number }[];
  totalPoints: number;
  windowPoints: number;
}

// ---------------------------------------------------------------------------
// Axis grouping logic
// ---------------------------------------------------------------------------

type AxisSide = "left" | "right";

interface AxisAssignment {
  channelId: number;
  side: AxisSide;
}

/**
 * Group signals into y-axis assignments.
 * - 1 signal: left axis with its unit name.
 * - 2 signals, same unit: both left, single axis label.
 * - 2 signals, different units: one per axis, each labeled with its unit.
 * - 3+ signals: smart clustering by unit + value range into 2 groups.
 */
function assignAxes(
  signals: TimeSeriesSignal[],
  selectedIds: Set<number>,
): { assignments: Map<number, AxisSide>; leftLabel: string; rightLabel: string; useAxisTags: boolean } {
  const selected = signals.filter((s) => selectedIds.has(s.channel_id));
  if (selected.length === 0) return { assignments: new Map(), leftLabel: "", rightLabel: "", useAxisTags: false };

  // Group by unit
  const unitGroups = new Map<string, TimeSeriesSignal[]>();
  for (const s of selected) {
    const u = s.unit || "value";
    if (!unitGroups.has(u)) unitGroups.set(u, []);
    unitGroups.get(u)!.push(s);
  }

  const units = Array.from(unitGroups.keys());
  const assignments = new Map<number, AxisSide>();

  if (units.length <= 1) {
    // Single unit: all left, label is the unit name
    for (const s of selected) assignments.set(s.channel_id, "left");
    return { assignments, leftLabel: units[0] || "value", rightLabel: "", useAxisTags: false };
  }

  if (units.length === 2) {
    // Two units: one per axis, no [L]/[R] tags needed (axis label is clear)
    const [u1, u2] = units;
    const g1 = unitGroups.get(u1)!;
    const g2 = unitGroups.get(u2)!;
    const [leftUnit, rightUnit] = g1.length >= g2.length ? [u1, u2] : [u2, u1];
    for (const s of selected) {
      assignments.set(s.channel_id, (s.unit || "value") === leftUnit ? "left" : "right");
    }
    return { assignments, leftLabel: leftUnit, rightLabel: rightUnit, useAxisTags: false };
  }

  // 3+ units: cluster by median value range into 2 groups, show [L]/[R] tags
  const unitMedians = units.map((u) => {
    const sigs = unitGroups.get(u)!;
    const mid = sigs.reduce((sum, s) => {
      const lo = s.min_value ?? 0;
      const hi = s.max_value ?? 0;
      return sum + (lo + hi) / 2;
    }, 0) / sigs.length;
    return { unit: u, median: mid, count: sigs.length };
  });
  unitMedians.sort((a, b) => a.median - b.median);

  const splitIdx = Math.max(1, unitMedians.length - 1);
  const leftUnits = new Set(unitMedians.slice(0, splitIdx).map((u) => u.unit));
  const rightUnits = new Set(unitMedians.slice(splitIdx).map((u) => u.unit));

  for (const s of selected) {
    const u = s.unit || "value";
    assignments.set(s.channel_id, leftUnits.has(u) ? "left" : "right");
  }

  const leftLabel = Array.from(leftUnits).join(", ");
  const rightLabel = Array.from(rightUnits).join(", ");
  return { assignments, leftLabel, rightLabel, useAxisTags: true };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPointCount(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

/** Convert seconds-offset to epoch milliseconds for Plotly date axis. */
function toEpochMs(tSeconds: number, baseMs: number): number {
  return baseMs + tSeconds * 1000;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

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

  // Loaded channels (from /load)
  const [loadedChannels, setLoadedChannels] = useState<Map<number, LoadedChannel>>(new Map());
  const [loadingPhase, setLoadingPhase] = useState<string | null>(null);

  // Chart state
  const [traces, setTraces] = useState<TraceData[]>([]);
  const [normalized, setNormalized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Current zoom window (nanoseconds)
  const [windowNs, setWindowNs] = useState<{ min: number | null; max: number | null }>({ min: null, max: null });

  // Debounce zoom/pan resample calls
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Container start time for timestamp conversion
  const activeContainer = useMemo(
    () => containers.find((c) => c.container_id === selectedContainer),
    [containers, selectedContainer],
  );
  const baseMs = useMemo(
    () => (activeContainer?.start_dt ? new Date(activeContainer.start_dt).getTime() : 0),
    [activeContainer],
  );

  // Aggregate stats for the status bar
  const totalViewingPoints = useMemo(
    () => traces.reduce((sum, t) => sum + t.windowPoints, 0),
    [traces],
  );
  const totalLoadedPoints = useMemo(
    () => traces.reduce((sum, t) => sum + t.totalPoints, 0),
    [traces],
  );
  const showingPerTrace = traces.length > 0 ? traces[0].data.length : 0;

  // Detail threshold: if all traces have <10k window points, use rich hover
  const isDetailLevel = useMemo(
    () => traces.length > 0 && traces.every((t) => t.windowPoints <= 10_000),
    [traces],
  );

  // Axis assignments
  const { assignments: axisMap, leftLabel, rightLabel, useAxisTags } = useMemo(
    () => assignAxes(signals, selectedSignals),
    [signals, selectedSignals],
  );
  const hasDualAxis = rightLabel !== "";

  // ------ Data loading ------

  useEffect(() => {
    listCatalogs()
      .then((r) => {
        const names = r.catalogs.map((c) => c.name);
        // Always include synthetic test data option
        if (!names.includes("synthetic")) names.unshift("synthetic");
        setCatalogs(names);
      })
      .catch(() => setCatalogs(["synthetic"]));
  }, []);

  useEffect(() => {
    if (!catalog) { setSchemas([]); return; }
    if (catalog === "synthetic") { setSchemas(["test"]); return; }
    listSchemas(catalog)
      .then((r) => setSchemas(r.schemas.map((s) => s.name)))
      .catch(() => setSchemas([]));
  }, [catalog]);

  useEffect(() => {
    if (!catalog || !schema) { setContainers([]); return; }
    setError(null);
    fetchTimeSeriesContainers(catalog, schema)
      .then((r) => {
        setContainers(r.containers);
        // Auto-select first container (especially useful for synthetic data)
        if (r.containers.length === 1) {
          setSelectedContainer(r.containers[0].container_id);
        }
      })
      .catch((e) => {
        setContainers([]);
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("404")) setError("No ingested data found for this catalog/schema.");
        else setError(`Failed to load containers: ${msg}`);
      });
  }, [catalog, schema]);

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

  // ------ Load & Explore ------

  const doResample = useCallback(async (
    cacheKeys: string[],
    xMinNs: number | null,
    xMaxNs: number | null,
    norm: boolean,
  ) => {
    if (cacheKeys.length === 0) return;
    try {
      const resp = await resampleTimeSeries(cacheKeys, xMinNs, xMaxNs, 5000, norm);
      const newTraces: TraceData[] = resp.traces.map((rt) => {
        const sig = signals.find((s) => s.channel_id === rt.channel_id);
        return {
          cacheKey: rt.cache_key,
          channelId: rt.channel_id,
          channelName: sig?.channel_name || `ch_${rt.channel_id}`,
          unit: sig?.unit || "",
          data: rt.data,
          totalPoints: rt.total_points,
          windowPoints: rt.window_points,
        };
      });
      setTraces(newTraces);
    } catch (e) {
      setError(`Resample failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [signals]);

  const handleLoadAndExplore = useCallback(async () => {
    if (!catalog || !schema || selectedContainer == null || selectedSignals.size === 0) return;
    setError(null);
    setLoadingPhase("Loading data into memory...");
    setTraces([]);
    setWindowNs({ min: null, max: null });

    try {
      const channelIds = Array.from(selectedSignals);
      const resp = await loadTimeSeriesChannels(
        catalog, schema, selectedContainer, channelIds,
        (msg, elapsedMs) => setLoadingPhase(`${msg} (${Math.round(elapsedMs / 1000)}s)`),
      );

      const loaded = new Map<number, LoadedChannel>();
      const cacheKeys: string[] = [];
      for (const ch of resp.channels) {
        loaded.set(ch.channel_id, {
          channelId: ch.channel_id,
          cacheKey: ch.cache_key,
          totalPoints: ch.total_points,
          tMinNs: ch.t_min_ns,
          tMaxNs: ch.t_max_ns,
        });
        cacheKeys.push(ch.cache_key);
      }
      setLoadedChannels(loaded);

      setLoadingPhase("Rendering chart...");
      await doResample(cacheKeys, null, null, normalized);
    } catch (e) {
      setError(`Load failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoadingPhase(null);
    }
  }, [catalog, schema, selectedContainer, selectedSignals, normalized, doResample]);

  // ------ Zoom / Pan ------

  const handleRelayout = useCallback((event: Record<string, any>) => {
    const xMinRaw = event["xaxis.range[0]"];
    const xMaxRaw = event["xaxis.range[1]"];

    // Double-click reset (autorange)
    if (event["xaxis.autorange"]) {
      setWindowNs({ min: null, max: null });
      const cacheKeys = traces.map((t) => t.cacheKey);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        doResample(cacheKeys, null, null, normalized);
      }, 150);
      return;
    }

    if (xMinRaw == null || xMaxRaw == null) return;

    // With numeric x values (epoch ms), Plotly sends range as numbers.
    // Convert back to nanoseconds: raw_ns = (epoch_ms - baseMs) * 1e6
    const xMinMs = typeof xMinRaw === "number" ? xMinRaw : new Date(xMinRaw).getTime();
    const xMaxMs = typeof xMaxRaw === "number" ? xMaxRaw : new Date(xMaxRaw).getTime();
    if (isNaN(xMinMs) || isNaN(xMaxMs)) return;

    const xMinNs = (xMinMs - baseMs) * 1e6;
    const xMaxNs = (xMaxMs - baseMs) * 1e6;
    setWindowNs({ min: xMinNs, max: xMaxNs });

    const cacheKeys = traces.map((t) => t.cacheKey);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      doResample(cacheKeys, xMinNs, xMaxNs, normalized);
    }, 200);
  }, [traces, baseMs, normalized, doResample]);

  // ------ Normalize toggle ------

  const handleNormalizeToggle = useCallback(() => {
    const next = !normalized;
    setNormalized(next);
    const cacheKeys = traces.map((t) => t.cacheKey);
    if (cacheKeys.length > 0) {
      doResample(cacheKeys, windowNs.min, windowNs.max, next);
    }
  }, [normalized, traces, windowNs, doResample]);

  // ------ Build Plotly traces ------

  const plotlyTraces = useMemo(() => {
    return traces.map((trace, i) => {
      const side = axisMap.get(trace.channelId) || "left";
      const yAxisRef = side === "right" && hasDualAxis ? ("y2" as const) : ("y" as const);
      const xDates = trace.data.map((p) => toEpochMs(p.t, baseMs));
      const axisTag = useAxisTags && hasDualAxis ? (side === "left" ? " [L]" : " [R]") : "";
      const displayName = `${trace.channelName}${trace.unit ? ` (${trace.unit})` : ""}${axisTag}`;

      // Progressive hover: rich detail when zoomed in, basic at overview
      let hovertemplate: string;
      if (normalized && trace.data[0]?.v_raw != null) {
        hovertemplate = isDetailLevel
          ? `<b>${trace.channelName}</b><br>%{x|%Y-%m-%d %H:%M:%S.%3f}<br>%{y:.4f} (${trace.unit}: %{customdata:.4f})<extra></extra>`
          : `<b>${trace.channelName}</b><br>%{x}<br>%{y:.3f} (${trace.unit}: %{customdata:.2f})<extra></extra>`;
      } else {
        hovertemplate = isDetailLevel
          ? `<b>${trace.channelName}</b><br>%{x|%Y-%m-%d %H:%M:%S.%3f}<br>%{y:.4f} ${trace.unit}<extra></extra>`
          : `<b>${trace.channelName}</b><br>%{x}<br>%{y:.2f} ${trace.unit}<extra></extra>`;
      }

      return {
        x: xDates,
        y: trace.data.map((p) => p.v),
        customdata: trace.data.map((p) => p.v_raw ?? p.v),
        name: displayName,
        type: "scatter" as const,
        mode: "lines" as const,
        line: { color: PALETTE[i % PALETTE.length], width: 1.5, shape: "hv" as const },
        yaxis: yAxisRef,
        hovertemplate,
      };
    });
  }, [traces, baseMs, axisMap, hasDualAxis, normalized, isDetailLevel]);

  const layout = useMemo(() => {
    const yTitle = normalized ? "Normalized [0–1]" : (leftLabel || "value");
    const axisTitleFont = { size: 12, color: "rgba(200,200,200,0.9)" };
    return mergeLayout({
      xaxis: {
        title: { text: "Time", font: axisTitleFont },
        type: "date" as const,
      },
      yaxis: {
        title: { text: yTitle, font: axisTitleFont },
      },
      ...(hasDualAxis && !normalized ? {
        yaxis2: {
          title: { text: rightLabel, font: axisTitleFont },
          overlaying: "y" as const,
          side: "right" as const,
          gridcolor: "rgba(128,128,128,0.08)",
          tickfont: { size: 10 },
        },
      } : {}),
      hovermode: isDetailLevel ? ("x unified" as const) : ("closest" as const),
      showlegend: traces.length > 1,
      legend: { orientation: "h" as const, y: -0.15, font: { size: 10 } },
      margin: { t: 8, r: hasDualAxis && !normalized ? 64 : 24, b: 64, l: 64 },
    });
  }, [leftLabel, rightLabel, hasDualAxis, normalized, isDetailLevel, traces.length]);

  // ------ Render ------

  const isExploring = traces.length > 0;

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
              onChange={(e) => { setCatalog(e.target.value); setSchema(""); setContainers([]); setSelectedContainer(null); setSignals([]); setSelectedSignals(new Set()); setTraces([]); setLoadedChannels(new Map()); }}
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
              onChange={(e) => { setSchema(e.target.value); setSelectedContainer(null); setSignals([]); setSelectedSignals(new Set()); setTraces([]); setLoadedChannels(new Map()); }}
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
                    onChange={() => { setSelectedContainer(c.container_id); setSelectedSignals(new Set()); setTraces([]); setLoadedChannels(new Map()); }}
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
              {signals.map((s) => {
                const side = axisMap.get(s.channel_id);
                const axisTag = useAxisTags && hasDualAxis && side ? (side === "left" ? " [L]" : " [R]") : "";
                return (
                  <label key={s.channel_id} className="viz-checkbox-row">
                    <input
                      type="checkbox"
                      checked={selectedSignals.has(s.channel_id)}
                      onChange={() => toggleSignal(s.channel_id)}
                    />
                    <div className="viz-hist-info">
                      <span className="viz-checkbox-label">
                        {s.channel_name}{axisTag}
                      </span>
                      <span className="viz-hist-desc">
                        {s.unit && `${s.unit} · `}
                        {s.sample_count > 0 ? `${formatPointCount(s.sample_count)} samples` : ""}
                        {s.min_value != null ? ` · ${s.min_value.toFixed(1)}–${s.max_value?.toFixed(1)}` : ""}
                      </span>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        <button
          className="action-btn primary viz-apply-btn"
          disabled={selectedSignals.size === 0 || !!loadingPhase}
          onClick={handleLoadAndExplore}
        >
          {loadingPhase ? (
            <><span className="spinner" style={{ width: 14, height: 14, marginRight: 6 }} />{loadingPhase}</>
          ) : (
            `Load & Explore ${selectedSignals.size} Signal${selectedSignals.size !== 1 ? "s" : ""}`
          )}
        </button>
      </div>

      <div className="visualize-main">
        {error && <div className="viz-error-banner">{error}</div>}

        {!isExploring && !loadingPhase && (
          <div className="visualize-empty">
            <div className="visualize-empty-icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <rect x="4" y="4" width="40" height="40" rx="6" fill="var(--accent-bg)" stroke="var(--accent)" strokeWidth="1.5" />
                <polyline points="10,34 18,22 26,28 34,14 40,18" stroke="var(--accent)" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="visualize-empty-text">
              Select a catalog, schema, container, and signals, then click <strong>Load &amp; Explore</strong>.
            </div>
          </div>
        )}

        {isExploring && (
          <div className="chart-card" style={{ flex: 1, minHeight: 500, display: "flex", flexDirection: "column" }}>
            {/* Status bar */}
            <div className="chart-card-header" style={{ flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
              {/* Row 1: Currently viewing counter */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", fontSize: 13 }}>
                <span style={{ fontWeight: 600 }}>
                  Currently viewing: {formatPointCount(totalViewingPoints)} data points
                </span>
                {totalViewingPoints > showingPerTrace * traces.length * 2 && (
                  <span className="viz-hint">
                    (downsampled to {showingPerTrace.toLocaleString()} per trace)
                  </span>
                )}
                {isDetailLevel && (
                  <span style={{ marginLeft: 4, color: "var(--success, #22c55e)", fontSize: 11 }}>
                    ● Detail hover active
                  </span>
                )}
                <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                  <button
                    className={`action-btn${!normalized ? " primary" : ""}`}
                    style={{ padding: "2px 8px", fontSize: 11 }}
                    onClick={handleNormalizeToggle}
                  >
                    Absolute
                  </button>
                  <button
                    className={`action-btn${normalized ? " primary" : ""}`}
                    style={{ padding: "2px 8px", fontSize: 11 }}
                    onClick={handleNormalizeToggle}
                  >
                    Normalized
                  </button>
                </div>
              </div>

              {/* Row 2: Signal → axis mapping */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", fontSize: 11, color: "var(--text-secondary)" }}>
                {hasDualAxis && !normalized ? (
                  <>
                    <span>
                      <strong>L:</strong>{" "}
                      {traces.filter((t) => axisMap.get(t.channelId) === "left").map((t) => `${t.channelName} (${t.unit})`).join(", ")}
                    </span>
                    <span style={{ margin: "0 4px" }}>|</span>
                    <span>
                      <strong>R:</strong>{" "}
                      {traces.filter((t) => axisMap.get(t.channelId) === "right").map((t) => `${t.channelName} (${t.unit})`).join(", ")}
                    </span>
                  </>
                ) : (
                  <span>
                    {traces.map((t) => `${t.channelName}${t.unit ? ` (${t.unit})` : ""}`).join(", ")}
                  </span>
                )}
                <span className="viz-hint" style={{ marginLeft: "auto" }}>
                  Total loaded: {formatPointCount(totalLoadedPoints)}
                </span>
              </div>
            </div>

            {/* Chart */}
            <Plot
              data={plotlyTraces}
              layout={layout}
              config={BASE_CONFIG}
              useResizeHandler
              style={{ width: "100%", flex: 1, minHeight: 0 }}
              onRelayout={handleRelayout}
            />
          </div>
        )}
      </div>
    </div>
  );
}
