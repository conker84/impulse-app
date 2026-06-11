import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HistogramBuilder from "./HistogramBuilder";
import type { SignalDefinition } from "../types";

const SIGNALS = [
  { var_name: "rpm", signal_type: "physical", description: "" },
  { var_name: "odo", signal_type: "physical", description: "" },
] as unknown as SignalDefinition[];

function setup(overrides: Partial<React.ComponentProps<typeof HistogramBuilder>> = {}) {
  const onAdd = vi.fn();
  const onSuggestBins = vi.fn();
  const props = {
    signals: SIGNALS,
    events: [],
    existingNames: new Set<string>(),
    onAdd,
    onSuggestBins,
    ...overrides,
  };
  render(<HistogramBuilder {...props} />);
  return { onAdd, onSuggestBins, user: userEvent.setup() };
}

const binsBox = () => screen.getByPlaceholderText("0, 500, 1000, 1500, 2000, ...");
const addBtn = () => screen.getByRole("button", { name: "Add Histogram" });

describe("HistogramBuilder", () => {
  it("hides the form until a histogram type is chosen", async () => {
    const { user } = setup();
    expect(screen.queryByText("Bins")).not.toBeInTheDocument();
    await user.click(screen.getByText("Duration"));
    expect(screen.getByText("Bins")).toBeInTheDocument();
  });

  it("keeps Add disabled until a signal and >=2 valid bins are entered", async () => {
    const { user } = setup();
    await user.click(screen.getByText("Duration"));
    expect(addBtn()).toBeDisabled();

    await user.selectOptions(screen.getAllByRole("combobox")[0], "rpm");
    expect(addBtn()).toBeDisabled(); // bins still empty

    await user.type(binsBox(), "1000"); // single value is not enough
    expect(addBtn()).toBeDisabled();

    await user.type(binsBox(), ", 2000");
    expect(addBtn()).toBeEnabled();
  });

  it("treats non-numeric bin input as invalid", async () => {
    const { user } = setup();
    await user.click(screen.getByText("Duration"));
    await user.selectOptions(screen.getAllByRole("combobox")[0], "rpm");
    await user.type(binsBox(), "0, abc, 2000");
    expect(addBtn()).toBeDisabled();
  });

  it("emits a well-formed duration histogram payload", async () => {
    const { user, onAdd } = setup();
    await user.click(screen.getByText("Duration"));
    await user.selectOptions(screen.getAllByRole("combobox")[0], "rpm");
    await user.type(binsBox(), "0, 1000, 2000");
    await user.click(addBtn());

    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd.mock.calls[0][0]).toMatchObject({
      agg_kind: "histogram_1d",
      histogram_type: "duration",
      signal_ref: "rpm",
      bins: [0, 1000, 2000],
      max_duration: null,
      weight_signal_ref: null,
    });
    // auto-generated name when none typed
    expect(onAdd.mock.calls[0][0].name).toBe("rpm_duration_p1");
  });

  it("requires a weight signal before a distance histogram can be added", async () => {
    const { user, onAdd } = setup();
    await user.click(screen.getByText("Distance"));
    await user.selectOptions(screen.getAllByRole("combobox")[0], "rpm"); // signal
    await user.type(binsBox(), "0, 10, 20");
    expect(addBtn()).toBeDisabled(); // no weight yet

    await user.selectOptions(screen.getAllByRole("combobox")[1], "odo"); // weight
    expect(addBtn()).toBeEnabled();

    await user.click(addBtn());
    expect(onAdd.mock.calls[0][0]).toMatchObject({
      histogram_type: "distance",
      weight_signal_ref: "odo",
    });
  });

  it("converts the max-duration cap from seconds to nanoseconds", async () => {
    const { user, onAdd } = setup();
    await user.click(screen.getByText("Duration"));
    await user.selectOptions(screen.getAllByRole("combobox")[0], "rpm");
    await user.type(binsBox(), "0, 1000");
    await user.click(screen.getByLabelText("Limit max sample duration"));
    await user.type(screen.getByPlaceholderText("e.g. 100"), "100");
    await user.click(addBtn());
    expect(onAdd.mock.calls[0][0].max_duration).toBe(100 * 1e9);
  });

  it("blocks a duplicate name and surfaces an error instead of calling onAdd", async () => {
    const { user, onAdd } = setup({ existingNames: new Set(["dup"]) });
    await user.click(screen.getByText("Duration"));
    await user.selectOptions(screen.getAllByRole("combobox")[0], "rpm");
    await user.type(binsBox(), "0, 1000");
    await user.type(screen.getByPlaceholderText("rpm_duration_p1"), "dup");
    await user.click(addBtn());

    expect(onAdd).not.toHaveBeenCalled();
    expect(screen.getByText(/already exists/)).toBeInTheDocument();
  });

  it("auto-fills bins + name from a suggestion, de-duplicating the name", async () => {
    const onSuggestBins = vi.fn().mockResolvedValue({
      bins: [0, 1, 2],
      bins_unit: "rpm",
      description: "suggested",
      name: "rpm_hist",
    });
    const { user } = setup({ onSuggestBins, existingNames: new Set(["rpm_hist"]) });
    await user.click(screen.getByText("Duration"));
    await user.selectOptions(screen.getAllByRole("combobox")[0], "rpm");
    await user.click(screen.getByRole("button", { name: "Auto-fill" }));

    expect(onSuggestBins).toHaveBeenCalledWith("duration", "rpm");
    expect(binsBox()).toHaveValue("0, 1, 2");
    // "rpm_hist" already exists -> deduped to rpm_hist_2
    expect(screen.getByPlaceholderText("rpm_duration_p1")).toHaveValue("rpm_hist_2");
  });
});
