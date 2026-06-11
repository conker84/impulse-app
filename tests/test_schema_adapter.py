"""Tests for SQL generation in server/schema_adapter.py.

These assert structural properties of the generated SQL (table paths, filters,
escaping, CTE shape) rather than exact whitespace, so they stay robust to
formatting tweaks while still catching logic regressions.
"""

from __future__ import annotations

import pytest

from server.schema_adapter import SchemaAdapter
from server.schema_profile import SchemaProfile

CATALOG = "cat"
SCHEMA = "sch"


def adapter(**profile_overrides) -> SchemaAdapter:
    profile = SchemaProfile(**profile_overrides)
    return SchemaAdapter(profile, CATALOG, SCHEMA)


class TestPathHelpers:
    def test_full_path_appends_catalog_schema_for_bare_name(self):
        a = adapter()
        assert a._full_path("container_metrics") == "cat.sch.container_metrics"

    def test_full_path_passes_through_qualified_name(self):
        a = adapter()
        assert a._full_path("other.db.table") == "other.db.table"

    def test_metrics_paths(self):
        a = adapter()
        assert a.container_metrics_path() == "cat.sch.container_metrics"
        assert a.channel_metrics_path() == "cat.sch.channel_metrics"
        assert a.timeseries_path() == "cat.sch.channels"

    def test_aliases_path_none_when_unset(self):
        assert adapter().aliases_path() is None

    def test_aliases_path_when_set(self):
        a = adapter(aliases_table="alias_tbl")
        assert a.aliases_path() == "cat.sch.alias_tbl"


class TestSqlLiteral:
    def test_int_is_unquoted(self):
        assert SchemaAdapter._sql_literal(42) == "42"

    def test_float_is_unquoted(self):
        assert SchemaAdapter._sql_literal(3.5) == "3.5"

    def test_string_is_quoted(self):
        assert SchemaAdapter._sql_literal("abc") == "'abc'"

    def test_string_single_quotes_are_escaped(self):
        assert SchemaAdapter._sql_literal("o'brien") == "'o''brien'"


class TestVehicleCandidatesQuery:
    def test_tag_source_reads_container_tags_table(self):
        sql = adapter().vehicle_candidates_query()
        assert "cat.sch.container_tags" in sql
        assert "key = 'vehicle_key'" in sql

    def test_constant_source(self):
        sql = adapter(
            vehicle_source="constant", vehicle_constant="fleet_a"
        ).vehicle_candidates_query()
        assert "'fleet_a' AS vehicle_id" in sql
        assert "cat.sch.container_metrics" in sql

    def test_column_source(self):
        sql = adapter(
            vehicle_source="column", vehicle_column="vin"
        ).vehicle_candidates_query()
        assert "CAST(vin AS STRING) AS vehicle_id" in sql
        assert "vin IS NOT NULL" in sql


class TestContainerTagsCte:
    def test_uses_real_table_when_configured(self):
        cte = adapter()._container_tags_cte()
        assert "cat.sch.container_tags" in cte

    def test_synthesizes_constant_vehicle_key(self):
        cte = adapter(
            container_tags_table=None,
            vehicle_source="constant",
            vehicle_constant="fleet_a",
        )._container_tags_cte()
        assert "'vehicle_key' AS key" in cte
        assert "'fleet_a' AS value" in cte

    def test_synthesizes_column_vehicle_key(self):
        cte = adapter(
            container_tags_table=None,
            vehicle_source="column",
            vehicle_column="vin",
        )._container_tags_cte()
        assert "CAST(vin AS STRING) AS value" in cte


class TestChannelTagsCte:
    def test_uses_real_table_when_configured(self):
        cte = adapter()._channel_tags_cte()
        assert "cat.sch.channel_tags" in cte

    def test_synthesizes_unit_from_unit_col(self):
        cte = adapter(
            channel_tags_table=None, channel_unit_col="uom"
        )._channel_tags_cte()
        assert "'unit' AS key" in cte
        assert "COALESCE(uom, '')" in cte

    def test_synthesizes_unit_from_aliases_join(self):
        cte = adapter(
            channel_tags_table=None,
            channel_unit_col=None,
            aliases_table="alias_tbl",
            aliases_unit_col="unit",
        )._channel_tags_cte()
        assert "LEFT JOIN cat.sch.alias_tbl" in cte

    def test_empty_unit_fallback(self):
        cte = adapter(
            channel_tags_table=None,
            channel_unit_col=None,
            aliases_table=None,
        )._channel_tags_cte()
        assert "'' AS value" in cte


class TestQueries:
    def test_containers_list_query_has_cte_and_columns(self):
        sql = adapter().containers_list_query()
        assert sql.startswith("WITH ")
        assert "vehicle_key" in sql
        assert "duration_ms" in sql
        assert "ORDER BY start_dt DESC" in sql

    def test_signals_list_query_escapes_container_id(self):
        sql = adapter().signals_list_query("c'1")
        assert "'c''1'" in sql
        assert "t_name.key = 'channel_name'" in sql

    def test_channel_catalog_query_no_vehicle_filter(self):
        sql = adapter().channel_catalog_query()
        assert "ct_veh" not in sql
        assert "GROUP BY t_name.value" in sql

    def test_channel_catalog_query_with_vehicle_filter(self):
        sql = adapter().channel_catalog_query(vehicle_ids=["a", "b"])
        assert "ct_veh" in sql
        assert "'a'" in sql and "'b'" in sql

    def test_aliases_search_query_none_without_aliases_table(self):
        assert adapter().aliases_search_query("temp") is None

    def test_aliases_search_query_escapes_keyword_and_limits(self):
        sql = adapter(aliases_table="alias_tbl").aliases_search_query("o'temp", limit=10)
        assert "%o''temp%" in sql
        assert "LIMIT 10" in sql

    def test_aliases_search_query_limit_int_coercion_blocks_injection(self):
        a = adapter(aliases_table="alias_tbl")
        # A clean int produces a clean LIMIT clause...
        assert "LIMIT 5" in a.aliases_search_query("x", limit=5)
        # ...and a non-numeric limit is rejected by int() rather than interpolated,
        # which prevents SQL injection through the limit parameter.
        with pytest.raises(ValueError):
            a.aliases_search_query("x", limit="5; DROP TABLE t")


class TestDataTimeRangeQuery:
    def test_no_vehicle_ids(self):
        sql = adapter().data_time_range_query()
        assert "MIN(c.start_dt)" in sql
        assert "WHERE" not in sql

    def test_constant_source_ignores_vehicle_filter(self):
        sql = adapter(
            vehicle_source="constant", vehicle_constant="f"
        ).data_time_range_query(vehicle_ids=["f"])
        assert "WHERE" not in sql

    def test_column_source_filters_by_column(self):
        sql = adapter(
            vehicle_source="column", vehicle_column="vin"
        ).data_time_range_query(vehicle_ids=["v1", "v2"])
        assert "CAST(c.vin AS STRING) IN ('v1', 'v2')" in sql

    def test_tag_source_joins_container_tags(self):
        sql = adapter().data_time_range_query(vehicle_ids=["v1"])
        assert "JOIN cat.sch.container_tags" in sql
        assert "key = 'vehicle_key'" in sql


class TestTimeseries:
    def test_has_tend_false_by_default_when_none(self):
        assert adapter(timeseries_end_time_col=None).has_tend() is False

    def test_has_tend_true_when_set(self):
        assert adapter(timeseries_end_time_col="tend").has_tend() is True

    def test_ts_fetch_query_includes_tend_when_present(self):
        sql = adapter(timeseries_end_time_col="tend").ts_explorer_signal_fetch_query(
            "c1", "ch1"
        )
        assert "AS tend" in sql
        assert "'c1'" in sql and "'ch1'" in sql

    def test_ts_fetch_query_omits_tend_when_absent(self):
        sql = adapter(timeseries_end_time_col=None).ts_explorer_signal_fetch_query(
            "c1", "ch1"
        )
        assert "AS tend" not in sql
        assert "AS tstart" in sql


class TestFromActiveProfile:
    def test_session_overrides_applied(self, monkeypatch):
        import server.schema_adapter as sa

        monkeypatch.setattr(sa, "get_profile", lambda: SchemaProfile())
        a = SchemaAdapter.from_active_profile(
            CATALOG, SCHEMA, session_overrides={"container_table": "override_tbl"}
        )
        assert a.profile.container_table == "override_tbl"

    def test_none_overrides_ignored(self, monkeypatch):
        import server.schema_adapter as sa

        monkeypatch.setattr(sa, "get_profile", lambda: SchemaProfile(container_table="base"))
        a = SchemaAdapter.from_active_profile(
            CATALOG, SCHEMA, session_overrides={"container_table": None}
        )
        assert a.profile.container_table == "base"
