"""Pydantic data models for Impulse report state.

SignalDefinition   <- define-channels skill
Histogram1DDefinition <- create-histogram-1d skill
Histogram2DDefinition <- (future) create-histogram-2d skill
StatisticsDefinition  <- (future) create-statistics skill
VehicleConfig      <- configure-report skill (vehicles section)
DataSourceConfig   <- configure-report skill (data section)
ReportState        <- aggregation of all the above
ChatMessage        <- chat endpoint I/O
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Discriminator, Field, Tag


# ---------------------------------------------------------------------------
# Signal definitions (from define-channels skill)
# ---------------------------------------------------------------------------

class EvalType(str, Enum):
    SAMPLE_SERIES = "SampleSeries"
    INTERVALS = "Intervals"
    POINTS_IN_TIME = "PointsInTime"
    PIT_SERIES = "PitSeries"


class AvailableChannel(BaseModel):
    """A channel discovered from the silver layer after ingest."""
    channel_name: str
    unit: str = ""
    sample_count: int = 0
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    sample_rate: float | None = None
    container_count: int = 0


class SignalCandidate(BaseModel):
    alias: str
    channel_name: str = ""
    unit: str = ""
    device_name: str = ""
    description: str = ""


class SignalDefinition(BaseModel):
    var_name: str
    signal_type: Literal["physical", "virtual"] = "physical"
    alias: str | None = None
    channel_name: str | None = None
    expression: str | None = None
    eval_type: EvalType = EvalType.SAMPLE_SERIES
    description: str = ""


# ---------------------------------------------------------------------------
# Aggregation definitions (discriminated union)
# ---------------------------------------------------------------------------

class HistogramType(str, Enum):
    DURATION = "duration"
    DISTANCE = "distance"
    DURATION_COUNT = "duration_count"
    EVENT_COUNT = "event_count"


class Histogram1DDefinition(BaseModel):
    agg_kind: Literal["histogram_1d"] = "histogram_1d"
    name: str
    histogram_type: HistogramType = HistogramType.DURATION
    signal_ref: str
    bins: list[float] = Field(default_factory=list)
    bins_unit: str | None = None
    values_unit: str | None = None
    description: str = ""
    max_duration: float | None = None
    event_signal_ref: str | None = None
    weight_signal_ref: str | None = None
    weight_const: float | None = None


class Histogram2DDefinition(BaseModel):
    agg_kind: Literal["histogram_2d"] = "histogram_2d"
    name: str
    x_signal_ref: str
    y_signal_ref: str
    x_bins: list[float] = Field(default_factory=list)
    y_bins: list[float] = Field(default_factory=list)
    x_bins_unit: str | None = None
    y_bins_unit: str | None = None
    x_signal_name: str | None = None
    y_signal_name: str | None = None
    values_unit: str | None = None
    description: str = ""


class StatisticsDefinition(BaseModel):
    agg_kind: Literal["statistics"] = "statistics"
    name: str
    signal_refs: list[str] = Field(default_factory=list)
    stat_labels: list[str] = Field(default_factory=lambda: ["min", "max", "mean", "median", "std", "count"])
    event_signal_ref: str | None = None
    signal_names: list[str] | None = None
    description: str = ""


def _get_agg_kind(v: Any) -> str:
    if isinstance(v, dict):
        return v.get("agg_kind", "histogram_1d")
    return getattr(v, "agg_kind", "histogram_1d")


AggregationDefinition = Annotated[
    Union[
        Annotated[Histogram1DDefinition, Tag("histogram_1d")],
        Annotated[Histogram2DDefinition, Tag("histogram_2d")],
        Annotated[StatisticsDefinition, Tag("statistics")],
    ],
    Discriminator(_get_agg_kind),
]

# Backward-compatible alias
HistogramDefinition = Histogram1DDefinition


# ---------------------------------------------------------------------------
# Vehicle config (from configure-report skill — vehicles section)
# ---------------------------------------------------------------------------

class VehicleCandidate(BaseModel):
    vehicle_id: str
    datapoint_count: int = 0


class VehicleConfig(BaseModel):
    vehicle_id: str
    col_name: str = "test_object_name"
    col_type: str = "string"
    start_ts: str = ""
    stop_ts: str | None = None


# ---------------------------------------------------------------------------
# Data source config (from configure-report skill — data section)
# ---------------------------------------------------------------------------

class DataSourceConfig(BaseModel):
    container_metrics: str = ""
    channel_metrics: str = ""
    channels: list[str] = Field(default_factory=list)
    aliases: str | None = None
    aliases_copy_table_name: str | None = None
    device_aliases: str | None = None
    device_aliases_copy_table_name: str | None = None
    destination_catalog: str = ""
    destination_schema: str = ""
    table_prefix: str = ""


# ---------------------------------------------------------------------------
# Deployment / validation state
# ---------------------------------------------------------------------------

class SourceDataMode(str, Enum):
    NONE = "none"
    UPLOAD = "upload"
    EXISTING = "existing"


class IngestStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SourceDataConfig(BaseModel):
    mode: SourceDataMode = SourceDataMode.NONE
    upload_catalog: str = ""
    upload_schema: str = ""
    upload_volume: str = ""
    upload_volume_path: str = ""
    uploaded_files: list[str] = Field(default_factory=list)
    silver_catalog: str = ""
    silver_schema: str = ""
    ingest_run_id: int | None = None
    ingest_status: IngestStatus = IngestStatus.NOT_STARTED


class WizardStep(str, Enum):
    SOURCE_DATA = "source_data"
    REPORT_NAME = "report_name"
    CHANNELS = "channels"
    AGGREGATIONS = "aggregations"
    VEHICLES = "vehicles"
    READY = "ready"

WIZARD_ORDER = list(WizardStep)


class DeploymentStatus(str, Enum):
    NOT_STARTED = "not_started"
    SCAFFOLDING = "scaffolding"
    DEPLOYING = "deploying"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ValidationLevel(BaseModel):
    name: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationResults(BaseModel):
    levels: list[ValidationLevel] = Field(default_factory=list)
    histogram_summary: list[dict[str, Any]] = Field(default_factory=list)
    aggregation_summary: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Aggregate report state
# ---------------------------------------------------------------------------

class ReportState(BaseModel):
    name: str = ""
    description: str = ""
    creator: str = ""
    wizard_step: WizardStep = WizardStep.SOURCE_DATA
    source_data: SourceDataConfig = Field(default_factory=SourceDataConfig)
    available_channels: list[AvailableChannel] = Field(default_factory=list)
    signal_candidates: list[SignalCandidate] = Field(default_factory=list)
    signals: list[SignalDefinition] = Field(default_factory=list)
    aggregations: list[AggregationDefinition] = Field(default_factory=list)
    vehicle_candidates: list[VehicleCandidate] = Field(default_factory=list)
    vehicles: list[VehicleConfig] = Field(default_factory=list)
    data_sources: DataSourceConfig = Field(default_factory=DataSourceConfig)
    use_all_purpose_cluster: bool = False
    all_purpose_cluster_id: str = ""
    deployment: DeploymentStatus = DeploymentStatus.NOT_STARTED
    deploy_started_at: float | None = None
    user_email: str = ""
    run_id: str | None = None
    run_url: str | None = None
    validation: ValidationResults | None = None


# ---------------------------------------------------------------------------
# Chat models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"] = "user"
    content: str = ""


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    message: ChatMessage
    report_state: ReportState
    session_id: str
