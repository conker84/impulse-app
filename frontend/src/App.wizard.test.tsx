/**
 * End-to-end test for the report-creation wizard at the App level.
 *
 * Renders <App/> and drives it through all six steps
 * (source_data -> report_name -> vehicles -> channels -> aggregations -> ready),
 * the frontend mirror of tests/test_wizard.py on the backend.
 *
 * The `api` module is mocked with a small stateful fake that mimics the backend
 * step machine, and the heavy presentational children (PreviewPanel, etc.) are
 * replaced with thin stubs that surface the wizard callbacks as buttons — so we
 * test App's orchestration (session handling, step advancement, state
 * propagation) without rendering Plotly.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const STEPS = ["source_data", "report_name", "vehicles", "channels", "aggregations", "ready"];

// A mutable fake "server" state shared by the api mocks.
const srv: { state: any } = { state: null };

function makeInitialState() {
  return {
    name: "",
    wizard_step: "source_data",
    source_data: { mode: "none", uploaded_files: [], silver_catalog: "", silver_schema: "" },
    available_channels: [],
    signal_candidates: [],
    signals: [],
    events: [],
    aggregations: [],
    vehicle_candidates: [],
    vehicles: [],
    data_sources: { container_metrics: "", channels: [], destination_catalog: "", table_prefix: "" },
    use_all_purpose_cluster: false,
    deployment: "not_started",
  };
}

// Hoisted vi.fn()s so they can be both wired into the mock and asserted on.
const apiMocks = vi.hoisted(() => ({
  getUserStatus: vi.fn(),
  setSourceData: vi.fn(),
  advanceStep: vi.fn(),
  goBack: vi.fn(),
  setMetadata: vi.fn(),
  selectVehicles: vi.fn(),
  selectCandidates: vi.fn(),
  addHistogram: vi.fn(),
  fetchChannelCatalog: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

// Replace heavy children. PreviewPanel becomes a driver that exposes the wizard
// callbacks as buttons and renders the current step + counts.
vi.mock("./components/PreviewPanel", () => ({
  default: (props: any) => (
    <div>
      <div data-testid="current-step">{props.state.wizard_step}</div>
      <div data-testid="counts">
        {props.state.vehicles.length}|{props.state.signals.length}|{props.state.aggregations.length}
      </div>
      <button onClick={() => props.onSetSourceData("existing", { silver_catalog: "cat", silver_schema: "sch" })}>
        set-source
      </button>
      <button onClick={() => props.onAdvanceStep()}>next</button>
      <button onClick={() => props.onGoBack()}>back</button>
      <button onClick={() => props.onSaveMetadata({ name: "My Report", description: "", creator: "" })}>
        save-metadata
      </button>
      <button onClick={() => props.onSelectVehicles([{ vehicle_id: "vw_golf", start_ts: "2024-01-01" }])}>
        select-vehicles
      </button>
      <button
        onClick={() =>
          props.onSelectCandidates([
            { alias: "nmot", var_name: "engine_speed", channel_name: "nmot", description: "" },
          ])
        }
      >
        select-candidates
      </button>
      <button
        onClick={() =>
          props.onAddHistogram({
            agg_kind: "histogram_1d",
            name: "rpm_hist",
            histogram_type: "duration",
            signal_ref: "engine_speed",
            bins: [0, 1000, 2000],
          })
        }
      >
        add-histogram
      </button>
    </div>
  ),
}));

vi.mock("./components/LandingScreen", () => ({
  default: (props: any) => <button onClick={props.onNewReport}>new-report</button>,
}));
vi.mock("./components/AppSidebar", () => ({ default: () => <nav data-testid="app-nav" /> }));
vi.mock("./components/ChatPanel", () => ({ default: () => <div data-testid="chat" /> }));
vi.mock("./components/SettingsModal", () => ({ default: () => null }));
vi.mock("./components/VisualizeView", () => ({ default: () => null }));
vi.mock("./components/TimeSeriesView", () => ({ default: () => null }));

import App from "./App";

beforeEach(() => {
  srv.state = makeInitialState();

  apiMocks.getUserStatus.mockResolvedValue({ local_mode: true });

  apiMocks.setSourceData.mockImplementation(async (_sid, mode, opts) => {
    srv.state = { ...srv.state, source_data: { ...srv.state.source_data, mode, ...opts } };
    return { session_id: "s1", report_state: srv.state };
  });

  apiMocks.advanceStep.mockImplementation(async () => {
    const i = STEPS.indexOf(srv.state.wizard_step);
    srv.state = { ...srv.state, wizard_step: STEPS[i + 1] };
    return { wizard_step: srv.state.wizard_step, report_state: srv.state };
  });

  apiMocks.goBack.mockImplementation(async () => {
    const i = STEPS.indexOf(srv.state.wizard_step);
    srv.state = { ...srv.state, wizard_step: STEPS[i - 1] };
    return { wizard_step: srv.state.wizard_step, report_state: srv.state };
  });

  apiMocks.setMetadata.mockImplementation(async (_sid, data) => {
    srv.state = { ...srv.state, name: data.name.toLowerCase().replace(/ /g, "_") };
    return { session_id: "s1", report_state: srv.state };
  });

  apiMocks.selectVehicles.mockImplementation(async (_sid, selected) => {
    srv.state = {
      ...srv.state,
      vehicles: selected.map((s: any) => ({ vehicle_id: s.vehicle_id, start_ts: s.start_ts })),
    };
    return { added: selected.map((s: any) => s.vehicle_id), report_state: srv.state };
  });

  apiMocks.selectCandidates.mockImplementation(async (_sid, selected) => {
    srv.state = {
      ...srv.state,
      signals: selected.map((s: any) => ({ var_name: s.var_name, signal_type: "physical" })),
    };
    return { added: selected.map((s: any) => s.var_name), report_state: srv.state };
  });

  apiMocks.addHistogram.mockImplementation(async (_sid, hist) => {
    srv.state = { ...srv.state, aggregations: [...srv.state.aggregations, hist] };
    return { report_state: srv.state };
  });

  apiMocks.fetchChannelCatalog.mockImplementation(async () => ({
    report_state: srv.state,
    channels: [],
  }));
});

const step = () => screen.getByTestId("current-step").textContent;
const counts = () => screen.getByTestId("counts").textContent;

async function enterEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByText("new-report"));
  expect(await screen.findByTestId("current-step")).toBeInTheDocument();
}

describe("report wizard (App)", () => {
  it("walks every step from source data to ready, building the report", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enterEditor(user);
    expect(step()).toBe("source_data");

    // Step 1: source data establishes the session, then advance
    await user.click(screen.getByText("set-source"));
    await waitFor(() => expect(apiMocks.setSourceData).toHaveBeenCalled());
    await user.click(screen.getByText("next"));
    await waitFor(() => expect(step()).toBe("report_name"));

    // Step 2: report name
    await user.click(screen.getByText("save-metadata"));
    await user.click(screen.getByText("next"));
    await waitFor(() => expect(step()).toBe("vehicles"));

    // Step 3: vehicles
    await user.click(screen.getByText("select-vehicles"));
    await waitFor(() => expect(counts()).toBe("1|0|0"));
    await user.click(screen.getByText("next"));
    await waitFor(() => expect(step()).toBe("channels"));

    // Step 4: channels (App auto-fetches the catalog on entry)
    await waitFor(() => expect(apiMocks.fetchChannelCatalog).toHaveBeenCalledWith("s1"));
    await user.click(screen.getByText("select-candidates"));
    await waitFor(() => expect(counts()).toBe("1|1|0"));
    await user.click(screen.getByText("next"));
    await waitFor(() => expect(step()).toBe("aggregations"));

    // Step 5: aggregations
    await user.click(screen.getByText("add-histogram"));
    await waitFor(() => expect(counts()).toBe("1|1|1"));
    await user.click(screen.getByText("next"));
    await waitFor(() => expect(step()).toBe("ready"));

    // advanceStep was driven by the session created in step 1
    expect(apiMocks.advanceStep).toHaveBeenCalledWith("s1");
    expect(apiMocks.advanceStep).toHaveBeenCalledTimes(5);
  });

  it("passes the typed report name through to setMetadata and stores the session", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enterEditor(user);

    await user.click(screen.getByText("set-source"));
    await user.click(screen.getByText("next"));
    await waitFor(() => expect(step()).toBe("report_name"));
    await user.click(screen.getByText("save-metadata"));

    await waitFor(() =>
      expect(apiMocks.setMetadata).toHaveBeenCalledWith("s1", {
        name: "My Report",
        description: "",
        creator: "",
      }),
    );
  });

  it("does not call advanceStep before a session exists", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enterEditor(user);

    // No source data set yet -> no session -> handler is a no-op
    await user.click(screen.getByText("next"));
    expect(apiMocks.advanceStep).not.toHaveBeenCalled();
    expect(step()).toBe("source_data");
  });

  it("supports going back a step", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enterEditor(user);

    await user.click(screen.getByText("set-source"));
    await user.click(screen.getByText("next"));
    await waitFor(() => expect(step()).toBe("report_name"));

    await user.click(screen.getByText("back"));
    await waitFor(() => expect(step()).toBe("source_data"));
    expect(apiMocks.goBack).toHaveBeenCalledWith("s1");
  });
});
