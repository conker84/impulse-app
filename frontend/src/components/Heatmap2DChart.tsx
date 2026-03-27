import { useMemo } from "react";
import Plot from "react-plotly.js";
import type { Heatmap2DResult } from "../types";
import { HEATMAP_COLORSCALE, BASE_CONFIG, mergeLayout } from "../plotlyTheme";

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
      colorscale: HEATMAP_COLORSCALE,
      colorbar: {
        title: { text: result.values_unit || "value", side: "right" as const },
        tickfont: { size: 10 },
      },
      hoverongaps: false,
      hovertemplate:
        `<b>X:</b> %{x}<br><b>Y:</b> %{y}<br><b>Value:</b> %{z:.2f} ${result.values_unit}<extra></extra>`,
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
        layout={mergeLayout({
          margin: { t: 8, r: 16, b: 64, l: 64 },
          xaxis: { title: result.x_bins_unit || undefined, tickangle: -45 },
          yaxis: { title: result.y_bins_unit || undefined },
        })}
        config={BASE_CONFIG}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
