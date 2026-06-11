import { describe, it, expect } from "vitest";
import {
  PALETTE,
  BASE_LAYOUT,
  BASE_CONFIG,
  HEATMAP_COLORSCALE,
  mergeLayout,
} from "./plotlyTheme";

describe("palette + constants", () => {
  it("exposes 10 distinct hex colours", () => {
    expect(PALETTE).toHaveLength(10);
    expect(new Set(PALETTE).size).toBe(10);
    for (const c of PALETTE) {
      expect(c).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("heatmap colourscale is monotonically increasing from 0 to 1", () => {
    const stops = HEATMAP_COLORSCALE.map(([stop]) => stop);
    expect(stops[0]).toBe(0);
    expect(stops[stops.length - 1]).toBe(1);
    for (let i = 1; i < stops.length; i++) {
      expect(stops[i]).toBeGreaterThan(stops[i - 1]);
    }
  });

  it("base config hides the plotly logo and disables lasso/select", () => {
    expect(BASE_CONFIG.displaylogo).toBe(false);
    expect(BASE_CONFIG.modeBarButtonsToRemove).toContain("lasso2d");
    expect(BASE_CONFIG.modeBarButtonsToRemove).toContain("select2d");
  });
});

describe("mergeLayout", () => {
  it("returns base layout untouched when no overrides given", () => {
    const merged = mergeLayout({});
    expect(merged.autosize).toBe(true);
    expect(merged.paper_bgcolor).toBe("transparent");
    expect(merged.font).toEqual(BASE_LAYOUT.font);
  });

  it("shallow-merges top-level keys", () => {
    const merged = mergeLayout({ showlegend: true, autosize: false });
    expect(merged.showlegend).toBe(true);
    expect(merged.autosize).toBe(false);
    // unrelated base keys preserved
    expect(merged.plot_bgcolor).toBe("transparent");
  });

  it("deep-merges nested font/axis/hoverlabel rather than replacing them", () => {
    const merged = mergeLayout({
      font: { size: 20 },
      xaxis: { title: "Time" },
      yaxis: { type: "log" },
      hoverlabel: { align: "left" },
    });
    // overridden field applied...
    expect(merged.font.size).toBe(20);
    // ...while sibling base fields survive
    expect(merged.font.color).toBe(BASE_LAYOUT.font.color);
    expect(merged.xaxis.title).toBe("Time");
    expect(merged.xaxis.gridcolor).toBe(BASE_LAYOUT.xaxis.gridcolor);
    expect(merged.yaxis.type).toBe("log");
    expect(merged.yaxis.tickfont).toEqual(BASE_LAYOUT.yaxis.tickfont);
    expect(merged.hoverlabel.align).toBe("left");
    expect(merged.hoverlabel.bgcolor).toBe(BASE_LAYOUT.hoverlabel.bgcolor);
  });

  it("does not mutate the shared BASE_LAYOUT", () => {
    const before = JSON.stringify(BASE_LAYOUT);
    mergeLayout({ font: { size: 99 }, autosize: false });
    expect(JSON.stringify(BASE_LAYOUT)).toBe(before);
  });
});
