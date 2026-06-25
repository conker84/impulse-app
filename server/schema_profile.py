from __future__ import annotations

import os
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class SchemaProfile(BaseModel):
    name: str = "default"

    container_table: str = "container_metrics"
    container_id_col: str = "container_id"
    container_start_col: str = "start_dt"
    container_stop_col: str = "stop_dt"

    channel_table: str = "channel_metrics"
    channel_container_id_col: str = "container_id"
    channel_id_col: str = "channel_id"
    channel_name_col: str = "channel_name"
    channel_secondary_id_col: str | None = None
    channel_unit_col: str | None = None
    channel_min_col: str = "min"
    channel_max_col: str = "max"
    channel_mean_col: str = "mean"
    channel_sample_count_col: str = "sample_count"
    channel_sample_rate_expr: str | None = "sample_rate"

    container_tags_table: str | None = "container_tags"
    # Column in container_tags_table that joins back to a container. Aliased to
    # the canonical `container_id` when the physical table uses a different name
    # (e.g. recording_session_id). Only used when container_tags_table is set.
    container_tags_id_col: str = "container_id"

    channel_tags_table: str | None = "channel_tags"
    # Columns in channel_tags_table that join back to a (container, channel).
    # Aliased to canonical container_id / channel_id. Only used when
    # channel_tags_table is set.
    channel_tags_container_id_col: str = "container_id"
    channel_tags_channel_id_col: str = "channel_id"

    vehicle_source: Literal["tag", "column", "constant"] = "tag"
    vehicle_column: str | None = None
    vehicle_constant: str | None = None

    aliases_table: str | None = None
    aliases_alias_col: str = "channel_alias_name"
    aliases_unit_col: str | None = "unit"
    aliases_description_col: str | None = "description"

    timeseries_table: str = "channels"
    timeseries_time_col: str = "tstart"
    timeseries_end_time_col: str | None = "tend"
    timeseries_value_col: str = "value"
    timeseries_container_match_col: str | None = None
    timeseries_channel_match_expr: str | None = None

    duration_scale_to_seconds: float = 1e9

    framework_solver: str = "DeltaSolver"
    framework_data_type: str = "RLE"
    framework_measurement_dimensions: list[str] = Field(
        default_factory=lambda: ["container_id", "vehicle_key", "start_ts", "stop_ts"]
    )
    # RAW physical sample columns the framework's solver_config maps to the
    # canonical `timestamp` / `value`. Distinct from the viewer's
    # timeseries_time_col / timeseries_value_col, which may be SQL expressions
    # (e.g. unit conversions) and so cannot serve as column_name_mapping keys.
    # Defaults equal the canonical names, so no mapping is emitted unless set.
    framework_channel_time_col: str = "timestamp"
    framework_channel_value_col: str = "value"

    channel_call_kwargs: dict[str, str] = Field(
        default_factory=lambda: {"channel_name": "channel_name"}
    )

    @model_validator(mode="after")
    def _check_vehicle_source(self) -> "SchemaProfile":
        if self.vehicle_source == "tag" and self.container_tags_table is None:
            raise ValueError(
                "vehicle_source='tag' requires container_tags_table to be set"
            )
        if self.vehicle_source == "column" and not self.vehicle_column:
            raise ValueError("vehicle_source='column' requires vehicle_column to be set")
        if self.vehicle_source == "constant" and not self.vehicle_constant:
            raise ValueError("vehicle_source='constant' requires vehicle_constant to be set")
        return self


_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "profiles.yaml")
_cached_profile: SchemaProfile | None = None


def get_profile() -> SchemaProfile:
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile

    if os.path.isfile(_PROFILE_PATH):
        with open(_PROFILE_PATH) as f:
            data = yaml.safe_load(f) or {}
        # Customer profiles default to sample-based (no RLE end-time column);
        # they opt in to step rendering by setting timeseries_end_time_col explicitly.
        data.setdefault("timeseries_end_time_col", None)
        _cached_profile = SchemaProfile.model_validate(data)
    else:
        _cached_profile = SchemaProfile()
    return _cached_profile


def reset_profile_cache() -> None:
    global _cached_profile
    _cached_profile = None
