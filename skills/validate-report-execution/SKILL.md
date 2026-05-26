---
name: validate-report-execution
description: Feedback loop for Impulse framework reports executed as Databricks Jobs. Deploy, run, collect results, parse errors and fix the report, or validate gold layer output tables for meaningful histogram results. Use when the user wants to run a report, check job results, debug a failed report run, or verify report output.
compatibility: Requires Databricks CLI with a configured profile, and a scaffolded Impulse report.
allowed-tools: Bash Read Edit
---

# Validate Report Execution

Deploy an Impulse framework report as a Databricks Job, monitor the run, and close the feedback loop — either by fixing errors or validating that meaningful results were produced.

**Usage:** `/validate-report-execution [report_name]`

## Prerequisites

- The report must be scaffolded and configured (signals, histograms, `dev_config.json`).
- The Databricks CLI must be installed with a configured profile in `~/.databrickscfg`.
- The working directory must be `nameda/` (repository root containing the `Makefile`).

## Workflow Overview

```
Deploy & Run ──► Monitor Job ──► Collect Result
                                      │
                         ┌────────────┴────────────┐
                         ▼                          ▼
                    JOB FAILED                JOB SUCCEEDED
                         │                          │
                    Parse Errors              Validate Gold Layer
                         │                          │
                  ┌──► Present Diagnosis ◄──  Present Findings
                  │    to User [GATE 1]       to User [GATE 3]
                  │         │                       │
                  │    User confirms /          User accepts /
                  │    provides guidance        requests changes
                  │         │                       │
                  │    Apply Fix                Investigate or
                  │         │                   adjust report
                  │    Confirm Fix ◄──────────      │
                  │    with User [GATE 2]           │
                  │         │                       │
                  │    Re-run Job                  Done
                  │         │
                  └─────────┘
```

## Human Feedback Principles

The agent must **never silently auto-fix and re-run**. Every iteration through the loop includes explicit user checkpoints:

| Gate | When | What to present | Wait for |
|---|---|---|---|
| **GATE 1** | After error diagnosis | Error classification, root cause, proposed fix with file + change | User confirms fix, suggests alternative, or asks to investigate further |
| **GATE 2** | After applying a fix | Summary of changes made, diff if helpful | User approves re-run, or wants additional changes first |
| **GATE 3** | After gold layer validation | Results summary table (per histogram: value, bin coverage, sessions) | User accepts results, flags issues, or requests deeper investigation |

**Confidence-based escalation**: If the error clearly matches a known pattern with a single unambiguous fix (e.g. a typo in an alias name), present the fix with high confidence and ask for a quick confirmation. If the error is ambiguous or has multiple possible causes, present all candidates and ask the user to choose.

## Steps

### 1. Identify report

- If no report name is provided, list folders under `nameda/` and ask the user which report to validate.
- Read the report's config file at `<report_name>/src/config/dev_config.json` to extract:
  - `data.destination.catalog` — target catalog
  - `data.destination.schema` — target schema
  - `data.destination.table_prefix` — prefix for all output tables
- Store these for gold layer validation later.

### 2. Deploy and run

Use the repository Makefile:

```bash
cd nameda && make run REPORT_NAME=<report_name>
```

This runs `databricks bundle deploy` followed by `databricks bundle run <report_name>_job`.

The `bundle run` command outputs a **run URL**. Capture it — it's needed for monitoring.

Alternatively, deploy and run separately for more control:

```bash
cd nameda/<report_name> && databricks bundle deploy --target dev --profile $DATABRICKS_PROFILE
cd nameda/<report_name> && databricks bundle run <report_name>_job --target dev --profile $DATABRICKS_PROFILE
```

### 3. Monitor the job run

The `databricks bundle run` command blocks until the job completes and streams output. Monitor it:

- **If the command is still running**: check the terminal output periodically for progress or errors.
- **If it completes with exit code 0**: proceed to **Step 5 (Success path)**.
- **If it completes with a non-zero exit code**: proceed to **Step 4 (Failure path)**.

If you need to check run status separately (e.g. after a timeout):

```bash
databricks jobs get-run <run_id> --profile $DATABRICKS_PROFILE -o json
```

Key fields in the run result:
- `state.result_state`: `SUCCESS`, `FAILED`, `TIMEDOUT`, `CANCELED`
- `state.state_message`: human-readable failure reason
- `tasks[].state`: per-task status

### 4. Failure path — Parse errors and fix

When the job fails, follow this sequence:

#### 4a. Collect error details

Get the full run output:

```bash
databricks jobs get-run <run_id> --profile $DATABRICKS_PROFILE -o json
```

For task-level errors, find the failed task and get its output:

```bash
databricks jobs get-run-output <run_id> --profile $DATABRICKS_PROFILE -o json
```

Look at:
- `error` — top-level error message
- `error_trace` — full Python traceback
- `metadata.run_page_url` — link to the Databricks UI for detailed logs

#### 4b. Classify the error

Read [references/error-patterns.md](references/error-patterns.md) for the full catalog of common errors. The main categories are:

| Category | Typical Error Pattern | Likely Fix |
|---|---|---|
| **Signal not found** | `Signal alias ... not found` | Wrong alias name in `01_signal_definitions.py` — look up correct alias |
| **Table not found** | `TABLE_OR_VIEW_NOT_FOUND` | Wrong table path in `dev_config.json` |
| **Permission denied** | `PERMISSION_DENIED`, `ACCESS_DENIED` | Missing grants on source or destination tables |
| **Type mismatch** | `Cannot apply ... to Intervals/SampleSeries` | Expression type wrong for histogram type — check signal definitions |
| **Config error** | `KeyError`, `JSONDecodeError` | Malformed or missing fields in `dev_config.json` |
| **Cluster error** | `CLOUD_PROVIDER_LAUNCH_ERROR`, `DRIVER_UNREACHABLE` | Transient — retry the run |
| **Framework error** | `impulse_reporting` traceback | Check the Impulse framework pin (`@<commit-sha>`) in `report_template/template/resources/jobs.yml.tmpl` against an available version on github.com/databrickslabs/impulse |

#### 4c. Present diagnosis to user (GATE 1)

**Do not apply any fix yet.** Present the following to the user:

1. **Error classification** — which category from the table above
2. **Root cause** — the specific signal, table, config field, or expression that caused the failure
3. **Proposed fix** — the exact file and change you intend to make
4. **Confidence level** — high (single clear fix), medium (likely fix but worth confirming), or low (ambiguous, multiple possibilities)

For **low confidence** errors (ambiguous, unknown pattern, or multiple possible causes):
- Present all candidate causes and ask the user which to investigate
- If the error doesn't match any known pattern, show the raw traceback and ask the user for guidance
- Never guess — ask

For **permission or infrastructure errors** that cannot be fixed in code:
- Explain what access or resource is needed
- Ask the user to resolve it externally (e.g. request grants from a workspace admin)
- Offer to retry once the user confirms the issue is resolved

Wait for the user to confirm, adjust, or redirect before proceeding.

#### 4d. Apply fix and confirm (GATE 2)

1. Apply the confirmed fix to the relevant file:
   - Signal errors → edit `src/01_signal_definitions.py`
   - Config errors → edit `src/config/dev_config.json`
   - Histogram errors → edit the page file under `src/chapters/`
2. Show the user a summary of what was changed (file, old value → new value).
3. Ask: *"Fix applied. Should I re-deploy and re-run the job, or do you want to make additional changes first?"*
4. If the user confirms re-run → go back to **Step 2**.
5. If the user wants more changes → wait for instructions, apply them, and ask again.

### 5. Success path — Validate gold layer

When the job succeeds, validate that meaningful results were produced. Read [references/gold-layer-validation.md](references/gold-layer-validation.md) for the full set of SQL queries.

The validation has three levels, executed in order. **Stop at the first level that fails.**

#### 5a. Check table existence

Query the destination schema for expected tables:

```sql
SHOW TABLES IN <catalog>.<schema> LIKE '<table_prefix>*'
```

Expected tables for a histogram report:
- `<table_prefix>_histogram_fact` — computed histogram values
- `<table_prefix>_histogram_dim` — histogram metadata (names, bins, units)
- `<table_prefix>_sessions` — processed session metadata

**If tables are missing**: the job likely succeeded at the orchestrator level but no data matched the vehicle/time filter. Check:
- Vehicle ID in `dev_config.json` matches data in `container_metrics`
- Start timestamp is not in the future
- The channel table has data for this vehicle

#### 5b. Check row counts

```sql
SELECT COUNT(*) as row_count FROM <catalog>.<schema>.<table_prefix>_histogram_fact;
SELECT COUNT(*) as row_count FROM <catalog>.<schema>.<table_prefix>_sessions;
```

**If tables exist but are empty (0 rows)**: sessions were found but no histogram data was computed. Check:
- Signal aliases resolve to actual channels in the data
- The time range contains data for the referenced signals
- Enable/masking conditions aren't filtering out all data

#### 5c. Check histogram values

```sql
SELECT
    d.histogram_name,
    COUNT(*) AS bin_count,
    SUM(f.histogram_value) AS total_value,
    MAX(f.histogram_value) AS max_value
FROM <catalog>.<schema>.<table_prefix>_histogram_fact f
JOIN <catalog>.<schema>.<table_prefix>_histogram_dim d
    ON f.histogram_id = d.histogram_id
GROUP BY d.histogram_name
ORDER BY d.histogram_name
```

For each histogram, check:

| Condition | Verdict | Action |
|---|---|---|
| `total_value > 0` and `max_value > 0` | Results look meaningful | Report to user |
| `total_value = 0` for all histograms | All zeros — no data matched | Check signal availability and enable conditions |
| `total_value = 0` for some histograms | Partial data — some signals missing | Investigate the zero-value histograms specifically |
| Only 1 bin has data | Data outside expected range | Review bin definitions (min/max/width) |

**If all histogram values are zero**: the signals exist but contain no data in the configured time range, or the enable/masking conditions are too restrictive. Investigate by checking the raw signal availability:

```sql
SELECT DISTINCT signal_name
FROM <catalog>.<schema>.<table_prefix>_sessions s
JOIN <source_channel_metrics_table> m ON s.global_session_id = m.global_session_id
WHERE signal_name LIKE '%<keyword>%'
LIMIT 20
```

### 6. (Optional) Compare against expected results — Level 4

If the user provides reference tables with expected results, add a fourth validation level that compares actual output against the expected baseline. This step is **only performed when the user explicitly provides expected result tables**.

#### 6a. Collect reference table paths

Ask the user for:
- **Expected dimension table** — fully qualified path (e.g. `catalog.schema.report_histogram_dimension`)
- **Expected fact table** — fully qualified path (e.g. `catalog.schema.report_histogram_fact`)

Both tables must follow the standard Impulse schema (`visual_id`, `name`, `bins`, `hist_value`, `bin_ID`, `lower_bound`, `upper_bound`, `global_session_id`).

#### 6b. Match histograms by name

Join expected and actual dimension tables on the `name` column (not `visual_id`, which differs between reports). Present the matching result:

```sql
SELECT
    COALESCE(e.name, a.name) AS histogram_name,
    e.name IS NOT NULL AS in_expected,
    a.name IS NOT NULL AS in_actual
FROM <expected_dim> e
FULL OUTER JOIN <actual_dim> a ON e.name = a.name
ORDER BY histogram_name
```

Report:
- **Matched** — histograms present in both expected and actual
- **Missing from actual** — histograms in expected but not produced by the report (likely a migration gap or naming difference)
- **Extra in actual** — new histograms not in the reference (expected for newly added histograms)

#### 6c. Compare aggregated values

For matched histograms, compare totals and compute deviation percentages. Read [references/expected-results-comparison.md](references/expected-results-comparison.md) for the full set of SQL queries.

Present a summary table:

| Histogram | Expected Total | Actual Total | Deviation | Sessions (E/A) | Verdict |
|---|---|---|---|---|---|
| `engine_speed_hist_p1` | 12,456.3 | 12,456.3 | 0.0% | 42/42 | MATCH |
| `intake_air_temp_hist_p1` | 892.1 | 845.7 | 5.2% | 42/40 | INVESTIGATE |
| `lambda_hist_p1` | 334.8 | 0.0 | 100% | 42/0 | FAIL |

**Deviation thresholds:**

| Deviation | Verdict |
|---|---|
| < 1% | MATCH — results are effectively identical |
| 1–5% | CLOSE — minor deviation, likely different session coverage |
| 5–20% | INVESTIGATE — significant deviation, present to user |
| > 20% or missing | FAIL — likely a bug in signal definitions or bin config |

#### 6d. Drill down on deviations (user-driven)

For histograms marked INVESTIGATE or FAIL, offer the user two drill-down options:

1. **Session diff** — show which sessions are in expected but not actual (or vice versa). This is the most common cause of deviations.
2. **Per-bin comparison** — for a specific session present in both, compare bin-by-bin values to find where the deviation originates.

Only drill down when the user asks — do not auto-run these expensive queries for every histogram.

### 7. Present results to user (GATE 3)

After validation, present a structured summary and ask for the user's assessment.

**Success with data:**
> The report executed successfully. Here are the results per histogram:
>
> | Histogram | Sessions | Total Value | Bins with Data | Status |
> |---|---|---|---|---|
> | `battery_voltage_hist_p1` | 42 | 1,245.3 | 18/20 | OK |
> | `intake_air_temp_hist_p1` | 42 | 892.1 | 12/14 | OK |
> | ... | ... | ... | ... | ... |
>
> *Do these results look reasonable? Should I investigate any histogram in more detail?*

**Success but partial (some histograms zero):**
> The job completed, but some histograms have no data:
>
> | Histogram | Status | Possible Cause |
> |---|---|---|
> | `lambda_deviation_hist_p1` | All zeros | Enable condition may be too restrictive |
>
> *Should I investigate why these histograms are empty, or are these expected to have no data for this vehicle?*

**Success but empty (all zero / no tables):**
> The job completed successfully, but the gold layer tables are empty. This typically means no measurement sessions matched your vehicle/time filter.
>
> *Possible causes:*
> 1. Vehicle ID "VH-001" has no data after 2025-08-01
> 2. Channel table doesn't contain signals for this vehicle
>
> *Should I run diagnostic queries to pinpoint the issue, or would you like to adjust the config?*

**Success with expected results comparison:**
> Compared actual output against reference tables. Results:
>
> | Histogram | Deviation | Verdict |
> |---|---|---|
> | `battery_voltage_hist_p1` | 0.0% | MATCH |
> | `intake_air_temp_hist_p1` | 3.2% | CLOSE (2 fewer sessions) |
> | `lambda_deviation_hist_p1` | 100% | FAIL (no actual data) |
>
> *Should I drill down on the deviations, or are the CLOSE results acceptable?*

Wait for the user's response. Depending on feedback:
- **User accepts results** → done
- **User flags specific histograms** → investigate those (query bin distribution, check signal availability, or drill into expected vs actual per session/bin)
- **User wants config changes** → apply changes and re-run (back to **Step 2**)
- **User wants to adjust bin ranges or signals** → edit the report files and re-run

## Edge Cases

- If `databricks bundle run` times out, the job may still be running on the cluster. Use `databricks jobs get-run` to check.
- If the user wants to re-run without re-deploying, use `databricks bundle run` directly (skip `deploy`).
- If multiple vehicles are configured, gold layer validation should check results per vehicle.
- If the report uses `global_report_table` and `channel_mapping`, table existence checks must account for the mapping structure.

## Related Skills

- [create-report](../create-report/) — scaffold a new report
- [configure-report](../configure-report/) — set up data sources and vehicles
- [define-channels](../define-channels/) — define signal aliases
- [create-histogram-1d](../create-histogram-1d/) — add histogram visualizations
- [databricks-jobs](../databricks-jobs/) — general Databricks Jobs management
