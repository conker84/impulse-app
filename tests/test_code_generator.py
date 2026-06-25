"""Tests for report code generation in server/code_generator.py."""

from __future__ import annotations

import json

import pytest

from server.code_generator import (
    _generate_event_expr,
    generate_all_files,
    generate_config_json,
    generate_report_notebook,
)
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


class TestGenerateEventExpr:
    def test_change_points(self):
        evt = EventDefinition(
            name="shift", event_type="change_points",
            signal_ref="gear", from_state=1, to_state=2,
        )
        expr = _generate_event_expr(evt)
        assert expr == 'signals["gear"].change_points(from_state=1.0, to_state=2.0)'

    def test_periodic_distance(self):
        evt = EventDefinition(
            name="km", event_type="periodic_distance", signal_ref="odo", step=1000,
        )
        expr = _generate_event_expr(evt)
        assert 'signals["odo"] % 1000.0' in expr
        assert "intervals_between_falling_edges()" in expr

    def test_single_condition_interval(self):
        evt = EventDefinition(
            name="e", event_type="interval",
            conditions=[ThresholdCondition(signal_ref="rpm", operator=">", value=4000)],
        )
        assert _generate_event_expr(evt) == '(signals["rpm"] > 4000.0)'

    def test_multi_condition_and_logic(self):
        evt = EventDefinition(
            name="e", event_type="interval", compound_logic="AND",
            conditions=[
                ThresholdCondition(signal_ref="rpm", operator=">", value=4000),
                ThresholdCondition(signal_ref="temp", operator="<", value=90),
            ],
        )
        expr = _generate_event_expr(evt)
        assert " & " in expr
        assert '(signals["rpm"] > 4000.0)' in expr
        assert '(signals["temp"] < 90.0)' in expr

    def test_multi_condition_or_logic(self):
        evt = EventDefinition(
            name="e", event_type="interval", compound_logic="OR",
            conditions=[
                ThresholdCondition(signal_ref="a", operator=">", value=1),
                ThresholdCondition(signal_ref="b", operator="<", value=2),
            ],
        )
        assert " | " in _generate_event_expr(evt)

    def test_rising_edges_wraps_expr(self):
        evt = EventDefinition(
            name="e", event_type="rising_edges",
            conditions=[ThresholdCondition(signal_ref="rpm", operator=">", value=4000)],
        )
        assert _generate_event_expr(evt).endswith(".rising_edges()")

    def test_falling_edges_wraps_expr(self):
        evt = EventDefinition(
            name="e", event_type="falling_edges",
            conditions=[ThresholdCondition(signal_ref="rpm", operator=">", value=4000)],
        )
        assert _generate_event_expr(evt).endswith(".falling_edges()")


class TestGenerateReportNotebook:
    def test_starts_with_databricks_header(self, report_state):
        nb = generate_report_notebook(report_state)
        assert nb.startswith("# Databricks notebook source")

    def test_includes_physical_signal_channel_call(self, report_state):
        nb = generate_report_notebook(report_state)
        assert "engine_speed = query.channel(" in nb
        assert '"engine_speed": engine_speed' in nb

    def test_includes_virtual_signal_expression(self, virtual_signal):
        state = ReportState(name="r", signals=[virtual_signal])
        nb = generate_report_notebook(state)
        assert 'speed_kmh = signals["speed_ms"] * 3.6' in nb

    def test_duration_histogram_uses_duration_class(self, report_state):
        nb = generate_report_notebook(report_state)
        assert "HistogramDuration(" in nb
        assert 'name="rpm_duration"' in nb
        assert 'base_expr=signals["engine_speed"]' in nb

    def test_distance_histogram_emits_weights(self):
        state = ReportState(
            name="r",
            signals=[SignalDefinition(var_name="odo", channel_name="odo")],
            aggregations=[
                Histogram1DDefinition(
                    name="dist_h",
                    histogram_type=HistogramType.DISTANCE,
                    signal_ref="odo",
                    bins=[0, 100],
                    weight_signal_ref="odo",
                )
            ],
        )
        nb = generate_report_notebook(state)
        assert "HistogramDistance(" in nb
        assert 'weights_expr=signals["odo"]' in nb

    def test_distance_histogram_without_weight_raises(self):
        """The model accepts a weightless distance histogram (when weight is
        omitted); code generation is where that missing weight is caught."""
        state = ReportState(
            name="r",
            signals=[SignalDefinition(var_name="odo", channel_name="odo")],
            aggregations=[
                Histogram1DDefinition(
                    name="dist_h",
                    histogram_type=HistogramType.DISTANCE,
                    signal_ref="odo",
                    bins=[0, 100],
                )
            ],
        )
        with pytest.raises(ValueError, match="requires a weight signal"):
            generate_report_notebook(state)

    def test_histogram_2d_emits_axes(self):
        state = ReportState(
            name="r",
            signals=[
                SignalDefinition(var_name="rpm", channel_name="rpm"),
                SignalDefinition(var_name="trq", channel_name="trq"),
            ],
            aggregations=[
                Histogram2DDefinition(
                    name="map",
                    x_signal_ref="rpm",
                    y_signal_ref="trq",
                    x_bins=[0, 1],
                    y_bins=[0, 1],
                )
            ],
        )
        nb = generate_report_notebook(state)
        assert "Histogram2DDuration(" in nb
        assert 'x_expr=signals["rpm"]' in nb
        assert 'y_expr=signals["trq"]' in nb

    def test_statistics_without_event_creates_container_event(self):
        state = ReportState(
            name="r",
            signals=[SignalDefinition(var_name="rpm", channel_name="rpm")],
            aggregations=[
                StatisticsDefinition(name="stats", signal_refs=["rpm"])
            ],
        )
        nb = generate_report_notebook(state)
        assert "StatsAggregator(" in nb
        assert "ContainerEvent(name=" in nb

    def test_aggregation_referencing_event_emits_basic_event(self):
        state = ReportState(
            name="r",
            signals=[SignalDefinition(var_name="rpm", channel_name="rpm")],
            events=[
                EventDefinition(
                    name="hot",
                    event_type="interval",
                    conditions=[ThresholdCondition(signal_ref="rpm", operator=">", value=4000)],
                )
            ],
            aggregations=[
                Histogram1DDefinition(
                    name="h", signal_ref="rpm", bins=[0, 1], event_ref="hot"
                )
            ],
        )
        nb = generate_report_notebook(state)
        assert 'BasicEvent(name="hot"' in nb
        assert "evt_hot" in nb
        assert "my_report.add_event(evt_hot)" in nb


class TestGenerateConfigJson:
    def test_basic_structure(self, report_state):
        cfg = generate_config_json(report_state)
        assert cfg["source"]["container_metrics_table"] == "cat.sch.container_metrics"
        assert cfg["unity_sink"]["catalog"] == "cat"
        assert cfg["unity_sink"]["schema"] == "sch"

    def test_table_prefix_defaults_to_report_name(self):
        state = ReportState(name="foo", data_sources=DataSourceConfig())
        cfg = generate_config_json(state)
        assert cfg["unity_sink"]["table_prefix"] == "foo_report"

    def test_explicit_table_prefix_wins(self):
        state = ReportState(
            name="foo",
            data_sources=DataSourceConfig(table_prefix="custom"),
        )
        cfg = generate_config_json(state)
        assert cfg["unity_sink"]["table_prefix"] == "custom"

    def test_units_under_test_includes_end_ts_only_when_set(self):
        state = ReportState(
            name="r",
            vehicles=[
                VehicleConfig(vehicle_id="v1", start_ts="2024-01-01"),
                VehicleConfig(vehicle_id="v2", start_ts="2024-01-01", stop_ts="2024-02-01"),
            ],
        )
        cfg = generate_config_json(state)
        uuts = cfg["units_under_test"]
        assert "end_ts" not in uuts[0]
        assert uuts[1]["end_ts"]["value"] == "2024-02-01"

    def test_query_engine_from_profile_defaults(self, report_state, monkeypatch):
        import server.code_generator as cg
        from server.schema_profile import SchemaProfile

        monkeypatch.setattr(cg, "get_profile", lambda: SchemaProfile())
        cfg = generate_config_json(report_state)
        assert cfg["query_engine"]["solver"] == "DeltaSolver"
        assert cfg["query_engine"]["data_type"] == "RLE"

    def test_default_profile_emits_no_solver_config(self, report_state, monkeypatch):
        """A profile whose source columns are already canonical needs no mapping."""
        import server.code_generator as cg
        from server.schema_profile import SchemaProfile

        monkeypatch.setattr(cg, "get_profile", lambda: SchemaProfile())
        cfg = generate_config_json(report_state)
        assert "solver_config" not in cfg["query_engine"]

    def test_solver_config_reflects_profile_column_mappings(self, report_state, monkeypatch):
        """Renamed source columns in the profile become solver_config
        column_name_mappings (source -> canonical) in the generated config."""
        import server.code_generator as cg
        from server.schema_profile import SchemaProfile

        profile = SchemaProfile(
            container_id_col="recording_session_id",
            channel_container_id_col="recording_session_id",
            channel_id_col="signal_network",
            timeseries_table="signal_new_with_fields",
            # Viewer projections are SQL expressions and must NOT leak into the
            # framework column_name_mapping below.
            timeseries_time_col="CAST(time * 1e9 AS BIGINT)",
            timeseries_value_col="TRY_CAST(value_double AS DOUBLE)",
            timeseries_container_match_col="recording_session_id",
            timeseries_channel_match_expr="signal_network",
            framework_channel_time_col="time",
            framework_channel_value_col="value_double",
            container_tags_table="container_tags",
            container_tags_id_col="recording_session_id",
            channel_tags_table="channel_tags",
            channel_tags_container_id_col="recording_session_id",
            channel_tags_channel_id_col="signal_network",
            framework_solver="KeyValueStoreSolver",
            framework_data_type="RAW",
        )
        monkeypatch.setattr(cg, "get_profile", lambda: profile)
        cfg = generate_config_json(report_state)
        solver_config = cfg["query_engine"]["solver_config"]
        assert solver_config["container_metrics"]["column_name_mapping"] == {
            "recording_session_id": "container_id",
        }
        assert solver_config["channel_metrics"]["column_name_mapping"] == {
            "signal_network": "channel_id",
            "recording_session_id": "container_id",
        }
        assert solver_config["channels"]["column_name_mapping"] == {
            "recording_session_id": "container_id",
            "signal_network": "channel_id",
            "time": "timestamp",
            "value_double": "value",
        }
        assert solver_config["container_tags"]["column_name_mapping"] == {
            "recording_session_id": "container_id",
        }
        assert solver_config["channel_tags"]["column_name_mapping"] == {
            "recording_session_id": "container_id",
            "signal_network": "channel_id",
        }

    def test_tag_solver_config_omitted_when_tag_tables_absent(self, report_state, monkeypatch):
        """No tag mapping when the profile has no physical tag tables."""
        import server.code_generator as cg
        from server.schema_profile import SchemaProfile

        profile = SchemaProfile(
            channel_id_col="signal_network",
            container_tags_table=None,
            channel_tags_table=None,
            vehicle_source="constant",
            vehicle_constant="demo",
            framework_solver="KeyValueStoreSolver",
        )
        monkeypatch.setattr(cg, "get_profile", lambda: profile)
        solver_config = generate_config_json(report_state)["query_engine"]["solver_config"]
        assert "container_tags" not in solver_config
        assert "channel_tags" not in solver_config

    def test_optional_tag_tables_included_when_set(self):
        state = ReportState(
            name="r",
            data_sources=DataSourceConfig(
                container_tags="cat.sch.ctags",
                channel_tags="cat.sch.chtags",
            ),
        )
        cfg = generate_config_json(state)
        assert cfg["source"]["container_tags_table"] == "cat.sch.ctags"
        assert cfg["source"]["channel_tags_table"] == "cat.sch.chtags"


class TestGenerateAllFiles:
    def test_produces_expected_paths(self, report_state):
        files = generate_all_files(report_state)
        assert set(files) == {"src/report.py", "src/config/dev_config.json"}

    def test_config_json_is_valid_json(self, report_state):
        files = generate_all_files(report_state)
        parsed = json.loads(files["src/config/dev_config.json"])
        assert parsed["unity_sink"]["catalog"] == "cat"


class TestOptionalFieldBranches:
    """Cover the conditional emission of optional aggregation/signal fields."""

    def test_physical_signal_channel_name_falls_back_to_alias(self):
        # No channel_name set -> generator falls back to alias, then var_name.
        state = ReportState(
            name="r",
            signals=[SignalDefinition(var_name="rpm", alias="nmot")],
        )
        nb = generate_report_notebook(state)
        assert 'channel_name="nmot"' in nb

    def test_physical_signal_channel_name_falls_back_to_var_name(self):
        state = ReportState(name="r", signals=[SignalDefinition(var_name="rpm")])
        nb = generate_report_notebook(state)
        assert 'channel_name="rpm"' in nb

    def test_custom_signal_kwarg_resolved_from_profile(self, monkeypatch):
        """A profile whose channel_call_kwargs maps a `signal` kwarg must have it
        filled from the signal's fallbacks when the mapped field is empty."""
        import server.code_generator as cg
        from server.schema_profile import SchemaProfile

        profile = SchemaProfile(channel_call_kwargs={"signal": "signal"})
        monkeypatch.setattr(cg, "get_profile", lambda: profile)
        state = ReportState(name="r", signals=[SignalDefinition(var_name="rpm", channel_name="nmot")])
        nb = generate_report_notebook(state)
        assert 'signal="nmot"' in nb

    def test_both_physical_and_virtual_signals_emit_separator(self):
        state = ReportState(
            name="r",
            signals=[
                SignalDefinition(var_name="rpm", channel_name="nmot"),
                SignalDefinition(var_name="rpm2", signal_type="virtual", expression="rpm * 2"),
            ],
        )
        nb = generate_report_notebook(state)
        assert "rpm = query.channel(" in nb
        assert "rpm2 = rpm * 2" in nb

    def test_histogram_1d_emits_description_and_values_unit(self):
        state = ReportState(
            name="r",
            signals=[SignalDefinition(var_name="rpm", channel_name="nmot")],
            aggregations=[
                Histogram1DDefinition(
                    name="h",
                    signal_ref="rpm",
                    bins=[0, 1],
                    description="time in band",
                    values_unit="s",
                )
            ],
        )
        nb = generate_report_notebook(state)
        assert 'desc="time in band"' in nb
        assert 'values_unit="s"' in nb

    def test_histogram_2d_emits_all_optional_fields(self):
        state = ReportState(
            name="r",
            signals=[
                SignalDefinition(var_name="rpm", channel_name="nmot"),
                SignalDefinition(var_name="trq", channel_name="trq"),
            ],
            events=[
                EventDefinition(
                    name="hot",
                    event_type="interval",
                    conditions=[ThresholdCondition(signal_ref="rpm", operator=">", value=1)],
                )
            ],
            aggregations=[
                Histogram2DDefinition(
                    name="map",
                    x_signal_ref="rpm",
                    y_signal_ref="trq",
                    x_bins=[0, 1],
                    y_bins=[0, 1],
                    description="operating map",
                    x_bins_unit="rpm",
                    y_bins_unit="Nm",
                    values_unit="s",
                    event_ref="hot",
                )
            ],
        )
        nb = generate_report_notebook(state)
        assert 'desc="operating map"' in nb
        assert 'x_bins_unit="rpm"' in nb
        assert 'y_bins_unit="Nm"' in nb
        assert 'values_unit="s"' in nb
        assert "event=evt_hot" in nb

    def test_statistics_with_event_ref_reuses_basic_event(self):
        state = ReportState(
            name="r",
            signals=[SignalDefinition(var_name="rpm", channel_name="nmot")],
            events=[
                EventDefinition(
                    name="hot",
                    event_type="interval",
                    conditions=[ThresholdCondition(signal_ref="rpm", operator=">", value=1)],
                )
            ],
            aggregations=[
                StatisticsDefinition(
                    name="stats",
                    signal_refs=["rpm"],
                    event_ref="hot",
                    description="quick stats",
                )
            ],
        )
        nb = generate_report_notebook(state)
        # Reuses the BasicEvent rather than creating a ContainerEvent.
        assert "event=evt_hot" in nb
        assert "stats_container_event" not in nb
        assert 'desc="quick stats"' in nb
