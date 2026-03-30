import type { DeploymentStatus, ValidationResults } from "../types";

interface Props {
  deployment: DeploymentStatus;
  validation: ValidationResults | null;
  runUrl: string | null;
  validating: boolean;
}

export default function ResultsTab({ deployment, validation, runUrl, validating }: Props) {
  return (
    <div>
      {runUrl && (
        <div className="card" style={{ borderLeft: "3px solid var(--primary)", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Last Job Run</div>
            <a
              href={runUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: 12 }}
            >
              View in Databricks &rarr;
            </a>
          </div>
        </div>
      )}

      {deployment === "completed" && !validation && validating && (
        <div className="card" style={{ textAlign: "center", padding: 16 }}>
          <span className="spinner" style={{ marginRight: 8 }} />
          Validating results...
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

      {deployment === "not_started" && !validation && !runUrl && (
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
