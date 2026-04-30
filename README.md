# Impulse — Databricks App

A full-stack web application for creating **Impulse framework** data reports through a guided, natural-language interface. Users describe their report requirements in plain English and the app scaffolds, deploys, and runs the report as a Databricks job. Report definitions are persisted in Lakebase so they can be loaded and re-deployed later.

The app reads silver-layer measurement data based on a **schema profile** (`profiles.yaml` at the repo root) that maps a customer's table and column names to the canonical names the wizard expects. Defaults match the upstream impulse-app silver-layer convention; per-customer overrides go in this single YAML file. The full field reference is in [Schema Profile](#schema-profile) below.

> **Deploy with:**
> ```bash
> test/deploy.sh [--skip-build]
> ```
> Both the deployed app name (`name:`) and the Databricks CLI profile (`profile:`) come from `app.yaml`. Edit `app.yaml` to retarget. `DATABRICKS_PROFILE=<other>` may be passed as a shell override; the script prints a loud warning and uses it instead, but never falls back to a default.

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
| `app.yaml` | Databricks App configuration (env vars, command) |
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
| `.template/` | DAB template for report scaffolding (Go template syntax) |

## Prerequisites

1. **Databricks workspace** with:
   - A SQL Warehouse
   - A Foundation Model API serving endpoint (e.g. `databricks-claude-sonnet-4-6`)
   - Unity Catalog tables for channel aliases and vehicle mapping

2. **Databricks CLI** configured with a profile in `~/.databrickscfg`

3. **Python 3.12+** — managed via `uv`

4. **Node.js 18+** and npm (for frontend builds)

## Deploy to Databricks

### Step 1: Create and deploy the app

First make sure `app.yaml`'s top-level `name:` and `profile:` fields point at the app and CLI profile you want to deploy with.

```bash
# First time: the deploy script auto-creates the app with OBO scopes
# Subsequent times: it just syncs and redeploys
git add -A && git commit -m "deploy"
test/deploy.sh
```

On first run, the script creates the app and provisions a service principal. After it finishes, capture the SP's client ID — you'll need it for Steps 2-4:

```bash
databricks apps get <app-name> --profile <your-profile> -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['service_principal_client_id'])"
```

Save this value; it's referenced as `<sp-client-id>` below.

### Step 2: Create Lakebase infrastructure (first time only)

```bash
# Create a Lakebase project (managed PostgreSQL)
databricks postgres create-project impulse \
  --json '{"spec": {"display_name": "Impulse"}}' \
  --no-wait -p <your-profile>

# Wait for endpoint to become ACTIVE (~1-2 min), then note the host
databricks postgres list-endpoints \
  projects/impulse/branches/production \
  -p <your-profile> -o json
```

Once the endpoint is active, create the database and set up the service principal's OAuth role. Connect as the project owner (your human user):

```python
import subprocess, json, psycopg

# Generate a short-lived OAuth token
result = subprocess.run(
    ["databricks", "postgres", "generate-database-credential",
     "projects/impulse/branches/production/endpoints/primary",
     "-o", "json", "--profile", "<your-profile>"],
    capture_output=True, text=True,
)
cred = json.loads(result.stdout)

# Connect to default database and create the app database
conn = psycopg.connect(
    host="<endpoint-host>", port=5432,
    dbname="databricks_postgres",
    user="<your-email>", password=cred["token"],
    sslmode="require", autocommit=True,
)
conn.cursor().execute("CREATE DATABASE impulse;")
conn.close()

# Reconnect to the new database and set up auth
conn = psycopg.connect(
    host="<endpoint-host>", port=5432,
    dbname="impulse",
    user="<your-email>", password=cred["token"],
    sslmode="require", autocommit=True,
)
cur = conn.cursor()
cur.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth;")
cur.execute("SELECT databricks_create_role('<sp-client-id>', 'SERVICE_PRINCIPAL');")
cur.execute('GRANT ALL PRIVILEGES ON DATABASE impulse TO "<sp-client-id>";')
cur.execute('GRANT ALL ON SCHEMA public TO "<sp-client-id>";')
conn.close()
```

> **Important:** You must use `databricks_create_role()` — plain `CREATE ROLE` does not support OAuth token authentication and will fail with `password authentication failed`.

The app automatically creates the required tables on first startup via `server/db.py`.

> **If recreating the app** (delete + create): the new service principal gets a new client ID. You must re-run `databricks_create_role()` and grants for the new SP. If tables already exist from the old SP, drop them first — the new SP cannot ALTER tables it doesn't own.

### Step 3: Create a secret scope for PAT encryption

```bash
databricks secrets create-scope impulse --profile <your-profile>

# Generate and store a Fernet encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
databricks secrets put-secret impulse fernet-key \
  --string-value "<generated-key>" --profile <your-profile>

# Grant the app's service principal READ access
databricks secrets put-acl impulse <sp-client-id> READ \
  --profile <your-profile>
```

### Step 4: Update `app.yaml`

`app.yaml` is the **single source of truth** for the deployed app. Edit:

- **`name:`** (top-level) — the app name on the workspace, e.g. `impulse-stla`. The deploy script reads this and derives the workspace path as `/Workspace/Users/<you>/<name>-app`.
- **`profile:`** (top-level) — the Databricks CLI profile to deploy with, matching a section in `~/.databrickscfg`. The script aborts if this is missing.
- **`env:`** — verify the variables match your workspace:

| Variable | Description |
|----------|-------------|
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse ID |
| `SERVING_ENDPOINT` | Default Foundation Model API endpoint used for chat. Users can switch to any endpoint listed in `AVAILABLE_MODELS` (`server/config.py`) from the Settings UI |
| `LAKEBASE_HOST` | Endpoint host from `list-endpoints` output |
| `LAKEBASE_PORT` | Lakebase port (default `5432` — rarely changed) |
| `LAKEBASE_DB` | Lakebase database name (e.g. `impulse`) |
| `LAKEBASE_PROJECT` | Lakebase project name (e.g. `impulse`) |
| `SECRET_SCOPE` | Databricks secret scope for the Fernet key (default `impulse`) |
| `SECRET_KEY_NAME` | Secret key name within the scope (default `fernet-key`) |
| `IMPULSE_FRAMEWORK_WHEEL_FILENAME` | Filename of the Impulse framework wheel bundled in `.template/template/lib/`. Bumping the wheel = drop the new file in `lib/` and update this value |
| `INGEST_NOTEBOOK_ROOT` | *(optional)* Override the workspace path for ingest notebooks. Default is derived from the deploying user + app name |

### Step 5: Grant permissions

**Service principal grants** (needed for the app to function):

| Resource | Permission | How to grant |
|----------|-----------|--------------|
| Lakebase database | OAuth role + `ALL PRIVILEGES` | See Step 2 |
| Secret scope (`SECRET_SCOPE`) | `READ` | `databricks secrets put-acl <scope> <sp-client-id> READ` |
| Foundation Model API endpoint | `CAN QUERY` *(only if not already inherited)* | Most workspaces grant `EXECUTE` on `system.ai.*` to all account users by default — in that case the SP gets implicit access. For workspaces that don't, or when using a custom (non-system) serving endpoint, grant explicitly via the AI Gateway / Serving page |

> SQL Warehouse and Unity Catalog permissions on the SP are **not needed** — those operations use the user's OBO token.

**End-user grants** (needed for each person using the app):

| Resource | Permission |
|----------|-----------|
| SQL Warehouse referenced by `DATABRICKS_WAREHOUSE_ID` | `CAN USE` |
| Unity Catalog tables read by the wizard (channel/container/aliases) | `SELECT` |
| Unity Catalog catalog/schemas being browsed | `USE CATALOG` / `USE SCHEMA` |
| The app itself | `CAN USE` (granted in the app's Permissions tab) |

### Step 6: Redeploy

After completing Steps 2-5, redeploy so the app picks up the Lakebase and secrets configuration:

```bash
test/deploy.sh --skip-build
```

The app URL will be shown in the output, e.g.: `https://impulse-<hash>.databricksapps.com`

Use `--skip-build` for backend-only changes, `--sync-only` for just syncing files.

### Redeployment (after code changes)

```bash
git add -A && git commit -m "update"
test/deploy.sh              # full rebuild
test/deploy.sh --skip-build # backend-only
```

## Run Locally

Local mode uses your Databricks CLI profile for authentication. No Lakebase, no PAT storage, no settings UI — sessions are in-memory only.

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

## Authentication & Permissions

### Identity Model

| Identity | Used for |
|----------|----------|
| **User OBO token** (automatic via User Authorization) | SQL queries, UC browsing, MCP tools, file uploads |
| **App Service Principal** (auto-provisioned) | LLM calls (FMAPI), Lakebase read/write, Fernet key retrieval, MCP tool discovery |
| **User's PAT** (entered in Settings UI) | Job deploy and job run only (ingest + report deploy) |

The app uses **User Authorization (OBO)** as the primary auth mechanism. When a user accesses the app, Databricks issues an OBO token that is forwarded via the `X-Forwarded-Access-Token` header. This token carries the user's identity and permissions for all data operations.

LLM inference (Foundation Model API) uses the app service principal because the serving endpoint scopes (`serving.serving-endpoints`, `serving.serving-endpoints-data-plane`) break the OAuth consent flow when set as `user_api_scopes`.

A PAT is only required for the two job operations (MF4 ingest and report deploy) because OBO tokens lack the `jobs` scope.

### User Authorization Scopes

The app requires these scopes (set at app creation time via the deploy script):

```
sql, dashboards.genie, files.files, catalog.connections,
catalog.catalogs:read, catalog.schemas:read, catalog.tables:read
```

Serving endpoint scopes (`serving.serving-endpoints`, `serving.serving-endpoints-data-plane`) are intentionally NOT included — they break the OAuth consent flow. FMAPI calls use the app service principal instead.

`test/deploy.sh` sets these scopes on every deploy (the `USER_API_SCOPES` constant near the top of the script is the source of truth).

### Local Development Auth

When running locally, all operations use your `~/.databrickscfg` profile. No Lakebase, no PAT storage, no settings UI.

## Impulse Framework

The app depends on the Impulse framework library which is developed in a separate repository. A pre-built wheel is bundled at `.template/template/lib/` and automatically included in every scaffolded report project.

**Updating the framework version:**

1. Build a new wheel in the framework repo: `uv build --wheel`
2. Drop the new `.whl` in `.template/template/lib/`
3. Update `IMPULSE_FRAMEWORK_WHEEL_FILENAME` in `app.yaml` to match the new filename
4. Commit and redeploy

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

Native key-value tag tables are optional. When `null`, the adapter synthesizes equivalent rows in CTEs from the container/channel tables plus the vehicle dimension config — so the wizard's hardcoded JOINs against `container_tags` / `channel_tags` continue to work.

| Field | Default | Purpose |
|---|---|---|
| `container_tags_table` | `container_tags` | Set to `null` to synthesize from `container_table` + `vehicle_*` |
| `channel_tags_table` | `channel_tags` | Set to `null` to synthesize from `channel_table` + aliases (for unit) |

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
| `timeseries_container_match_col` | `null` → `channel_container_id_col` | Column on the timeseries table matched against the requested `container_id`. Only set if it differs from the channel-metrics container column. |
| `timeseries_channel_match_expr` | `null` → `channel_id_col` | SQL expression on the timeseries table matched against the requested `channel_id`. Use a column for trivial cases; use an expression when the timeseries table keys differently from `channel_metrics` (e.g. `"concat_ws(':', split(signal_name, ':')[0], split(signal_name, ':')[2])"` for a 3-part signal_name → 2-part match). |

#### Framework / solver

| Field | Default | Purpose |
|---|---|---|
| `framework_solver` | `DeltaSolver` | |
| `framework_data_type` | `RLE` | |
| `framework_measurement_dimensions` | `["container_id", "vehicle_key", "start_ts", "stop_ts"]` | Columns the framework writes into the `measurement_dimension` gold-layer table |
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

## Troubleshooting

**`password authentication failed for user '<sp-client-id>'`**
The Lakebase Postgres role must be created with `databricks_create_role()`, not `CREATE ROLE`. See Step 2 above.

**`PermissionDenied: does not have READ permission on scope impulse`**
Grant the SP read access: `databricks secrets put-acl impulse <sp-client-id> READ`

**`401 User authorization token required`**
The app requires User Authorization scopes. Ensure scopes are set on the app (see above) and that the user has consented to the authorization prompt on first access.

**Deploy doesn't pick up changes**
`databricks sync` only syncs git-tracked files. Make sure to `git commit` before deploying.

**Lakebase schema out of date (missing columns)**
`CREATE TABLE IF NOT EXISTS` doesn't alter existing tables. Run `ALTER TABLE` manually against Lakebase to add missing columns, or drop and recreate the table.
