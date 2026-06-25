# Impulse — Databricks App

A full-stack web application for creating **Impulse framework** data reports through a guided, natural-language interface. Users describe their report requirements in plain English and the app scaffolds, deploys, and runs the report as a Databricks job. Report definitions are persisted in Lakebase so they can be loaded and re-deployed later.

The app reads silver-layer measurement data based on a **schema profile** (`profiles.yaml` at the repo root) that maps a customer's table and column names to the canonical names the wizard expects. Defaults match the upstream impulse-app silver-layer convention; per-customer overrides go in this single YAML file. The full field reference is in [Schema Profile](#schema-profile) below.

> **Deploy with:** `./install.sh` — see [INSTALL.md](INSTALL.md). The app name comes from `databricks.yml`'s `app_name` bundle variable (default `impulse-v3`); the CLI profile is whichever you're currently authenticated with.

**Stack:** FastAPI (Python) + React (TypeScript), hosted as a Databricks App.

## Architecture

```
React Frontend (TypeScript + Vite)
        ↓ REST API
FastAPI Backend (Python)
        ↓           ↓           ↓
   LLM Agent    Lakebase DB    Databricks APIs
   (Claude/GPT    (PostgreSQL)   (Jobs, SQL,
    via FMAPI)                    UC, MCP)
```

The app guides users through a **6-step wizard**:

1. **Source Data** — Select or ingest MDF4 measurement data
2. **Report Name** — Set name, description, creator
3. **Vehicles** — Select test objects and time ranges
4. **Channels** — Define physical and virtual signals (via chat + alias search)
5. **Aggregations** — Define 1D/2D histograms and statistics with bin edges
6. **Ready** — Review generated code, deploy as Databricks job, validate and visualize results

An LLM agent (configurable per-user from Foundation Model API endpoints) assists throughout — users can describe what they need in natural language and the agent calls tools to build the report incrementally.

### Time Series Explorer

Separate from the report wizard, the **"Explore Time Series"** feature (accessible from the landing screen) provides interactive visualization of massive time series datasets (100M–300M+ data points) from the Impulse silver layer.

**How it works:**

1. **Select** a catalog, schema, container, and one or more signals from the sidebar
2. **Load** — click "Load & Explore" to fetch channel data from the SQL Warehouse via `databricks-sql-connector` (Arrow-native). Data is loaded into server memory as Polars DataFrames. This is the slow step (~1–5 min for 300M rows depending on warehouse size)
3. **Explore** — the chart renders with a full-range overview. Drag to zoom into any region and the backend instantly re-aggregates using the LTTB algorithm (`tsdownsample`), selecting ~5,000 visually representative points from however many are in the window. Zoom/pan responses are <50ms regardless of dataset size
4. **Reset** — double-click to return to the full range

Multiple signals can be overlaid on one chart with automatic dual y-axis grouping by unit, with an optional `[0–1]` normalized view for comparing signals with different magnitudes. After the initial load all interactions (zoom, pan, signal toggling) are served from the in-memory Polars cache — no further SQL queries. LRU eviction manages memory when many channels are loaded. Tested with 300M+ data points on a Large (12 GB) app instance.

**Architecture:**

```
Browser (Plotly.js scatter + hv lines)
  │  POST /resample (~50ms)
  ▼
FastAPI (ts_cache.py: numpy arrays + LTTB)
  │  POST /load (once, via background thread)
  ▼
SQL Warehouse (databricks-sql-connector, Arrow batches)
  │
  ▼
Delta Lake (silver layer: channels table, RLE format)
```

### Key Directories

| Path | Description |
|------|-------------|
| `app.py` | FastAPI entry point, serves built frontend as static files |
| `server/` | Backend: agent, routes, config, database, code generation |
| `server/routes/` | API endpoint routers (chat, state, deploy, validate, visualize, etc.) |
| `server/agent.py` | LLM agent with tool-calling loop (step-gated tools) |
| `server/models.py` | Pydantic data models — source of truth for state shape |
| `server/config.py` | Auth + environment detection (App vs Local mode) |
| `server/db.py` | Lakebase (PostgreSQL) connection layer |
| `server/code_generator.py` | Generates signal defs, histograms, config JSON from report state |
| `server/mcp_tools.py` | MCP server integration for SQL and UC browsing |
| `server/ts_cache.py` | In-memory Polars cache + LTTB resample engine for time series |
| `server/ts_connector.py` | Direct SQL connector for Arrow-native time series data fetching |
| `frontend/src/` | React TypeScript source |
| `frontend/dist/` | Production build (served as static files) |
| `skills/` | Domain-specific knowledge loaded into the agent's system prompt |
| `ingest/` | MDF4-to-Silver ingest pipeline notebooks |
| `report_template/` | Runtime DAB template the app runs `bundle init` against to scaffold each user-defined report (Go template syntax). The framework is pulled at job-deploy time from `github.com/databrickslabs/impulse` via pip. |
| `databricks.yml` | Bundle definition — Lakebase instance, SQL warehouse, app + all bindings/permissions |
| `install.sh` | Customer install script — see [INSTALL.md](INSTALL.md) |

## Prerequisites (for development)

For customer install prereqs see [INSTALL.md](INSTALL.md). For local development:

1. **Databricks workspace** with Apps, Lakebase, and FMAPI enabled
2. **Databricks CLI** configured with a profile in `~/.databrickscfg`
3. **Python 3.12+** — managed via `uv`
4. **Node.js 18+** and npm (for frontend builds)

## Deploy to Databricks

See **[INSTALL.md](INSTALL.md)** for the customer-facing install guide. TL;DR:

```bash
cp profiles.yaml.example profiles.yaml   # only if your schema differs from defaults
databricks auth login --host https://<workspace>.cloud.databricks.com --profile <name>
./install.sh
```

`install.sh` runs `databricks bundle deploy` (which creates the Lakebase instance, SQL warehouse, app, and all bindings), then `databricks bundle run` to start the app. It issues **no** Unity Catalog grants — the app reads your silver-layer data as the logged-in user (OBO), so data access is governed by each end user's own UC permissions. Re-runs are idempotent.

### Resource names

The bundle creates everything with the name set by the `app_name` variable in `databricks.yml` (this repo's default is `impulse-v3`):

- App: `impulse-v3`
- Lakebase instance: `impulse-v3`
- SQL warehouse: `impulse-v3` (Medium, serverless, 10-min auto-stop)

App metadata lives in `databricks_postgres.impulse.*` inside the Lakebase instance (see `.claude/TASKS.md` follow-ups for why this shape).

## Run Locally

Local mode uses your Databricks CLI profile for authentication. No Lakebase, no settings UI — sessions are in-memory only.

```bash
# Install dependencies
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..

# Start the backend (also serves the built frontend)
python3 -m uvicorn app:app --reload --port 8001

# Optional: frontend hot reload in a separate terminal
cd frontend && npm run dev    # runs on :5173, proxies /api to :8001
```

Set `DATABRICKS_PROFILE` to override the CLI profile used.

## Testing

The backend has a pytest suite covering the deterministic business-logic modules
(models, schema profile/adapter, code generation, skill loading, time-series
cache). These tests need no Databricks workspace, network, or Lakebase.

```bash
# From the repo root, with the venv created above:
uv pip install --group dev          # installs pytest + pytest-cov
python -m pytest                    # run the suite

# With coverage for the tested modules:
python -m pytest --cov=server --cov-report=term-missing
```

Tests live in `tests/` and are excluded from bundle deploys via `.bundleignore`.
When adding a new pure-logic helper to `server/`, add a matching `tests/test_*.py`.
I/O glue (routes, `db.py`, `mcp_tools.py`, `agent.py`, `ts_connector.py`) is not
covered here — it requires a live workspace and is better exercised by integration
tests.

## Authentication & Permissions

### Identity Model

| Identity | Used for |
|----------|----------|
| **User OBO token** (forwarded via `X-Forwarded-Access-Token`) | SQL queries, UC browsing, MCP tools, file uploads, FMAPI inference |
| **App Service Principal** (auto-provisioned) | Lakebase read/write, MCP tool discovery, ingest + report-deploy job orchestration |

The app uses **User Authorization (OBO)** as the primary auth mechanism. When a user accesses the app, Databricks issues an OBO token forwarded via the `X-Forwarded-Access-Token` header — this token carries the user's identity and permissions for all data operations.

LLM inference (Foundation Model API) uses the user's OBO token via the `serving.serving-endpoints` scope (consent-flow fix shipped 2026-04-29). End users see their own usage in audit logs.

Jobs (MF4 ingest + report deploy) run as the app's service principal using its auto-injected OAuth client credentials (no PATs; the SP-as-orchestrator pattern). Triggering user identity is carried in job parameters / tags for audit.

### User Authorization Scopes

The app's `user_api_scopes` (set in `databricks.yml`):

```
sql, dashboards.genie, files.files, catalog.connections,
catalog.catalogs:read, catalog.schemas:read, catalog.tables:read,
serving.serving-endpoints
```

### Local Development Auth

When running locally, all operations use your `~/.databrickscfg` profile. No Lakebase, sessions are in-memory only.

## Impulse Framework

The app depends on the Impulse framework (PyPI name `databricks-impulse`, import path `impulse_reporting`) at https://github.com/databrickslabs/impulse. Each scaffolded report job's environment pulls the framework via pip directly from GitHub — no wheel binary is vendored in this repo.

**Framework version:** the scaffolded report jobs track upstream `main` (`@main` in `report_template/template/resources/jobs.yml.tmpl`). Each report deploy resolves to whatever's on impulse main at that moment. To freeze a specific report against a known framework version, edit the `@main` suffix on that report's own `resources/jobs.yml` post-scaffold.

## Schema Profile

The app's runtime data shape is described by `profiles.yaml` at the repo root. When the file is missing, the app falls back to a built-in default that matches the upstream impulse-app silver-layer convention. The schema is validated against `SchemaProfile` in `server/schema_profile.py`.

### How the profile is consumed

Two consumers, both at runtime:

1. **`SchemaAdapter`** (`server/schema_adapter.py`) — builds every wizard SQL string from the active profile. Result columns are projected to logical names (`container_id`, `channel_id`, `vehicle_key`, `channel_alias_name`, …) so downstream Python code doesn't change with the customer.
2. **`code_generator`** (`server/code_generator.py`) — emits the framework job's `report.py` and `dev_config.json`. Solver, data type, source-key name (`channels_table` vs `channels_uri`), `measurement_dimensions`, and the `query.channel(**kwargs)` map are all read from the profile.

### Field reference

The full source of truth is `server/schema_profile.py`. Every field has a default that produces the upstream impulse-app behavior, so a profile only needs to specify what diverges from the default.

#### Container metrics (one row per recording)

| Field | Default | Purpose |
|---|---|---|
| `container_table` | `container_metrics` | Table suffix; resolved against `<silver_catalog>.<silver_schema>` unless the value already contains a `.` |
| `container_id_col` | `container_id` | Column the wizard treats as the container's opaque identifier (string-typed downstream) |
| `container_start_col` | `start_dt` | Readable start timestamp |
| `container_stop_col` | `stop_dt` | Readable stop timestamp |

#### Channel metrics (one row per `(container, channel)`)

| Field | Default | Purpose |
|---|---|---|
| `channel_table` | `channel_metrics` | |
| `channel_container_id_col` | `container_id` | FK column joining back to the container table |
| `channel_id_col` | `channel_id` | Column uniquely identifying a channel within a container; treat as opaque string |
| `channel_name_col` | `channel_name` | Display name |
| `channel_secondary_id_col` | `null` | Optional secondary identifier column. Set this when the same `channel_name` can appear multiple times within a container, distinguished by some other column (e.g. source, device, bus). Used to disambiguate the unit-by-alias join when both this and `aliases_secondary_id_col` are set. |
| `channel_unit_col` | `null` | If set, unit comes from this column directly. If null, unit is sourced from a left-join to the aliases table (when available) |
| `channel_min_col` / `channel_max_col` / `channel_mean_col` | `min` / `max` / `mean` | |
| `channel_sample_count_col` | `sample_count` | |
| `channel_sample_rate_expr` | `sample_rate` | SQL expression; `null` means the wizard treats sample_rate as unknown |

#### Tags

Native key-value tag tables are optional. When `null`, the adapter synthesizes equivalent rows in CTEs from the container/channel tables plus the vehicle dimension config. When a physical table is set, the adapter normalizes its join column(s) to the canonical `container_id` / `channel_id` via the `*_id_col` fields below — so tables keyed by a different name (e.g. `recording_session_id`) work without renaming the underlying table.

| Field | Default | Purpose |
|---|---|---|
| `container_tags_table` | `container_tags` | Set to `null` to synthesize from `container_table` + `vehicle_*` |
| `container_tags_id_col` | `container_id` | Column in `container_tags_table` that joins to a container; aliased to `container_id` (e.g. set to `recording_session_id`). Used only when the table is set. |
| `channel_tags_table` | `channel_tags` | Set to `null` to synthesize from `channel_table` + aliases (for unit) |
| `channel_tags_container_id_col` | `container_id` | Column in `channel_tags_table` joining to a container; aliased to `container_id`. Used only when the table is set. |
| `channel_tags_channel_id_col` | `channel_id` | Column in `channel_tags_table` joining to a channel; aliased to `channel_id`. Used only when the table is set. |

#### Vehicle dimension

The wizard's Vehicles step shows a "vehicle_key" picker. Three modes:

| `vehicle_source` | What it does | Required fields |
|---|---|---|
| `tag` (default) | Reads `container_tags` rows where `key='vehicle_key'`. | Requires `container_tags_table` to be set. |
| `column` | Vehicle key is a column on the container table. | Set `vehicle_column`. |
| `constant` | Single static value for all containers. | Set `vehicle_constant`. |

#### Aliases (chat skill: friendly name → physical signal lookup)

When `aliases_table` is `null`, the chat skill's alias-search path is disabled (and the LLM falls back to enumerating the channel catalog directly).

The aliases table is expected to expose the physical channel-name column (and optional secondary-id column) under the **same names as `channel_metrics`** — i.e. `channel_name_col` and `channel_secondary_id_col`. If the underlying alias table uses different names, wrap it in a view that renames them.

| Field | Default | Purpose |
|---|---|---|
| `aliases_table` | `null` | Suffix or full path |
| `aliases_alias_col` | `channel_alias_name` | Friendly name column |
| `aliases_unit_col` | `unit` | |
| `aliases_description_col` | `description` | |

#### Time-series source (per-sample data)

| Field | Default | Purpose |
|---|---|---|
| `timeseries_table` | `channels` | Suffix or full path of the per-sample data table |
| `timeseries_time_col` | `tstart` | Column or SQL expression projected as the canonical timestamp (the TS Viewer cache reads `tstart`). For nanosecond-precision timestamps, use a column directly; for seconds-typed columns, multiply: `"CAST(time * 1e9 AS BIGINT)"`. |
| `timeseries_value_col` | `value` | Column or SQL expression projected as the canonical value. Use a cast when the source is string-typed: `"TRY_CAST(value_double AS DOUBLE)"`. |
| `timeseries_end_time_col` | `null` (sample-based) | Interval end-time column for RLE (step) data, projected as `tend`. Leave `null` for per-sample data; set a column to opt into step rendering. (The model default is `tend`, but customer profiles loaded from `profiles.yaml` default this to `null`.) |
| `timeseries_container_match_col` | `null` → `channel_container_id_col` | Column on the timeseries table matched against the requested `container_id`. Only set if it differs from the channel-metrics container column. |
| `timeseries_channel_match_expr` | `null` → `channel_id_col` | SQL expression on the timeseries table matched against the requested `channel_id`. Use a column for trivial cases; use an expression when the timeseries table keys differently from `channel_metrics` (e.g. `"concat_ws(':', split(signal_name, ':')[0], split(signal_name, ':')[2])"` for a 3-part signal_name → 2-part match). |

#### Duration histogram values

| Field | Default | Purpose |
|---|---|---|
| `duration_scale_to_seconds` | `1e9` | Divisor applied to duration-histogram values for display (converts to seconds). Default `1e9` (nanoseconds); `1e6` for microseconds, `1e3` for milliseconds, `1` for seconds. |

#### Framework / solver

| Field | Default | Purpose |
|---|---|---|
| `framework_solver` | `DeltaSolver` | |
| `framework_data_type` | `RLE` | |
| `framework_measurement_dimensions` | `["container_id", "vehicle_key", "start_ts", "stop_ts"]` | Columns the framework writes into the `measurement_dimension` gold-layer table |
| `framework_channel_time_col` | `timestamp` | RAW physical sample-time column the generated `query_engine.solver_config` maps to the canonical `timestamp` (for solvers like `KeyValueStoreSolver`). **Distinct from `timeseries_time_col`**, which is the *viewer's* projection and may be a SQL expression (e.g. `CAST(time * 1e9 AS BIGINT)`) — an expression can't be a `column_name_mapping` key, so the framework needs the raw column name here. Defaults to the canonical name, so no mapping is emitted unless it differs. |
| `framework_channel_value_col` | `value` | RAW physical sample-value column mapped to canonical `value` in `solver_config`. Same viewer/framework split as above vs. `timeseries_value_col`. |
| `channel_call_kwargs` | `{"channel_name": "channel_name"}` | Maps generated-code kwarg name → `SignalDefinition` field name. Default emits `query.channel(channel_name=sig.channel_name)`. Override to emit different kwargs (e.g. `{"signal": "signal", "network": "network"}` for solvers that take both). |

### Examples

Minimal override — only one column name differs:

```yaml
name: example
channel_name_col: alias_name
```

Customer with a different container key, no native tag tables, single-vehicle constant, custom aliases table, and a non-default solver:

```yaml
name: example_customer

container_id_col: recording_session_id
container_start_col: start_ts
container_stop_col: stop_ts

channel_container_id_col: recording_session_id
channel_id_col: signal_source
channel_name_col: signal
channel_secondary_id_col: source
channel_sample_rate_expr: "CAST(sample_count AS DOUBLE) / NULLIF(duration, 0)"

container_tags_table: null
channel_tags_table: null

vehicle_source: constant
vehicle_constant: my_demo

aliases_table: signal_lookup
aliases_alias_col: parameter

timeseries_table: signal_new

framework_solver: CustomSolver
framework_data_type: RAW
framework_measurement_dimensions:
  - container_id
  - start_ts
  - stop_ts

channel_call_kwargs:
  signal: signal
  network: network
```

Customer with physical key-value tag tables keyed by `recording_session_id` (vehicles come from real `key='vehicle_key'` rows). The `*_id_col` fields alias the join columns to the canonical names:

```yaml
name: example_physical_tags

container_id_col: recording_session_id
channel_container_id_col: recording_session_id
channel_id_col: signal_network

container_tags_table: container_tags
container_tags_id_col: recording_session_id

channel_tags_table: channel_tags
channel_tags_container_id_col: recording_session_id
channel_tags_channel_id_col: signal_network

vehicle_source: tag
```

## Troubleshooting

Most install-time errors are documented in **[INSTALL.md → Troubleshooting](INSTALL.md#troubleshooting)**. A few dev-specific ones:

**`401 User authorization token required`**
The app requires User Authorization scopes. Ensure scopes are set on the app (see `databricks.yml` `user_api_scopes`) and that the user has consented to the authorization prompt on first access.

**Bundle doesn't pick up changes**
`databricks bundle deploy` respects `.gitignore` AND `.bundleignore`. If your file isn't being uploaded, check both. `profiles.yaml` is gitignored (customer-local — copy from `profiles.yaml.example`); add it explicitly to `.bundleignore` overrides or `git add -f` if you want it in your fork's deploy.

**Lakebase schema out of date (missing columns)**
`CREATE TABLE IF NOT EXISTS` doesn't alter existing tables. `server/db.py` has idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements for known migrations; add to `_SCHEMA_SQL` when introducing new columns.
