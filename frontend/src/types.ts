export interface AvailableChannel {
  channel_name: string;
  unit: string;
  sample_count: number;
  min_value: number | null;
  max_value: number | null;
  mean_value: number | null;
  sample_rate: number | null;
  container_count: number;
}

export interface SignalCandidate {
  alias: string;
  channel_name: string;
  unit: string;
  device_name: string;
  description: string;
}

export interface SignalDefinition {
  var_name: string;
  signal_type: "physical" | "virtual";
  alias: string | null;
  channel_name: string | null;
  expression: string | null;
  eval_type: "SampleSeries" | "Intervals" | "PointsInTime" | "PitSeries";
  description: string;
}

export interface Histogram1DDefinition {
  agg_kind: "histogram_1d";
  name: string;
  histogram_type: "duration" | "distance" | "duration_count" | "event_count";
  signal_ref: string;
  bins: number[];
  bins_unit: string | null;
  values_unit: string | null;
  description: string;
  max_duration: number | null;
  event_signal_ref: string | null;
  weight_signal_ref: string | null;
  weight_const: number | null;
}

export interface Histogram2DDefinition {
  agg_kind: "histogram_2d";
  name: string;
  x_signal_ref: string;
  y_signal_ref: string;
  x_bins: number[];
  y_bins: number[];
  x_bins_unit: string | null;
  y_bins_unit: string | null;
  x_signal_name: string | null;
  y_signal_name: string | null;
  values_unit: string | null;
  description: string;
}

export interface StatisticsDefinition {
  agg_kind: "statistics";
  name: string;
  signal_refs: string[];
  stat_labels: string[];
  event_signal_ref: string | null;
  signal_names: string[] | null;
  description: string;
}

export type AggregationDefinition =
  | Histogram1DDefinition
  | Histogram2DDefinition
  | StatisticsDefinition;

// Backward-compatible alias
export type HistogramDefinition = Histogram1DDefinition;

export interface VehicleCandidate {
  vehicle_id: string;
  datapoint_count: number;
}

export interface VehicleConfig {
  vehicle_id: string;
  col_name: string;
  col_type: string;
  start_ts: string;
  stop_ts: string | null;
}

export interface DataSourceConfig {
  container_metrics: string;
  channel_metrics: string;
  channels: string[];
  aliases: string | null;
  aliases_copy_table_name: string | null;
  device_aliases: string | null;
  device_aliases_copy_table_name: string | null;
  destination_catalog: string;
  destination_schema: string;
  table_prefix: string;
}

export interface ValidationLevel {
  name: string;
  passed: boolean;
  details: Record<string, unknown>;
}

export interface HistogramSummary {
  histogram_name: string;
  sessions: number;
  total_value: number;
  non_zero_bins: number;
  status: string;
}

export interface ValidationResults {
  levels: ValidationLevel[];
  histogram_summary: HistogramSummary[];
}

export type SourceDataMode = "none" | "upload" | "existing";

export type IngestStatus = "not_started" | "running" | "succeeded" | "failed";

export interface SourceDataConfig {
  mode: SourceDataMode;
  upload_catalog: string;
  upload_schema: string;
  upload_volume: string;
  upload_volume_path: string;
  uploaded_files: string[];
  silver_catalog: string;
  silver_schema: string;
  ingest_run_id: number | null;
  ingest_status: IngestStatus;
}

export type WizardStep =
  | "source_data"
  | "report_name"
  | "channels"
  | "aggregations"
  | "vehicles"
  | "ready";

export type DeploymentStatus =
  | "not_started"
  | "scaffolding"
  | "deploying"
  | "running"
  | "completed"
  | "failed";

export interface ReportState {
  name: string;
  description: string;
  creator: string;
  wizard_step: WizardStep;
  source_data: SourceDataConfig;
  available_channels: AvailableChannel[];
  signal_candidates: SignalCandidate[];
  signals: SignalDefinition[];
  aggregations: AggregationDefinition[];
  vehicle_candidates: VehicleCandidate[];
  vehicles: VehicleConfig[];
  data_sources: DataSourceConfig;
  use_all_purpose_cluster: boolean;
  all_purpose_cluster_id: string;
  deployment: DeploymentStatus;
  run_id: string | null;
  run_url: string | null;
  validation: ValidationResults | null;
}

export interface SavedReportSummary {
  id: string;
  report_name: string;
  description: string;
  creator: string;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// Visualization types (gold layer query results)
// ---------------------------------------------------------------------------

export interface HistogramMeta {
  visual_id: number;
  name: string;
  type: string;
  description: string;
  bins_unit: string;
  values_unit: string;
}

export interface HistogramBinData {
  bin_id: number;
  bin_name: string;
  lower_bound: number;
  upper_bound: number;
  hist_value: number;
  relative_pct: number;
}

export interface HistogramResult {
  type: string;
  bins_unit: string;
  values_unit: string;
  description: string;
  series: Record<string, HistogramBinData[]>;
}

export interface VehicleOption {
  id: string;
  name: string;
}

export interface VisualizeFilters {
  vehicle_ids: string[];
  start_ts: string | null;
  end_ts: string | null;
  min_mileage: number | null;
  max_mileage: number | null;
  group_by_vehicle: boolean;
}

export interface FilterRange {
  min_ts: string | null;
  max_ts: string | null;
  min_mileage: number | null;
  max_mileage: number | null;
}

// Aggregation metadata (unified across 1D, 2D, statistics)
export interface AggregationMeta {
  visual_id: number;
  name: string;
  agg_type: "histogram_1d" | "histogram_2d" | "statistics";
  type: string;            // histogram sub-type (duration, distance, etc.) or ""
  description: string;
  bins_unit: string;
  values_unit: string;
  x_bins_unit: string;
  y_bins_unit: string;
}

// 2D histogram heatmap data
export interface Heatmap2DCell {
  x_bin_id: number;
  y_bin_id: number;
  x_bin_name: string;
  y_bin_name: string;
  hist_value: number;
}

export interface Heatmap2DResult {
  x_labels: string[];
  y_labels: string[];
  z: number[][];           // z[y_idx][x_idx]
  x_bins_unit: string;
  y_bins_unit: string;
  values_unit: string;
  description: string;
}

// Statistics table data
export interface StatisticsRow {
  signal_name: string;
  aggregation_label: string;
  value: number;
  event_instance_id: string | null;
}

export interface StatisticsResult {
  rows: StatisticsRow[];
  signal_names: string[];
  stat_labels: string[];
  description: string;
}

// Time series types
export interface TimeSeriesContainer {
  container_id: number;
  filename: string;
  vehicle_key: string;
  start_dt: string | null;
  stop_dt: string | null;
  num_channels: number;
  duration_ms: number;
}

export interface TimeSeriesSignal {
  channel_id: number;
  channel_name: string;
  unit: string;
  sample_count: number;
  min_value: number | null;
  max_value: number | null;
  mean_value: number | null;
}

export interface TimeSeriesPoint {
  t: number; // seconds
  v: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  message: ChatMessage;
  report_state: ReportState;
  session_id: string;
}
