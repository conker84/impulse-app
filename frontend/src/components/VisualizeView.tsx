import { useState, useEffect, useCallback } from "react";
import type {
  AggregationMeta,
  DataSourceConfig,
  Heatmap2DResult,
  HistogramResult,
  StatisticsResult,
} from "../types";
import {
  fetchVisualizeAggregations,
  fetchHistogramData,
  fetchHistogram2DData,
  fetchStatisticsData,
} from "../api";
import HistogramChart from "./HistogramChart";
import Heatmap2DChart from "./Heatmap2DChart";
import StatisticsTable from "./StatisticsTable";
import StatisticsLineChart from "./StatisticsLineChart";

interface Props {
  dataSources: DataSourceConfig;
  reportName: string;
  reportDescription?: string;
  onBack: () => void;
  settingsButton?: React.ReactNode;
}

const AGG_TYPE_LABELS: Record<string, string> = {
  histogram_1d: "1D",
  histogram_2d: "2D",
  statistics: "Stats",
};

export default function VisualizeView({ dataSources, reportName, reportDescription, onBack, settingsButton }: Props) {
  const { destination_catalog: catalog, destination_schema: schema, table_prefix: prefix } = dataSources;

  const [aggMeta, setAggMeta] = useState<AggregationMeta[]>([]);
  const [selectedAggs, setSelectedAggs] = useState<Set<string>>(new Set());

  // Results keyed by name
  const [hist1DResults, setHist1DResults] = useState<Record<string, HistogramResult>>({});
  const [hist2DResults, setHist2DResults] = useState<Record<string, Heatmap2DResult>>({});
  const [statsResults, setStatsResults] = useState<Record<string, StatisticsResult>>({});
  // Per-stats-aggregation view toggle: "table" or "lines"
  const [statsView, setStatsView] = useState<Record<string, "table" | "lines">>({});

  // Layout
  const [gridCols, setGridCols] = useState<1 | 2 | 3>(1);

  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchVisualizeAggregations(catalog, schema, prefix)
      .then((aggRes) => {
        if (cancelled) return;
        setAggMeta(aggRes.aggregations);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.includes("404")) {
          setError("This report has not been calculated yet. Go back and deploy the report first.");
        } else {
          setError(`Failed to load report data: ${msg}`);
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [catalog, schema, prefix]);

  const handleFetchData = useCallback(async () => {
    const names = Array.from(selectedAggs);
    if (names.length === 0) return;
    setFetching(true);
    setError(null);

    // Partition selected names by type
    const metaByName = new Map(aggMeta.map((m) => [m.name, m]));
    const hist1DNames = names.filter((n) => metaByName.get(n)?.agg_type === "histogram_1d");
    const hist2DNames = names.filter((n) => metaByName.get(n)?.agg_type === "histogram_2d");
    const statsNames = names.filter((n) => metaByName.get(n)?.agg_type === "statistics");

    try {
      const promises: Promise<void>[] = [];

      if (hist1DNames.length > 0) {
        promises.push(
          fetchHistogramData(catalog, schema, prefix, hist1DNames)
            .then((r) => setHist1DResults(r.histograms))
        );
      } else {
        setHist1DResults({});
      }

      if (hist2DNames.length > 0) {
        promises.push(
          fetchHistogram2DData(catalog, schema, prefix, hist2DNames)
            .then((r) => setHist2DResults(r.histograms))
        );
      } else {
        setHist2DResults({});
      }

      if (statsNames.length > 0) {
        promises.push(
          fetchStatisticsData(catalog, schema, prefix, statsNames)
            .then((r) => setStatsResults(r.statistics))
        );
      } else {
        setStatsResults({});
      }

      await Promise.all(promises);
    } catch (err) {
      setError(`Query failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setFetching(false);
    }
  }, [catalog, schema, prefix, selectedAggs, aggMeta]);

  const toggleAgg = (name: string) => {
    setSelectedAggs((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const toggleAllAggs = () => {
    if (selectedAggs.size === aggMeta.length) {
      setSelectedAggs(new Set());
    } else {
      setSelectedAggs(new Set(aggMeta.map((a) => a.name)));
    }
  };

  if (loading) {
    return (
      <div className="visualize-layout">
        <div className="visualize-loading">
          <span className="spinner" style={{ marginRight: 8 }} />
          Loading report metadata...
        </div>
      </div>
    );
  }

  if (error && aggMeta.length === 0) {
    return (
      <div className="visualize-layout">
        <div className="visualize-empty">
          <div className="visualize-empty-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <rect x="4" y="4" width="40" height="40" rx="6" stroke="var(--text-muted)" strokeWidth="1.5" strokeDasharray="4 3" />
              <path d="M24 16v10M24 30v2" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <div className="visualize-empty-text">{error}</div>
          <button className="action-btn" onClick={onBack} style={{ marginTop: 16 }}>Back to Home</button>
        </div>
      </div>
    );
  }

  const selectedNames = Array.from(selectedAggs);
  const hasResults = Object.keys(hist1DResults).length > 0
    || Object.keys(hist2DResults).length > 0
    || Object.keys(statsResults).length > 0;

  return (
    <div className="visualize-layout">
      <div className="visualize-sidebar">
        <div className="viz-sidebar-scroll">
          <div className="viz-sidebar-header">
            <span className="viz-report-name" title={reportName} style={{ textAlign: "center" }}>{reportName}</span>
          </div>

          {reportDescription && (
            <div className="viz-section viz-section--desc">
              <div className="viz-section-title">Description</div>
              <div className="viz-report-desc-text">{reportDescription}</div>
            </div>
          )}

          {/* Aggregation selector */}
          <div className="viz-section">
            <div className="viz-section-title">
              Aggregations
              {aggMeta.length > 0 && (
                <label className="viz-toggle-all">
                  <input
                    type="checkbox"
                    checked={selectedAggs.size === aggMeta.length && aggMeta.length > 0}
                    onChange={toggleAllAggs}
                  />
                  All
                </label>
              )}
            </div>
            <div className="viz-checkbox-list">
              {aggMeta.map((a) => (
                <label key={a.name} className="viz-checkbox-row">
                  <input
                    type="checkbox"
                    checked={selectedAggs.has(a.name)}
                    onChange={() => toggleAgg(a.name)}
                  />
                  <div className="viz-hist-info">
                    <span className="viz-checkbox-label">
                      {a.name}
                      <span className={`viz-agg-badge viz-agg-badge--${a.agg_type}`}>
                        {AGG_TYPE_LABELS[a.agg_type] || a.agg_type}
                      </span>
                    </span>
                    {a.description && <span className="viz-hist-desc">{a.description}</span>}
                    {a.type && a.agg_type === "histogram_1d" && <span className="viz-hist-type">{a.type}</span>}
                  </div>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="viz-sidebar-footer">
          <button
            className="action-btn primary"
            style={{ width: "100%" }}
            disabled={selectedAggs.size === 0 || fetching}
            onClick={handleFetchData}
          >
            {fetching ? (
              <><span className="spinner" style={{ width: 14, height: 14, marginRight: 6 }} />Loading...</>
            ) : (
              `Show ${selectedAggs.size} Aggregation${selectedAggs.size !== 1 ? "s" : ""}`
            )}
          </button>
        </div>
      </div>

      <div className="visualize-main">
        {error && (
          <div className="viz-error-banner">{error}</div>
        )}

        {hasResults && (
          <div className="viz-layout-controls">
            <span className="viz-layout-label">Layout</span>
            {([1, 2, 3] as const).map((n) => (
              <button
                key={n}
                className={`viz-grid-btn${gridCols === n ? " active" : ""}`}
                onClick={() => setGridCols(n)}
                title={`${n} column${n > 1 ? "s" : ""}`}
              >
                {Array.from({ length: n }, (_, i) => (
                  <span key={i} className="viz-grid-bar" />
                ))}
              </button>
            ))}
          </div>
        )}

        {selectedNames.length === 0 && !hasResults && (
          <div className="visualize-empty">
            <div className="visualize-empty-icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <rect x="4" y="4" width="40" height="40" rx="6" fill="var(--accent-bg)" stroke="var(--accent)" strokeWidth="1.5" />
                <rect x="11" y="28" width="6" height="10" rx="1.5" fill="var(--accent)" opacity="0.5" />
                <rect x="21" y="20" width="6" height="18" rx="1.5" fill="var(--accent)" opacity="0.7" />
                <rect x="31" y="12" width="6" height="26" rx="1.5" fill="var(--accent)" />
              </svg>
            </div>
            <div className="visualize-empty-text">
              Select aggregations from the sidebar and click <strong>Show</strong> to visualize.
            </div>
          </div>
        )}

        <div className={`chart-grid chart-grid--cols-${gridCols}`}>
          {selectedNames.map((name) => {
            const meta = aggMeta.find((a) => a.name === name);
            if (!meta) return null;

            if (meta.agg_type === "histogram_1d") {
              const result = hist1DResults[name];
              if (!result) return null;
              return <HistogramChart key={name} name={name} result={result} />;
            }

            if (meta.agg_type === "histogram_2d") {
              const result = hist2DResults[name];
              if (!result) return null;
              return <Heatmap2DChart key={name} name={name} result={result} />;
            }

            if (meta.agg_type === "statistics") {
              const result = statsResults[name];
              if (!result) return null;
              const instanceCount = new Set(result.rows.map((r) => r.event_instance_id)).size;
              const defaultView: "table" | "lines" = instanceCount >= 2 ? "lines" : "table";
              const view = statsView[name] || defaultView;
              return (
                <div key={name} style={{ display: "contents" }}>
                  <div className="chart-card stats-card-wrapper" style={{ padding: 0 }}>
                    <div style={{
                      padding: "6px 10px",
                      display: "flex",
                      gap: 6,
                      borderBottom: "1px solid rgba(128,128,128,0.15)",
                      background: "rgba(30,41,59,0.25)",
                    }}>
                      <button
                        className={`action-btn${view === "table" ? " primary" : ""}`}
                        style={{ fontSize: 11, padding: "2px 8px" }}
                        onClick={() => setStatsView((v) => ({ ...v, [name]: "table" }))}
                      >Table</button>
                      <button
                        className={`action-btn${view === "lines" ? " primary" : ""}`}
                        style={{ fontSize: 11, padding: "2px 8px" }}
                        disabled={instanceCount < 2}
                        title={instanceCount < 2 ? "Need ≥2 event instances for a line chart" : ""}
                        onClick={() => setStatsView((v) => ({ ...v, [name]: "lines" }))}
                      >Lines</button>
                      <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>
                        {instanceCount} event instance{instanceCount === 1 ? "" : "s"}
                      </span>
                    </div>
                    {view === "lines"
                      ? <StatisticsLineChart name={name} result={result} />
                      : <StatisticsTable name={name} result={result} />}
                  </div>
                </div>
              );
            }

            return null;
          })}
        </div>
      </div>
    </div>
  );
}
