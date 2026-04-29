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

// Roll up per-event-instance values into a single number per (channel, label)
// using the same convention the old SQL used: min→MIN, max→MAX, count→SUM,
// everything else → mean.
function rollup(values: number[], label: string): number | null {
  if (values.length === 0) return null;
  if (values.length === 1) return values[0];
  if (label === "min") return Math.min(...values);
  if (label === "max") return Math.max(...values);
  if (label === "count") return values.reduce((a, b) => a + b, 0);
  return values.reduce((a, b) => a + b, 0) / values.length;
}

export default function StatisticsTable({ name, result }: Props) {
  const title = result.description || name;

  // Group raw rows: channel -> label -> [values...]
  const grouped = new Map<string, Map<string, number[]>>();
  for (const row of result.rows) {
    if (!grouped.has(row.channel_name)) grouped.set(row.channel_name, new Map());
    const labelMap = grouped.get(row.channel_name)!;
    if (!labelMap.has(row.aggregation_label)) labelMap.set(row.aggregation_label, []);
    labelMap.get(row.aggregation_label)!.push(row.value);
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
            {result.channel_names.map((ch) => (
              <tr key={ch}>
                <td className="stats-signal-name" title={ch}>{ch}</td>
                {result.stat_labels.map((label) => {
                  const vals = grouped.get(ch)?.get(label) || [];
                  const val = rollup(vals, label);
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
