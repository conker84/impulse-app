/**
 * Shared Plotly theme — all chart components import from here so colours,
 * grid lines, fonts, and modebar config are consistent across chart types.
 *
 * Colour values use CSS custom properties where Plotly supports strings
 * (font.color, paper/plot bgcolor). For traces we use a fixed palette that
 * works on both light and dark backgrounds.
 */

// Trace colour palette — 10 distinct colours, legible on both themes.
export const PALETTE = [
  "#3b82f6", // blue
  "#f97316", // orange
  "#22c55e", // green
  "#ef4444", // red
  "#a855f7", // purple
  "#eab308", // yellow
  "#06b6d4", // cyan
  "#ec4899", // pink
  "#64748b", // slate
  "#14b8a6", // teal
];

/** Shared Plotly layout defaults merged into every chart. */
export const BASE_LAYOUT: Record<string, any> = {
  autosize: true,
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  font: { color: "var(--text-primary)", size: 11, family: "inherit" },
  margin: { t: 8, r: 16, b: 56, l: 56 },
  xaxis: {
    gridcolor: "rgba(128,128,128,0.15)",
    zerolinecolor: "rgba(128,128,128,0.25)",
    tickfont: { size: 10 },
  },
  yaxis: {
    gridcolor: "rgba(128,128,128,0.15)",
    zerolinecolor: "rgba(128,128,128,0.25)",
    tickfont: { size: 10 },
  },
  hoverlabel: {
    bgcolor: "var(--bg-secondary)",
    bordercolor: "var(--border)",
    font: { color: "var(--text-primary)", size: 11 },
  },
};

/** Shared Plotly config — enables useful modebar buttons. */
export const BASE_CONFIG: Record<string, any> = {
  responsive: true,
  displayModeBar: true,
  displaylogo: false,
  modeBarButtonsToRemove: [
    "select2d",
    "lasso2d",
    "autoScale2d",
    "hoverClosestCartesian",
    "hoverCompareCartesian",
    "toggleSpikelines",
  ] as any[],
  modeBarButtonsToAdd: [] as any[],
};

/** Heatmap-specific colour scale. */
export const HEATMAP_COLORSCALE: [number, string][] = [
  [0, "#1e293b"],
  [0.2, "#1e40af"],
  [0.4, "#7c3aed"],
  [0.6, "#db2777"],
  [0.8, "#f97316"],
  [1.0, "#fbbf24"],
];

/** Merge base layout with chart-specific overrides. */
export function mergeLayout(
  overrides: Record<string, any>,
): Record<string, any> {
  return {
    ...BASE_LAYOUT,
    ...overrides,
    font: { ...BASE_LAYOUT.font, ...overrides.font },
    xaxis: { ...BASE_LAYOUT.xaxis, ...overrides.xaxis },
    yaxis: { ...BASE_LAYOUT.yaxis, ...overrides.yaxis },
    hoverlabel: { ...BASE_LAYOUT.hoverlabel, ...overrides.hoverlabel },
  };
}
