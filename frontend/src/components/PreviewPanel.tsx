import React, { useState, useEffect, useRef, useCallback } from "react";
import type { AggregationDefinition, AvailableChannel, Histogram1DDefinition, Histogram2DDefinition, ReportState, SignalCandidate, SourceDataConfig, StatisticsDefinition, VehicleCandidate, WizardStep } from "../types";
import type { DeployStatusResponse } from "../api";
import { listCatalogs, listSchemas, listVolumes } from "../api";
import SignalsTab from "./SignalsTab";
import AggregationsTab from "./AggregationsTab";
import HistogramBuilder from "./HistogramBuilder";
import Histogram2DBuilder from "./Histogram2DBuilder";
import StatisticsBuilder from "./StatisticsBuilder";
import ConfigTab from "./ConfigTab";
import CodePreviewTab from "./CodePreviewTab";
import ResultsTab from "./ResultsTab";

interface WizardStepDef {
  key: WizardStep;
  label: string;
  icon: string;
}

interface Props {
  state: ReportState;
  wizardSteps: WizardStepDef[];
  currentStepIdx: number;
  onSaveMetadata: (data: { name: string; description: string; creator: string }) => void;
  onAdvanceStep: () => void;
  onGoBack: () => void;
  onSelectCandidates: (selected: { alias: string; var_name: string; channel_name: string; description: string }[]) => void;
  onDeleteSignal: (varName: string) => void;
  onUpdateSignal: (varName: string, payload: { var_name: string; expression?: string; eval_type?: string; description?: string; alias?: string }) => void;
  onAddVirtualSignal: (payload: { var_name: string; expression: string; eval_type?: string; description?: string }) => void;
  channelsLoading: boolean;
  onFetchVehicleCandidates: () => void;
  onSelectVehicles: (selected: { vehicle_id: string; start_ts: string }[]) => void;
  onDeleteVehicle: (vehicleId: string) => void;
  onUpdateTimestamps: (payload: {
    global_start_ts: string;
    global_stop_ts: string | null;
    per_vehicle: { vehicle_id: string; start_ts: string; stop_ts: string | null }[];
  }) => void;
  onFetchDataRange: () => Promise<{ min_start: string | null; max_stop: string | null } | null>;
  onDeploy: () => void;
  onCancelRun: () => void;
  onClusterConfigChange: (useAllPurpose: boolean, clusterId: string) => void;
  onSaveReport: () => void;
  onBackToLanding: () => void;
  onViewResults: () => void;
  onSetSourceData: (mode: "upload" | "existing", opts?: {
    silver_catalog?: string;
    silver_schema?: string;
    upload_catalog?: string;
    upload_schema?: string;
    upload_volume?: string;
  }) => void;
  onUploadFiles: (files: FileList) => void;
  onTriggerIngest: () => void;
  ingestTasks: { task_key: string; life_cycle_state: string; result_state: string | null }[];
  onAddHistogram: (histogram: Histogram1DDefinition) => void;
  onAddHistogram2D: (histogram: Histogram2DDefinition) => void;
  onAddStatistics: (stats: StatisticsDefinition) => void;
  onDeleteAggregation: (name: string) => void;
  onUpdateAggregation: (originalName: string, histogram: Histogram1DDefinition) => void;
  onSuggestBins: (type: string, signalRef: string) => Promise<{
    bins: number[]; bins_unit: string; description: string; name: string;
  }>;
  jobStatus: DeployStatusResponse | null;
  deploying: boolean;
  validating: boolean;
  saving: boolean;
}

function canAdvance(state: ReportState): boolean {
  const step = state.wizard_step;
  if (step === "source_data") {
    if (state.source_data.mode === "existing")
      return !!state.source_data.silver_catalog && !!state.source_data.silver_schema;
    if (state.source_data.mode === "upload")
      return state.source_data.ingest_status === "succeeded"
        && !!state.source_data.silver_catalog && !!state.source_data.silver_schema;
    return false;
  }
  if (step === "report_name") return !!state.name;
  if (step === "vehicles") return state.vehicles.length > 0;
  if (step === "channels") return state.signals.length > 0;
  if (step === "aggregations") return state.aggregations.length > 0;
  return false;
}

export default function PreviewPanel({
  state,
  wizardSteps,
  currentStepIdx,
  onSaveMetadata,
  onAdvanceStep,
  onGoBack,
  onSelectCandidates,
  onDeleteSignal,
  onUpdateSignal,
  onAddVirtualSignal,
  channelsLoading,
  onFetchVehicleCandidates,
  onSelectVehicles,
  onDeleteVehicle,
  onUpdateTimestamps,
  onFetchDataRange,
  onDeploy,
  onCancelRun,
  onClusterConfigChange,
  onSaveReport,
  onBackToLanding,
  onViewResults,
  onSetSourceData,
  onUploadFiles,
  onTriggerIngest,
  ingestTasks,
  onAddHistogram,
  onAddHistogram2D,
  onAddStatistics,
  onDeleteAggregation,
  onUpdateAggregation,
  onSuggestBins,
  jobStatus,
  deploying,
  validating,
  saving,
}: Props) {
  const isReady = state.wizard_step === "ready";
  const clusterReady = !state.use_all_purpose_cluster || !!state.all_purpose_cluster_id;
  const canDeploy = isReady && state.deployment === "not_started" && clusterReady;

  const [editingHistogram, setEditingHistogram] = useState<Histogram1DDefinition | null>(null);

  const handleEditAggregation = useCallback((agg: AggregationDefinition) => {
    if (agg.agg_kind === "histogram_1d") {
      setEditingHistogram(agg);
    }
  }, []);

  const handleAddOrUpdateHistogram = useCallback((histogram: Histogram1DDefinition) => {
    if (editingHistogram) {
      onUpdateAggregation(editingHistogram.name, histogram);
      setEditingHistogram(null);
    } else {
      onAddHistogram(histogram);
    }
  }, [editingHistogram, onAddHistogram, onUpdateAggregation]);

  const candidateRef = useRef<HTMLDivElement>(null);
  const prevCandidateCount = useRef(0);

  useEffect(() => {
    const count = state.signal_candidates.length;
    if (count > 0 && prevCandidateCount.current === 0) {
      candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    prevCandidateCount.current = count;
  }, [state.signal_candidates.length]);

  return (
    <div className="preview-panel">
      <div className="wizard-stepper">
        {wizardSteps.map((step, idx) => {
          const isCompleted = idx < currentStepIdx;
          const isCurrent = idx === currentStepIdx;
          const cls = isCompleted ? "completed" : isCurrent ? "current" : "upcoming";
          const connectorCls = isCompleted ? "completed" : isCurrent ? "current" : "upcoming";
          return (
            <React.Fragment key={step.key}>
              <div className={`wizard-step ${cls}`}>
                <div className="wizard-step-indicator">
                  {isCompleted ? "\u2713" : idx + 1}
                </div>
                <span className="wizard-step-label">
                  {step.label}
                  {step.key === "channels" && state.signal_candidates.length > 0 && (
                    <span className="candidate-badge">{state.signal_candidates.length}</span>
                  )}
                </span>
              </div>
              {idx < wizardSteps.length - 1 && (
                <div className={`wizard-step-connector ${connectorCls}`} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      <div className="step-content">
        {state.wizard_step === "source_data" && (
          <SourceDataStep
            sourceData={state.source_data}
            onSetSourceData={onSetSourceData}
            onUploadFiles={onUploadFiles}
            onTriggerIngest={onTriggerIngest}
            ingestTasks={ingestTasks}
          />
        )}
        {state.wizard_step === "report_name" && (
          <MetadataForm state={state} onSaveMetadata={onSaveMetadata} />
        )}
        {state.wizard_step === "vehicles" && (
          <VehiclesStep
            state={state}
            onFetchCandidates={onFetchVehicleCandidates}
            onSelectVehicles={onSelectVehicles}
            onDeleteVehicle={onDeleteVehicle}
            onUpdateTimestamps={onUpdateTimestamps}
            onFetchDataRange={onFetchDataRange}
          />
        )}
        {state.wizard_step === "channels" && (
          <StepSection title="Channels" subtitle={`${state.signals.length} signal(s) defined`}>
            {channelsLoading && (
              <div className="card" style={{ textAlign: "center", padding: 24, color: "var(--text-muted)" }}>
                <span className="spinner" style={{ marginRight: 8 }} />
                Loading available channels for selected vehicles...
              </div>
            )}
            {state.signal_candidates.length > 0 && (
              <div ref={candidateRef} className="candidate-highlight">
                <CandidateSelector
                  candidates={state.signal_candidates}
                  existingAliases={new Set(state.signals.filter((s) => s.alias).map((s) => s.alias!))}
                  onConfirm={onSelectCandidates}
                />
              </div>
            )}
            {!channelsLoading && (
              <ChannelBrowser
                channels={state.available_channels || []}
                existingNames={new Set(state.signals.filter((s) => s.channel_name).map((s) => s.channel_name!))}
                onAdd={onSelectCandidates}
              />
            )}
            <SignalsTab
              signals={state.signals}
              silverCatalog={state.source_data.silver_catalog}
              silverSchema={state.source_data.silver_schema}
              vehicles={state.vehicles}
              onDelete={onDeleteSignal}
              onUpdate={onUpdateSignal}
              onAddVirtual={onAddVirtualSignal}
            />
          </StepSection>
        )}
        {state.wizard_step === "aggregations" && (
          <StepSection title="Aggregations" subtitle={`${state.aggregations.length} aggregation(s) defined`}>
            <AggregationsTab
              aggregations={state.aggregations}
              onDelete={onDeleteAggregation}
              onEdit={handleEditAggregation}
            />
            <HistogramBuilder
              signals={state.signals}
              existingNames={new Set(state.aggregations.map((a) => a.name))}
              onAdd={handleAddOrUpdateHistogram}
              onSuggestBins={onSuggestBins}
              editingHistogram={editingHistogram}
              onCancelEdit={() => setEditingHistogram(null)}
            />
            <Histogram2DBuilder
              signals={state.signals}
              existingNames={new Set(state.aggregations.map((a) => a.name))}
              onAdd={onAddHistogram2D}
              onSuggestBins={onSuggestBins}
            />
            <StatisticsBuilder
              signals={state.signals}
              existingNames={new Set(state.aggregations.map((a) => a.name))}
              onAdd={onAddStatistics}
            />
          </StepSection>
        )}
        {state.wizard_step === "ready" && (
          <ReadyPanel
            state={state}
            deploying={deploying}
            jobStatus={jobStatus}
            validating={validating}
            onClusterConfigChange={onClusterConfigChange}
            onViewResults={onViewResults}
          />
        )}
      </div>

      <div className="action-bar">
        <button className="action-btn" onClick={onBackToLanding} title="Back to Home">
          Home
        </button>
        {currentStepIdx > 0 && (
          <button className="action-btn" onClick={onGoBack}>
            &larr; Back
          </button>
        )}
        {!isReady && (
          <button
            className="action-btn primary"
            disabled={!canAdvance(state)}
            onClick={onAdvanceStep}
          >
            Next Step &rarr;
          </button>
        )}
        {isReady && !deploying && (
          <>
            <button
              className="action-btn"
              disabled={!state.name || saving}
              onClick={onSaveReport}
            >
              {saving ? "Saving..." : "Save"}
            </button>
            <button
              className="action-btn primary"
              disabled={!canDeploy}
              onClick={onDeploy}
            >
              Deploy &amp; Run
            </button>
          </>
        )}
        {isReady && deploying && (
          <button
            className="action-btn danger"
            onClick={onCancelRun}
          >
            Cancel Run
          </button>
        )}
        {isReady && validating && (
          <span className="action-btn" style={{ opacity: 0.6, pointerEvents: "none" }}>
            <span className="spinner" /> Validating...
          </span>
        )}
      </div>
    </div>
  );
}

function useCatalogOptions() {
  const [catalogs, setCatalogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const fetched = useRef(false);

  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    setLoading(true);
    listCatalogs()
      .then((r) => setCatalogs(r.catalogs.map((c) => c.name)))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return { catalogs, loading };
}

function useSchemaOptions(catalog: string) {
  const [schemas, setSchemas] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!catalog) { setSchemas([]); return; }
    setLoading(true);
    listSchemas(catalog)
      .then((r) => setSchemas(r.schemas.map((s) => s.name)))
      .catch(() => setSchemas([]))
      .finally(() => setLoading(false));
  }, [catalog]);

  return { schemas, loading };
}

function useVolumeOptions(catalog: string, schema: string) {
  const [volumes, setVolumes] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!catalog || !schema) { setVolumes([]); return; }
    setLoading(true);
    listVolumes(catalog, schema)
      .then((r) => setVolumes(r.volumes.map((v) => v.name)))
      .catch(() => setVolumes([]))
      .finally(() => setLoading(false));
  }, [catalog, schema]);

  return { volumes, loading };
}

function IngestProgressTracker({ tasks }: { tasks?: { task_key: string; life_cycle_state: string; result_state: string | null }[] }) {
  const displayTasks = [
    { key: "setup_tables", label: "Setup tables" },
    { key: "detect_new_files", label: "Detect new files" },
    { key: "get_next_batch", label: "Select batch" },
    { key: "mdf_to_delta", label: "Convert MDF to Delta" },
    { key: "analytical_layer", label: "Build Silver layer" },
    { key: "channel_metadata", label: "Extract channel metadata" },
    { key: "container_metadata", label: "Extract container metadata" },
    { key: "conversion_succeeded", label: "Finalize" },
  ];

  const taskMap = new Map((tasks || []).map((t) => [t.task_key, t]));

  return (
    <div className="deploy-tracker" style={{ marginTop: 12 }}>
      <div className="deploy-tracker-title">Ingest Pipeline Progress</div>
      <div className="deploy-tracker-steps">
        {displayTasks.map((dt) => {
          const t = taskMap.get(dt.key);
          const isRunning = t?.life_cycle_state === "RUNNING";
          const isDone = t?.result_state === "SUCCESS";
          const isFailed = t?.result_state === "FAILED" || t?.result_state === "TIMEDOUT";
          const isSkipped = t?.result_state === "EXCLUDED" || t?.result_state === "UPSTREAM_FAILED";

          let icon = "\u25CB";
          let color = "var(--text-muted)";
          if (isDone) { icon = "\u2713"; color = "var(--success)"; }
          else if (isFailed) { icon = "\u2715"; color = "var(--error)"; }
          else if (isSkipped) { icon = "\u2014"; color = "var(--text-muted)"; }
          else if (isRunning) { color = "var(--accent)"; }

          return (
            <div key={dt.key} className="deploy-tracker-step" style={{ color }}>
              <span className="deploy-tracker-step-icon">
                {isRunning ? <span className="spinner" style={{ width: 14, height: 14 }} /> : icon}
              </span>
              <span className="deploy-tracker-step-label">{dt.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ComboBox({
  value,
  onChange,
  options,
  disabled,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  disabled?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // If value exactly matches an option, show all (user already picked one).
  // Otherwise filter (user is mid-search).
  const exactMatch = options.some((o) => o.toLowerCase() === value.toLowerCase());
  const filtered = value && !exactMatch
    ? options.filter((o) => o.toLowerCase().includes(value.toLowerCase()))
    : options;

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <div style={{ display: "flex", gap: 0 }}>
        <input
          className="form-input"
          style={{ borderTopRightRadius: 0, borderBottomRightRadius: 0 }}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => { onChange(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
        />
        <button
          type="button"
          disabled={disabled || options.length === 0}
          className="form-input"
          style={{
            width: 32, flexShrink: 0, padding: 0, cursor: "pointer",
            borderTopLeftRadius: 0, borderBottomLeftRadius: 0,
            borderLeft: "none", display: "flex", alignItems: "center", justifyContent: "center",
          }}
          onClick={() => setOpen((o) => !o)}
          tabIndex={-1}
        >
          ▾
        </button>
      </div>
      {open && filtered.length > 0 && !disabled && (
        <div style={{
          position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20,
          background: "var(--bg-primary)", border: "1px solid var(--border)",
          borderRadius: "var(--radius)", marginTop: 2, maxHeight: 180, overflowY: "auto",
        }}>
          {filtered.map((o) => (
            <div
              key={o}
              style={{
                padding: "7px 12px", fontSize: 13, cursor: "pointer",
                color: "var(--text-primary)",
              }}
              onMouseDown={() => { onChange(o); setOpen(false); }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              {o}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SourceDataStep({
  sourceData,
  onSetSourceData,
  onUploadFiles,
  onTriggerIngest,
  ingestTasks,
}: {
  sourceData: SourceDataConfig;
  onSetSourceData: (mode: "upload" | "existing", opts?: {
    silver_catalog?: string;
    silver_schema?: string;
    upload_catalog?: string;
    upload_schema?: string;
    upload_volume?: string;
  }) => void;
  onUploadFiles: (files: FileList) => void;
  onTriggerIngest: () => void;
  ingestTasks: { task_key: string; life_cycle_state: string; result_state: string | null }[];
}) {
  const [catalog, setCatalog] = useState(sourceData.silver_catalog);
  const [schema, setSchema] = useState(sourceData.silver_schema);
  const [uploadCatalog, setUploadCatalog] = useState(sourceData.upload_catalog);
  const [uploadSchema, setUploadSchema] = useState(sourceData.upload_schema);
  const [uploadVolume, setUploadVolume] = useState(sourceData.upload_volume);
  const [silverCatalog, setSilverCatalog] = useState(sourceData.silver_catalog || sourceData.upload_catalog);
  const [silverSchema, setSilverSchema] = useState(sourceData.silver_schema);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { catalogs, loading: catalogsLoading } = useCatalogOptions();
  const { schemas: existingSchemas, loading: existingSchemasLoading } = useSchemaOptions(catalog);
  const { schemas: uploadSchemas, loading: uploadSchemasLoading } = useSchemaOptions(uploadCatalog);
  const { volumes, loading: volumesLoading } = useVolumeOptions(uploadCatalog, uploadSchema);
  const { schemas: silverSchemas, loading: silverSchemasLoading } = useSchemaOptions(silverCatalog);

  const mode = sourceData.mode;
  const volumeConfigured = !!(uploadCatalog && uploadSchema && uploadVolume);
  const hasFiles = sourceData.uploaded_files.length > 0;
  const silverConfigured = !!(silverCatalog && silverSchema);
  const canTransform = hasFiles && silverConfigured && sourceData.ingest_status === "not_started";
  const isIngesting = sourceData.ingest_status === "running";
  const ingestDone = sourceData.ingest_status === "succeeded";
  const ingestFailed = sourceData.ingest_status === "failed";

  const saveUploadConfig = useCallback(() => {
    onSetSourceData("upload", {
      upload_catalog: uploadCatalog,
      upload_schema: uploadSchema,
      upload_volume: uploadVolume,
    });
  }, [onSetSourceData, uploadCatalog, uploadSchema, uploadVolume]);

  useEffect(() => {
    if (mode === "upload" && uploadCatalog && uploadSchema && uploadVolume) {
      saveUploadConfig();
    }
  }, [uploadCatalog, uploadSchema, uploadVolume, mode, saveUploadConfig]);

  // Auto-default silver catalog to upload catalog
  useEffect(() => {
    if (mode === "upload" && uploadCatalog && !silverCatalog) {
      setSilverCatalog(uploadCatalog);
    }
  }, [uploadCatalog, silverCatalog, mode]);

  // Sync silver destination to backend
  useEffect(() => {
    if (mode === "upload" && silverCatalog && silverSchema) {
      onSetSourceData("upload", {
        upload_catalog: uploadCatalog,
        upload_schema: uploadSchema,
        upload_volume: uploadVolume,
        silver_catalog: silverCatalog,
        silver_schema: silverSchema,
      });
    }
  }, [silverCatalog, silverSchema]);

  useEffect(() => {
    if (mode === "existing" && catalog && schema) {
      onSetSourceData("existing", { silver_catalog: catalog, silver_schema: schema });
    }
  }, [catalog, schema, mode, onSetSourceData]);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    setUploading(true);
    try {
      await Promise.resolve(onUploadFiles(e.target.files));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div>
      <div className="step-header">
        <div className="step-title">Choose Data Source</div>
        <div className="step-subtitle">
          Upload MF4 measurement files or connect to existing Silver layer tables
        </div>
      </div>

      <div className="source-mode-buttons">
        <button
          className={`action-btn ${mode === "upload" ? "primary" : ""}`}
          onClick={() => onSetSourceData("upload")}
          disabled={isIngesting}
        >
          Upload MF4 Files
        </button>
        <button
          className={`action-btn ${mode === "existing" ? "primary" : ""}`}
          onClick={() => onSetSourceData("existing")}
          disabled={isIngesting}
        >
          Existing Silver Tables
        </button>
      </div>

      {mode === "upload" && (
        <div>
          {/* Step 1: Volume + Upload */}
          <div className="card" style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              1. Upload MF4 Files to Volume
            </div>
            <div className="form-group">
              <label className="form-label">Catalog</label>
              <ComboBox
                value={uploadCatalog}
                options={catalogs}
                disabled={isIngesting || ingestDone}
                placeholder={catalogsLoading ? "Loading..." : "Select or type a catalog"}
                onChange={(v) => { setUploadCatalog(v); setUploadSchema(""); setUploadVolume(""); }}
              />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label">Schema</label>
                <ComboBox
                  value={uploadSchema}
                  options={uploadSchemas}
                  disabled={!uploadCatalog || isIngesting || ingestDone}
                  placeholder={!uploadCatalog ? "..." : uploadSchemasLoading ? "Loading..." : "Select or type"}
                  onChange={(v) => { setUploadSchema(v); setUploadVolume(""); }}
                />
              </div>
              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label">Volume</label>
                <ComboBox
                  value={uploadVolume}
                  options={volumes}
                  disabled={!uploadSchema || isIngesting || ingestDone}
                  placeholder={!uploadSchema ? "..." : volumesLoading ? "Loading..." : "Select or type"}
                  onChange={setUploadVolume}
                />
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".mf4,.MF4"
              style={{ display: "none" }}
              onChange={handleFileSelect}
            />
            <button
              className="action-btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={!volumeConfigured || uploading || isIngesting || ingestDone}
              style={{ width: "100%", marginTop: 4 }}
            >
              {uploading ? (
                <><span className="spinner" style={{ width: 14, height: 14, marginRight: 6 }} />Uploading...</>
              ) : (
                "Select MF4 Files"
              )}
            </button>
            {hasFiles && (
              <div className="source-file-list" style={{ marginTop: 8 }}>
                {sourceData.uploaded_files.map((f, i) => (
                  <div key={i} className="source-file-item">
                    <span className="file-icon">&#128196;</span>
                    {f}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Step 2: Silver destination + Transform */}
          {hasFiles && !ingestDone && (
            <div className="card" style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
                2. Transform to Silver Layer
              </div>
              <div className="form-hint" style={{ marginBottom: 8 }}>
                Choose where the processed Silver tables will be created.
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label className="form-label">Catalog</label>
                  <ComboBox
                    value={silverCatalog}
                    options={catalogs}
                    disabled={isIngesting}
                    placeholder={catalogsLoading ? "Loading..." : "Select or type"}
                    onChange={(v) => { setSilverCatalog(v); setSilverSchema(""); }}
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label className="form-label">Schema</label>
                  <ComboBox
                    value={silverSchema}
                    options={silverSchemas}
                    disabled={!silverCatalog || isIngesting}
                    placeholder={!silverCatalog ? "..." : silverSchemasLoading ? "Loading..." : "Select or type"}
                    onChange={setSilverSchema}
                  />
                </div>
              </div>

              {!isIngesting && (
                <button
                  className="action-btn primary"
                  disabled={!silverConfigured || !hasFiles}
                  onClick={onTriggerIngest}
                  style={{ width: "100%", marginTop: 4 }}
                >
                  {ingestFailed ? "Retry Transform" : "Transform to Silver Layer"}
                </button>
              )}
              {isIngesting && (
                <div style={{ textAlign: "center", padding: "8px 0", color: "var(--text-muted)", fontSize: 13 }}>
                  <span className="spinner" style={{ width: 14, height: 14, marginRight: 6 }} />
                  Transform in progress...
                </div>
              )}
            </div>
          )}

          {/* Progress tracker */}
          {isIngesting && <IngestProgressTracker tasks={ingestTasks} />}

          {/* Success */}
          {ingestDone && (
            <div className="card" style={{ borderLeft: "3px solid var(--success)" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--success)", marginBottom: 4 }}>
                Silver layer tables created
              </div>
              <div className="form-hint">
                {silverCatalog}.{silverSchema}: channels, channel_tags, channel_metrics, container_tags, container_metrics
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-secondary)" }}>
                Click <strong>Next Step</strong> to continue.
              </div>
            </div>
          )}

          {/* Failed */}
          {ingestFailed && (
            <div className="card" style={{ borderLeft: "3px solid var(--error)" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--error)" }}>
                Transform failed
              </div>
              <div className="form-hint">
                Check the Databricks job run for details. You can retry the transform above.
              </div>
            </div>
          )}
        </div>
      )}

      {mode === "existing" && (
        <div>
          <div className="form-group">
            <label className="form-label">Catalog</label>
            <ComboBox
              value={catalog}
              options={catalogs}
              placeholder={catalogsLoading ? "Loading..." : "Select or type a catalog"}
              onChange={(v) => { setCatalog(v); setSchema(""); }}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Schema</label>
            <ComboBox
              value={schema}
              options={existingSchemas}
              disabled={!catalog}
              placeholder={!catalog ? "Select a catalog first" : existingSchemasLoading ? "Loading..." : "Select or type a schema"}
              onChange={setSchema}
            />
          </div>
          <div className="form-hint">
            Schema should contain: channels, channel_tags, channel_metrics, container_tags, container_metrics
          </div>
        </div>
      )}
    </div>
  );
}


function StepSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="step-header">
        <div className="step-title">{title}</div>
        {subtitle && <div className="step-subtitle">{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

function MetadataForm({
  state,
  onSaveMetadata,
}: {
  state: ReportState;
  onSaveMetadata: (data: { name: string; description: string; creator: string }) => void;
}) {
  const [formName, setFormName] = useState(state.name);
  const [formDesc, setFormDesc] = useState(state.description);
  const [formCreator, setFormCreator] = useState(state.creator);

  const handleSave = () => {
    if (!formName.trim()) return;
    onSaveMetadata({ name: formName, description: formDesc, creator: formCreator });
  };

  return (
    <div>
      <div className="step-header">
        <div className="step-title">Report Metadata</div>
        <div className="step-subtitle">Give your report a name and description</div>
      </div>
      <div className="card">
        <div className="form-group">
          <label className="form-label">
            Report Name <span style={{ color: "var(--error)" }}>*</span>
          </label>
          <input
            className="form-input"
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            placeholder="e.g. oil_temp_report"
          />
          <div className="form-hint">Lowercase, underscores, no spaces</div>
        </div>
        <div className="form-group">
          <label className="form-label">Description</label>
          <input
            className="form-input"
            value={formDesc}
            onChange={(e) => setFormDesc(e.target.value)}
            placeholder="e.g. Oil temperature duration analysis"
          />
        </div>
        <div className="form-group">
          <label className="form-label">Report Creator</label>
          <input
            className="form-input"
            value={formCreator}
            onChange={(e) => setFormCreator(e.target.value)}
            placeholder="e.g. John Doe"
          />
        </div>
        <button
          className="action-btn primary"
          style={{ marginTop: 8, width: "100%" }}
          disabled={!formName.trim()}
          onClick={handleSave}
        >
          {state.name ? "Update Metadata" : "Save Metadata"}
        </button>
        {state.name && (
          <div style={{ marginTop: 12, fontSize: 12, color: "var(--success)" }}>
            Saved. Click <strong>Next Step</strong> below to proceed.
          </div>
        )}
      </div>
    </div>
  );
}

function ChannelBrowser({
  channels,
  existingNames,
  onAdd,
}: {
  channels: AvailableChannel[];
  existingNames: Set<string>;
  onAdd: (selected: { alias: string; var_name: string; channel_name: string; description: string }[]) => void;
}) {
  const [filter, setFilter] = useState("");
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [collapsed, setCollapsed] = useState(false);

  if (channels.length === 0) return null;

  const filtered = filter
    ? channels.filter(
        (ch) =>
          ch.channel_name.toLowerCase().includes(filter.toLowerCase()) ||
          ch.unit.toLowerCase().includes(filter.toLowerCase())
      )
    : channels;

  const toggle = (idx: number) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleAdd = () => {
    const selected = Array.from(checked)
      .map((i) => filtered[i])
      .filter(Boolean)
      .map((ch) => {
        const varName = ch.channel_name
          .replace(/[^a-zA-Z0-9_]/g, "_")
          .replace(/_+/g, "_")
          .replace(/^_|_$/g, "")
          .toLowerCase();
        return {
          alias: ch.channel_name,
          var_name: varName,
          channel_name: ch.channel_name,
          description: ch.unit ? `${ch.channel_name} [${ch.unit}]` : ch.channel_name,
        };
      });
    onAdd(selected);
    setChecked(new Set());
  };

  const formatNum = (v: number | null) =>
    v != null ? (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2)) : "—";

  return (
    <div className="channel-browser">
      <div
        className="candidate-header"
        style={{ cursor: "pointer" }}
        onClick={() => setCollapsed((p) => !p)}
      >
        <span className="candidate-title">
          Browse Channels ({channels.length})
        </span>
        <span style={{ fontSize: 12, opacity: 0.6 }}>{collapsed ? "+" : "−"}</span>
      </div>
      {!collapsed && (
        <>
          <input
            type="text"
            className="channel-filter"
            placeholder="Filter by name or unit..."
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setChecked(new Set());
            }}
          />
          <div className="candidate-list" style={{ maxHeight: 280 }}>
            {filtered.map((ch, i) => {
              const alreadyAdded = existingNames.has(ch.channel_name);
              return (
                <label key={ch.channel_name} className={`candidate-row ${alreadyAdded ? "disabled" : ""}`}>
                  <input
                    type="checkbox"
                    checked={checked.has(i)}
                    disabled={alreadyAdded}
                    onChange={() => toggle(i)}
                  />
                  <div className="candidate-info">
                    <div className="candidate-alias">{ch.channel_name}</div>
                    <div className="candidate-meta">
                      {ch.unit && <span className="candidate-unit">{ch.unit}</span>}
                      <span style={{ opacity: 0.5, fontSize: 11 }}>
                        {formatNum(ch.min_value)} – {formatNum(ch.max_value)}
                      </span>
                      <span style={{ opacity: 0.4, fontSize: 11 }}>
                        {ch.sample_count.toLocaleString()} samples
                      </span>
                    </div>
                  </div>
                  {alreadyAdded && <span className="candidate-badge">Added</span>}
                </label>
              );
            })}
            {filtered.length === 0 && (
              <div style={{ padding: 12, opacity: 0.5, textAlign: "center" }}>
                No channels match "{filter}"
              </div>
            )}
          </div>
          {checked.size > 0 && (
            <button
              className="action-btn primary"
              style={{ marginTop: 8, width: "100%" }}
              onClick={handleAdd}
            >
              Add {checked.size} Channel{checked.size !== 1 ? "s" : ""}
            </button>
          )}
        </>
      )}
    </div>
  );
}


function CandidateSelector({
  candidates,
  existingAliases,
  onConfirm,
}: {
  candidates: SignalCandidate[];
  existingAliases: Set<string>;
  onConfirm: (selected: { alias: string; var_name: string; channel_name: string; description: string }[]) => void;
}) {
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const toggle = (idx: number) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleAll = () => {
    if (checked.size === candidates.length) {
      setChecked(new Set());
    } else {
      setChecked(new Set(candidates.map((_, i) => i)));
    }
  };

  const handleAdd = () => {
    const selected = Array.from(checked).map((i) => {
      const c = candidates[i];
      const varName = (c.channel_name || c.alias)
        .replace(/[^a-zA-Z0-9_]/g, "_")
        .replace(/_+/g, "_")
        .replace(/^_|_$/g, "")
        .toLowerCase();
      return {
        alias: c.alias,
        var_name: varName,
        channel_name: c.channel_name || c.alias,
        description: c.description || "",
      };
    });
    onConfirm(selected);
    setChecked(new Set());
  };

  return (
    <div className="candidate-selector">
      <div className="candidate-header">
        <span className="candidate-title">Signal Candidates</span>
        <label className="candidate-toggle-all">
          <input
            type="checkbox"
            checked={checked.size === candidates.length && candidates.length > 0}
            onChange={toggleAll}
          />
          Select all
        </label>
      </div>
      <div className="candidate-list">
        {candidates.map((c, i) => {
          const alreadyAdded = existingAliases.has(c.alias);
          return (
            <label key={i} className={`candidate-row ${alreadyAdded ? "disabled" : ""}`}>
              <input
                type="checkbox"
                checked={checked.has(i)}
                disabled={alreadyAdded}
                onChange={() => toggle(i)}
              />
              <div className="candidate-info">
                <div className="candidate-alias">{c.channel_name || c.alias}</div>
                <div className="candidate-meta">
                  {c.unit && <span className="candidate-unit">{c.unit}</span>}
                  {c.description && <span className="candidate-desc">{c.description}</span>}
                  {c.device_name && <span className="candidate-device">{c.device_name}</span>}
                </div>
              </div>
              {alreadyAdded && <span className="candidate-badge">Added</span>}
            </label>
          );
        })}
      </div>
      <button
        className="action-btn primary"
        style={{ marginTop: 8, width: "100%" }}
        disabled={checked.size === 0}
        onClick={handleAdd}
      >
        Add {checked.size} Selected Signal{checked.size !== 1 ? "s" : ""}
      </button>
    </div>
  );
}

function VehiclesStep({
  state,
  onFetchCandidates,
  onSelectVehicles,
  onDeleteVehicle,
  onUpdateTimestamps,
  onFetchDataRange,
}: {
  state: ReportState;
  onFetchCandidates: () => void;
  onSelectVehicles: (selected: { vehicle_id: string; start_ts: string }[]) => void;
  onDeleteVehicle: (vehicleId: string) => void;
  onUpdateTimestamps: (payload: {
    global_start_ts: string;
    global_stop_ts: string | null;
    per_vehicle: { vehicle_id: string; start_ts: string; stop_ts: string | null }[];
  }) => void;
  onFetchDataRange: () => Promise<{ min_start: string | null; max_stop: string | null } | null>;
}) {
  const [loading, setLoading] = useState(false);
  const [fetched, setFetched] = useState(false);
  const [showCandidates, setShowCandidates] = useState(false);

  // Auto-fetch on first render when no vehicles exist
  useEffect(() => {
    if (state.vehicle_candidates.length === 0 && state.vehicles.length === 0 && !fetched) {
      setLoading(true);
      setFetched(true);
      setShowCandidates(true);
      Promise.resolve(onFetchCandidates()).finally(() => setLoading(false));
    }
  }, [state.vehicle_candidates.length, state.vehicles.length, fetched, onFetchCandidates]);

  const handleLoadMore = () => {
    setLoading(true);
    setShowCandidates(true);
    Promise.resolve(onFetchCandidates()).finally(() => setLoading(false));
  };

  return (
    <div>
      <div className="step-header">
        <div className="step-title">Vehicles & Data Sources</div>
        <div className="step-subtitle">{state.vehicles.length} vehicle(s) configured</div>
      </div>

      {loading && (
        <div className="card" style={{ textAlign: "center", padding: 24, color: "var(--text-muted)" }}>
          <span className="spinner" style={{ marginRight: 8 }} />
          Loading available vehicles from Unity Catalog...
        </div>
      )}

      {!loading && showCandidates && state.vehicle_candidates.length > 0 && (
        <VehicleCandidateSelector
          candidates={state.vehicle_candidates}
          existingIds={new Set(state.vehicles.map((v) => v.vehicle_id))}
          onConfirm={(selected) => {
            onSelectVehicles(selected);
            setShowCandidates(false);
          }}
        />
      )}

      {!loading && state.vehicle_candidates.length === 0 && state.vehicles.length === 0 && fetched && (
        <div className="card" style={{ color: "var(--text-muted)", fontSize: 13 }}>
          No vehicles found in the data. You can add vehicles manually via the chat instead.
        </div>
      )}

      {/* Selected vehicles list with delete */}
      {state.vehicles.length > 0 && (
        <div className="candidate-selector" style={{ marginTop: 12 }}>
          <div className="candidate-header">
            <span className="candidate-title">Selected Vehicles ({state.vehicles.length})</span>
          </div>
          <div className="candidate-list" style={{ maxHeight: 200 }}>
            {state.vehicles.map((v) => (
              <div key={v.vehicle_id} className="candidate-row" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div className="candidate-info">
                  <div className="candidate-alias">{v.vehicle_id}</div>
                  <div className="candidate-meta">
                    {v.start_ts && <span style={{ fontSize: 11, opacity: 0.6 }}>from {v.start_ts}</span>}
                    {v.stop_ts && <span style={{ fontSize: 11, opacity: 0.6 }}> to {v.stop_ts}</span>}
                  </div>
                </div>
                <button
                  className="action-btn danger"
                  style={{ fontSize: 10, padding: "2px 6px", flexShrink: 0 }}
                  onClick={() => onDeleteVehicle(v.vehicle_id)}
                  title="Remove vehicle"
                >
                  &#x2715;
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add more vehicles button */}
      {!loading && !showCandidates && (
        <button
          className="action-btn"
          style={{ marginTop: 8, fontSize: 11 }}
          onClick={handleLoadMore}
        >
          + Add More Vehicles
        </button>
      )}

      {state.vehicles.length > 0 && (
        <TimestampEditor vehicles={state.vehicles} onSave={onUpdateTimestamps} onFetchDataRange={onFetchDataRange} />
      )}

      {state.vehicles.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <ConfigTab vehicles={state.vehicles} dataSources={state.data_sources} />
        </div>
      )}
    </div>
  );
}

function _toDatetimeLocal(ts: string): string {
  // Convert "2025-01-15 08:30:00" or ISO to "2025-01-15T08:30" for datetime-local input
  if (!ts) return "";
  const clean = ts.replace(" ", "T").replace(/Z$/, "");
  return clean.slice(0, 16); // "YYYY-MM-DDTHH:MM"
}

function _lastNDays(n: number): { start: string; stop: string } {
  const now = new Date();
  const start = new Date(now.getTime() - n * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) =>
    d.getFullYear() +
    "-" + String(d.getMonth() + 1).padStart(2, "0") +
    "-" + String(d.getDate()).padStart(2, "0") +
    "T" + String(d.getHours()).padStart(2, "0") +
    ":" + String(d.getMinutes()).padStart(2, "0");
  return { start: fmt(start), stop: fmt(now) };
}

function TimestampEditor({
  vehicles,
  onSave,
  onFetchDataRange,
}: {
  vehicles: ReportState["vehicles"];
  onSave: (payload: {
    global_start_ts: string;
    global_stop_ts: string | null;
    per_vehicle: { vehicle_id: string; start_ts: string; stop_ts: string | null }[];
  }) => void;
  onFetchDataRange: () => Promise<{ min_start: string | null; max_stop: string | null } | null>;
}) {
  const [globalStart, setGlobalStart] = useState(() => vehicles[0]?.start_ts || "");
  const [globalStop, setGlobalStop] = useState(() => vehicles[0]?.stop_ts || "");
  const [perVehicle, setPerVehicle] = useState(false);
  const [rows, setRows] = useState(() =>
    vehicles.map((v) => ({ vehicle_id: v.vehicle_id, start_ts: v.start_ts, stop_ts: v.stop_ts || "" }))
  );
  const [loadingRange, setLoadingRange] = useState(false);

  const updateRow = (idx: number, field: "start_ts" | "stop_ts", value: string) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, [field]: value } : r)));
  };

  const applyPreset = (days: number) => {
    const { start, stop } = _lastNDays(days);
    if (perVehicle) {
      setRows((prev) => prev.map((r) => ({ ...r, start_ts: start, stop_ts: stop })));
    } else {
      setGlobalStart(start);
      setGlobalStop(stop);
    }
  };

  const applyFromData = async () => {
    setLoadingRange(true);
    try {
      const range = await onFetchDataRange();
      if (range) {
        const start = range.min_start ? _toDatetimeLocal(range.min_start) : "";
        const stop = range.max_stop ? _toDatetimeLocal(range.max_stop) : "";
        if (perVehicle) {
          setRows((prev) => prev.map((r) => ({
            ...r,
            start_ts: start || r.start_ts,
            stop_ts: stop || r.stop_ts,
          })));
        } else {
          if (start) setGlobalStart(start);
          if (stop) setGlobalStop(stop);
        }
      }
    } finally {
      setLoadingRange(false);
    }
  };

  const handleSave = () => {
    if (perVehicle) {
      onSave({
        global_start_ts: "",
        global_stop_ts: null,
        per_vehicle: rows.map((r) => ({
          vehicle_id: r.vehicle_id,
          start_ts: r.start_ts,
          stop_ts: r.stop_ts || null,
        })),
      });
    } else {
      onSave({
        global_start_ts: globalStart,
        global_stop_ts: globalStop || null,
        per_vehicle: [],
      });
    }
  };

  const hasStart = perVehicle ? rows.some((r) => r.start_ts) : !!globalStart;

  return (
    <div className="candidate-selector" style={{ marginTop: 16 }}>
      <div className="candidate-header">
        <span className="candidate-title">Analysis Timeframe</span>
        <label className="candidate-toggle-all">
          <input
            type="checkbox"
            checked={perVehicle}
            onChange={() => setPerVehicle(!perVehicle)}
          />
          Per vehicle
        </label>
      </div>

      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 8 }}>
        <button className="ts-preset-btn" onClick={() => applyPreset(1)} title="Last 24 hours">L1D</button>
        <button className="ts-preset-btn" onClick={() => applyPreset(7)} title="Last 7 days">L7D</button>
        <button className="ts-preset-btn" onClick={() => applyPreset(30)} title="Last 30 days">L30D</button>
        <button className="ts-preset-btn" onClick={() => applyPreset(90)} title="Last 90 days">L90D</button>
        <button
          className="ts-preset-btn ts-preset-data"
          onClick={applyFromData}
          disabled={loadingRange}
          title="Set to full range of actual data"
        >
          {loadingRange ? "..." : "From Data"}
        </button>
      </div>

      {!perVehicle && (
        <div style={{ display: "flex", gap: 8 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">
              Start <span style={{ color: "var(--error)" }}>*</span>
            </label>
            <input
              className="form-input"
              type="datetime-local"
              value={globalStart}
              onChange={(e) => setGlobalStart(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Stop (optional)</label>
            <input
              className="form-input"
              type="datetime-local"
              value={globalStop}
              onChange={(e) => setGlobalStop(e.target.value)}
            />
          </div>
        </div>
      )}

      {perVehicle && (
        <div className="candidate-list" style={{ maxHeight: 300 }}>
          {rows.map((r, i) => (
            <div key={r.vehicle_id} className="timestamp-row">
              <div className="timestamp-vehicle-id">{r.vehicle_id}</div>
              <div style={{ display: "flex", gap: 6, flex: 1 }}>
                <input
                  className="form-input"
                  type="datetime-local"
                  value={r.start_ts}
                  onChange={(e) => updateRow(i, "start_ts", e.target.value)}
                  placeholder="Start"
                  style={{ flex: 1, fontSize: 12 }}
                />
                <input
                  className="form-input"
                  type="datetime-local"
                  value={r.stop_ts}
                  onChange={(e) => updateRow(i, "stop_ts", e.target.value)}
                  placeholder="Stop"
                  style={{ flex: 1, fontSize: 12 }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <button
        className="action-btn primary"
        style={{ marginTop: 8, width: "100%" }}
        disabled={!hasStart}
        onClick={handleSave}
      >
        Save Timestamps
      </button>
    </div>
  );
}

function VehicleCandidateSelector({
  candidates,
  existingIds,
  onConfirm,
}: {
  candidates: VehicleCandidate[];
  existingIds: Set<string>;
  onConfirm: (selected: { vehicle_id: string; start_ts: string }[]) => void;
}) {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");

  const filtered = filter
    ? candidates.filter((c) => c.vehicle_id.toLowerCase().includes(filter.toLowerCase()))
    : candidates;

  const toggle = (idx: number) => {
    const realIdx = candidates.indexOf(filtered[idx]);
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(realIdx)) next.delete(realIdx);
      else next.add(realIdx);
      return next;
    });
  };

  const toggleAll = () => {
    const filteredIndices = filtered.map((c) => candidates.indexOf(c));
    const allChecked = filteredIndices.every((i) => checked.has(i));
    setChecked((prev) => {
      const next = new Set(prev);
      for (const i of filteredIndices) {
        if (existingIds.has(candidates[i].vehicle_id)) continue;
        if (allChecked) next.delete(i);
        else next.add(i);
      }
      return next;
    });
  };

  const handleAdd = () => {
    const selected = Array.from(checked).map((i) => ({
      vehicle_id: candidates[i].vehicle_id,
      start_ts: "",
    }));
    onConfirm(selected);
    setChecked(new Set());
  };

  const allFilteredChecked =
    filtered.length > 0 &&
    filtered.every((c) => existingIds.has(c.vehicle_id) || checked.has(candidates.indexOf(c)));

  return (
    <div className="candidate-selector">
      <div className="candidate-header">
        <span className="candidate-title">Available Vehicles ({candidates.length})</span>
        <label className="candidate-toggle-all">
          <input type="checkbox" checked={allFilteredChecked} onChange={toggleAll} />
          Select all
        </label>
      </div>
      {candidates.length > 10 && (
        <input
          className="form-input"
          style={{ marginBottom: 8, fontSize: 12 }}
          placeholder="Filter vehicles..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      )}
      <div className="candidate-list">
        {filtered.map((c, i) => {
          const realIdx = candidates.indexOf(c);
          const alreadyAdded = existingIds.has(c.vehicle_id);
          return (
            <label key={c.vehicle_id} className={`candidate-row ${alreadyAdded ? "disabled" : ""}`}>
              <input
                type="checkbox"
                checked={checked.has(realIdx)}
                disabled={alreadyAdded}
                onChange={() => toggle(i)}
              />
              <div className="candidate-info">
                <div className="candidate-alias">{c.vehicle_id}</div>
                <div className="candidate-meta">
                  <span>{c.datapoint_count} datapoint(s)</span>
                </div>
              </div>
              {alreadyAdded && <span className="candidate-badge">Added</span>}
            </label>
          );
        })}
      </div>
      <button
        className="action-btn primary"
        style={{ marginTop: 8, width: "100%" }}
        disabled={checked.size === 0}
        onClick={handleAdd}
      >
        Add {checked.size} Selected Vehicle{checked.size !== 1 ? "s" : ""}
      </button>
    </div>
  );
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// Known execution order for job tasks (dependency chain from jobs.yml)
const TASK_ORDER = ["pre_processing", "Vehicle_Config_Available", "report_generation", "post_processing"];

function RunTimeline({
  deployment,
  jobStatus,
}: {
  deployment: ReportState["deployment"];
  jobStatus: DeployStatusResponse | null;
}) {
  const deployPhases: { key: string; label: string; doneWhen: ReportState["deployment"][] }[] = [
    { key: "scaffold", label: "Scaffolding report", doneWhen: ["deploying", "running", "completed"] },
    { key: "deploy", label: "Deploying bundle", doneWhen: ["running", "completed"] },
  ];

  const isFailed = deployment === "failed";
  const isCompleted = deployment === "completed";
  const jobTasks = jobStatus?.tasks || [];

  // Sort job tasks by known dependency order
  const sortedTasks = [...jobTasks].sort((a, b) => {
    const ai = TASK_ORDER.indexOf(a.task_key);
    const bi = TASK_ORDER.indexOf(b.task_key);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

  function stepIcon(done: boolean, active: boolean, failed: boolean) {
    if (done) return <span style={{ color: "var(--success)" }}>✓</span>;
    if (failed) return <span style={{ color: "var(--error)" }}>✕</span>;
    if (active) return <span className="spinner" style={{ width: 14, height: 14 }} />;
    return <span style={{ color: "var(--text-muted)" }}>○</span>;
  }

  return (
    <div className="job-tracker">
      <div className="job-tracker-header">
        <span className="job-tracker-title">
          {isCompleted
            ? <span style={{ color: "var(--success)" }}>Report Completed</span>
            : isFailed
              ? <span style={{ color: "var(--error)" }}>Run Failed</span>
              : <><span className="spinner" style={{ marginRight: 8 }} />Running Report</>}
        </span>
        {jobStatus && <span className="job-tracker-elapsed">{formatElapsed(jobStatus.elapsed_seconds)}</span>}
      </div>

      <div className="job-tracker-tasks">
        {/* Deploy phases */}
        {deployPhases.map((phase) => {
          const done = phase.doneWhen.includes(deployment) || isCompleted;
          const active =
            (phase.key === "scaffold" && deployment === "scaffolding") ||
            (phase.key === "deploy" && deployment === "deploying");
          const failed = isFailed && !done && active;

          return (
            <div key={phase.key} className="job-tracker-task" style={{ color: done ? "var(--success)" : active ? "var(--accent)" : failed ? "var(--error)" : "var(--text-muted)" }}>
              <span className="job-tracker-task-icon">{stepIcon(done, active, failed)}</span>
              <span className="job-tracker-task-name">{phase.label}</span>
              <span className="job-tracker-task-state">
                {done ? "DONE" : active ? "IN PROGRESS" : failed ? "FAILED" : ""}
              </span>
            </div>
          );
        })}

        {/* Job tasks — only show once we have a run */}
        {sortedTasks.map((t) => {
          const taskDone = t.result_state === "SUCCESS";
          const taskFail = t.result_state === "FAILED" || t.result_state === "TIMEDOUT" || t.result_state === "EXCLUDED";
          const taskRunning = t.life_cycle_state === "RUNNING";
          let color = "var(--text-muted)";
          if (taskDone) color = "var(--success)";
          else if (taskFail) color = "var(--error)";
          else if (taskRunning) color = "var(--accent)";

          return (
            <div key={t.task_key} className="job-tracker-task" style={{ color }}>
              <span className="job-tracker-task-icon">{stepIcon(taskDone, taskRunning, taskFail)}</span>
              <span className="job-tracker-task-name">{t.task_key}</span>
              <span className="job-tracker-task-state">
                {t.result_state || t.life_cycle_state || "—"}
              </span>
            </div>
          );
        })}

        {/* Placeholder for job tasks while waiting for run to start */}
        {sortedTasks.length === 0 && (deployment === "running" || deployment === "deploying" || deployment === "scaffolding") && !isFailed && (
          TASK_ORDER.map((key) => (
            <div key={key} className="job-tracker-task" style={{ color: "var(--text-muted)" }}>
              <span className="job-tracker-task-icon">○</span>
              <span className="job-tracker-task-name">{key}</span>
              <span className="job-tracker-task-state">—</span>
            </div>
          ))
        )}
      </div>

      {jobStatus?.run_url && (
        <a
          className="job-tracker-link"
          href={jobStatus.run_url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ marginTop: 8, display: "inline-block" }}
        >
          View in Databricks &rarr;
        </a>
      )}

      {isFailed && (
        <div style={{ color: "var(--error)", fontSize: 13, marginTop: 8 }}>
          Check the chat for error details.
        </div>
      )}
    </div>
  );
}

function ClusterConfigSection({
  useAllPurpose,
  clusterId,
  onChange,
}: {
  useAllPurpose: boolean;
  clusterId: string;
  onChange: (useAllPurpose: boolean, clusterId: string) => void;
}) {
  const [localClusterId, setLocalClusterId] = useState(clusterId);

  useEffect(() => {
    setLocalClusterId(clusterId);
  }, [clusterId]);

  return (
    <div className="candidate-selector" style={{ marginTop: 16 }}>
      <div className="candidate-header">
        <span className="candidate-title">Compute Configuration</span>
      </div>
      <div style={{ padding: "8px 0" }}>
        <div style={{ display: "flex", gap: 12 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13 }}>
            <input
              type="radio"
              name="cluster-mode"
              checked={!useAllPurpose}
              onChange={() => onChange(false, "")}
            />
            Serverless
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13 }}>
            <input
              type="radio"
              name="cluster-mode"
              checked={useAllPurpose}
              onChange={() => onChange(true, localClusterId)}
            />
            All-Purpose Cluster
          </label>
        </div>
        {useAllPurpose && (
          <div style={{ marginTop: 10 }}>
            {clusterId ? (
              <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                Using cluster: <code style={{ background: "var(--bg-secondary)", padding: "2px 6px", borderRadius: 4 }}>{clusterId}</code>
              </div>
            ) : (
              <div style={{ fontSize: 13, color: "var(--warning)" }}>
                No cluster configured. Open Settings (gear icon) to set an all-purpose cluster ID.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ReadyPanel({
  state,
  deploying,
  jobStatus,
  validating,
  onClusterConfigChange,
  onViewResults,
}: {
  state: ReportState;
  deploying: boolean;
  jobStatus: DeployStatusResponse | null;
  validating: boolean;
  onClusterConfigChange: (useAllPurpose: boolean, clusterId: string) => void;
  onViewResults: () => void;
}) {
  const hasActivity = deploying || state.deployment === "scaffolding" || state.deployment === "deploying" || state.deployment === "running" || state.deployment === "completed" || state.deployment === "failed";

  return (
    <div>
      <div className="step-header">
        <div className="step-title">Report Ready</div>
        <div className="step-subtitle">
          {state.signals.length} signals, {state.aggregations.length} aggregations, {state.vehicles.length} vehicles
        </div>
      </div>

      {hasActivity && (
        <RunTimeline deployment={state.deployment} jobStatus={jobStatus} />
      )}

      {!hasActivity && (
        <>
          <div className="card">
            <div className="card-title" style={{ fontSize: 18 }}>{state.name}</div>
            <div style={{ color: "var(--text-secondary)", marginTop: 4, fontSize: 14 }}>
              {state.description}
            </div>
            {state.creator && (
              <div style={{ color: "var(--text-muted)", marginTop: 4, fontSize: 13 }}>
                Created by: {state.creator}
              </div>
            )}
          </div>
          <ClusterConfigSection
            useAllPurpose={state.use_all_purpose_cluster}
            clusterId={state.all_purpose_cluster_id}
            onChange={onClusterConfigChange}
          />
          <div className="code-label" style={{ marginTop: 16 }}>Signals</div>
          <SignalsTab signals={state.signals} silverCatalog={state.source_data.silver_catalog} silverSchema={state.source_data.silver_schema} />
          <div className="code-label" style={{ marginTop: 16 }}>Aggregations</div>
          <AggregationsTab aggregations={state.aggregations} />
          <div className="code-label" style={{ marginTop: 16 }}>Vehicles & Data Sources</div>
          <ConfigTab vehicles={state.vehicles} dataSources={state.data_sources} />
        </>
      )}

      {hasActivity && (state.deployment === "running" || state.deployment === "completed" || state.deployment === "failed") && (
        <ResultsTab
          deployment={state.deployment}
          validation={state.validation}
          runUrl={state.run_url}
          validating={validating}
        />
      )}

      {state.deployment === "completed" && state.data_sources.destination_catalog && (
        <button
          className="action-btn primary"
          style={{ marginTop: 16, width: "100%" }}
          onClick={onViewResults}
        >
          View Results
        </button>
      )}
    </div>
  );
}
