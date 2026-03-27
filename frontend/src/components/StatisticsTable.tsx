import type { StatisticsResult } from "../types";

interface Props {
  name: string;
  result: StatisticsResult;
}

function formatValue(val: number): string {
  if (Math.abs(val) >= 1e6) return val.toExponential(3);
  if (Math.abs(val) >= 100) return val.toFixed(1);
  if (Math.abs(val) >= 1) return val.toFixed(3);
  if (val === 0) return "0";
  return val.toFixed(4);
}

export default function StatisticsTable({ name, result }: Props) {
  const title = result.description || name;

  // Build a lookup: signal -> label -> value
  const lookup = new Map<string, Map<string, number>>();
  for (const row of result.rows) {
    if (!lookup.has(row.signal_name)) lookup.set(row.signal_name, new Map());
    lookup.get(row.signal_name)!.set(row.aggregation_label, row.value);
  }

  return (
    <div className="chart-card stats-card">
      <div className="chart-card-header">
        <span className="chart-card-title" title={name}>{title}</span>
        <span className="chart-type-badge stats-badge">Stats</span>
      </div>
      <div className="stats-table-wrapper">
        <table className="stats-table">
          <thead>
            <tr>
              <th>Signal</th>
              {result.stat_labels.map((label) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.signal_names.map((sig) => (
              <tr key={sig}>
                <td className="stats-signal-name" title={sig}>{sig}</td>
                {result.stat_labels.map((label) => {
                  const val = lookup.get(sig)?.get(label);
                  return (
                    <td key={label} className="stats-value">
                      {val != null ? formatValue(val) : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
