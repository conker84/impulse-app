import type { SignalDefinition } from "../types";

interface Props {
  signals: SignalDefinition[];
}

export default function SignalsTab({ signals }: Props) {
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
    <table className="data-table">
      <thead>
        <tr>
          <th>Variable</th>
          <th>Type</th>
          <th>Alias / Expression</th>
          <th>Eval Type</th>
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
          </tr>
        ))}
      </tbody>
    </table>
  );
}
