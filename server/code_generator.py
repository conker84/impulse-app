from __future__ import annotations

import json
from typing import Any

from server.models import EventDefinition, Histogram1DDefinition, Histogram2DDefinition, HistogramType, ReportState, StatisticsDefinition
from server.schema_profile import get_profile


_HISTOGRAM_CLASS_MAP = {
    HistogramType.DURATION: "HistogramDuration",
    HistogramType.DISTANCE: "HistogramDistance",
}

_OP_MAP = {">": ">", "<": "<", ">=": ">=", "<=": "<=", "==": "==", "!=": "!="}
_LOGIC_MAP = {"AND": "&", "OR": "|"}

_SEP = "\n\n# COMMAND ----------\n\n"


def _generate_event_expr(event: EventDefinition) -> str:
    """Generate the Python expression string for a BasicEvent from an EventDefinition."""
    if event.event_type == "change_points":
        return f'signals["{event.signal_ref}"].change_points(from_state={event.from_state}, to_state={event.to_state})'

    if event.event_type == "periodic_distance":
        return (
            f'(signals["{event.signal_ref}"] % {event.step})'
            f".intervals_between_falling_edges()"
        )

    # Build threshold expression from conditions
    parts = []
    for c in event.conditions:
        op = _OP_MAP[c.operator]
        parts.append(f'(signals["{c.signal_ref}"] {op} {c.value})')

    logic = _LOGIC_MAP[event.compound_logic]
    if len(parts) == 1:
        base_expr = parts[0]
    else:
        base_expr = f" {logic} ".join(parts)

    if event.event_type == "interval":
        return base_expr
    elif event.event_type == "rising_edges":
        return f"({base_expr}).rising_edges()"
    elif event.event_type == "falling_edges":
        return f"({base_expr}).falling_edges()"
    return base_expr


def generate_report_notebook(state: ReportState) -> str:
    cells: list[str] = []

    cells.append("# Databricks notebook source")

    # ---- Setup ----
    cells.append("\n".join([
        "import sys, os, json",
        "from datetime import datetime",
        "",
        'base_path = os.path.dirname(os.path.abspath("__file__"))',
        "base_path = base_path[:base_path.find('src')]",
        'sys.path.append(f"{base_path}/src/")',
        "",
        'spark.conf.set("spark.sql.shuffle.partitions", "auto")',
        "",
        "from impulse_reporting.core.report import Report",
        "from impulse_reporting.core.page import Page",
        "from impulse_reporting.aggregations.histogram import HistogramDuration, HistogramDistance",
        "from impulse_reporting.aggregations.histogram2d import Histogram2DDuration",
        "from impulse_reporting.aggregations.stats_aggregator import StatsAggregator",
        "from impulse_reporting.aggregations.aggregation_types import AggregationType",
        "from impulse_reporting.events.basic_event import BasicEvent",
        "from impulse_reporting.events.container_event import ContainerEvent",
        "from impulse_reporting.events.event_types import EventType",
        "",
        "from databricks.sdk import WorkspaceClient",
        "",
        "from utils.report_utils import drop_all_report_tables",
    ]))

    # ---- Initialize Report ----
    cells.append("\n".join([
        'dbutils.widgets.text("config_path", "./config/dev_config.json")',
        'dbutils.widgets.dropdown("reset_report", "False", ["True", "False"])',
        "",
        'config_path = dbutils.widgets.get("config_path")',
        'reset_report = dbutils.widgets.get("reset_report").lower() == "true"',
        "",
        'my_report = Report(name="report", spark=spark, workspace_client=WorkspaceClient(), config_path=config_path)',
        "query = my_report.query",
        "",
        "catalog = my_report.config.unity_sink.catalog",
        "schema_ = my_report.config.unity_sink.schema",
        "table_prefix = my_report.config.unity_sink.table_prefix",
        'print(f"Report: {catalog}.{schema_}.{table_prefix}")',
        "",
        "if reset_report:",
        "    drop_all_report_tables(catalog, schema_, table_prefix)",
    ]))

    # ---- Signal Definitions ----
    sig_lines: list[str] = []
    physical = [s for s in state.signals if s.signal_type == "physical"]
    virtual = [s for s in state.signals if s.signal_type == "virtual"]

    profile = get_profile()
    for sig in physical:
        sig_dict = sig.model_dump()
        kwargs_str_parts: list[str] = []
        for kwarg_name, field_name in profile.channel_call_kwargs.items():
            value = sig_dict.get(field_name)
            if not value and kwarg_name == "channel_name":
                value = sig.channel_name or sig.alias or sig.var_name
            if not value and kwarg_name == "signal":
                value = sig.signal or sig.channel_name or sig.alias or sig.var_name
            if value:
                kwargs_str_parts.append(f'{kwarg_name}="{value}"')
        kwargs_str = ", ".join(kwargs_str_parts) if kwargs_str_parts else f'channel_name="{sig.channel_name or sig.var_name}"'
        sig_lines.append(f'{sig.var_name} = query.channel({kwargs_str})')

    if physical and virtual:
        sig_lines.append("")

    for sig in virtual:
        sig_lines.append(f"{sig.var_name} = {sig.expression}")

    sig_lines += ["", "signals = {"]
    for sig in state.signals:
        sig_lines.append(f'    "{sig.var_name}": {sig.var_name},')
    sig_lines += ["}"]
    cells.append("\n".join(sig_lines))

    # var_name → display name lookup for signal_names in Statistics.
    # Prefer the user-typed var_name so downstream visuals show friendly names.
    sig_lookup = {s.var_name: (s.var_name or s.alias or s.channel_name) for s in state.signals}

    # ---- Event definitions ----
    # Build a lookup of event definitions by name
    event_lookup: dict[str, EventDefinition] = {e.name: e for e in state.events}

    # Collect unique event refs used by aggregations
    used_event_refs: set[str] = set()
    for agg in state.aggregations:
        ref = getattr(agg, "event_ref", None)
        if ref and ref in event_lookup:
            used_event_refs.add(ref)

    event_lines: list[str] = []
    # Generate BasicEvent variables for referenced events
    for ref in sorted(used_event_refs):
        evt = event_lookup[ref]
        var = f"evt_{ref}"
        expr = _generate_event_expr(evt)
        event_lines.append(f'{var} = BasicEvent(name="{ref}", expr={expr})')
        event_lines.append(f"my_report.add_event({var})")
        event_lines.append("")

    # ---- Aggregations ----
    agg_lines: list[str] = [
        "page = Page(page_number=1)",
        "my_report.add_page(page)",
        "",
    ]

    for hist in (a for a in state.aggregations if isinstance(a, Histogram1DDefinition)):
        cls = _HISTOGRAM_CLASS_MAP[hist.histogram_type]
        params = [f'    name="{hist.name}"', f'    base_expr=signals["{hist.signal_ref}"]']
        if hist.histogram_type == HistogramType.DISTANCE:
            if not hist.weight_signal_ref:
                raise ValueError(
                    f"Distance histogram '{hist.name}' requires a weight signal "
                    "(e.g. odometer) — set weight_signal_ref."
                )
            params.append(f'    weights_expr=signals["{hist.weight_signal_ref}"]')
        params.append(f"    bins={hist.bins}")
        if hist.description:
            params.append(f'    desc="{hist.description}"')
        if hist.bins_unit:
            params.append(f'    bins_unit="{hist.bins_unit}"')
        if hist.values_unit:
            params.append(f'    values_unit="{hist.values_unit}"')
        if hist.event_ref and hist.event_ref in event_lookup:
            params.append(f'    event=evt_{hist.event_ref}')
        agg_lines.append(f"page.add_aggregation({cls}(")
        agg_lines.append(",\n".join(params) + ",")
        agg_lines.append("))")
        agg_lines.append("")

    for hist2d in (a for a in state.aggregations if isinstance(a, Histogram2DDefinition)):
        x_label = hist2d.x_signal_name or hist2d.x_signal_ref
        y_label = hist2d.y_signal_name or hist2d.y_signal_ref
        params = [
            f'    name="{hist2d.name}"', f'    x_expr=signals["{hist2d.x_signal_ref}"]',
            f'    y_expr=signals["{hist2d.y_signal_ref}"]', f"    x_bins={hist2d.x_bins}", f"    y_bins={hist2d.y_bins}",
            f'    x_channel_name="{x_label}"', f'    y_channel_name="{y_label}"',
        ]
        if hist2d.description:
            params.append(f'    desc="{hist2d.description}"')
        if hist2d.x_bins_unit:
            params.append(f'    x_bins_unit="{hist2d.x_bins_unit}"')
        if hist2d.y_bins_unit:
            params.append(f'    y_bins_unit="{hist2d.y_bins_unit}"')
        if hist2d.values_unit:
            params.append(f'    values_unit="{hist2d.values_unit}"')
        if hist2d.event_ref and hist2d.event_ref in event_lookup:
            params.append(f'    event=evt_{hist2d.event_ref}')
        agg_lines.append("page.add_aggregation(Histogram2DDuration(")
        agg_lines.append(",\n".join(params) + ",")
        agg_lines.append("))")
        agg_lines.append("")

    for stats in (a for a in state.aggregations if isinstance(a, StatisticsDefinition)):
        # Use referenced event or fall back to ContainerEvent
        if stats.event_ref and stats.event_ref in event_lookup:
            event_var = f"evt_{stats.event_ref}"
        else:
            event_var = f"{stats.name}_container_event"
            agg_lines.append(f'{event_var} = ContainerEvent(name="{event_var}")')
            agg_lines.append(f"my_report.add_event({event_var})")
            agg_lines.append("")
        selections_items = ", ".join(f'signals["{ref}"]' for ref in stats.signal_refs)
        signal_names = [sig_lookup.get(ref, ref) for ref in stats.signal_refs]
        params = [f'    name="{stats.name}"', f"    input_expressions=[{selections_items}]", f"    statistics={repr(stats.stat_labels)}", f"    event={event_var}", f"    channel_names={repr(signal_names)}"]
        if stats.description:
            params.append(f'    desc="{stats.description}"')
        agg_lines.append("page.add_aggregation(StatsAggregator(")
        agg_lines.append(",\n".join(params) + ",")
        agg_lines.append("))")
        agg_lines.append("")

    cells.append("\n".join(event_lines + agg_lines))

    # ---- Execute ----
    cells.append("\n".join([
        'print(f"[{datetime.now().isoformat()}] Running determine_report()...")',
        "my_report.determine_report()",
        'print(f"[{datetime.now().isoformat()}] determine_report() complete.")',
        "",
        'print(f"[{datetime.now().isoformat()}] Running persist_results()...")',
        "my_report.persist_results()",
        'print(f"[{datetime.now().isoformat()}] Done. Report results persisted.")',
    ]))

    # ---- Post-processing ----
    cells.append("\n".join([
        "table_names = []",
        "for agg_type in AggregationType:",
        "    table_names.append(agg_type.get_fact_table_name())",
        "    table_names.append(agg_type.get_dimension_table_name())",
        "for evt_type in EventType:",
        "    fact = evt_type.get_fact_table_name()",
        "    dim = evt_type.get_dimension_table_name()",
        "    if fact not in table_names:",
        "        table_names.append(fact)",
        "    if dim not in table_names:",
        "        table_names.append(dim)",
        'table_names.append("report_summary")',
        "",
        "for table_name in table_names:",
        '    table_path = f"{catalog}.{schema_}.{table_prefix}_{table_name}"',
        "    if spark.catalog.tableExists(table_path):",
        '        print(f"Optimizing: {table_path}")',
        '        spark.sql(f"OPTIMIZE {table_path}")',
    ]))

    return _SEP.join(cells)


# Solvers that consume a per-table column_name_mapping (canonical timestamp/value
# key-value shape). DeltaSolver reads RLE tstart/tend data and does not.
_SOLVER_CONFIG_SOLVERS = {"KeyValueStoreSolver"}


def _build_solver_config(profile) -> dict[str, Any]:
    """Build the query_engine.solver_config column_name_mapping from the profile.

    The profile stores the SOURCE column name for each canonical concept, so the
    framework's `source_column -> canonical_name` mappings are the inverse. Only
    non-identity renames are emitted (a column already named canonically needs no
    mapping). Emitted only for solvers that consume it (see
    ``_SOLVER_CONFIG_SOLVERS``); other solvers get no solver_config key.
    """
    if profile.framework_solver not in _SOLVER_CONFIG_SOLVERS:
        return {}

    def mapping(pairs: list[tuple[str | None, str]]) -> dict[str, str]:
        return {src: canon for src, canon in pairs if src and src != canon}

    container = mapping([
        (profile.container_id_col, "container_id"),
    ])
    channel_metrics = mapping([
        (profile.channel_container_id_col, "container_id"),
        (profile.channel_id_col, "channel_id"),
    ])
    # The framework reads the RAW channels table, so this mapping must use
    # physical column names — never the viewer's timeseries_* projections, which
    # may be SQL expressions (e.g. "CAST(time * 1e9 AS BIGINT)").
    channels = mapping([
        (profile.timeseries_container_match_col or profile.channel_container_id_col, "container_id"),
        (profile.channel_id_col, "channel_id"),
        (profile.framework_channel_time_col, "timestamp"),
        (profile.framework_channel_value_col, "value"),
    ])
    # Physical key/value tag tables, when present, are keyed by the same
    # container/channel id columns and need the same canonical renames.
    container_tags = mapping([
        (profile.container_tags_id_col, "container_id"),
    ]) if profile.container_tags_table else {}
    channel_tags = mapping([
        (profile.channel_tags_container_id_col, "container_id"),
        (profile.channel_tags_channel_id_col, "channel_id"),
    ]) if profile.channel_tags_table else {}

    solver_config: dict[str, Any] = {}
    if container:
        solver_config["container_metrics"] = {"column_name_mapping": container}
    if container_tags:
        solver_config["container_tags"] = {"column_name_mapping": container_tags}
    if channel_metrics:
        solver_config["channel_metrics"] = {"column_name_mapping": channel_metrics}
    if channel_tags:
        solver_config["channel_tags"] = {"column_name_mapping": channel_tags}
    if channels:
        solver_config["channels"] = {"column_name_mapping": channels}
    return solver_config


def generate_config_json(state: ReportState) -> dict[str, Any]:
    ds = state.data_sources
    profile = get_profile()

    units_under_test = []
    for v in state.vehicles:
        entry: dict[str, Any] = {
            "uut_name": {"col_name": v.col_name, "value": v.vehicle_id},
            "start_ts": {"col_name": "start_dt", "value": v.start_ts},
        }
        if v.stop_ts:
            entry["end_ts"] = {"col_name": "stop_dt", "value": v.stop_ts}
        units_under_test.append(entry)

    source: dict[str, Any] = {
        "container_metrics_table": ds.container_metrics,
        "channel_metrics_table": ds.channel_metrics,
        "channels_uri": ds.channels[0] if ds.channels else "",
    }
    if ds.container_tags:
        source["container_tags_table"] = ds.container_tags
    if ds.channel_tags:
        source["channel_tags_table"] = ds.channel_tags

    query_engine: dict[str, Any] = {
        "solver": profile.framework_solver,
        "data_type": profile.framework_data_type,
    }
    solver_config = _build_solver_config(profile)
    if solver_config:
        query_engine["solver_config"] = solver_config

    return {
        "source": source,
        "unity_sink": {
            "catalog": ds.destination_catalog,
            "schema": ds.destination_schema,
            "table_prefix": ds.table_prefix or f"{state.name}_report",
        },
        "units_under_test": units_under_test,
        "query_engine": query_engine,
        "incremental": {"enabled": False},
        "measurement_dimensions": list(profile.framework_measurement_dimensions),
    }


def generate_all_files(state: ReportState) -> dict[str, str]:
    return {
        "src/report.py": generate_report_notebook(state),
        "src/config/dev_config.json": json.dumps(generate_config_json(state), indent=2),
    }
