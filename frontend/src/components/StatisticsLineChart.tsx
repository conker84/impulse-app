import { useMemo, useState } from "react";
import Plot from "react-plotly.js";
import type { StatisticsResult } from "../types";
import { BASE_CONFIG, mergeLayout } from "../plotlyTheme";

interface Props {
  name: string;
  result: StatisticsResult;
}

const STAT_STYLE: Record<string, { dash: "solid" | "dash" | "dot"; color: string; width: number }> = {
  mean:   { dash: "solid", color: "#3b82f6", width: 2 },
  median: { dash: "dash",  color: "#f97316", width: 2 },
  min:    { dash: "dot",   color: "#22c55e", width: 1.5 },
  max:    { dash: "dot",   color: "#ef4444", width: 1.5 },
};

function pickDefaultXChannel(channels: string[]): string {
  return channels.find((c) => /distance|odometer|odo|km/i.test(c)) || channels[0] || "";
}

export default function StatisticsLineChart({ name, result }: Props) {
  const title = result.description || name;

  const [xChannel, setXChannel] = useState<string>(() => pickDefaultXChannel(result.channel_names));
  const [yChannels, setYChannels] = useState<string[]>(() => {
    const xDefault = pickDefaultXChannel(result.channel_names);
    return result.channel_names.filter((c) => c !== xDefault);
  });
  const [statLabels, setStatLabels] = useState<string[]>(() => result.stat_labels.slice());
  const [showSettings, setShowSettings] = useState(false);

  const byInstance = useMemo(() => {
    const map = new Map<number, Map<string, Map<string, number>>>();
    for (const r of result.rows) {
      let chMap = map.get(r.event_instance_id);
      if (!chMap) { chMap = new Map(); map.set(r.event_instance_id, chMap); }
      let lblMap = chMap.get(r.channel_name);
      if (!lblMap) { lblMap = new Map(); chMap.set(r.channel_name, lblMap); }
      lblMap.set(r.aggregation_label, r.value);
    }
    return map;
  }, [result]);

  const orderedInstances = useMemo(() => {
    if (!xChannel) return [] as { instanceId: number; x: number }[];
    const items: { instanceId: number; x: number }[] = [];
    for (const [instanceId, chMap] of byInstance) {
      const labels = chMap.get(xChannel);
      if (!labels) continue;
      const xVal = labels.get("min") ?? labels.get("mean") ?? labels.get("median") ?? labels.get("max");
      if (xVal == null) continue;
      items.push({ instanceId, x: xVal });
    }
    items.sort((a, b) => a.x - b.x);
    return items;
  }, [byInstance, xChannel]);

  const traces = useMemo(() => {
    if (orderedInstances.length === 0 || yChannels.length === 0) return [];
    const xs = orderedInstances.map((i) => i.x);
    const t: any[] = [];
    yChannels.forEach((ch, yIdx) => {
      const axisRef = yIdx === 0 ? "y" : `y${yIdx + 1}`;
      const xAxisRef = yIdx === 0 ? "x" : `x${yIdx + 1}`;

      const statSeries: Record<string, (number | null)[]> = {};
      for (const stat of statLabels) {
        statSeries[stat] = orderedInstances.map(({ instanceId }) => {
          const v = byInstance.get(instanceId)?.get(ch)?.get(stat);
          return v == null ? null : v;
        });
      }

      if (statLabels.includes("min") && statLabels.includes("max")) {
        t.push({
          x: xs,
          y: statSeries["max"],
          xaxis: xAxisRef,
          yaxis: axisRef,
          type: "scatter",
          mode: "lines",
          line: { width: 0 },
          showlegend: false,
          hoverinfo: "skip",
          name: `${ch} max-band`,
        });
        t.push({
          x: xs,
          y: statSeries["min"],
          xaxis: xAxisRef,
          yaxis: axisRef,
          type: "scatter",
          mode: "lines",
          line: { width: 0 },
          fill: "tonexty",
          fillcolor: "rgba(59,130,246,0.10)",
          showlegend: false,
          hoverinfo: "skip",
          name: `${ch} min-band`,
        });
      }

      for (const stat of statLabels) {
        const style = STAT_STYLE[stat] || { dash: "solid", color: "#94a3b8", width: 1.5 };
        t.push({
          x: xs,
          y: statSeries[stat],
          xaxis: xAxisRef,
          yaxis: axisRef,
          type: "scatter",
          mode: "lines",
          name: stat,
          legendgroup: stat,
          showlegend: yIdx === 0,
          line: { dash: style.dash, color: style.color, width: style.width },
          hovertemplate: `<b>${ch}</b> %{y:.3g}<br>${stat} @ ${xChannel}=%{x:.3g}<extra></extra>`,
        });
      }
    });
    return t;
  }, [orderedInstances, yChannels, statLabels, byInstance, xChannel]);

  const layout = useMemo(() => {
    const n = yChannels.length;
    if (n === 0) return mergeLayout({});
    const gap = 0.04;
    const rowH = (1 - gap * (n - 1)) / n;
    const overrides: Record<string, any> = {
      margin: { t: 8, r: 16, b: 56, l: 80 },
      showlegend: true,
      legend: { orientation: "h", y: -0.12, font: { size: 12, color: "#c8cad4" } },
    };
    yChannels.forEach((ch, idx) => {
      const top = 1 - idx * (rowH + gap);
      const bottom = top - rowH;
      const yKey = idx === 0 ? "yaxis" : `yaxis${idx + 1}`;
      const xKey = idx === 0 ? "xaxis" : `xaxis${idx + 1}`;
      overrides[yKey] = {
        domain: [Math.max(0, bottom), Math.min(1, top)],
        title: { text: ch, standoff: 10 },
        gridcolor: "rgba(128,128,128,0.15)",
        zerolinecolor: "rgba(128,128,128,0.25)",
        tickfont: { size: 11, color: "#c8cad4" },
        automargin: true,
      };
      overrides[xKey] = {
        anchor: idx === 0 ? "y" : `y${idx + 1}`,
        gridcolor: "rgba(128,128,128,0.15)",
        zerolinecolor: "rgba(128,128,128,0.25)",
        tickfont: { size: 11, color: "#c8cad4" },
        showticklabels: idx === n - 1,
        title: idx === n - 1 ? { text: xChannel, standoff: 10 } : undefined,
        matches: idx === 0 ? undefined : "x",
        automargin: true,
      };
    });
    return mergeLayout(overrides);
  }, [yChannels, xChannel]);

  const toggleY = (ch: string) => {
    setYChannels((prev) => prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch]);
  };
  const toggleStat = (lbl: string) => {
    setStatLabels((prev) => prev.includes(lbl) ? prev.filter((s) => s !== lbl) : [...prev, lbl]);
  };

  const chartHeight = Math.max(560, yChannels.length * 220);

  return (
    <div className="chart-card stats-line-card">
      <div className="chart-card-header">
        <span className="chart-card-title" title={name}>{title}</span>
        <button
          className="action-btn"
          style={{ marginLeft: "auto", fontSize: 11, padding: "2px 8px" }}
          onClick={() => setShowSettings((s) => !s)}
        >
          {showSettings ? "Hide" : "Configure"}
        </button>
      </div>

      {showSettings && (
        <div className="stats-line-settings" style={{
          padding: "8px 12px",
          background: "rgba(30,41,59,0.4)",
          borderBottom: "1px solid rgba(128,128,128,0.15)",
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 12,
          fontSize: 12,
        }}>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>X-axis</div>
            <select
              className="form-input"
              style={{ width: "100%", fontSize: 12 }}
              value={xChannel}
              onChange={(e) => {
                const newX = e.target.value;
                setXChannel(newX);
                setYChannels((prev) => prev.filter((c) => c !== newX));
              }}
            >
              {result.channel_names.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Y-axis channels</div>
            <div style={{ maxHeight: 140, overflowY: "auto" }}>
              {result.channel_names.filter((c) => c !== xChannel).map((c) => (
                <label key={c} style={{ display: "block", padding: "1px 0" }}>
                  <input type="checkbox" checked={yChannels.includes(c)} onChange={() => toggleY(c)} />{" "}
                  {c}
                </label>
              ))}
            </div>
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Stats</div>
            {result.stat_labels.map((lbl) => (
              <label key={lbl} style={{ display: "block", padding: "1px 0" }}>
                <input type="checkbox" checked={statLabels.includes(lbl)} onChange={() => toggleStat(lbl)} />{" "}
                <span style={{ color: STAT_STYLE[lbl]?.color || "inherit" }}>{lbl}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {orderedInstances.length < 2 ? (
        <div style={{ padding: 16, fontSize: 12, color: "var(--text-muted)" }}>
          Only {orderedInstances.length} event instance(s) — need at least 2 to draw a line. Use a periodic event (e.g. periodic_distance) when defining this statistics aggregation.
        </div>
      ) : yChannels.length === 0 ? (
        <div style={{ padding: 16, fontSize: 12, color: "var(--text-muted)" }}>
          Pick at least one Y-axis channel via Configure.
        </div>
      ) : (
        <Plot
          data={traces}
          layout={layout}
          config={BASE_CONFIG}
          useResizeHandler
          style={{ width: "100%", height: chartHeight }}
        />
      )}
    </div>
  );
}
