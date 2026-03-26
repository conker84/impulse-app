import type { HistogramDefinition } from "../types";

interface Props {
  histograms: HistogramDefinition[];
}

export default function HistogramsTab({ histograms }: Props) {
  if (histograms.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">&#x1F4CA;</div>
        <div>No histograms defined yet</div>
        <div style={{ fontSize: 12 }}>
          Ask the assistant to add histogram visualizations.
        </div>
      </div>
    );
  }

  return (
    <div>
      {histograms.map((h) => (
        <div className="card" key={h.name}>
          <div className="card-title">
            <code>{h.name}</code>
            <span className={`badge ${h.histogram_type}`} style={{ marginLeft: 8 }}>
              {h.histogram_type}
            </span>
          </div>
          {h.description && (
            <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
              {h.description}
            </div>
          )}
          <div className="card-meta">
            <span>Signal: <code>{h.signal_ref}</code></span>
            <span>Bins: {h.bins.length} edges</span>
            {h.bins_unit && <span>Unit: {h.bins_unit}</span>}
            {h.max_duration && (
              <span>Max dur: {(h.max_duration / 1e9).toFixed(0)}s</span>
            )}
            {h.event_signal_ref && (
              <span>Event: <code>{h.event_signal_ref}</code></span>
            )}
          </div>
          <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-muted)" }}>
            Range: [{h.bins[0]} ... {h.bins[h.bins.length - 1]}]
          </div>
        </div>
      ))}
    </div>
  );
}
