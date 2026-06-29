import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// VisualizeView transitively imports Plotly (via the chart components), which
// cannot initialise under jsdom. Stub the wrapper to keep the import chain loadable.
vi.mock("react-plotly.js", () => ({ default: () => null }));

// No aggregations needed — we only assert the sidebar's Description section.
vi.mock("../api", () => ({
  fetchVisualizeAggregations: vi.fn().mockResolvedValue({ aggregations: [] }),
  fetchHistogramData: vi.fn(),
  fetchHistogram2DData: vi.fn(),
  fetchStatisticsData: vi.fn(),
}));

import VisualizeView from "./VisualizeView";
import type { DataSourceConfig } from "../types";

const dataSources = {
  destination_catalog: "cat",
  destination_schema: "sch",
  table_prefix: "pfx",
} as unknown as DataSourceConfig;

describe("VisualizeView description section", () => {
  it("renders the description before the Aggregations section", async () => {
    render(
      <VisualizeView
        dataSources={dataSources}
        reportName="My Report"
        reportDescription="Fleet braking analysis"
        onBack={vi.fn()}
      />
    );

    // Wait for the post-load sidebar to render.
    await screen.findByText("Aggregations");

    const desc = screen.getByText("Fleet braking analysis");
    const aggs = screen.getByText("Aggregations");
    expect(desc).toBeInTheDocument();
    // Description must come before Aggregations in document order.
    expect(desc.compareDocumentPosition(aggs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("omits the Description section when no description is given", async () => {
    render(
      <VisualizeView dataSources={dataSources} reportName="My Report" onBack={vi.fn()} />
    );
    await screen.findByText("Aggregations");
    expect(screen.queryByText("Description")).toBeNull();
  });
});
