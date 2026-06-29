import { describe, it, expect, vi } from "vitest";

// The module imports react-plotly.js at the top, which cannot initialise under
// jsdom. We only test the pure helpers, so stub the Plotly wrapper.
vi.mock("react-plotly.js", () => ({ default: () => null }));

import { assignAxes, formatPointCount, toEpochMs } from "./TimeSeriesView";
import type { TimeSeriesSignal } from "../types";

function sig(channel_id: number, unit: string, min: number | null = 0, max: number | null = 0): TimeSeriesSignal {
  return { channel_id, channel_name: `ch${channel_id}`, unit, sample_count: 0, min_value: min, max_value: max, mean_value: null };
}

describe("formatPointCount", () => {
  it("formats by magnitude", () => {
    expect(formatPointCount(999)).toBe("999");
    expect(formatPointCount(1_500)).toBe("1.5K");
    expect(formatPointCount(2_300_000)).toBe("2.3M");
    expect(formatPointCount(4_100_000_000)).toBe("4.1B");
  });
});

describe("toEpochMs", () => {
  it("adds the seconds offset (in ms) to the base", () => {
    expect(toEpochMs(0, 1000)).toBe(1000);
    expect(toEpochMs(1.5, 1000)).toBe(2500);
  });
});

describe("assignAxes", () => {
  it("returns empty when nothing is selected", () => {
    const r = assignAxes([sig(1, "kph")], new Set());
    expect(r.assignments.size).toBe(0);
    expect(r.useAxisTags).toBe(false);
  });

  it("puts a single unit on the left with the unit as the label", () => {
    const signals = [sig(1, "kph"), sig(2, "kph")];
    const r = assignAxes(signals, new Set([1, 2]));
    expect(r.leftLabel).toBe("kph");
    expect(r.rightLabel).toBe("");
    expect(r.useAxisTags).toBe(false);
    expect(r.assignments.get(1)).toBe("left");
    expect(r.assignments.get(2)).toBe("left");
  });

  it("splits two units one per axis, larger group on the left, no tags", () => {
    const signals = [sig(1, "kph"), sig(2, "kph"), sig(3, "rpm")];
    const r = assignAxes(signals, new Set([1, 2, 3]));
    expect(r.useAxisTags).toBe(false);
    expect(r.leftLabel).toBe("kph");
    expect(r.rightLabel).toBe("rpm");
    expect(r.assignments.get(1)).toBe("left");
    expect(r.assignments.get(3)).toBe("right");
  });

  it("clusters 3+ units into two groups by median range, with tags", () => {
    const signals = [sig(1, "A", 0, 10), sig(2, "B", 0, 100), sig(3, "C", 0, 1000)];
    const r = assignAxes(signals, new Set([1, 2, 3]));
    expect(r.useAxisTags).toBe(true);
    // Highest-range unit (C) lands on the right; lower ones on the left.
    expect(r.assignments.get(3)).toBe("right");
    expect(r.assignments.get(1)).toBe("left");
    expect(r.assignments.get(2)).toBe("left");
    expect(r.rightLabel).toBe("C");
  });
});
