import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// PreviewPanel transitively imports Plotly (via the chart components), which
// cannot initialise under jsdom. The report_name step renders none of it, so
// stub the Plotly wrapper to keep the import chain loadable.
vi.mock("react-plotly.js", () => ({ default: () => null }));

import PreviewPanel from "./PreviewPanel";
import type { ReportState, WizardStep } from "../types";

const WIZARD_STEPS: { key: WizardStep; label: string; icon: string }[] = [
  { key: "source_data", label: "Source Data", icon: "" },
  { key: "report_name", label: "Report Name", icon: "" },
  { key: "vehicles", label: "Vehicles", icon: "" },
  { key: "channels", label: "Channels", icon: "" },
  { key: "aggregations", label: "Aggregations", icon: "" },
  { key: "ready", label: "Ready", icon: "" },
];

function makeState(overrides: Partial<ReportState> = {}): ReportState {
  return {
    name: "",
    description: "",
    creator: "",
    wizard_step: "report_name",
    source_data: {
      mode: "none",
      upload_catalog: "",
      upload_schema: "",
      upload_volume: "",
      upload_volume_path: "",
      uploaded_files: [],
      silver_catalog: "",
      silver_schema: "",
      ingest_run_id: null,
      ingest_run_url: null,
      ingest_status: "not_started",
    },
    available_channels: [],
    signal_candidates: [],
    signals: [],
    events: [],
    aggregations: [],
    vehicle_candidates: [],
    vehicles: [],
    data_sources: {
      container_metrics: "",
      channel_metrics: "",
      channels: [],
      aliases: null,
      aliases_copy_table_name: null,
      device_aliases: null,
      device_aliases_copy_table_name: null,
      destination_catalog: "",
      destination_schema: "",
      table_prefix: "",
    },
    use_all_purpose_cluster: false,
    all_purpose_cluster_id: "",
    deployment: "not_started",
    run_id: null,
    run_url: null,
    validation: null,
    ...overrides,
  } as ReportState;
}

// Only onSaveMetadata is exercised in the report_name step; the remaining
// callbacks are required props, so we stub them all with spies.
function makeProps(state: ReportState): React.ComponentProps<typeof PreviewPanel> {
  const callbacks = [
    "onSaveMetadata", "onAdvanceStep", "onGoBack", "onGoToStep", "onSelectCandidates",
    "onDeleteSignal", "onUpdateSignal", "onAddVirtualSignal", "onFetchVehicleCandidates",
    "onSelectVehicles", "onDeleteVehicle", "onUpdateTimestamps", "onDeploy", "onCancelRun",
    "onClusterConfigChange", "onSaveReport", "onBackToLanding", "onViewResults", "onTimeSeries",
    "onSetSourceData", "onUploadFiles", "onTriggerIngest", "onAddHistogram", "onAddHistogram2D",
    "onAddStatistics", "onDeleteAggregation", "onUpdateAggregation", "onUpdateHistogram2D",
    "onUpdateStatistics", "onStateUpdate",
  ];
  const props: Record<string, unknown> = {
    state,
    wizardSteps: WIZARD_STEPS,
    currentStepIdx: 1,
    sessionId: "s1",
    ingestTasks: [],
    jobStatus: null,
    deploying: false,
    validating: false,
    saving: false,
    channelsLoading: false,
    onFetchDataRange: vi.fn(async () => null),
    onSuggestBins: vi.fn(async () => ({ bins: [], bins_unit: "", description: "", name: "" })),
  };
  for (const key of callbacks) props[key] = vi.fn();
  return props as unknown as React.ComponentProps<typeof PreviewPanel>;
}

const nameInput = () => screen.getByPlaceholderText("e.g. oil_temp_report") as HTMLInputElement;
const descInput = () =>
  screen.getByPlaceholderText("e.g. Oil temperature duration analysis") as HTMLInputElement;
const creatorInput = () => screen.getByPlaceholderText("e.g. John Doe") as HTMLInputElement;

describe("MetadataForm (PreviewPanel report_name step)", () => {
  it("seeds the inputs from the initial report state", () => {
    render(<PreviewPanel {...makeProps(makeState({ name: "oil_temp_report", description: "Oil temp", creator: "Jane" }))} />);
    expect(nameInput().value).toBe("oil_temp_report");
    expect(descInput().value).toBe("Oil temp");
    expect(creatorInput().value).toBe("Jane");
  });

  it("fills the form when the agent updates the metadata via report_state", () => {
    // Initially empty (e.g. the user just reached the step).
    const { rerender } = render(<PreviewPanel {...makeProps(makeState())} />);
    expect(nameInput().value).toBe("");

    // Agent mode calls set_report_metadata -> backend returns an updated
    // report_state -> the parent re-renders PreviewPanel with the new props.
    rerender(
      <PreviewPanel
        {...makeProps(makeState({ name: "oil_temp_report", description: "Oil temp duration", creator: "Jane" }))}
      />,
    );

    expect(nameInput().value).toBe("oil_temp_report");
    expect(descInput().value).toBe("Oil temp duration");
    expect(creatorInput().value).toBe("Jane");
  });

  it("does not discard text the user is actively typing", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<PreviewPanel {...makeProps(makeState())} />);
    await user.type(nameInput(), "my_report");

    // A re-render that leaves the metadata unchanged must not wipe the draft.
    rerender(<PreviewPanel {...makeProps(makeState())} />);
    expect(nameInput().value).toBe("my_report");
  });
});
