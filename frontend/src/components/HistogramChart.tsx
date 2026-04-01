import { useState, useMemo } from "react";
import Plot from "react-plotly.js";
import type { HistogramResult } from "../types";
import { PALETTE, BASE_CONFIG, mergeLayout } from "../plotlyTheme";

interface Props {
  name: string;
  result: HistogramResult;
}

type BarMode = "abs" | "relative" | "stacked";

export default function HistogramChart({ name, result }: Props) {
  const [mode, setMode] = useState<BarMode>("abs");

  const seriesKeys = useMemo(() => Object.keys(result.series), [result.series]);
  const isSingleSeries = seriesKeys.length === 1 && seriesKeys[0] === "_all";
  const isMulti = !isSingleSeries;

  const hasData = useMemo(() => {
    return seriesKeys.some((key) =>
      result.series[key].some((b) => b.hist_value !== 0),
    );
  }, [seriesKeys, result.series]);

  const traces = useMemo(() => {
    return seriesKeys.map((key, i) => {
      const bins = result.series[key];
      const showRel = mode === "relative";
      return {
        x: bins.map((b) => b.bin_name),
        y: bins.map((b) => (showRel ? b.relative_pct : b.hist_value)),
        name: isSingleSeries ? name : key,
        type: "bar" as const,
        marker: { color: PALETTE[i % PALETTE.length] },
        hovertemplate: bins.map((b) => {
          const val = showRel ? b.relative_pct : b.hist_value;
          const unit = showRel ? "%" : (result.values_unit || "");
          return `<b>${b.bin_name}</b><br>` +
            `${b.lower_bound} – ${b.upper_bound} ${result.bins_unit || ""}<br>` +
            `Value: ${showRel ? val.toFixed(1) : val.toFixed(2)} ${unit}` +
            (showRel ? "" : `<br>Relative: ${b.relative_pct.toFixed(1)}%`) +
            `<extra>${isSingleSeries ? "" : key}</extra>`;
        }),
      };
    });
  }, [seriesKeys, result, mode, isSingleSeries, name]);

  const yLabel = mode === "relative"
    ? "Relative (%)"
    : result.values_unit || (result.type === "duration" ? "seconds" : "value");

  const title = result.description || name;

  const barmode = mode === "stacked" ? "stack" : (isSingleSeries ? "relative" : "group");

  const nextMode = (): BarMode => {
    if (mode === "abs") return "relative";
    if (mode === "relative" && isMulti) return "stacked";
    return "abs";
  };

  const modeLabel = mode === "abs" ? "%" : mode === "relative" && isMulti ? "Stack" : "Abs";

  if (!hasData) {
    return (
      <div className="chart-card">
        <div className="chart-card-header">
          <span className="chart-card-title" title={name}>{title}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, color: "var(--text-muted)", fontSize: 14 }}>
          No data available — the report job produced no results for this histogram.
        </div>
      </div>
    );
  }

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title" title={name}>{title}</span>
        <button
          className="chart-toggle-btn"
          onClick={() => setMode(nextMode())}
          title={
            mode === "abs" ? "Show relative (%)"
            : mode === "relative" && isMulti ? "Show stacked bars"
            : "Show absolute values"
          }
        >
          {modeLabel}
        </button>
      </div>
      <Plot
        data={traces}
        layout={mergeLayout({
          margin: { t: 8, r: 16, b: 110, l: 64 },
          xaxis: { title: result.bins_unit ? `Value [${result.bins_unit}]` : "Value", tickangle: -45 },
          yaxis: { title: yLabel },
          barmode: barmode as any,
          showlegend: isMulti,
          legend: { orientation: "h", y: -0.3, font: { size: 10 } },
        })}
        config={BASE_CONFIG}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
