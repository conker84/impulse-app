import { useState, useMemo } from "react";
import Plot from "react-plotly.js";
import type { HistogramResult } from "../types";

interface Props {
  name: string;
  result: HistogramResult;
}

export default function HistogramChart({ name, result }: Props) {
  const [showRelative, setShowRelative] = useState(false);

  const seriesKeys = useMemo(() => Object.keys(result.series), [result.series]);
  const isSingleSeries = seriesKeys.length === 1 && seriesKeys[0] === "_all";

  const traces = useMemo(() => {
    return seriesKeys.map((key) => {
      const bins = result.series[key];
      return {
        x: bins.map((b) => b.bin_name),
        y: bins.map((b) => (showRelative ? b.relative_pct : b.hist_value)),
        name: isSingleSeries ? name : key,
        type: "bar" as const,
      };
    });
  }, [seriesKeys, result.series, showRelative, isSingleSeries, name]);

  const yLabel = showRelative
    ? "Relative (%)"
    : result.values_unit || (result.type === "duration" ? "seconds" : "value");

  const title = result.description || name;

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title" title={name}>{title}</span>
        <button
          className="chart-toggle-btn"
          onClick={() => setShowRelative((p) => !p)}
          title={showRelative ? "Show absolute values" : "Show relative (%)"}
        >
          {showRelative ? "Abs" : "%"}
        </button>
      </div>
      <Plot
        data={traces}
        layout={{
          autosize: true,
          margin: { t: 8, r: 16, b: 52, l: 56 },
          xaxis: { title: result.bins_unit || undefined, tickangle: -45 },
          yaxis: { title: yLabel },
          barmode: isSingleSeries ? "relative" : "group",
          showlegend: !isSingleSeries,
          legend: { orientation: "h", y: -0.25 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { color: "var(--text-primary)", size: 11 },
        }}
        config={{ responsive: true, displayModeBar: false }}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
