"""Validate endpoint — /api/validate

Gold layer validation following validate-report-execution skill steps 5a-5c.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from server.agent import _sessions
from server.mcp_tools import execute_sql
from server.models import ValidationLevel, ValidationResults

router = APIRouter(prefix="/api", tags=["validate"])


@router.post("/validate/{session_id}")
async def validate_report(session_id: str, request: Request):
    """Run 3-level gold layer validation."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    user_token = request.headers.get("X-Forwarded-Access-Token")

    state = session.state
    ds = state.data_sources
    catalog = ds.destination_catalog
    schema = ds.destination_schema
    prefix = ds.table_prefix or f"{state.name}_report"
    fqn = f"{catalog}.{schema}"

    results = ValidationResults()

    level1 = _check_table_existence(fqn, prefix, user_token)
    results.levels.append(level1)
    if not level1.passed:
        state.validation = results
        return results

    level2 = _check_row_counts(fqn, prefix, user_token)
    results.levels.append(level2)
    if not level2.passed:
        state.validation = results
        return results

    level3, histogram_summary = _check_histogram_values(fqn, prefix, user_token)
    results.levels.append(level3)
    results.histogram_summary = histogram_summary

    state.validation = results
    return results


def _check_table_existence(fqn: str, prefix: str, user_token: str | None = None) -> ValidationLevel:
    try:
        result = execute_sql(f"SHOW TABLES IN {fqn} LIKE '{prefix}*'", user_token=user_token)
        tables = [row[1] for row in result["rows"]] if result["rows"] else []

        expected_patterns = ["histogram_dimension", "histogram_fact"]
        found = {p: any(p in t for t in tables) for p in expected_patterns}
        all_found = all(found.values())

        return ValidationLevel(
            name="Table Existence",
            passed=all_found,
            details={"tables_found": tables, "expected_check": found},
        )
    except Exception as e:
        return ValidationLevel(name="Table Existence", passed=False, details={"error": str(e)})


def _check_row_counts(fqn: str, prefix: str, user_token: str | None = None) -> ValidationLevel:
    tables_to_check = [
        f"{prefix}_histogram_dimension",
        f"{prefix}_histogram_fact",
    ]
    counts: dict[str, int] = {}
    try:
        parts = []
        for tbl in tables_to_check:
            short = tbl.replace(f"{prefix}_", "")
            parts.append(f"SELECT '{short}' AS tbl, COUNT(*) AS cnt FROM {fqn}.{tbl}")
        sql = " UNION ALL ".join(parts)
        result = execute_sql(sql, user_token=user_token)

        for row in result["rows"]:
            counts[row[0]] = int(row[1])

        all_non_empty = all(c > 0 for c in counts.values())
        return ValidationLevel(
            name="Row Counts",
            passed=all_non_empty,
            details={"counts": counts},
        )
    except Exception as e:
        return ValidationLevel(name="Row Counts", passed=False, details={"error": str(e)})


def _check_histogram_values(fqn: str, prefix: str, user_token: str | None = None) -> tuple[ValidationLevel, list[dict[str, Any]]]:
    try:
        sql = (
            f"SELECT d.name, "
            f"COUNT(DISTINCT f.container_id) AS sessions, "
            f"ROUND(SUM(f.hist_value), 2) AS total_value, "
            f"COUNT(CASE WHEN f.hist_value > 0 THEN 1 END) AS non_zero_bins "
            f"FROM {fqn}.{prefix}_histogram_fact f "
            f"JOIN {fqn}.{prefix}_histogram_dimension d ON f.visual_id = d.visual_id "
            f"GROUP BY d.name ORDER BY d.name"
        )
        result = execute_sql(sql, user_token=user_token)

        summary: list[dict[str, Any]] = []
        all_have_data = True
        for row in result["rows"]:
            total = float(row[2]) if row[2] else 0
            entry = {
                "histogram_name": row[0],
                "sessions": int(row[1]),
                "total_value": total,
                "non_zero_bins": int(row[3]),
                "status": "OK" if total > 0 else "EMPTY",
            }
            summary.append(entry)
            if total == 0:
                all_have_data = False

        dim_count_sql = f"SELECT COUNT(*) FROM {fqn}.{prefix}_histogram_dimension"
        dim_result = execute_sql(dim_count_sql, user_token=user_token)
        total_defined = int(dim_result["rows"][0][0]) if dim_result["rows"] else 0
        histograms_with_data = len([s for s in summary if s["status"] == "OK"])

        passed = histograms_with_data > 0
        return (
            ValidationLevel(
                name="Histogram Values",
                passed=passed,
                details={
                    "total_defined": total_defined,
                    "with_data": histograms_with_data,
                    "empty": total_defined - histograms_with_data,
                },
            ),
            summary,
        )
    except Exception as e:
        return ValidationLevel(name="Histogram Values", passed=False, details={"error": str(e)}), []
