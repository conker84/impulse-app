from __future__ import annotations

from server.schema_profile import SchemaProfile, get_profile


class SchemaAdapter:
    def __init__(self, profile: SchemaProfile, catalog: str, schema: str):
        self.profile = profile
        self.catalog = catalog
        self.schema = schema

    @classmethod
    def from_active_profile(
        cls,
        catalog: str,
        schema: str,
        session_overrides: dict | None = None,
    ) -> "SchemaAdapter":
        profile = get_profile()
        if session_overrides:
            data = profile.model_dump()
            data.update({k: v for k, v in session_overrides.items() if v is not None})
            profile = SchemaProfile.model_validate(data)
        return cls(profile, catalog, schema)

    def _full_path(self, suffix_or_path: str) -> str:
        if "." in suffix_or_path:
            return suffix_or_path
        return f"{self.catalog}.{self.schema}.{suffix_or_path}"

    def container_metrics_path(self) -> str:
        return self._full_path(self.profile.container_table)

    def channel_metrics_path(self) -> str:
        return self._full_path(self.profile.channel_table)

    def timeseries_path(self) -> str:
        return self._full_path(self.profile.timeseries_table)

    def aliases_path(self) -> str | None:
        return self._full_path(self.profile.aliases_table) if self.profile.aliases_table else None

    def _container_tags_cte(self) -> str:
        p = self.profile
        if p.container_tags_table:
            return (
                f"container_tags AS (SELECT {p.container_tags_id_col} AS container_id, "
                f"key, value FROM {self._full_path(p.container_tags_table)})"
            )

        cm = self.container_metrics_path()
        cid = p.container_id_col
        rows: list[str] = []

        rows.append(
            f"SELECT {cid} AS container_id, 'filename' AS key, "
            f"CAST({cid} AS STRING) AS value FROM {cm}"
        )

        if p.vehicle_source == "constant":
            rows.append(
                f"SELECT {cid} AS container_id, 'vehicle_key' AS key, "
                f"'{p.vehicle_constant}' AS value FROM {cm}"
            )
        elif p.vehicle_source == "column":
            rows.append(
                f"SELECT {cid} AS container_id, 'vehicle_key' AS key, "
                f"CAST({p.vehicle_column} AS STRING) AS value FROM {cm}"
            )

        return "container_tags AS (\n  " + "\n  UNION ALL\n  ".join(rows) + "\n)"

    def _channel_tags_cte(self) -> str:
        p = self.profile
        if p.channel_tags_table:
            return (
                f"channel_tags AS (SELECT {p.channel_tags_container_id_col} AS container_id, "
                f"{p.channel_tags_channel_id_col} AS channel_id, key, value "
                f"FROM {self._full_path(p.channel_tags_table)})"
            )

        cm = self.channel_metrics_path()
        c_id = p.channel_container_id_col
        ch_id = p.channel_id_col
        rows: list[str] = []

        rows.append(
            f"SELECT {c_id} AS container_id, {ch_id} AS channel_id, "
            f"'channel_name' AS key, {p.channel_name_col} AS value FROM {cm}"
        )

        if p.channel_unit_col:
            rows.append(
                f"SELECT {c_id} AS container_id, {ch_id} AS channel_id, "
                f"'unit' AS key, COALESCE({p.channel_unit_col}, '') AS value FROM {cm}"
            )
        elif p.aliases_table and p.aliases_unit_col:
            ali = self._full_path(p.aliases_table)
            join_keys = [f"a.{p.channel_name_col} = cm.{p.channel_name_col}"]
            if p.channel_secondary_id_col:
                join_keys.append(f"a.{p.channel_secondary_id_col} = cm.{p.channel_secondary_id_col}")
            join_cond = " AND ".join(join_keys)
            rows.append(
                f"SELECT cm.{c_id} AS container_id, cm.{ch_id} AS channel_id, "
                f"'unit' AS key, COALESCE(a.{p.aliases_unit_col}, '') AS value "
                f"FROM {cm} cm LEFT JOIN {ali} a ON {join_cond}"
            )
        else:
            rows.append(
                f"SELECT {c_id} AS container_id, {ch_id} AS channel_id, "
                f"'unit' AS key, '' AS value FROM {cm}"
            )

        return "channel_tags AS (\n  " + "\n  UNION ALL\n  ".join(rows) + "\n)"

    def _resolve_expr(self, expr: str) -> str:
        return expr.format(
            container_metrics=self.container_metrics_path(),
            channel_metrics=self.channel_metrics_path(),
            timeseries=self.timeseries_path(),
            aliases=self.aliases_path() or "",
        )

    def containers_list_query(self) -> str:
        p = self.profile
        cm = self.container_metrics_path()
        chm = self.channel_metrics_path()
        return (
            "WITH " + self._container_tags_cte() + "\n"
            f"SELECT c.{p.container_id_col} AS container_id, "
            f"  COALESCE(t_vk.value, '') AS vehicle_key, "
            f"  c.{p.container_start_col} AS start_dt, "
            f"  c.{p.container_stop_col} AS stop_dt, "
            f"  COALESCE(ch.num_channels, 0) AS num_channels, "
            f"  CAST(unix_millis(c.{p.container_stop_col}) - unix_millis(c.{p.container_start_col}) AS BIGINT) AS duration_ms "
            f"FROM {cm} c "
            f"LEFT JOIN container_tags t_vk ON c.{p.container_id_col} = t_vk.container_id AND t_vk.key = 'vehicle_key' "
            f"LEFT JOIN (SELECT {p.channel_container_id_col} AS cid, COUNT(*) AS num_channels FROM {chm} GROUP BY 1) ch "
            f"  ON c.{p.container_id_col} = ch.cid "
            f"ORDER BY start_dt DESC"
        )

    def vehicle_candidates_query(self) -> str:
        p = self.profile
        cm = self.container_metrics_path()
        if p.vehicle_source == "constant":
            return (
                f"SELECT '{p.vehicle_constant}' AS vehicle_id, "
                f"COUNT(*) AS container_count FROM {cm} "
                f"GROUP BY 1"
            )
        if p.vehicle_source == "column":
            return (
                f"SELECT CAST({p.vehicle_column} AS STRING) AS vehicle_id, "
                f"COUNT(DISTINCT {p.container_id_col}) AS container_count "
                f"FROM {cm} "
                f"WHERE {p.vehicle_column} IS NOT NULL "
                f"GROUP BY 1 ORDER BY 1"
            )
        ct = self._full_path(p.container_tags_table)
        return (
            f"SELECT value AS vehicle_id, COUNT(DISTINCT {p.container_tags_id_col}) AS container_count "
            f"FROM {ct} WHERE key = 'vehicle_key' AND value IS NOT NULL AND value != 'NA' "
            f"GROUP BY value ORDER BY value"
        )

    def signals_list_query(self, container_id: str) -> str:
        p = self.profile
        sample_rate_expr = self._resolve_expr(p.channel_sample_rate_expr) if p.channel_sample_rate_expr else "NULL"
        return (
            "WITH " + self._channel_tags_cte() + "\n"
            f"SELECT t_name.channel_id AS channel_id, "
            f"  t_name.value AS channel_name, "
            f"  COALESCE(t_unit.value, '') AS unit, "
            f"  m.{p.channel_sample_count_col} AS sample_count, "
            f"  m.{p.channel_min_col} AS min, "
            f"  m.{p.channel_max_col} AS max, "
            f"  m.{p.channel_mean_col} AS mean, "
            f"  {sample_rate_expr} AS sample_rate "
            f"FROM channel_tags t_name "
            f"LEFT JOIN channel_tags t_unit "
            f"  ON t_name.container_id = t_unit.container_id "
            f"  AND t_name.channel_id = t_unit.channel_id "
            f"  AND t_unit.key = 'unit' "
            f"LEFT JOIN {self.channel_metrics_path()} m "
            f"  ON t_name.container_id = m.{p.channel_container_id_col} "
            f"  AND t_name.channel_id = m.{p.channel_id_col} "
            f"WHERE t_name.key = 'channel_name' "
            f"  AND t_name.container_id = {self._sql_literal(container_id)} "
            f"ORDER BY channel_name"
        )

    def channel_catalog_query(self, vehicle_ids: list[str] | None = None) -> str:
        p = self.profile
        sample_rate_expr = self._resolve_expr(p.channel_sample_rate_expr) if p.channel_sample_rate_expr else "NULL"

        cte_parts = [self._channel_tags_cte()]
        vehicle_filter_join = ""
        if vehicle_ids:
            cte_parts.append(self._container_tags_cte())
            ids_str = ", ".join(self._sql_literal(v) for v in vehicle_ids)
            vehicle_filter_join = (
                f"JOIN container_tags ct_veh "
                f"  ON t_name.container_id = ct_veh.container_id "
                f"  AND ct_veh.key = 'vehicle_key' "
                f"  AND ct_veh.value IN ({ids_str}) "
            )

        return (
            "WITH " + ",\n".join(cte_parts) + "\n"
            f"SELECT t_name.value AS channel_name, "
            f"  COALESCE(t_unit.value, '') AS unit, "
            f"  CAST(SUM(m.{p.channel_sample_count_col}) AS INT) AS sample_count, "
            f"  MIN(m.{p.channel_min_col}) AS min_value, "
            f"  MAX(m.{p.channel_max_col}) AS max_value, "
            f"  AVG(m.{p.channel_mean_col}) AS mean_value, "
            f"  AVG({sample_rate_expr}) AS sample_rate, "
            f"  COUNT(DISTINCT t_name.container_id) AS container_count "
            f"FROM channel_tags t_name "
            f"LEFT JOIN channel_tags t_unit "
            f"  ON t_name.container_id = t_unit.container_id "
            f"  AND t_name.channel_id = t_unit.channel_id "
            f"  AND t_unit.key = 'unit' "
            f"JOIN {self.channel_metrics_path()} m "
            f"  ON t_name.container_id = m.{p.channel_container_id_col} "
            f"  AND t_name.channel_id = m.{p.channel_id_col} "
            f"{vehicle_filter_join}"
            f"WHERE t_name.key = 'channel_name' "
            f"GROUP BY t_name.value, t_unit.value "
            f"ORDER BY channel_name"
        )

    def aliases_search_query(self, keyword: str, limit: int = 50) -> str | None:
        p = self.profile
        if not p.aliases_table:
            return None

        kw = keyword.replace("'", "''")
        ali = self._full_path(p.aliases_table)

        cols = [
            f"{p.aliases_alias_col} AS channel_alias_name",
            f"{p.channel_name_col} AS channel_name",
            f"{p.channel_name_col} AS signal",
        ]
        if p.channel_secondary_id_col:
            cols.append(f"{p.channel_secondary_id_col} AS device_name")
            cols.append(f"{p.channel_secondary_id_col} AS network")
        else:
            cols.append("'' AS device_name")
            cols.append("CAST(NULL AS STRING) AS network")
        cols.append(f"{p.aliases_unit_col or 'NULL'} AS unit")
        cols.append(f"{p.aliases_description_col or 'NULL'} AS description")

        return (
            f"SELECT {', '.join(cols)} FROM {ali} "
            f"WHERE {p.aliases_alias_col} LIKE '%{kw}%' "
            f"  OR {p.channel_name_col} LIKE '%{kw}%' "
            f"ORDER BY {p.aliases_alias_col} "
            f"LIMIT {int(limit)}"
        )

    def data_time_range_query(self, vehicle_ids: list[str] | None = None) -> str:
        p = self.profile
        cm = self.container_metrics_path()

        if not vehicle_ids:
            return (
                f"SELECT MIN(c.{p.container_start_col}) AS min_start, "
                f"  MAX(c.{p.container_stop_col}) AS max_stop "
                f"FROM {cm} c"
            )

        ids_str = ", ".join(self._sql_literal(v) for v in vehicle_ids)

        if p.vehicle_source == "constant":
            return (
                f"SELECT MIN(c.{p.container_start_col}) AS min_start, "
                f"  MAX(c.{p.container_stop_col}) AS max_stop "
                f"FROM {cm} c"
            )
        if p.vehicle_source == "column":
            return (
                f"SELECT MIN(c.{p.container_start_col}) AS min_start, "
                f"  MAX(c.{p.container_stop_col}) AS max_stop "
                f"FROM {cm} c "
                f"WHERE CAST(c.{p.vehicle_column} AS STRING) IN ({ids_str})"
            )
        ct = self._full_path(p.container_tags_table)
        return (
            f"SELECT MIN(c.{p.container_start_col}) AS min_start, "
            f"  MAX(c.{p.container_stop_col}) AS max_stop "
            f"FROM {cm} c "
            f"JOIN {ct} ct ON c.{p.container_id_col} = ct.{p.container_tags_id_col} "
            f"  AND ct.key = 'vehicle_key' AND ct.value IN ({ids_str})"
        )

    def has_tend(self) -> bool:
        return self.profile.timeseries_end_time_col is not None

    def ts_explorer_signal_fetch_query(self, container_id: str, channel_id: str) -> str:
        p = self.profile
        ts = self.timeseries_path()
        time_expr = p.timeseries_time_col
        value_expr = p.timeseries_value_col
        container_match = p.timeseries_container_match_col or p.channel_container_id_col
        channel_match = p.timeseries_channel_match_expr or p.channel_id_col
        if p.timeseries_end_time_col:
            select_clause = (
                f"{time_expr} AS tstart, {p.timeseries_end_time_col} AS tend, {value_expr} AS value"
            )
        else:
            select_clause = f"{time_expr} AS tstart, {value_expr} AS value"
        return (
            f"SELECT {select_clause} FROM {ts} "
            f"WHERE {container_match} = {self._sql_literal(container_id)} "
            f"  AND ({channel_match}) = {self._sql_literal(channel_id)}"
        )

    @staticmethod
    def _sql_literal(value: str | int) -> str:
        if isinstance(value, (int, float)):
            return str(value)
        s = str(value).replace("'", "''")
        return f"'{s}'"
