import { useState, useEffect, useCallback } from "react";
import type { DataSourceConfig, FilterRange, HistogramMeta, HistogramResult, VehicleOption, VisualizeFilters } from "../types";
import {
  fetchVisualizeHistograms,
  fetchVisualizeVehicles,
  fetchVisualizeFilterRange,
  fetchHistogramData,
} from "../api";
import HistogramChart from "./HistogramChart";

interface Props {
  dataSources: DataSourceConfig;
  reportName: string;
  onBack: () => void;
}

const EMPTY_FILTERS: VisualizeFilters = {
  vehicle_ids: [],
  start_ts: null,
  end_ts: null,
  min_mileage: null,
  max_mileage: null,
  group_by_vehicle: false,
};

export default function VisualizeView({ dataSources, reportName, onBack }: Props) {
  const { destination_catalog: catalog, destination_schema: schema, table_prefix: prefix } = dataSources;

  const [histogramsMeta, setHistogramsMeta] = useState<HistogramMeta[]>([]);
  const [vehicles, setVehicles] = useState<VehicleOption[]>([]);
  const [filterRange, setFilterRange] = useState<FilterRange | null>(null);
  const [selectedHistograms, setSelectedHistograms] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<VisualizeFilters>(EMPTY_FILTERS);
  const [results, setResults] = useState<Record<string, HistogramResult>>({});
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchVisualizeHistograms(catalog, schema, prefix),
      fetchVisualizeVehicles(catalog, schema, prefix),
      fetchVisualizeFilterRange(catalog, schema, prefix),
    ])
      .then(([histRes, vehRes, rangeRes]) => {
        if (cancelled) return;
        setHistogramsMeta(histRes.histograms);
        setVehicles(vehRes.vehicles);
        setFilterRange(rangeRes);
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
    const names = Array.from(selectedHistograms);
    if (names.length === 0) return;
    setFetching(true);
    try {
      const resp = await fetchHistogramData(catalog, schema, prefix, names, filters);
      setResults(resp.histograms);
    } catch (err) {
      setError(`Query failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setFetching(false);
    }
  }, [catalog, schema, prefix, selectedHistograms, filters]);

  const toggleHistogram = (name: string) => {
    setSelectedHistograms((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const toggleAllHistograms = () => {
    if (selectedHistograms.size === histogramsMeta.length) {
      setSelectedHistograms(new Set());
    } else {
      setSelectedHistograms(new Set(histogramsMeta.map((h) => h.name)));
    }
  };

  const toggleVehicle = (vid: string) => {
    setFilters((prev) => {
      const ids = prev.vehicle_ids.includes(vid)
        ? prev.vehicle_ids.filter((v) => v !== vid)
        : [...prev.vehicle_ids, vid];
      return { ...prev, vehicle_ids: ids };
    });
  };

  const toggleAllVehicles = () => {
    setFilters((prev) => {
      if (prev.vehicle_ids.length === vehicles.length) {
        return { ...prev, vehicle_ids: [] };
      }
      return { ...prev, vehicle_ids: vehicles.map((v) => v.id) };
    });
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

  if (error && histogramsMeta.length === 0) {
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

  const selectedNames = Array.from(selectedHistograms);

  return (
    <div className="visualize-layout">
      <div className="visualize-sidebar">
        <div className="viz-sidebar-header">
          <button className="action-btn" onClick={onBack} title="Back to Home">Home</button>
          <span className="viz-report-name" title={reportName}>{reportName}</span>
        </div>

        {/* Vehicle filter */}
        <div className="viz-section">
          <div className="viz-section-title">
            Vehicles
            {vehicles.length > 0 && (
              <label className="viz-toggle-all">
                <input
                  type="checkbox"
                  checked={filters.vehicle_ids.length === vehicles.length && vehicles.length > 0}
                  onChange={toggleAllVehicles}
                />
                All
              </label>
            )}
          </div>
          <div className="viz-checkbox-list">
            {vehicles.map((v) => (
              <label key={v.id} className="viz-checkbox-row">
                <input
                  type="checkbox"
                  checked={filters.vehicle_ids.includes(v.id)}
                  onChange={() => toggleVehicle(v.id)}
                />
                <span className="viz-checkbox-label">{v.name}</span>
              </label>
            ))}
            {vehicles.length === 0 && (
              <div className="viz-hint">No vehicles found</div>
            )}
          </div>
        </div>

        {/* Time range filter */}
        <div className="viz-section">
          <div className="viz-section-title">Time Range</div>
          <div className="viz-filter-row">
            <label className="form-label">Start</label>
            <input
              className="form-input"
              type="datetime-local"
              value={filters.start_ts || ""}
              onChange={(e) => setFilters((p) => ({ ...p, start_ts: e.target.value || null }))}
            />
          </div>
          <div className="viz-filter-row">
            <label className="form-label">End</label>
            <input
              className="form-input"
              type="datetime-local"
              value={filters.end_ts || ""}
              onChange={(e) => setFilters((p) => ({ ...p, end_ts: e.target.value || null }))}
            />
          </div>
          {filterRange && (
            <div className="viz-hint">
              Data range: {filterRange.min_ts?.slice(0, 10) || "?"} to {filterRange.max_ts?.slice(0, 10) || "?"}
            </div>
          )}
        </div>

        {/* Mileage filter */}
        <div className="viz-section">
          <div className="viz-section-title">Mileage Range (km)</div>
          <div className="viz-filter-row" style={{ display: "flex", gap: 6 }}>
            <input
              className="form-input"
              type="number"
              placeholder={filterRange?.min_mileage != null ? String(Math.floor(filterRange.min_mileage)) : "Min"}
              value={filters.min_mileage ?? ""}
              onChange={(e) => setFilters((p) => ({ ...p, min_mileage: e.target.value ? Number(e.target.value) : null }))}
              style={{ flex: 1 }}
            />
            <input
              className="form-input"
              type="number"
              placeholder={filterRange?.max_mileage != null ? String(Math.ceil(filterRange.max_mileage)) : "Max"}
              value={filters.max_mileage ?? ""}
              onChange={(e) => setFilters((p) => ({ ...p, max_mileage: e.target.value ? Number(e.target.value) : null }))}
              style={{ flex: 1 }}
            />
          </div>
        </div>

        {/* Group by vehicle toggle */}
        <div className="viz-section">
          <label className="viz-checkbox-row">
            <input
              type="checkbox"
              checked={filters.group_by_vehicle}
              onChange={(e) => setFilters((p) => ({ ...p, group_by_vehicle: e.target.checked }))}
            />
            <span className="viz-checkbox-label">Group by vehicle</span>
          </label>
        </div>

        {/* Histogram selector */}
        <div className="viz-section">
          <div className="viz-section-title">
            Histograms
            {histogramsMeta.length > 0 && (
              <label className="viz-toggle-all">
                <input
                  type="checkbox"
                  checked={selectedHistograms.size === histogramsMeta.length && histogramsMeta.length > 0}
                  onChange={toggleAllHistograms}
                />
                All
              </label>
            )}
          </div>
          <div className="viz-checkbox-list">
            {histogramsMeta.map((h) => (
              <label key={h.name} className="viz-checkbox-row">
                <input
                  type="checkbox"
                  checked={selectedHistograms.has(h.name)}
                  onChange={() => toggleHistogram(h.name)}
                />
                <div className="viz-hist-info">
                  <span className="viz-checkbox-label">{h.name}</span>
                  {h.description && <span className="viz-hist-desc">{h.description}</span>}
                  <span className="viz-hist-type">{h.type}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        <button
          className="action-btn primary viz-apply-btn"
          disabled={selectedHistograms.size === 0 || fetching}
          onClick={handleFetchData}
        >
          {fetching ? (
            <><span className="spinner" style={{ width: 14, height: 14, marginRight: 6 }} />Loading...</>
          ) : (
            `Show ${selectedHistograms.size} Histogram${selectedHistograms.size !== 1 ? "s" : ""}`
          )}
        </button>
      </div>

      <div className="visualize-main">
        {error && (
          <div className="viz-error-banner">{error}</div>
        )}

        {selectedNames.length === 0 && Object.keys(results).length === 0 && (
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
              Select histograms from the sidebar and click <strong>Show</strong> to visualize.
            </div>
          </div>
        )}

        <div className="chart-grid">
          {selectedNames.map((name) => {
            const result = results[name];
            if (!result) return null;
            return <HistogramChart key={name} name={name} result={result} />;
          })}
        </div>
      </div>
    </div>
  );
}
