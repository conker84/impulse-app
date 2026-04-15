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
        tickfont: { size: 12, color: "#c8cad4" },
      },
      hoverongaps: false,
      hovertemplate:
        `<b>X:</b> %{x}<br><b>Y:</b> %{y}<br><b>Value:</b> %{z:.2f} ${result.values_unit}<extra></extra>`,
    };
  }, [result]);

  const title = result.description || name;

  // Build axis labels: "signal_name [unit]" or just "unit" or just "signal_name"
  const xTitle = result.x_signal_label && result.x_bins_unit
    ? `${result.x_signal_label} [${result.x_bins_unit}]`
    : result.x_signal_label || result.x_bins_unit || undefined;
  const yTitle = result.y_signal_label && result.y_bins_unit
    ? `${result.y_signal_label} [${result.y_bins_unit}]`
    : result.y_signal_label || result.y_bins_unit || undefined;

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title" title={name}>{title}</span>
        <span className="chart-type-badge">2D</span>
      </div>
      <Plot
        data={[trace]}
        layout={mergeLayout({
          margin: { t: 8, r: 16, b: 120, l: 120 },
          xaxis: { title: xTitle, tickangle: -45, automargin: true },
          yaxis: { title: yTitle, automargin: true },
        })}
        config={BASE_CONFIG}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
