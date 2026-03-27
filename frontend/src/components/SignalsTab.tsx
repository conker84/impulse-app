import { useState, useCallback } from "react";
import Plot from "react-plotly.js";
import type { SignalDefinition, TimeSeriesPoint } from "../types";
import { fetchTimeSeriesContainers, fetchTimeSeriesSignals, fetchTimeSeriesData } from "../api";
import { PALETTE, BASE_CONFIG, mergeLayout } from "../plotlyTheme";

interface Props {
  signals: SignalDefinition[];
  silverCatalog?: string;
  silverSchema?: string;
}

export default function SignalsTab({ signals, silverCatalog, silverSchema }: Props) {
  const [previewSignal, setPreviewSignal] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<TimeSeriesPoint[]>([]);
  const [previewUnit, setPreviewUnit] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");

  const canPreview = !!silverCatalog && !!silverSchema;

  const handlePreview = useCallback(async (sig: SignalDefinition) => {
    if (!silverCatalog || !silverSchema) return;
    const channelName = sig.channel_name || sig.alias || sig.var_name;

    if (previewSignal === sig.var_name) {
      setPreviewSignal(null);
      return;
    }

    setPreviewSignal(sig.var_name);
    setPreviewLoading(true);
    setPreviewError("");
    setPreviewData([]);

    try {
      // Get first container
      const cRes = await fetchTimeSeriesContainers(silverCatalog, silverSchema);
      if (cRes.containers.length === 0) {
        setPreviewError("No containers available.");
        return;
      }
      const containerId = cRes.containers[0].container_id;

      // Find matching channel
      const sRes = await fetchTimeSeriesSignals(silverCatalog, silverSchema, containerId);
      const match = sRes.signals.find((s) => s.channel_name === channelName);
      if (!match) {
        setPreviewError(`Channel "${channelName}" not found in container.`);
        return;
      }

      setPreviewUnit(match.unit);
      const dRes = await fetchTimeSeriesData(silverCatalog, silverSchema, containerId, match.channel_id);
      setPreviewData(dRes.data);
    } catch (e) {
      setPreviewError(`Preview failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPreviewLoading(false);
    }
  }, [silverCatalog, silverSchema, previewSignal]);

  if (signals.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">&#x1F50D;</div>
        <div>No signals defined yet</div>
        <div style={{ fontSize: 12 }}>
          Ask the assistant to add signals from channel aliases.
        </div>
      </div>
    );
  }

  return (
    <div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Variable</th>
            <th>Type</th>
            <th>Alias / Expression</th>
            <th>Eval Type</th>
            {canPreview && <th style={{ width: 60 }}></th>}
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.var_name}>
              <td>
                <code>{s.var_name}</code>
              </td>
              <td>
                <span className={`badge ${s.signal_type === "physical" ? "ok" : "duration"}`}>
                  {s.signal_type}
                </span>
              </td>
              <td>
                {s.signal_type === "physical" ? (
                  <code>{s.alias}</code>
                ) : (
                  <code style={{ fontSize: 12 }}>{s.expression}</code>
                )}
              </td>
              <td style={{ color: "var(--text-secondary)", fontSize: 12 }}>{s.eval_type}</td>
              {canPreview && (
                <td>
                  {s.signal_type === "physical" && (
                    <button
                      className={`action-btn${previewSignal === s.var_name ? " primary" : ""}`}
                      style={{ fontSize: 10, padding: "2px 8px" }}
                      onClick={() => handlePreview(s)}
                    >
                      {previewSignal === s.var_name ? "Hide" : "Preview"}
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Inline preview chart */}
      {previewSignal && (
        <div className="signal-preview" style={{ marginTop: 12 }}>
          {previewLoading && (
            <div style={{ padding: 16, textAlign: "center", color: "var(--text-muted)" }}>
              <span className="spinner" style={{ marginRight: 8 }} />Loading preview...
            </div>
          )}
          {previewError && (
            <div style={{ padding: 12, color: "var(--error)", fontSize: 12 }}>{previewError}</div>
          )}
          {previewData.length > 0 && (
            <div style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
              <Plot
                data={[{
                  x: previewData.map((p) => p.t),
                  y: previewData.map((p) => p.v),
                  type: "scattergl" as const,
                  mode: "lines" as const,
                  line: { color: PALETTE[0], width: 1.5 },
                  hovertemplate: `t=%{x:.3f}s<br>v=%{y:.4f}<extra></extra>`,
                }]}
                layout={mergeLayout({
                  height: 200,
                  margin: { t: 4, r: 12, b: 32, l: 48 },
                  xaxis: { title: "Time (s)" },
                  yaxis: { title: previewUnit || "value" },
                  showlegend: false,
                })}
                config={{ ...BASE_CONFIG, displayModeBar: false }}
                useResizeHandler
                style={{ width: "100%", height: 200 }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
