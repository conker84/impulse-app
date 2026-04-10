import { useState, useCallback, useRef, useEffect } from "react";
import type { ChatMessage, Histogram1DDefinition, Histogram2DDefinition, ReportState, StatisticsDefinition, WizardStep } from "./types";
import { sendChat, scaffoldReport, deployReport, advanceStep, goBack, goToStep, setMetadata, selectCandidates, fetchVehicleCandidates, selectVehicles, updateVehicleTimestamps, getDeployStatus, cancelRun, getTokenStatus, setClusterConfig, loadReport, saveReport, suggestBins, addHistogram, addHistogram2D, addStatistics, deleteAggregation, updateAggregation, setSourceData, uploadMf4Files, triggerIngest, getIngestStatus, fetchChannelCatalog, fetchDataTimeRange, deleteSignal, updateSignal, addVirtualSignal, deleteVehicle } from "./api";
import type { DeployStatusResponse, TokenStatusResponse } from "./api";
import type { DataSourceConfig } from "./types";
import ChatPanel from "./components/ChatPanel";
import PreviewPanel from "./components/PreviewPanel";
import SettingsModal from "./components/SettingsModal";
import LandingScreen from "./components/LandingScreen";
import VisualizeView from "./components/VisualizeView";
import TimeSeriesView from "./components/TimeSeriesView";

type AppView = "landing" | "editor" | "visualize" | "timeseries";

const WIZARD_STEPS: { key: WizardStep; label: string; icon: string }[] = [
  { key: "source_data", label: "Source Data", icon: "\uD83D\uDCC2" },
  { key: "report_name", label: "Report Name", icon: "\u270F\uFE0F" },
  { key: "vehicles", label: "Vehicles", icon: "\uD83D\uDE97" },
  { key: "channels", label: "Channels", icon: "\uD83D\uDCE1" },
  { key: "aggregations", label: "Aggregations", icon: "\uD83D\uDCCA" },
  { key: "ready", label: "Ready", icon: "\u2705" },
];

const INITIAL_STATE: ReportState = {
  name: "",
  description: "",
  creator: "",
  wizard_step: "source_data",
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
};

const STEP_PLACEHOLDER: Record<WizardStep, string> = {
  source_data: "Choose your data source: upload MF4 files or connect to existing Silver layer tables...",
  report_name: "Enter a report name, e.g. 'oil_temp_report'...",
  vehicles: "Add vehicles, e.g. 'Vehicle XY123 starting from 2024-01-01'...",
  channels: "Describe the signals you need, e.g. 'Add engine speed and oil temperature'...",
  aggregations: "Describe the histograms, e.g. 'Duration histogram for oil temp, 0-160 degC'...",
  ready: "Your report is ready! Click Deploy & Run.",
};

export default function App() {
  const [view, setView] = useState<AppView>(
    new URLSearchParams(window.location.search).has("synthetic") ? "timeseries" : "landing",
  );
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [reportState, setReportState] = useState<ReportState>(INITIAL_STATE);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [jobStatus, setJobStatus] = useState<DeployStatusResponse | null>(null);
  const [vizDataSources, setVizDataSources] = useState<DataSourceConfig | null>(null);
  const [vizReportName, setVizReportName] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tokenStatus, setTokenStatus] = useState<TokenStatusResponse | null>(null);
  const [ingestTasks, setIngestTasks] = useState<{ task_key: string; life_cycle_state: string; result_state: string | null }[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getTokenStatus().then(setTokenStatus).catch(() => {});
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Auto-fetch channel catalog when entering the Channels step
  // (filtered by selected vehicles since vehicles step comes first)
  const channelCatalogFetched = useRef(false);
  const lastVehicleCount = useRef(0);

  // Reset channel catalog fetch flag when vehicles change
  useEffect(() => {
    const vehicleCount = reportState.vehicles.length;
    if (vehicleCount !== lastVehicleCount.current) {
      lastVehicleCount.current = vehicleCount;
      channelCatalogFetched.current = false;
    }
  }, [reportState.vehicles.length]);

  useEffect(() => {
    if (
      reportState.wizard_step === "channels" &&
      sessionId &&
      !channelCatalogFetched.current
    ) {
      channelCatalogFetched.current = true;
      setChannelsLoading(true);
      fetchChannelCatalog(sessionId)
        .then((resp) => {
          setReportState(resp.report_state);
          if (resp.channels.length > 0) {
            setMessages((prev) => [
              ...prev,
              {
                role: "assistant" as const,
                content: `Discovered **${resp.channels.length} channels** available for your selected vehicles. Ask me to add signals — e.g. "add engine speed" or "show me all available channels".`,
              },
            ]);
          }
        })
        .catch((err) => {
          console.warn("Channel catalog fetch failed:", err);
          channelCatalogFetched.current = false;
        })
        .finally(() => setChannelsLoading(false));
    }
  }, [reportState.wizard_step, sessionId]);

  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      if (!sessionId) return;
      try {
        const status = await getDeployStatus(sessionId);
        setJobStatus(status);
        if (status.run_url) {
          setReportState((prev) => ({ ...prev, run_url: status.run_url }));
        }
        if (status.status === "completed" || status.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setReportState((prev) => ({
            ...prev,
            deployment: status.status as ReportState["deployment"],
          }));
          setDeploying(false);
          if (status.status === "failed") {
            setMessages((prev) => [...prev, { role: "assistant", content: `Report job failed. ${status.result_state || ""}` }]);
          } else {
            setMessages((prev) => [...prev, {
              role: "assistant",
              content: "Report job completed successfully. Click \"View Results\" to see your data.",
            }]);
          }
          // Auto-save so run_url and deployment status persist for re-open
          if (sessionId) saveReport(sessionId).catch(() => {});
        }
      } catch {
        // ignore transient errors during polling
      }
    }, 30000);
  }, [sessionId]);

  const handleSend = useCallback(
    async (text: string) => {
      setMessages((prev) => [...prev, { role: "user", content: text }]);
      setLoading(true);
      try {
        const resp = await sendChat(text, sessionId);
        setSessionId(resp.session_id);
        setReportState(resp.report_state);
        setMessages((prev) => [...prev, resp.message]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [sessionId]
  );

  const handleSelectCandidates = useCallback(
    async (selected: { alias: string; var_name: string; channel_name: string; description: string }[]) => {
      if (!sessionId) return;
      try {
        const resp = await selectCandidates(sessionId, selected);
        setReportState(resp.report_state);
        if (resp.added.length > 0) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Added ${resp.added.length} signal(s): ${resp.added.join(", ")}` },
          ]);
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleDeleteSignal = useCallback(
    async (varName: string) => {
      if (!sessionId) return;
      try {
        const resp = await deleteSignal(sessionId, varName);
        setReportState(resp.report_state);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleUpdateSignal = useCallback(
    async (varName: string, payload: { var_name: string; expression?: string; eval_type?: string; description?: string; alias?: string }) => {
      if (!sessionId) return;
      try {
        const resp = await updateSignal(sessionId, varName, payload);
        setReportState(resp.report_state);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleAddVirtualSignal = useCallback(
    async (payload: { var_name: string; expression: string; eval_type?: string; description?: string }) => {
      if (!sessionId) return;
      try {
        const resp = await addVirtualSignal(sessionId, payload);
        setReportState(resp.report_state);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleAddHistogram = useCallback(
    async (histogram: Histogram1DDefinition) => {
      if (!sessionId) return;
      try {
        const resp = await addHistogram(sessionId, histogram);
        setReportState(resp.report_state);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `Added ${histogram.histogram_type} histogram **${histogram.name}** on signal \`${histogram.signal_ref}\` with ${histogram.bins.length} bin edges.`,
          },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleSuggestBins = useCallback(
    async (type: string, signalRef: string) => {
      if (!sessionId) throw new Error("No active session.");
      return suggestBins(sessionId, { histogram_type: type, signal_ref: signalRef });
    },
    [sessionId]
  );

  const handleDeleteAggregation = useCallback(
    async (name: string) => {
      if (!sessionId) return;
      try {
        const resp = await deleteAggregation(sessionId, name);
        setReportState(resp.report_state);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Removed aggregation **${name}**.` },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleUpdateAggregation = useCallback(
    async (originalName: string, histogram: Histogram1DDefinition) => {
      if (!sessionId) return;
      try {
        const resp = await updateAggregation(sessionId, originalName, histogram);
        setReportState(resp.report_state);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Updated aggregation **${histogram.name}**.` },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleAddHistogram2D = useCallback(
    async (histogram: Histogram2DDefinition) => {
      if (!sessionId) return;
      try {
        const resp = await addHistogram2D(sessionId, histogram);
        setReportState(resp.report_state);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `Added 2D histogram **${histogram.name}** — X: \`${histogram.x_signal_ref}\`, Y: \`${histogram.y_signal_ref}\`.`,
          },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleAddStatistics = useCallback(
    async (stats: StatisticsDefinition) => {
      if (!sessionId) return;
      try {
        const resp = await addStatistics(sessionId, stats);
        setReportState(resp.report_state);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `Added statistics **${stats.name}** for ${stats.signal_refs.length} signal(s): ${stats.stat_labels.join(", ")}.`,
          },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleSetSourceData = useCallback(
    async (mode: "upload" | "existing", opts?: {
      silver_catalog?: string;
      silver_schema?: string;
      upload_catalog?: string;
      upload_schema?: string;
      upload_volume?: string;
    }) => {
      try {
        const resp = await setSourceData(sessionId, mode, opts);
        if (resp.session_id) setSessionId(resp.session_id);
        setReportState(resp.report_state);
      } catch (err) {
        console.error("Failed to set source data", err);
      }
    },
    [sessionId]
  );

  const handleUploadFiles = useCallback(
    async (files: FileList) => {
      let sid = sessionId;
      if (!sid) {
        const resp = await setSourceData(null, "upload");
        setSessionId(resp.session_id);
        setReportState(resp.report_state);
        sid = resp.session_id;
      }
      try {
        const resp = await uploadMf4Files(sid, files);
        setReportState(resp.report_state);
        if (resp.uploaded.length > 0) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Uploaded ${resp.uploaded.length} MF4 file(s) to Volume.` },
          ]);
        }
        if (resp.errors.length > 0) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Upload issues: ${resp.errors.join("; ")}` },
          ]);
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Upload error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const ingestPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleTriggerIngest = useCallback(async () => {
    if (!sessionId) return;
    if (tokenStatus && !tokenStatus.local_mode && !tokenStatus.has_token) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "⚠️ **A Personal Access Token (PAT) is required to run the ingest job.** Please open Settings (gear icon) and save your PAT first." },
      ]);
      return;
    }
    try {
      const resp = await triggerIngest(sessionId);
      setReportState(resp.report_state);
      const urlMsg = resp.run_url ? ` [View job](${resp.run_url})` : "";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Ingest pipeline started. Transforming MF4 files to Silver layer tables...${urlMsg}` },
      ]);

      // Poll until terminal state (succeeded/failed)
      const poll = async () => {
        try {
          const status = await getIngestStatus(sessionId);
          setReportState(status.report_state);
          if (status.tasks) setIngestTasks(status.tasks);
          if (status.status === "succeeded" || status.status === "failed") {
            if (ingestPollRef.current) { clearInterval(ingestPollRef.current); ingestPollRef.current = null; }
            const urlPart = status.run_url ? ` [View job](${status.run_url})` : "";
            const msg = status.status === "succeeded"
              ? `Silver layer tables created successfully! You can proceed to the next step.${urlPart}`
              : `Ingest pipeline failed.${urlPart}`;
            setMessages((prev) => [...prev, { role: "assistant", content: msg }]);
          }
        } catch { /* ignore transient errors */ }
      };
      if (ingestPollRef.current) clearInterval(ingestPollRef.current);
      setTimeout(poll, 3000);
      ingestPollRef.current = setInterval(poll, 10000);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Ingest error: ${err instanceof Error ? err.message : String(err)}` },
      ]);
    }
  }, [sessionId]);

  // Clean up ingest polling on unmount
  useEffect(() => {
    return () => { if (ingestPollRef.current) clearInterval(ingestPollRef.current); };
  }, []);

  const handleSaveMetadata = useCallback(
    async (data: { name: string; description: string; creator: string }) => {
      try {
        const resp = await setMetadata(sessionId, data);
        if (resp.session_id) setSessionId(resp.session_id);
        setReportState(resp.report_state);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleAdvanceStep = useCallback(async () => {
    if (!sessionId) return;
    try {
      const resp = await advanceStep(sessionId);
      setReportState(resp.report_state);
      const stepLabel = WIZARD_STEPS.find((s) => s.key === resp.wizard_step)?.label ?? resp.wizard_step;
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Moving to step: **${stepLabel}**` },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `${err instanceof Error ? err.message : String(err)}` },
      ]);
    }
  }, [sessionId]);

  const handleGoBack = useCallback(async () => {
    if (!sessionId) return;
    try {
      const resp = await goBack(sessionId);
      setReportState(resp.report_state);
      const stepLabel = WIZARD_STEPS.find((s) => s.key === resp.wizard_step)?.label ?? resp.wizard_step;
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Back to step: **${stepLabel}**` },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `${err instanceof Error ? err.message : String(err)}` },
      ]);
    }
  }, [sessionId]);

  const handleGoToStep = useCallback(async (step: WizardStep) => {
    if (!sessionId) return;
    try {
      const resp = await goToStep(sessionId, step);
      setReportState(resp.report_state);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `${err instanceof Error ? err.message : String(err)}` },
      ]);
    }
  }, [sessionId]);

  const handleFetchVehicleCandidates = useCallback(async () => {
    if (!sessionId) return;
    try {
      const resp = await fetchVehicleCandidates(sessionId);
      setReportState(resp.report_state);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error loading vehicles: ${err instanceof Error ? err.message : String(err)}` },
      ]);
    }
  }, [sessionId]);

  const handleSelectVehicles = useCallback(
    async (selected: { vehicle_id: string; start_ts: string }[]) => {
      if (!sessionId) return;
      try {
        const resp = await selectVehicles(sessionId, selected);
        setReportState(resp.report_state);
        if (resp.added.length > 0) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Added ${resp.added.length} vehicle(s): ${resp.added.join(", ")}. Data sources were auto-configured from the mapping table.` },
          ]);
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleDeleteVehicle = useCallback(
    async (vehicleId: string) => {
      if (!sessionId) return;
      try {
        const resp = await deleteVehicle(sessionId, vehicleId);
        setReportState(resp.report_state);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleUpdateTimestamps = useCallback(
    async (payload: {
      global_start_ts: string;
      global_stop_ts: string | null;
      per_vehicle: { vehicle_id: string; start_ts: string; stop_ts: string | null }[];
    }) => {
      if (!sessionId) return;
      try {
        const resp = await updateVehicleTimestamps(sessionId, payload);
        setReportState(resp.report_state);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Timestamps updated." },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleFetchDataRange = useCallback(async () => {
    if (!sessionId) return null;
    try {
      return await fetchDataTimeRange(sessionId);
    } catch {
      return null;
    }
  }, [sessionId]);

  const handleCancelRun = useCallback(async () => {
    if (!sessionId) return;
    try {
      await cancelRun(sessionId);
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Cancel request sent. Waiting for Databricks to confirm..." },
      ]);

      const poll = async (attempts: number) => {
        for (let i = 0; i < attempts; i++) {
          await new Promise((r) => setTimeout(r, 3000));
          try {
            const status = await getDeployStatus(sessionId);
            setJobStatus(status);
            if (status.status === "completed" || status.status === "failed") {
              setDeploying(false);
              setReportState((prev) => ({ ...prev, deployment: status.status as ReportState["deployment"] }));
              setMessages((prev) => [
                ...prev,
                { role: "assistant", content: "Job run has been cancelled." },
              ]);
              return;
            }
          } catch {
            // retry
          }
        }
        setDeploying(false);
        setReportState((prev) => ({ ...prev, deployment: "failed" }));
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Job run has been cancelled." },
        ]);
      };
      poll(10);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Cancel error: ${err instanceof Error ? err.message : String(err)}` },
      ]);
    }
  }, [sessionId]);

  const resetEditor = useCallback(() => {
    setMessages([]);
    setReportState(INITIAL_STATE);
    setSessionId(null);
    setDeploying(false);
    setValidating(false);
    setSaving(false);
    setJobStatus(null);
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const handleNewReport = useCallback(() => {
    resetEditor();
    setView("editor");
  }, [resetEditor]);

  const handleLoadReport = useCallback(async (reportId: string) => {
    try {
      const resp = await loadReport(reportId);
      resetEditor();
      setSessionId(resp.session_id);
      setReportState(resp.report_state);
      setView("editor");
    } catch (err) {
      alert(`Failed to load report: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [resetEditor]);

  const handleBackToLanding = useCallback(() => {
    resetEditor();
    setVizDataSources(null);
    setVizReportName("");
    setView("landing");
  }, [resetEditor]);

  const handleVisualize = useCallback(async (reportId: string) => {
    try {
      const resp = await loadReport(reportId);
      setVizDataSources(resp.report_state.data_sources);
      setVizReportName(resp.report_state.name);
      setView("visualize");
    } catch (err) {
      alert(`Failed to load report for visualization: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, []);

  const handleVisualizeFromEditor = useCallback(() => {
    setVizDataSources(reportState.data_sources);
    setVizReportName(reportState.name);
    setView("visualize");
  }, [reportState.data_sources, reportState.name]);

  const handleSaveReport = useCallback(async () => {
    if (!sessionId) return;
    setSaving(true);
    try {
      await saveReport(sessionId);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Report definition saved." },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Save error: ${err instanceof Error ? err.message : String(err)}` },
      ]);
    } finally {
      setSaving(false);
    }
  }, [sessionId]);

  const handleClusterConfigChange = useCallback(
    async (useAllPurpose: boolean, clusterId: string) => {
      if (!sessionId) return;
      try {
        const resp = await setClusterConfig(sessionId, {
          use_all_purpose_cluster: useAllPurpose,
          all_purpose_cluster_id: clusterId,
        });
        setReportState(resp.report_state);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ]);
      }
    },
    [sessionId]
  );

  const handleDeploy = useCallback(async () => {
    if (!sessionId) return;
    if (tokenStatus && !tokenStatus.local_mode && !tokenStatus.has_token) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "⚠️ **A Personal Access Token (PAT) is required to deploy and run the report job.** Please open Settings (gear icon) and save your PAT first." },
      ]);
      return;
    }

    setDeploying(true);
    setJobStatus(null);
    setReportState((prev) => ({ ...prev, deployment: "not_started", run_id: null, run_url: null, validation: null }));
    try {
      setReportState((prev) => ({ ...prev, deployment: "scaffolding" }));
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Scaffolding the report from the template..." },
      ]);
      await scaffoldReport(sessionId);

      setReportState((prev) => ({ ...prev, deployment: "deploying" }));
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Deploying and submitting the report job..." },
      ]);
      const result = await deployReport(sessionId);

      setReportState((prev) => ({
        ...prev,
        deployment: result.status as ReportState["deployment"],
      }));

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: (
            `The report job has been submitted and is now running on Databricks. ` +
            `You can track the job progress in the panel on the right. I'll notify you when it completes.`
          ),
        },
      ]);

      startPolling();
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Deploy error: ${err instanceof Error ? err.message : String(err)}` },
      ]);
      setReportState((prev) => ({ ...prev, deployment: "failed" }));
      setDeploying(false);
    }
  }, [sessionId, startPolling, tokenStatus]);

  const currentStepIdx = WIZARD_STEPS.findIndex((s) => s.key === reportState.wizard_step);

  const showSettingsIcon = !tokenStatus?.local_mode;

  const settingsBtn = showSettingsIcon ? (
    <button className="settings-btn-inline" onClick={() => setSettingsOpen(true)} title="Settings">
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
        <path d="M8.5 1.5a1.5 1.5 0 013 0v.7a6.5 6.5 0 011.7.7l.5-.5a1.5 1.5 0 012.12 2.12l-.5.5c.3.5.5 1.1.7 1.7h.7a1.5 1.5 0 010 3h-.7c-.2.6-.4 1.2-.7 1.7l.5.5a1.5 1.5 0 01-2.12 2.12l-.5-.5c-.5.3-1.1.5-1.7.7v.7a1.5 1.5 0 01-3 0v-.7a6.5 6.5 0 01-1.7-.7l-.5.5a1.5 1.5 0 01-2.12-2.12l.5-.5A6.5 6.5 0 014 10.5h-.7a1.5 1.5 0 010-3h.7c.2-.6.4-1.2.7-1.7l-.5-.5A1.5 1.5 0 016.3 3.18l.5.5c.5-.3 1.1-.5 1.7-.7V1.5zM10 7a3 3 0 100 6 3 3 0 000-6z" fill={tokenStatus?.has_token ? "currentColor" : "var(--warning)"}/>
      </svg>
    </button>
  ) : undefined;

  if (view === "landing") {
    return (
      <>
        <SettingsModal
          open={settingsOpen}
          onClose={() => {
            setSettingsOpen(false);
            getTokenStatus().then(setTokenStatus).catch(() => {});
          }}
        />
        <LandingScreen onNewReport={handleNewReport} onLoadReport={handleLoadReport} onVisualize={handleVisualize} onTimeSeries={() => setView("timeseries")} settingsButton={settingsBtn} />
      </>
    );
  }

  if (view === "visualize" && vizDataSources) {
    return (
      <>
        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        <VisualizeView
          dataSources={vizDataSources}
          reportName={vizReportName}
          onBack={handleBackToLanding}
          settingsButton={settingsBtn}
        />
      </>
    );
  }

  if (view === "timeseries") {
    const isSynthetic = new URLSearchParams(window.location.search).has("synthetic");
    return (
      <>
        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        <TimeSeriesView
          onBack={handleBackToLanding}
          settingsButton={settingsBtn}
          initialCatalog={isSynthetic ? "synthetic" : undefined}
          initialSchema={isSynthetic ? "test" : undefined}
        />
      </>
    );
  }

  return (
    <div className="app-layout">
      <SettingsModal
        open={settingsOpen}
        onClose={() => {
          setSettingsOpen(false);
          getTokenStatus().then((ts) => {
            setTokenStatus(ts);
            if (reportState.use_all_purpose_cluster && ts.cluster_id) {
              setReportState((prev) => ({ ...prev, all_purpose_cluster_id: ts.cluster_id || "" }));
              if (sessionId) {
                setClusterConfig(sessionId, {
                  use_all_purpose_cluster: true,
                  all_purpose_cluster_id: ts.cluster_id || "",
                }).catch(() => {});
              }
            }
          }).catch(() => {});
        }}
      />
      <ChatPanel
        messages={messages}
        onSend={handleSend}
        loading={loading}
        placeholder={STEP_PLACEHOLDER[reportState.wizard_step]}
        wizardStep={reportState.wizard_step}
        settingsButton={settingsBtn}
      />
      <PreviewPanel
        state={reportState}
        wizardSteps={WIZARD_STEPS}
        currentStepIdx={currentStepIdx}
        onSaveMetadata={handleSaveMetadata}
        onAdvanceStep={handleAdvanceStep}
        onGoBack={handleGoBack}
        onGoToStep={handleGoToStep}
        onSelectCandidates={handleSelectCandidates}
        onDeleteSignal={handleDeleteSignal}
        onUpdateSignal={handleUpdateSignal}
        onAddVirtualSignal={handleAddVirtualSignal}
        channelsLoading={channelsLoading}
        onFetchVehicleCandidates={handleFetchVehicleCandidates}
        onSelectVehicles={handleSelectVehicles}
        onDeleteVehicle={handleDeleteVehicle}
        onUpdateTimestamps={handleUpdateTimestamps}
        onFetchDataRange={handleFetchDataRange}
        onDeploy={handleDeploy}
        onCancelRun={handleCancelRun}
        onClusterConfigChange={handleClusterConfigChange}
        onSaveReport={handleSaveReport}
        onBackToLanding={handleBackToLanding}
        onViewResults={handleVisualizeFromEditor}
        onTimeSeries={() => setView("timeseries")}
        onSetSourceData={handleSetSourceData}
        onUploadFiles={handleUploadFiles}
        onTriggerIngest={handleTriggerIngest}
        ingestTasks={ingestTasks}
        onAddHistogram={handleAddHistogram}
        onAddHistogram2D={handleAddHistogram2D}
        onAddStatistics={handleAddStatistics}
        onDeleteAggregation={handleDeleteAggregation}
        onUpdateAggregation={handleUpdateAggregation}
        onSuggestBins={handleSuggestBins}
        sessionId={sessionId}
        onStateUpdate={setReportState}
        jobStatus={jobStatus}

        deploying={deploying}
        validating={validating}
        saving={saving}
      />
    </div>
  );
}
