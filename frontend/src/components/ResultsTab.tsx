import type { DeploymentStatus, ValidationResults } from "../types";

interface Props {
  deployment: DeploymentStatus;
  validation: ValidationResults | null;
  runUrl: string | null;
  onValidate: () => void;
  validating: boolean;
}

function StatusBadge({ status }: { status: DeploymentStatus }) {
  const map: Record<DeploymentStatus, { cls: string; label: string }> = {
    not_started: { cls: "", label: "Not Started" },
    scaffolding: { cls: "running", label: "Scaffolding" },
    deploying: { cls: "running", label: "Deploying" },
    running: { cls: "running", label: "Running" },
    completed: { cls: "ok", label: "Completed" },
    failed: { cls: "empty", label: "Failed" },
  };
  const { cls, label } = map[status];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export default function ResultsTab({ deployment, validation, runUrl, onValidate, validating }: Props) {
  return (
    <div>
      {deployment === "completed" && !validation && (
        <div className="card">
          <button
            className="action-btn primary"
            style={{ width: "100%" }}
            onClick={onValidate}
            disabled={validating}
          >
            {validating ? <><span className="spinner" /> Validating...</> : "Validate Results"}
          </button>
        </div>
      )}

      {validation && (
        <>
          <div className="code-label" style={{ marginTop: 20 }}>Validation Levels</div>
          {validation.levels.map((level, i) => (
            <div className="card" key={i}>
              <div className="card-title">
                {level.name}
                <span className={`badge ${level.passed ? "ok" : "empty"}`} style={{ marginLeft: 8 }}>
                  {level.passed ? "PASS" : "FAIL"}
                </span>
              </div>
              {level.details && (
                <pre style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 6, whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(level.details, null, 2)}
                </pre>
              )}
            </div>
          ))}

          {validation.histogram_summary.length > 0 && (
            <>
              <div className="code-label" style={{ marginTop: 20 }}>Histogram Results</div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Histogram</th>
                    <th>Sessions</th>
                    <th>Total Value</th>
                    <th>Non-Zero Bins</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {validation.histogram_summary.map((h) => (
                    <tr key={h.histogram_name}>
                      <td><code>{h.histogram_name}</code></td>
                      <td>{h.sessions}</td>
                      <td>{typeof h.total_value === "number" ? h.total_value.toExponential(2) : h.total_value}</td>
                      <td>{h.non_zero_bins}</td>
                      <td><span className={`badge ${h.status.toLowerCase()}`}>{h.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}

      {deployment === "not_started" && !validation && (
        <div className="empty-state">
          <div className="icon">&#x1F680;</div>
          <div>Report not deployed yet</div>
          <div style={{ fontSize: 12 }}>
            Use the Deploy button to scaffold, deploy, and run the report.
          </div>
        </div>
      )}
    </div>
  );
}
