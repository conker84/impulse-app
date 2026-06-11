"""Shared fixtures for the impulse-app backend test suite."""

from __future__ import annotations

import pytest

from server.models import (
    DataSourceConfig,
    EventDefinition,
    Histogram1DDefinition,
    Histogram2DDefinition,
    HistogramType,
    ReportState,
    SignalDefinition,
    StatisticsDefinition,
    ThresholdCondition,
    VehicleConfig,
)
from server.schema_profile import SchemaProfile


@pytest.fixture(autouse=True)
def _reset_profile_cache():
    """Ensure the module-level profile cache never leaks between tests."""
    import server.schema_profile as sp

    sp.reset_profile_cache()
    yield
    sp.reset_profile_cache()


@pytest.fixture
def default_profile() -> SchemaProfile:
    return SchemaProfile()


@pytest.fixture
def physical_signal() -> SignalDefinition:
    return SignalDefinition(
        var_name="engine_speed",
        signal_type="physical",
        alias="nmot",
        channel_name="nmot",
    )


@pytest.fixture
def virtual_signal() -> SignalDefinition:
    return SignalDefinition(
        var_name="speed_kmh",
        signal_type="virtual",
        expression='signals["speed_ms"] * 3.6',
    )


@pytest.fixture
def threshold_event() -> EventDefinition:
    return EventDefinition(
        name="high_rpm",
        event_type="interval",
        conditions=[ThresholdCondition(signal_ref="engine_speed", operator=">", value=4000)],
    )


@pytest.fixture
def duration_histogram() -> Histogram1DDefinition:
    return Histogram1DDefinition(
        name="rpm_duration",
        histogram_type=HistogramType.DURATION,
        signal_ref="engine_speed",
        bins=[0, 1000, 2000, 3000, 7000],
        bins_unit="rpm",
    )


@pytest.fixture
def report_state(physical_signal, duration_histogram) -> ReportState:
    return ReportState(
        name="my_report",
        description="A test report",
        signals=[physical_signal],
        aggregations=[duration_histogram],
        vehicles=[VehicleConfig(vehicle_id="vw_golf", start_ts="2024-01-01")],
        data_sources=DataSourceConfig(
            container_metrics="cat.sch.container_metrics",
            channel_metrics="cat.sch.channel_metrics",
            channels=["cat.sch.channels"],
            destination_catalog="cat",
            destination_schema="sch",
        ),
    )
