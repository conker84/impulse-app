import type { AggregationDefinition, AggregationMeta, AvailableChannel, ChatResponse, Heatmap2DResult, Histogram1DDefinition, HistogramMeta, HistogramResult, ReportState, SavedReportSummary, StatisticsResult, TimeSeriesContainer, TimeSeriesLoadResponse, TimeSeriesPoint, TimeSeriesResampleResponse, TimeSeriesSignal, ValidationResults, WizardStep } from "./types";

const BASE = "/api";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export async function sendChat(
  message: string,
  sessionId: string | null
): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId }),
  });
}

export async function getState(sessionId: string): Promise<ReportState> {
  return request<ReportState>(`/state/${sessionId}`);
}

export async function setSourceData(
  sessionId: string | null,
  mode: "upload" | "existing",
  opts?: {
    silver_catalog?: string;
    silver_schema?: string;
    upload_catalog?: string;
    upload_schema?: string;
    upload_volume?: string;
  }
): Promise<{ session_id: string; report_state: ReportState }> {
  const body = {
    mode,
    silver_catalog: opts?.silver_catalog || "",
    silver_schema: opts?.silver_schema || "",
    upload_catalog: opts?.upload_catalog || "",
    upload_schema: opts?.upload_schema || "",
    upload_volume: opts?.upload_volume || "",
  };
  if (sessionId) {
    return request(`/set-source-data/${sessionId}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }
  return request("/set-source-data", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function uploadMf4Files(
  sessionId: string,
  files: FileList
): Promise<{ uploaded: string[]; errors: string[]; report_state: ReportState }> {
  const formData = new FormData();
  for (let i = 0; i < files.length; i++) {
    formData.append("files", files[i]);
  }
  const res = await fetch(`${BASE}/upload-mf4/${sessionId}`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Unity Catalog browsing
// ---------------------------------------------------------------------------

export async function listCatalogs(): Promise<{ catalogs: { name: string; comment: string }[] }> {
  return request("/uc/catalogs");
}

export async function listSchemas(catalog: string): Promise<{ schemas: { name: string; comment: string }[] }> {
  return request(`/uc/schemas?catalog=${encodeURIComponent(catalog)}`);
}

export async function listVolumes(catalog: string, schema: string): Promise<{ volumes: { name: string; comment: string }[] }> {
  return request(`/uc/volumes?catalog=${encodeURIComponent(catalog)}&schema=${encodeURIComponent(schema)}`);
}

// ---------------------------------------------------------------------------
// Ingest pipeline
// ---------------------------------------------------------------------------

export interface IngestTaskStatus {
  task_key: string;
  life_cycle_state: string;
  result_state: string | null;
}

export interface IngestStatusResponse {
  status: string;
  life_cycle_state: string;
  result_state: string | null;
  run_url: string;
  elapsed_seconds: number;
  tasks: IngestTaskStatus[];
  report_state: ReportState;
}

export async function triggerIngest(
  sessionId: string
): Promise<{ run_id: number; run_url: string; report_state: ReportState }> {
  return request(`/ingest/trigger/${sessionId}`, { method: "POST" });
}

export async function getIngestStatus(
  sessionId: string
): Promise<IngestStatusResponse> {
  return request(`/ingest/status/${sessionId}`);
}

export async function fetchChannelCatalog(
  sessionId: string
): Promise<{ channels: AvailableChannel[]; report_state: ReportState }> {
  return request(`/channel-catalog/${sessionId}`);
}

export async function searchAliases(
  keyword: string
): Promise<{ aliases: Array<Record<string, string>>; count: number }> {
  return request(`/aliases/search?keyword=${encodeURIComponent(keyword)}`);
}

export async function scaffoldReport(
  sessionId: string
): Promise<{ status: string; files: string[] }> {
  return request(`/scaffold/${sessionId}`, { method: "POST" });
}

export async function deployReport(
  sessionId: string
): Promise<{ status: string; estimated_minutes?: number; message?: string; stdout?: string; stderr?: string }> {
  return request(`/deploy/${sessionId}`, { method: "POST" });
}

export interface DeployStatusResponse {
  status: string;
  elapsed_seconds: number;
  run_url: string | null;
  result_state?: string;
  life_cycle_state?: string;
  tasks?: Array<{ task_key: string; result_state: string | null; life_cycle_state: string | null }>;
  message?: string;
}

export async function cancelRun(
  sessionId: string
): Promise<{ status: string; message: string }> {
  return request(`/deploy/cancel/${sessionId}`, { method: "POST" });
}

export async function getDeployStatus(
  sessionId: string
): Promise<DeployStatusResponse> {
  return request(`/deploy/status/${sessionId}`);
}

export async function validateReport(
  sessionId: string
): Promise<ValidationResults> {
  return request(`/validate/${sessionId}`, { method: "POST" });
}

export async function advanceStep(
  sessionId: string
): Promise<{ wizard_step: WizardStep; report_state: ReportState }> {
  return request(`/advance-step/${sessionId}`, { method: "POST" });
}

export async function selectCandidates(
  sessionId: string,
  selected: { alias: string; var_name: string; channel_name?: string; description: string }[]
): Promise<{ added: string[]; report_state: ReportState }> {
  return request(`/select-candidates/${sessionId}`, {
    method: "POST",
    body: JSON.stringify({ selected }),
  });
}

export async function deleteSignal(
  sessionId: string,
  varName: string
): Promise<{ report_state: ReportState }> {
  return request(`/signal/${sessionId}/${encodeURIComponent(varName)}`, { method: "DELETE" });
}

export async function updateSignal(
  sessionId: string,
  varName: string,
  payload: { var_name: string; expression?: string; eval_type?: string; description?: string; alias?: string }
): Promise<{ report_state: ReportState }> {
  return request(`/signal/${sessionId}/${encodeURIComponent(varName)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function addVirtualSignal(
  sessionId: string,
  payload: { var_name: string; expression: string; eval_type?: string; description?: string }
): Promise<{ report_state: ReportState }> {
  return request(`/add-virtual-signal/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchVehicleCandidates(
  sessionId: string
): Promise<{ candidates: { vehicle_id: string; datapoint_count: number }[]; report_state: ReportState }> {
  return request(`/fetch-vehicle-candidates/${sessionId}`, { method: "POST" });
}

export async function selectVehicles(
  sessionId: string,
  selected: { vehicle_id: string; start_ts: string }[]
): Promise<{ added: string[]; report_state: ReportState }> {
  return request(`/select-vehicles/${sessionId}`, {
    method: "POST",
    body: JSON.stringify({ selected }),
  });
}

export async function deleteVehicle(
  sessionId: string,
  vehicleId: string
): Promise<{ report_state: ReportState }> {
  return request(`/vehicle/${sessionId}/${encodeURIComponent(vehicleId)}`, { method: "DELETE" });
}

export async function updateVehicleTimestamps(
  sessionId: string,
  payload: {
    global_start_ts: string;
    global_stop_ts: string | null;
    per_vehicle: { vehicle_id: string; start_ts: string; stop_ts: string | null }[];
  }
): Promise<{ report_state: ReportState }> {
  return request(`/update-vehicle-timestamps/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchDataTimeRange(
  sessionId: string
): Promise<{ min_start: string | null; max_stop: string | null }> {
  return request(`/data-time-range/${sessionId}`);
}

export interface AvailableModel {
  id: string;
  label: string;
}

export interface TokenStatusResponse {
  local_mode: boolean;
  has_token: boolean;
  user_email?: string;
  cluster_id?: string;
  serving_endpoint?: string;
  available_models?: AvailableModel[];
}

export async function getTokenStatus(): Promise<TokenStatusResponse> {
  return request("/settings/token-status");
}

export async function saveToken(pat: string): Promise<{ status: string; user_email?: string }> {
  return request("/settings/token", {
    method: "POST",
    body: JSON.stringify({ pat }),
  });
}

export async function deleteToken(): Promise<{ status: string }> {
  return request("/settings/token", { method: "DELETE" });
}

export async function saveModelSetting(
  servingEndpoint: string
): Promise<{ status: string; serving_endpoint: string }> {
  return request("/settings/model", {
    method: "POST",
    body: JSON.stringify({ serving_endpoint: servingEndpoint }),
  });
}

export async function saveClusterSetting(
  clusterId: string
): Promise<{ status: string; cluster_id: string }> {
  return request("/settings/cluster", {
    method: "POST",
    body: JSON.stringify({ cluster_id: clusterId }),
  });
}

export async function setClusterConfig(
  sessionId: string,
  payload: { use_all_purpose_cluster: boolean; all_purpose_cluster_id: string }
): Promise<{ report_state: ReportState }> {
  return request(`/set-cluster-config/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function suggestBins(
  sessionId: string,
  payload: { histogram_type: string; signal_ref: string }
): Promise<{ bins: number[]; bins_unit: string; description: string; name: string }> {
  return request(`/suggest-bins/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Event CRUD
// ---------------------------------------------------------------------------

export async function addEvent(
  sessionId: string,
  payload: {
    name: string;
    event_type: string;
    conditions?: { signal_ref: string; operator: string; value: number }[];
    compound_logic?: string;
    signal_ref?: string | null;
    from_state?: number | null;
    to_state?: number | null;
    step?: number | null;
    description?: string;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/add-event/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateEvent(
  sessionId: string,
  eventName: string,
  payload: {
    name: string;
    event_type: string;
    conditions?: { signal_ref: string; operator: string; value: number }[];
    compound_logic?: string;
    signal_ref?: string | null;
    from_state?: number | null;
    to_state?: number | null;
    step?: number | null;
    description?: string;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/event/${sessionId}/${encodeURIComponent(eventName)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteEvent(
  sessionId: string,
  eventName: string
): Promise<{ report_state: ReportState }> {
  return request(`/event/${sessionId}/${encodeURIComponent(eventName)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Histogram
// ---------------------------------------------------------------------------

export async function addHistogram(
  sessionId: string,
  payload: {
    name: string;
    histogram_type: string;
    signal_ref: string;
    bins: number[];
    bins_unit?: string | null;
    values_unit?: string | null;
    description?: string;
    max_duration?: number | null;
    event_ref?: string | null;
    weight_signal_ref?: string | null;
    weight_const?: number | null;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/add-histogram/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function addHistogram2D(
  sessionId: string,
  payload: {
    name: string;
    x_signal_ref: string;
    y_signal_ref: string;
    x_bins: number[];
    y_bins: number[];
    x_bins_unit?: string | null;
    y_bins_unit?: string | null;
    event_ref?: string | null;
    description?: string;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/add-histogram-2d/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function addStatistics(
  sessionId: string,
  payload: {
    name: string;
    signal_refs: string[];
    stat_labels: string[];
    event_ref?: string | null;
    description?: string;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/add-statistics/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteAggregation(
  sessionId: string,
  name: string
): Promise<{ report_state: ReportState }> {
  return request(`/aggregation/${sessionId}/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function updateAggregation(
  sessionId: string,
  originalName: string,
  payload: {
    name: string;
    histogram_type: string;
    signal_ref: string;
    bins: number[];
    bins_unit?: string | null;
    values_unit?: string | null;
    description?: string;
    max_duration?: number | null;
    event_ref?: string | null;
    weight_signal_ref?: string | null;
    weight_const?: number | null;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/aggregation/${sessionId}/${encodeURIComponent(originalName)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function updateHistogram2D(
  sessionId: string,
  originalName: string,
  payload: {
    name: string;
    x_signal_ref: string;
    y_signal_ref: string;
    x_bins: number[];
    y_bins: number[];
    x_bins_unit?: string | null;
    y_bins_unit?: string | null;
    x_signal_name?: string | null;
    y_signal_name?: string | null;
    values_unit?: string | null;
    event_ref?: string | null;
    description?: string;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/aggregation-2d/${sessionId}/${encodeURIComponent(originalName)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function updateStatistics(
  sessionId: string,
  originalName: string,
  payload: {
    name: string;
    signal_refs: string[];
    stat_labels: string[];
    event_ref?: string | null;
    signal_names?: string[] | null;
    description?: string;
  }
): Promise<{ report_state: ReportState }> {
  return request(`/aggregation-stats/${sessionId}/${encodeURIComponent(originalName)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function goBack(
  sessionId: string
): Promise<{ wizard_step: WizardStep; report_state: ReportState }> {
  return request(`/go-back/${sessionId}`, { method: "POST" });
}

export async function goToStep(
  sessionId: string,
  step: WizardStep
): Promise<{ wizard_step: WizardStep; report_state: ReportState }> {
  return request(`/goto-step/${sessionId}/${step}`, { method: "POST" });
}

export async function setMetadata(
  sessionId: string | null,
  data: { name: string; description: string; creator: string }
): Promise<{ session_id?: string; report_state: ReportState }> {
  if (sessionId) {
    return request(`/set-metadata/${sessionId}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }
  return request("/set-metadata", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listSavedReports(): Promise<{ reports: SavedReportSummary[] }> {
  return request("/reports");
}

export async function saveReport(
  sessionId: string
): Promise<{ status: string; id: string; report_name: string }> {
  return request(`/reports/save/${sessionId}`, { method: "POST" });
}

export async function loadReport(
  reportId: string
): Promise<{ session_id: string; report_state: ReportState }> {
  return request(`/reports/load/${reportId}`, { method: "POST" });
}

export async function deleteReport(
  reportId: string
): Promise<{ status: string }> {
  return request(`/reports/${reportId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Visualization APIs
// ---------------------------------------------------------------------------

function vizParams(catalog: string, schema: string, prefix: string): string {
  return `catalog=${encodeURIComponent(catalog)}&schema=${encodeURIComponent(schema)}&prefix=${encodeURIComponent(prefix)}`;
}

export async function fetchVisualizeHistograms(
  catalog: string, schema: string, prefix: string,
): Promise<{ histograms: HistogramMeta[] }> {
  return request(`/visualize/histograms?${vizParams(catalog, schema, prefix)}`);
}

export async function fetchHistogramData(
  catalog: string,
  schema: string,
  prefix: string,
  histogramNames: string[],
): Promise<{ histograms: Record<string, HistogramResult> }> {
  return request("/visualize/histogram-data", {
    method: "POST",
    body: JSON.stringify({
      catalog,
      schema_name: schema,
      prefix,
      histogram_names: histogramNames,
    }),
  });
}

export async function fetchVisualizeAggregations(
  catalog: string, schema: string, prefix: string,
): Promise<{ aggregations: AggregationMeta[] }> {
  return request(`/visualize/aggregations?${vizParams(catalog, schema, prefix)}`);
}

export async function fetchHistogram2DData(
  catalog: string,
  schema: string,
  prefix: string,
  histogramNames: string[],
): Promise<{ histograms: Record<string, Heatmap2DResult> }> {
  return request("/visualize/histogram2d-data", {
    method: "POST",
    body: JSON.stringify({
      catalog,
      schema_name: schema,
      prefix,
      histogram_names: histogramNames,
    }),
  });
}

export async function fetchStatisticsData(
  catalog: string,
  schema: string,
  prefix: string,
  statisticsNames: string[],
): Promise<{ statistics: Record<string, StatisticsResult> }> {
  return request("/visualize/statistics-data", {
    method: "POST",
    body: JSON.stringify({
      catalog,
      schema_name: schema,
      prefix,
      statistics_names: statisticsNames,
    }),
  });
}

// ---------------------------------------------------------------------------
// Time Series APIs
// ---------------------------------------------------------------------------

function enc(s: string) { return encodeURIComponent(s); }

export async function fetchTimeSeriesContainers(
  catalog: string, schema: string,
): Promise<{ containers: TimeSeriesContainer[] }> {
  return request(`/timeseries/containers?catalog=${enc(catalog)}&schema=${enc(schema)}`);
}

export async function fetchTimeSeriesSignals(
  catalog: string, schema: string, containerId: number,
): Promise<{ signals: TimeSeriesSignal[] }> {
  return request(
    `/timeseries/signals?catalog=${enc(catalog)}&schema=${enc(schema)}&container_id=${containerId}`,
  );
}

export async function fetchTimeSeriesData(
  catalog: string,
  schema: string,
  containerId: number,
  channelId: number,
  xMin?: number,
  xMax?: number,
  nPoints: number = 5000,
): Promise<{ data: TimeSeriesPoint[]; total_points: number }> {
  let url = `/timeseries/data?catalog=${enc(catalog)}&schema=${enc(schema)}&container_id=${containerId}&channel_id=${channelId}&n_points=${nPoints}`;
  if (xMin != null) url += `&x_min=${xMin}`;
  if (xMax != null) url += `&x_max=${xMax}`;
  return request(url);
}

// New load/resample API for large datasets (async with polling)
export async function loadTimeSeriesChannels(
  catalog: string,
  schema: string,
  containerId: number,
  channelIds: number[],
  onProgress?: (message: string, elapsedMs: number) => void,
): Promise<TimeSeriesLoadResponse> {
  const initial = await request<any>("/timeseries/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      catalog,
      schema_name: schema,
      container_id: containerId,
      channel_ids: channelIds,
    }),
  });

  // If already cached, result is immediate
  if (initial.status === "done") {
    return initial as TimeSeriesLoadResponse;
  }

  // Poll for completion
  const loadId = initial.load_id;
  while (true) {
    await new Promise((r) => setTimeout(r, 1000));
    const status = await request<any>(`/timeseries/load/status/${loadId}`);
    if (status.status === "loading") {
      onProgress?.(status.message || "Loading...", status.elapsed_ms || 0);
      continue;
    }
    if (status.status === "error") {
      throw new Error(status.error || "Load failed");
    }
    // Done
    return status as TimeSeriesLoadResponse;
  }
}

export async function resampleTimeSeries(
  cacheKeys: string[],
  xMinNs: number | null,
  xMaxNs: number | null,
  nPoints: number = 5000,
  normalize: boolean = false,
): Promise<TimeSeriesResampleResponse> {
  return request("/timeseries/resample", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cache_keys: cacheKeys,
      x_min_ns: xMinNs,
      x_max_ns: xMaxNs,
      n_points: nPoints,
      normalize,
    }),
  });
}
