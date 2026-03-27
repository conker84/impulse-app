import { useState, useCallback } from "react";
import Plot from "react-plotly.js";
import type { SignalDefinition, TimeSeriesPoint, TimeSeriesContainer, VehicleConfig } from "../types";
import { fetchTimeSeriesContainers, fetchTimeSeriesSignals, fetchTimeSeriesData } from "../api";
import { PALETTE, BASE_CONFIG, mergeLayout } from "../plotlyTheme";

interface Props {
  signals: SignalDefinition[];
  silverCatalog?: string;
  silverSchema?: string;
  vehicles?: VehicleConfig[];
  onDelete?: (varName: string) => void;
  onUpdate?: (varName: string, payload: { var_name: string; expression?: string; eval_type?: string; description?: string; alias?: string }) => void;
  onAddVirtual?: (payload: { var_name: string; expression: string; eval_type?: string; description?: string }) => void;
}

const EVAL_TYPES = ["SampleSeries", "Intervals", "PointsInTime", "PitSeries"];

/** Check if a container overlaps with the analysis timeframe from any vehicle. */
function containerInTimeframe(c: TimeSeriesContainer, vehicles: VehicleConfig[]): boolean {
  if (!vehicles.length) return true;
  // Get the earliest start and latest stop across all vehicles
  let earliest: number | null = null;
  let latest: number | null = null;
  for (const v of vehicles) {
    if (v.start_ts) {
      const ms = new Date(v.start_ts.replace(" ", "T")).getTime();
      if (!isNaN(ms) && (earliest === null || ms < earliest)) earliest = ms;
    }
    if (v.stop_ts) {
      const ms = new Date(v.stop_ts.replace(" ", "T")).getTime();
      if (!isNaN(ms) && (latest === null || ms > latest)) latest = ms;
    }
  }
  // If no timestamps set on vehicles, don't filter
  if (earliest === null && latest === null) return true;

  const cStart = c.start_dt ? new Date(c.start_dt).getTime() : null;
  const cStop = c.stop_dt ? new Date(c.stop_dt).getTime() : null;

  // Check overlap: container must not end before the timeframe starts
  // and must not start after the timeframe ends
  if (earliest !== null && cStop !== null && cStop < earliest) return false;
  if (latest !== null && cStart !== null && cStart > latest) return false;
  return true;
}

export default function SignalsTab({ signals, silverCatalog, silverSchema, vehicles, onDelete, onUpdate, onAddVirtual }: Props) {
  const PREVIEW_POINTS = 5000;

  const [previewSignal, setPreviewSignal] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<TimeSeriesPoint[]>([]);
  const [previewTotalPoints, setPreviewTotalPoints] = useState(0);
  const [previewUnit, setPreviewUnit] = useState("");
  const [previewBaseMs, setPreviewBaseMs] = useState(0); // container start_dt as epoch ms
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");

  // Edit state
  const [editingVar, setEditingVar] = useState<string | null>(null);
  const [editExpression, setEditExpression] = useState("");
  const [editEvalType, setEditEvalType] = useState("SampleSeries");
  const [editDescription, setEditDescription] = useState("");

  // Add virtual signal form
  const [showAddVirtual, setShowAddVirtual] = useState(false);
  const [newVarName, setNewVarName] = useState("");
  const [newExpression, setNewExpression] = useState("");
  const [newEvalType, setNewEvalType] = useState("SampleSeries");
  const [newDescription, setNewDescription] = useState("");

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
      const cRes = await fetchTimeSeriesContainers(silverCatalog, silverSchema);
      if (cRes.containers.length === 0) {
        setPreviewError("No containers available.");
        return;
      }
      // Filter containers by analysis timeframe if vehicles have timestamps set
      const inRange = vehicles?.length
        ? cRes.containers.filter((c) => containerInTimeframe(c, vehicles))
        : cRes.containers;
      if (inRange.length === 0) {
        setPreviewError("No data in the selected analysis timeframe.");
        return;
      }
      const container = inRange[0];
      const containerId = container.container_id;
      // start_dt is the absolute timestamp for the container — t values are relative offsets in seconds
      const baseMs = container.start_dt ? new Date(container.start_dt).getTime() : 0;
      setPreviewBaseMs(baseMs);

      const sRes = await fetchTimeSeriesSignals(silverCatalog, silverSchema, containerId);
      const match = sRes.signals.find((s) => s.channel_name === channelName);
      if (!match) {
        setPreviewError(`Channel "${channelName}" not found in container.`);
        return;
      }

      setPreviewUnit(match.unit);
      const dRes = await fetchTimeSeriesData(silverCatalog, silverSchema, containerId, match.channel_id, undefined, undefined, PREVIEW_POINTS);
      setPreviewData(dRes.data);
      setPreviewTotalPoints(dRes.total_points);
    } catch (e) {
      setPreviewError(`Preview failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPreviewLoading(false);
    }
  }, [silverCatalog, silverSchema, previewSignal]);

  const startEdit = (s: SignalDefinition) => {
    setEditingVar(s.var_name);
    setEditExpression(s.expression || "");
    setEditEvalType(s.eval_type);
    setEditDescription(s.description);
  };

  const saveEdit = (s: SignalDefinition) => {
    if (!onUpdate) return;
    onUpdate(s.var_name, {
      var_name: s.var_name,
      expression: s.signal_type === "virtual" ? editExpression : undefined,
      eval_type: editEvalType,
      description: editDescription,
    });
    setEditingVar(null);
  };

  const handleAddVirtual = () => {
    if (!onAddVirtual || !newVarName || !newExpression) return;
    onAddVirtual({
      var_name: newVarName.toLowerCase().replace(/[^a-z0-9_]/g, "_"),
      expression: newExpression,
      eval_type: newEvalType,
      description: newDescription,
    });
    setNewVarName("");
    setNewExpression("");
    setNewEvalType("SampleSeries");
    setNewDescription("");
    setShowAddVirtual(false);
  };

  return (
    <div>
      {signals.length === 0 && !showAddVirtual && (
        <div className="empty-state">
          <div className="icon">&#x1F50D;</div>
          <div>No signals defined yet</div>
          <div style={{ fontSize: 12 }}>
            Ask the assistant to add signals, browse channels above, or add a virtual signal.
          </div>
        </div>
      )}

      {signals.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Variable</th>
              <th>Type</th>
              <th>Alias / Expression</th>
              <th>Eval Type</th>
              <th style={{ width: 80 }}></th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              editingVar === s.var_name ? (
                <tr key={s.var_name}>
                  <td><code>{s.var_name}</code></td>
                  <td>
                    <span className={`badge ${s.signal_type === "physical" ? "ok" : "duration"}`}>
                      {s.signal_type}
                    </span>
                  </td>
                  <td>
                    {s.signal_type === "virtual" ? (
                      <input
                        className="form-input"
                        style={{ fontSize: 12 }}
                        value={editExpression}
                        onChange={(e) => setEditExpression(e.target.value)}
                        placeholder="Python expression"
                      />
                    ) : (
                      <code>{s.alias}</code>
                    )}
                  </td>
                  <td>
                    <select
                      className="form-input"
                      style={{ fontSize: 11, padding: "2px 4px" }}
                      value={editEvalType}
                      onChange={(e) => setEditEvalType(e.target.value)}
                    >
                      {EVAL_TYPES.map((et) => <option key={et} value={et}>{et}</option>)}
                    </select>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 2 }}>
                      <button
                        className="action-btn primary"
                        style={{ fontSize: 10, padding: "2px 6px" }}
                        onClick={() => saveEdit(s)}
                      >
                        Save
                      </button>
                      <button
                        className="action-btn"
                        style={{ fontSize: 10, padding: "2px 6px" }}
                        onClick={() => setEditingVar(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                <tr key={s.var_name}>
                  <td><code>{s.var_name}</code></td>
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
                  <td>
                    <div style={{ display: "flex", gap: 2 }}>
                      {canPreview && s.signal_type === "physical" && (
                        <button
                          className={`action-btn${previewSignal === s.var_name ? " primary" : ""}`}
                          style={{ fontSize: 10, padding: "2px 6px" }}
                          onClick={() => handlePreview(s)}
                          title="Preview time series"
                        >
                          {previewSignal === s.var_name ? "Hide" : "Preview"}
                        </button>
                      )}
                      {onUpdate && (
                        <button
                          className="action-btn"
                          style={{ fontSize: 10, padding: "2px 6px" }}
                          onClick={() => startEdit(s)}
                          title="Edit signal"
                        >
                          &#x270E;
                        </button>
                      )}
                      {onDelete && (
                        <button
                          className="action-btn danger"
                          style={{ fontSize: 10, padding: "2px 6px" }}
                          onClick={() => onDelete(s.var_name)}
                          title="Delete signal"
                        >
                          &#x2715;
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            ))}
          </tbody>
        </table>
      )}

      {/* Add virtual signal button + form */}
      {onAddVirtual && (
        <div style={{ marginTop: 8 }}>
          {!showAddVirtual ? (
            <button
              className="action-btn"
              style={{ fontSize: 11 }}
              onClick={() => setShowAddVirtual(true)}
            >
              + Add Virtual Signal
            </button>
          ) : (
            <div className="card" style={{ padding: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8 }}>New Virtual Signal</div>
              <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                <input
                  className="form-input"
                  style={{ flex: 1, fontSize: 12 }}
                  placeholder="Variable name (e.g. eng_spd_filtered)"
                  value={newVarName}
                  onChange={(e) => setNewVarName(e.target.value)}
                />
                <select
                  className="form-input"
                  style={{ fontSize: 11, padding: "2px 4px", width: 130 }}
                  value={newEvalType}
                  onChange={(e) => setNewEvalType(e.target.value)}
                >
                  {EVAL_TYPES.map((et) => <option key={et} value={et}>{et}</option>)}
                </select>
              </div>
              <input
                className="form-input"
                style={{ width: "100%", fontSize: 12, marginBottom: 6 }}
                placeholder="Expression (e.g. Eng_Spd.where((Eng_Spd >= 0) & (Eng_Spd <= 7000)))"
                value={newExpression}
                onChange={(e) => setNewExpression(e.target.value)}
              />
              <input
                className="form-input"
                style={{ width: "100%", fontSize: 12, marginBottom: 6 }}
                placeholder="Description (optional)"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
              />
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  className="action-btn primary"
                  style={{ fontSize: 11 }}
                  disabled={!newVarName || !newExpression}
                  onClick={handleAddVirtual}
                >
                  Add
                </button>
                <button
                  className="action-btn"
                  style={{ fontSize: 11 }}
                  onClick={() => setShowAddVirtual(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

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
                  x: previewData.map((p) => new Date(previewBaseMs + p.t * 1000).toISOString()),
                  y: previewData.map((p) => p.v),
                  type: "scattergl" as const,
                  mode: "lines" as const,
                  line: { color: PALETTE[0], width: 1.5 },
                  hovertemplate: `%{x}<br>%{y:.4f}<extra></extra>`,
                }]}
                layout={mergeLayout({
                  height: 200,
                  margin: { t: 4, r: 12, b: 32, l: 48 },
                  xaxis: { title: "Time", type: "date" },
                  yaxis: { title: previewUnit || "value" },
                  showlegend: false,
                })}
                config={{ ...BASE_CONFIG, displayModeBar: false }}
                useResizeHandler
                style={{ width: "100%", height: 200 }}
              />
              {previewTotalPoints > PREVIEW_POINTS && (
                <div style={{ padding: "4px 8px", fontSize: 11, color: "var(--text-muted)", background: "var(--surface)", borderTop: "1px solid var(--border)" }}>
                  Showing {previewData.length.toLocaleString()} of {previewTotalPoints.toLocaleString()} points (downsampled)
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
