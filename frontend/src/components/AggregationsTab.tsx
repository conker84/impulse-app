import type { AggregationDefinition, Histogram1DDefinition } from "../types";

interface Props {
  aggregations: AggregationDefinition[];
  onDelete?: (name: string) => void;
  onEdit?: (agg: AggregationDefinition) => void;
}

function Histogram1DCard({
  h,
  onDelete,
  onEdit,
}: {
  h: Histogram1DDefinition;
  onDelete?: (name: string) => void;
  onEdit?: (agg: AggregationDefinition) => void;
}) {
  return (
    <div className="card" style={{ position: "relative" }}>
      <div className="card-title">
        <code>{h.name}</code>
        <span className={`badge ${h.histogram_type}`} style={{ marginLeft: 8 }}>
          {h.histogram_type}
        </span>
        <span className="badge" style={{ marginLeft: 4, opacity: 0.5 }}>1D</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          {onEdit && (
            <button
              className="icon-btn"
              title="Edit"
              onClick={() => onEdit(h)}
            >
              &#9998;
            </button>
          )}
          {onDelete && (
            <button
              className="icon-btn danger"
              title="Delete"
              onClick={() => onDelete(h.name)}
            >
              &#128465;
            </button>
          )}
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
  );
}

export default function AggregationsTab({ aggregations, onDelete, onEdit }: Props) {
  if (aggregations.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">&#x1F4CA;</div>
        <div>No aggregations defined yet</div>
        <div style={{ fontSize: 12 }}>
          Use the builder below or ask the assistant to add aggregations.
        </div>
      </div>
    );
  }

  return (
    <div>
      {aggregations.map((a) => {
        if (a.agg_kind === "histogram_1d") {
          return (
            <Histogram1DCard
              key={a.name}
              h={a}
              onDelete={onDelete}
              onEdit={onEdit}
            />
          );
        }
        if (a.agg_kind === "histogram_2d") {
          return (
            <div className="card" key={a.name} style={{ position: "relative" }}>
              <div className="card-title">
                <code>{a.name}</code>
                <span className="badge" style={{ marginLeft: 8 }}>2D</span>
                <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                  {onDelete && (
                    <button
                      className="icon-btn danger"
                      title="Delete"
                      onClick={() => onDelete(a.name)}
                    >
                      &#128465;
                    </button>
                  )}
                </span>
              </div>
              {a.description && (
                <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
                  {a.description}
                </div>
              )}
              <div className="card-meta">
                <span>X: <code>{a.x_signal_ref}</code></span>
                <span>Y: <code>{a.y_signal_ref}</code></span>
              </div>
            </div>
          );
        }
        if (a.agg_kind === "statistics") {
          return (
            <div className="card" key={a.name} style={{ position: "relative" }}>
              <div className="card-title">
                <code>{a.name}</code>
                <span className="badge" style={{ marginLeft: 8 }}>stats</span>
                <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                  {onDelete && (
                    <button
                      className="icon-btn danger"
                      title="Delete"
                      onClick={() => onDelete(a.name)}
                    >
                      &#128465;
                    </button>
                  )}
                </span>
              </div>
              {a.description && (
                <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
                  {a.description}
                </div>
              )}
              <div className="card-meta">
                <span>Signals: {a.signal_refs.length}</span>
                <span>Stats: {a.stat_labels.join(", ")}</span>
              </div>
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}
