from __future__ import annotations

import json
from typing import Any

from server.models import Histogram1DDefinition, Histogram2DDefinition, HistogramType, ReportState, StatisticsDefinition


_HISTOGRAM_AGG_TYPE_MAP = {
    HistogramType.DURATION: "duration",
    HistogramType.DISTANCE: "distance",
}

_SEP = "\n\n# COMMAND ----------\n\n"


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
        "from mda_reporting.core.report import Report",
        "from mda_reporting.core.page import Page",
        "from mda_reporting.aggregations.histogram import Histogram",
        "from mda_reporting.aggregations.histogram2d import Histogram2D",
        "from mda_reporting.aggregations.statistics import Statistics",
        "from mda_reporting.aggregations.aggregation_types import AggregationType",
        "from mda_reporting.events.basic_event import BasicEvent",
        "from mda_reporting.events.container_event import ContainerEvent",
        "from mda_reporting.events.event_types import EventType",
        "",
        "from utils.report_utils import (",
        "    create_table_if_not_exists,",
        "    capture_table_versions,",
        "    add_new_run_entry,",
        "    get_latest_problematic_run,",
        "    wipe_new_tables_from_last_run,",
        "    attempt_rollback_from_run,",
        "    update_run_success,",
        "    update_run_failure,",
        "    get_full_table_uri,",
        "    drop_all_report_tables,",
        ")",
        "from utils.schemas import STATUS_TABLE_SCHEMA",
    ]))

    # ---- Initialize Report ----
    cells.append("\n".join([
        'dbutils.widgets.text("config_path", "./config/dev_config.json")',
        'dbutils.widgets.dropdown("reset_report", "False", ["True", "False"])',
        'dbutils.widgets.text("status_table_name", "status")',
        "",
        'config_path = dbutils.widgets.get("config_path")',
        'reset_report = dbutils.widgets.get("reset_report").lower() == "true"',
        'status_table_name = dbutils.widgets.get("status_table_name")',
        "",
        'my_report = Report(name="report", spark=spark, config_path=config_path)',
        "query = my_report.query",
        "",
        "catalog = my_report.config.unity_sink.catalog",
        "schema_ = my_report.config.unity_sink.schema",
        "table_prefix = my_report.config.unity_sink.table_prefix",
        'print(f"Report: {catalog}.{schema_}.{table_prefix}")',
    ]))

    # ---- Pre-processing ----
    cells.append("\n".join([
        "if reset_report:",
        "    drop_all_report_tables(catalog, schema_, table_prefix)",
        "",
        "status_table_full_name = get_full_table_uri(catalog, schema_, table_prefix, status_table_name)",
        "create_table_if_not_exists(status_table_full_name, STATUS_TABLE_SCHEMA)",
        "",
        "last_problematic_run = get_latest_problematic_run(catalog, schema_, table_prefix, status_table_name)",
        "if last_problematic_run:",
        "    if last_problematic_run.processing_status != 'success' and last_problematic_run.rollback_status != 'success':",
        "        wipe_new_tables_from_last_run(catalog, schema_, table_prefix, last_problematic_run.delta_versions, status_table_name)",
        "        attempt_rollback_from_run(catalog, schema_, table_prefix, last_problematic_run, status_table_name)",
        "",
        "current_delta_versions = capture_table_versions(catalog, schema_, table_prefix, exclude_tables=[status_table_name])",
        "current_run_id = add_new_run_entry(catalog, schema_, table_prefix, status_table_name, current_delta_versions)",
    ]))

    # ---- Signal Definitions ----
    sig_lines: list[str] = []
    physical = [s for s in state.signals if s.signal_type == "physical"]
    virtual = [s for s in state.signals if s.signal_type == "virtual"]

    for sig in physical:
        ch_name = sig.channel_name or sig.alias or sig.var_name
        sig_lines.append(f'{sig.var_name} = query.channel(channel_name="{ch_name}")')

    if physical and virtual:
        sig_lines.append("")

    for sig in virtual:
        sig_lines.append(f"{sig.var_name} = {sig.expression}")

    sig_lines += ["", "signals = {"]
    for sig in state.signals:
        sig_lines.append(f'    "{sig.var_name}": {sig.var_name},')
    sig_lines += ["}"]
    cells.append("\n".join(sig_lines))

    # ---- Aggregations ----
    agg_lines: list[str] = [
        "page = Page(page_number=1)",
        "my_report.add_page(page)",
        "",
    ]

    for hist in (a for a in state.aggregations if isinstance(a, Histogram1DDefinition)):
        agg_type = _HISTOGRAM_AGG_TYPE_MAP[hist.histogram_type]
        params = [f'    name="{hist.name}"', f'    base_expr=signals["{hist.signal_ref}"]', f"    bins={hist.bins}"]
        if hist.description:
            params.append(f'    desc="{hist.description}"')
        params.append(f'    agg_type="{agg_type}"')
        if hist.bins_unit:
            params.append(f'    bins_unit="{hist.bins_unit}"')
        if hist.values_unit:
            params.append(f'    values_unit="{hist.values_unit}"')
        agg_lines.append("page.add_aggregation(Histogram(")
        agg_lines.append(",\n".join(params) + ",")
        agg_lines.append("))")
        agg_lines.append("")

    for hist2d in (a for a in state.aggregations if isinstance(a, Histogram2DDefinition)):
        params = [
            f'    name="{hist2d.name}"', f'    x_expr=signals["{hist2d.x_signal_ref}"]',
            f'    y_expr=signals["{hist2d.y_signal_ref}"]', f"    x_bins={hist2d.x_bins}", f"    y_bins={hist2d.y_bins}",
        ]
        if hist2d.description:
            params.append(f'    desc="{hist2d.description}"')
        if hist2d.x_bins_unit:
            params.append(f'    x_bins_unit="{hist2d.x_bins_unit}"')
        if hist2d.y_bins_unit:
            params.append(f'    y_bins_unit="{hist2d.y_bins_unit}"')
        if hist2d.values_unit:
            params.append(f'    values_unit="{hist2d.values_unit}"')
        agg_lines.append("page.add_aggregation(Histogram2D(")
        agg_lines.append(",\n".join(params) + ",")
        agg_lines.append("))")
        agg_lines.append("")

    for stats in (a for a in state.aggregations if isinstance(a, StatisticsDefinition)):
        selections_items = ", ".join(f'signals["{ref}"]' for ref in stats.signal_refs)
        params = [f'    name="{stats.name}"', f"    selections=[{selections_items}]", f"    aggregation_labels={repr(stats.stat_labels)}"]
        if stats.event_signal_ref:
            params.append(f'    event=BasicEvent(name="{stats.name}_event", expr=signals["{stats.event_signal_ref}"])')
        else:
            params.append(f'    event=ContainerEvent(name="{stats.name}_event")')
        if stats.description:
            params.append(f'    desc="{stats.description}"')
        agg_lines.append("page.add_aggregation(Statistics(")
        agg_lines.append(",\n".join(params) + ",")
        agg_lines.append("))")
        agg_lines.append("")

    cells.append("\n".join(agg_lines))

    # ---- Execute (with failure handling) ----
    cells.append("\n".join([
        "try:",
        '    print(f"[{datetime.now().isoformat()}] Running determine_report()...")',
        "    my_report.determine_report()",
        '    print(f"[{datetime.now().isoformat()}] determine_report() complete.")',
        "",
        '    print(f"[{datetime.now().isoformat()}] Running persist_results()...")',
        "    my_report.persist_results()",
        '    print(f"[{datetime.now().isoformat()}] Done. Report results persisted.")',
        "except Exception:",
        "    update_run_failure(catalog, schema_, table_prefix, status_table_name, current_run_id)",
        "    raise",
    ]))

    # ---- Post-processing ----
    cells.append("\n".join([
        "update_run_success(catalog, schema_, table_prefix, status_table_name, current_run_id)",
        "",
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


def generate_config_json(state: ReportState) -> dict[str, Any]:
    ds = state.data_sources

    units_under_test = []
    for v in state.vehicles:
        entry: dict[str, Any] = {
            "uut_name": {"col_name": v.col_name, "value": v.vehicle_id},
            "start_ts": {"col_name": "start_dt", "value": v.start_ts},
        }
        if v.stop_ts:
            entry["end_ts"] = {"col_name": "stop_dt", "value": v.stop_ts}
        units_under_test.append(entry)

    return {
        "source": {
            "container_metrics_table": ds.container_metrics,
            "channel_metrics_table": ds.channel_metrics,
            "channels_table": ds.channels[0] if ds.channels else "",
            "container_tags_table": ds.container_tags,
            "channel_tags_table": ds.channel_tags,
        },
        "unity_sink": {
            "catalog": ds.destination_catalog,
            "schema": ds.destination_schema,
            "table_prefix": ds.table_prefix or f"{state.name}_report",
        },
        "units_under_test": units_under_test,
        "query_engine": {
            "solver": "DeltaSolver",
            "data_type": "RLE",
            "drop_implausible_data": False,
        },
        "measurement_dimensions": ["container_id", "vehicle_key", "start_ts", "stop_ts"],
    }


def generate_all_files(state: ReportState) -> dict[str, str]:
    return {
        "src/report.py": generate_report_notebook(state),
        "src/config/dev_config.json": json.dumps(generate_config_json(state), indent=2),
    }
