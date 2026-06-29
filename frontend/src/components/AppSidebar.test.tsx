import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AppSidebar from "./AppSidebar";

describe("AppSidebar", () => {
  it("fires the right handler for each menu item", async () => {
    const onHome = vi.fn();
    const onNewReport = vi.fn();
    const onTimeSeries = vi.fn();
    const onSettings = vi.fn();
    render(
      <AppSidebar
        active="landing"
        onHome={onHome}
        onNewReport={onNewReport}
        onTimeSeries={onTimeSeries}
        onSettings={onSettings}
      />
    );

    await userEvent.click(screen.getByText("New Report"));
    await userEvent.click(screen.getByText("Explore Time Series"));
    await userEvent.click(screen.getByText("Settings"));
    await userEvent.click(screen.getByTitle("Impulse — Home"));

    expect(onNewReport).toHaveBeenCalledOnce();
    expect(onTimeSeries).toHaveBeenCalledOnce();
    expect(onSettings).toHaveBeenCalledOnce();
    expect(onHome).toHaveBeenCalledOnce();
  });

  it("highlights the active view", () => {
    const { rerender } = render(
      <AppSidebar active="timeseries" onHome={vi.fn()} onNewReport={vi.fn()} onTimeSeries={vi.fn()} />
    );
    expect(screen.getByText("Explore Time Series").closest("button")).toHaveClass("active");
    expect(screen.getByText("New Report").closest("button")).not.toHaveClass("active");

    rerender(
      <AppSidebar active="editor" onHome={vi.fn()} onNewReport={vi.fn()} onTimeSeries={vi.fn()} />
    );
    expect(screen.getByText("New Report").closest("button")).toHaveClass("active");
    expect(screen.getByText("Explore Time Series").closest("button")).not.toHaveClass("active");
  });

  it("hides Settings when onSettings is not provided (local mode)", () => {
    render(<AppSidebar active="landing" onHome={vi.fn()} onNewReport={vi.fn()} onTimeSeries={vi.fn()} />);
    expect(screen.queryByText("Settings")).toBeNull();
  });
});
