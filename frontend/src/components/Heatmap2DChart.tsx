import { useMemo } from "react";
import Plot from "react-plotly.js";
import type { Heatmap2DResult } from "../types";

interface Props {
  name: string;
  result: Heatmap2DResult;
}

export default function Heatmap2DChart({ name, result }: Props) {
  const trace = useMemo(() => {
    return {
      x: result.x_labels,
      y: result.y_labels,
      z: result.z,
      type: "heatmap" as const,
      colorscale: "YlOrRd",
      colorbar: {
        title: result.values_unit || "value",
        titleside: "right" as const,
      },
      hoverongaps: false,
      hovertemplate:
        `X: %{x}<br>Y: %{y}<br>Value: %{z:.2f} ${result.values_unit}<extra></extra>`,
    };
  }, [result]);

  const title = result.description || name;

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title" title={name}>{title}</span>
        <span className="chart-type-badge">2D</span>
      </div>
      <Plot
        data={[trace]}
        layout={{
          autosize: true,
          margin: { t: 8, r: 16, b: 64, l: 64 },
          xaxis: {
            title: result.x_bins_unit || undefined,
            tickangle: -45,
          },
          yaxis: {
            title: result.y_bins_unit || undefined,
          },
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
