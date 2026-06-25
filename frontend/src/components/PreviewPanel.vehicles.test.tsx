import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// PreviewPanel transitively imports Plotly (via chart components), which cannot
// initialise under jsdom. Stub the wrapper to keep the import chain loadable.
vi.mock("react-plotly.js", () => ({ default: () => null }));

import PreviewPanel from "./PreviewPanel";
import type { ReportState, VehicleCandidate, VehicleConfig, WizardStep } from "../types";

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
    wizard_step: "vehicles",
    source_data: {
      mode: "existing",
      upload_catalog: "",
      upload_schema: "",
      upload_volume: "",
      upload_volume_path: "",
      uploaded_files: [],
      silver_catalog: "cat",
      silver_schema: "sch",
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
    currentStepIdx: 2,
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

const candidate = (id: string): VehicleCandidate => ({ vehicle_id: id, datapoint_count: 1 });
const vehicle = (id: string): VehicleConfig =>
  ({ vehicle_id: id, col_name: "vehicle_key", col_type: "string", start_ts: "2025-04-29 00:20:00", stop_ts: null });

describe("VehiclesStep — picker visibility (agent add)", () => {
  it("hides the Available Vehicles picker once a vehicle is added and candidates are cleared", async () => {
    // Mount empty: the auto-fetch effect sets showCandidates=true and asks for candidates.
    const { rerender } = render(<PreviewPanel {...makeProps(makeState())} />);

    // Candidates arrive -> picker is shown (await: the mount effect's loading
    // spinner clears in a microtask).
    rerender(
      <PreviewPanel {...makeProps(makeState({ vehicle_candidates: [candidate("v1"), candidate("v2")] }))} />,
    );
    expect(await screen.findByText(/Available Vehicles \(2\)/)).toBeTruthy();

    // Agent adds a vehicle via set_vehicle, which clears vehicle_candidates.
    rerender(
      <PreviewPanel {...makeProps(makeState({ vehicle_candidates: [], vehicles: [vehicle("v1")] }))} />,
    );

    // Picker collapses; the selected list and "Add More" affordance take over.
    await waitFor(() => expect(screen.queryByText(/Available Vehicles/)).toBeNull());
    expect(screen.getByText(/Selected Vehicles \(1\)/)).toBeTruthy();
    expect(screen.getByText(/Add More Vehicles/)).toBeTruthy();
  });
});
