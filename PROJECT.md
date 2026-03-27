# Impulse (impulse-app)

## What It Does

A full-stack Databricks App that lets users create Impulse data reports through a **natural language chat interface**. Instead of manually writing signal definitions, histogram configs, and config JSONs, users describe what they want in plain English and an LLM agent builds the report step by step.

The app guides users through a 5-step wizard:
1. **Report Name** — Set name, description, creator
2. **Channels** — Define physical & virtual signals (via chat + alias search)
3. **Aggregations** — Define 1D histograms with bin edges
4. **Vehicles** — Select test objects & time ranges
5. **Ready** — Review generated code, deploy as Databricks job, validate results

Once complete, it scaffolds a full DAB (Databricks Asset Bundle) project, deploys it as a job, monitors execution, and validates the Gold-layer output.

---

## Architecture

```
React Frontend (TypeScript + Vite)
        ↓ REST API
FastAPI Backend (Python)
        ↓           ↓           ↓
   LLM Agent    Lakebase DB    Databricks APIs
   (Claude Haiku   (PostgreSQL)   (Jobs, SQL,
    via FMAPI)                     UC, MCP)
```

### Backend (`/server`)

| File | Responsibility |
|------|----------------|
| `agent.py` | LLM agent loop — 8 custom tools + ~20 MCP tools, max 8 rounds per turn |
| `config.py` | Auth detection (App vs Local mode), env vars, workspace client factory |
| `models.py` | Pydantic models: `ReportState`, `SignalDefinition`, `HistogramDefinition`, `VehicleConfig` |
| `db.py` | Lakebase PostgreSQL connection & schema init |
| `token_store.py` | Encrypted PAT + cluster ID persistence (Fernet encryption) |
| `report_store.py` | Save/load/delete report definitions (JSONB in Lakebase) |
| `skill_loader.py` | Load skill index & full SKILL.md docs for system prompt composition |
| `code_generator.py` | Generate signal defs, histogram pages, orchestrator, config JSON from ReportState |
| `mcp_tools.py` | MCP server integration — tool discovery, SQL execution, stdio vs managed modes |

### Routes (`/server/routes`)

| File | Key Endpoints |
|------|---------------|
| `chat.py` | `POST /api/chat` — main agent loop |
| `state.py` | `/api/state/*`, `/api/advance-step/*`, candidate selection, vehicle management |
| `deploy.py` | `/api/scaffold/*`, `/api/deploy/*`, `/api/deploy/status/*` — scaffold, deploy, monitor |
| `validate.py` | `POST /api/validate/*` — 3-level Gold-layer validation |
| `visualize.py` | `/api/visualize/*` — histogram data queries with filters |
| `reports.py` | `/api/reports/*` — CRUD for saved reports |
| `settings.py` | `/api/settings/*` — PAT & cluster config |

### Frontend (`/frontend/src`)

| File | Responsibility |
|------|----------------|
| `App.tsx` | Main component — view routing (landing/editor/visualize), state management, polling |
| `api.ts` | REST client wrapping all backend endpoints |
| `types.ts` | TypeScript interfaces matching Pydantic models |
| `components/ChatPanel.tsx` | Chat input + message history |
| `components/PreviewPanel.tsx` | Right panel with tabs: signals, histograms, code preview, results, settings |
| `components/LandingScreen.tsx` | New / load / visualize report entry points |
| `components/VisualizeView.tsx` | Interactive Plotly histogram viewer with filters |
| `components/HistogramBuilder.tsx` | Form-based histogram creation |
| `components/ConfigTab.tsx` | Config JSON preview |
| `components/SignalsTab.tsx` | Signal candidate selection |
| `components/ResultsTab.tsx` | Deployment status + validation results |
| `components/SettingsModal.tsx` | PAT + cluster configuration (app mode only) |

### Skills (`/skills`)

Domain-specific knowledge loaded into the agent's system prompt:

| Skill | Purpose |
|-------|---------|
| `create-report` | DAB scaffold procedure |
| `configure-report` | Config JSON sections (data sources, vehicles, query solver) |
| `define-channels` | Physical alias lookup + virtual signal expressions |
| `create-histogram-1d` | 4 histogram types, bin definitions, parameter collection |
| `validate-report-execution` | Deploy, monitor, error diagnosis, Gold-layer validation |

Each skill has a `SKILL.md` and optional `references/` directory with API docs.

### Template (`/.template`)

Databricks Asset Bundle template scaffolded via `databricks bundle init`. Contains notebook templates, job definitions, config files, and CI/CD config. Files stored as `.txt` to avoid auto-conversion.

---

## Agent Design

- **Model:** Claude Haiku 4.5 via Databricks Foundation Model API (OpenAI-compatible)
- **8 Custom Tools:** `add_physical_signal`, `add_virtual_signal`, `suggest_signal_candidates`, `add_histogram`, `set_report_metadata`, `set_vehicle`, `set_data_sources`, `preview_code`, `load_skill`
- **~20 MCP Tools:** `execute_sql` (primary), UC browsing (`list_catalogs`, `list_schemas`, etc.), schema inspection
- **Max 8 tool rounds** per user turn to prevent infinite loops
- **Step-gated:** Tools only work in appropriate wizard steps
- **Auto-candidate fallback:** If LLM queries SQL but forgets to suggest candidates, backend auto-extracts aliases from results

---

## Deployment Flow

1. **Scaffold** — `databricks bundle init` with generated config → creates report directory
2. **Code inject** — Overwrites template files with generated signals, histograms, config JSON
3. **Deploy** — `databricks bundle deploy -t dev` + run (background thread)
4. **Monitor** — Frontend polls `/api/deploy/status` every 30s
5. **Validate** — 3-level Gold-layer check: table existence → row counts → histogram values

---

## Two Runtime Modes

### Local Development
- Auth via `~/.databrickscfg` profile (env var `DATABRICKS_PROFILE`)
- No Lakebase, no PAT storage, no settings UI
- MCP via stdio subprocess
- Sessions are in-memory only

### Deployed as Databricks App
- Service principal for system ops + user tokens for SQL
- Lakebase PostgreSQL for persistence (reports, PATs, settings)
- MCP via managed DBSQL server
- User identified via `X-Forwarded-Email` header
- PATs encrypted with Fernet (key in Databricks Secrets)

---

## Database Schema (Lakebase)

```sql
-- Per-user settings (PAT + cluster)
user_settings (user_email PK, encrypted_pat, cluster_id, updated_at)

-- Saved report definitions
saved_reports (id UUID PK, user_email, report_name, report_state JSONB, created_at, updated_at)
  UNIQUE(user_email, report_name)
```

---

## Code Generation Output

The app generates 4 files from `ReportState`:
1. **`01_signal_definitions.py`** — Physical channels (alias lookup) + virtual signals (expressions)
2. **Histogram page(s)** — `HistogramDuration`, `HistogramDistance`, etc. with bin definitions
3. **`02_report.ipynb`** — Orchestrator notebook
4. **`dev_config.json`** — Full config: metadata, data sources, destination, query solver, vehicles

---

## Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABRICKS_WAREHOUSE_ID` | `724ba849cc0940aa` | SQL Warehouse for queries |
| `SERVING_ENDPOINT` | `databricks-claude-haiku-4-5` | LLM endpoint |
| `DATABRICKS_PROFILE` | `mb-dev` | CLI profile (local only) |
| `LAKEBASE_HOST` | — | Lakebase endpoint (app only) |
| `LAKEBASE_DB` | `impulse` | Lakebase database name |
| `SECRET_SCOPE` | `impulse` | Databricks secret scope |
| `SKILLS_ROOT` | `./skills` | Skills directory |
| `TEMPLATE_ROOT` | `./.template` | Template directory |
| `NAMEDA_ROOT` | `./reports` | Output directory for scaffolded reports |

---

## Dependencies

**Python:** FastAPI, uvicorn, databricks-sdk, pydantic, openai, jinja2, databricks-mcp, psycopg, cryptography

**Node.js:** React 19, react-markdown, react-plotly.js, plotly.js, lucide-react, Vite 6, TypeScript 5.6

---

## Known Limitations

1. **PAT storage is a workaround** — Databricks Apps don't yet support OAuth scopes for job deployment; will be removed once available
2. **In-memory sessions** — Lost on server restart; only Lakebase-saved reports persist
3. **Max 8 tool rounds** — Agent caps at 8 tool-calling iterations per user message
4. **MCP whitelist** — Only ~20 of ~40 MCP tools exposed to fit LLM's 32-tool limit

---

## TODO

> Based on code analysis + Thomas's feedback session (2026-03-23)

### Pre-Work: Cleanup & Local Dev Setup (do first)

- [x] **Extract hardcoded Mercedes values to config** — Scaffold config in `deploy.py` now reads from env vars (`DAB_DEV_HOST`, `DAB_STG_HOST`, etc.) with workspace host as default. No more hardcoded customer URLs/groups/SP IDs.
- [x] **Fix local MCP paths** — `mcp_tools.py` now auto-discovers `databricks-mcp-server` from the project venv. Falls back to PATH, then env vars (`LOCAL_MCP_CMD`). Also passes resolved `DATABRICKS_HOST`/`DATABRICKS_TOKEN` instead of profile name (which the MCP server doesn't support).
- [x] **Replace `mb-dev` profile default** — Centralized to `DATABRICKS_PROFILE` constant in `config.py` (default: `fe-vm-maximhammer`). All references in `deploy.py`, `mcp_tools.py`, skills updated. Added `databricks-mcp-server` to `requirements.txt`.
- [x] **Update template defaults** — `.template/databricks_template_schema.json` defaults cleared to generic values (`users` group, empty hosts).
- [x] **Get local mode running** — Smoke tested: app starts, LLM agent responds via FMAPI, MCP discovers 5 tools, wizard step tracking works, `set_report_metadata` tool executes correctly.
- [x] **Update CLAUDE.md and PROJECT.md** — CLAUDE.md rewritten to be actionable instructions only. Profile/tooling/gotchas documented.

### Rebrand: MDA → Impulse

All references to "MDA", "MDA Report Studio", "NL Report Creator", and "nl-report-creator" have been renamed to **Impulse** across the codebase.

**Code & config:** all done
- [x] `app.py` — FastAPI title → "Impulse", root message → "Impulse API"
- [x] `server/agent.py` — docstrings → "Impulse reports", "Impulse skill steps"
- [x] `server/models.py` — module docstring → "Impulse report state"
- [x] `server/code_generator.py` — docstring → "Impulse report code", comments → "Auto-generated by Impulse"
- [x] `server/db.py` — Lakebase project default → `pulse`, DB default → `pulse`
- [x] `server/token_store.py` — secret scope default → `pulse`
- [x] `server/skill_loader.py` — system prompt → "Impulse report builder", "Impulse skills"
- [x] `server/routes/deploy.py` — env var → `PULSE_FRAMEWORK_VERSION`
- [x] `app.yaml` — Lakebase DB → `pulse`, project → `pulse`, secret scope → `pulse`
- [x] `.template/databricks_template_schema.json` — description → "Impulse framework"

**Frontend:** all done
- [x] `frontend/package.json` — name → `pulse`
- [x] `frontend/src/components/LandingScreen.tsx` — title → "Impulse", subtitle updated
- [x] `frontend/src/components/ChatPanel.tsx` — header → "Impulse"

**Skills:** all done — all SKILL.md, README.md, and reference docs updated across all 6 skill directories

**Documentation:**
- [x] `PROJECT.md` — title → "Impulse (impulse-app)"
- [x] `CLAUDE.md` — title → "Impulse", naming section added, related project updated
- [x] `README.md` — All references updated to Impulse, profile placeholders

> **Note:** Infra names (Lakebase project, secret scope, Databricks app name) will need to be recreated when deploying to FEVM. Code defaults are now `impulse` but existing infra on the original workspace still uses old names.

### Externalize Customer-Specific Config

Hardcoded Mercedes/YARP-specific values (catalog paths, alias tables, mapping tables, destination schemas, permission groups, Azure storage paths) are still scattered across `server/agent.py`, `server/routes/state.py`, `server/skill_loader.py`, skill reference docs, and `.template/` config files. These need to be extracted into a single `config.yaml` so each deployment can provide its own values.

**Config approach:** No server-side config files. All environment-specific values (Silver layer location, destination) are collected from the user during the wizard flow and persisted in Lakebase per-user. The Source Data step collects `silver_catalog`/`silver_schema`, which auto-populates destination defaults. Optional Mercedes-specific extensions (alias tables, mapping tables) available via env vars (`IMPULSE_MAPPING_TABLE`) for backward compat.

**Remove hardcoded values from code:** all done
- [x] `server/agent.py` — `_DS_DEFAULTS` replaced with `_get_ds_defaults()` reading from `app_config`. Tool descriptions say "from config.yaml".
- [x] `server/routes/state.py` — `_MAPPING_TABLE` replaced with `_get_mapping_table()`. `_auto_resolve_data_sources` reads all defaults from config.
- [x] `server/routes/visualize.py` — Same mapping table fix.
- [x] `server/skill_loader.py` — Alias table in system prompt reads from config, with fallback message if not configured.
- [x] `server/config.py` — `NAMEDA_ROOT` renamed to `REPORTS_ROOT`, fallback path changed from `nameda` to `reports`.

**Clean up templates:** all done
- [x] `dev_config.json.tmpl` — Cleared customer catalog/schema/creator/source_code.
- [x] `prd_config.json.tmpl` — Removed Mercedes git URLs, YARP team, access_groups, managed_location.
- [x] `stg_config.json.tmpl` — Removed customer catalog/schema/access_groups.
- [x] `jobs.yml.tmpl` — Removed `UseCaseId: "2024006"`.
- [x] `databricks.yml.tmpl` — Removed `policy_id`, customer `UseCaseId` tags. Replaced with generic cluster config.
- [x] `azure-pipelines.yaml.tmpl` — Replaced `2024006_NAMEDA_*` variable groups with `<stg_variable_group>`/`<prd_variable_group>` placeholders.
- [x] `mda_framework_version.json.tmpl` — Cleared Daimler PyPI URI and Azure Artifacts scope.
- [x] `00_setup.py.txt` — Replaced `tbonfer@emea.corpdir.net` paths with `<your-user>` placeholders.

**Clean up skill reference docs:** all done
- [x] All `westeurope_extollo_*` table paths replaced with `<aliases_table>`, `<device_aliases_table>`, `<container_metrics_table>`, `<channel_metrics_table>`, `<channels_table>`, `<destination_catalog>`, `<destination_schema>` across all SKILL.md, README.md, and references/*.md files.

**Wire Source Data step to downstream defaults:**
- [x] When user picks "Existing Silver Tables", their `silver_catalog`/`silver_schema` auto-populates destination catalog/schema in `_auto_resolve_data_sources`.

### Infrastructure & Deployment

- [x] **Set up Lakebase infra in FEVM** — Provisioned: Lakebase project `impulse`, database `impulse`, PG role for app SP, secret scope `impulse` with Fernet key, SP permissions on catalog/schema/volume/warehouse.
  - Lakebase host: `ep-bold-truth-d7c3zwwa.database.eu-central-1.cloud.databricks.com`
  - Lakebase project: `impulse`, branch: `production`, endpoint: `primary`
  - Secret scope: `impulse`, key: `fernet-key`
  - App SP client ID: `b4686f0c-6836-4e0e-9944-f427aeae072b` (SP ID: `70800910416960`)
  - SP entitlements: `workspace-access`, `databricks-sql-access`, `allow-cluster-create`
  - SP has CAN_READ on `/Users/maxim.hammer@databricks.com/impulse-app` workspace folder (needed for ingest job notebooks)
- [x] **Update `app.yaml` for FEVM** — Warehouse `e0458b451165d343` (Serverless Starter), serving endpoint `databricks-claude-haiku-4-5`, Lakebase host updated, secret scope `impulse`.
- [x] **Create UC resources** — Schema `maximhammer_catalog.impulse`, Volume `maximhammer_catalog.impulse.mf4_uploads` (managed). SP has USE_CATALOG, USE_SCHEMA, CREATE_TABLE, CREATE_VOLUME, READ_VOLUME, WRITE_VOLUME.
- [x] **Deploy Impulse app** — App name: `impulse`, URL: `https://impulse-7474650020296832.aws.databricksapps.com`. Source synced to `/Workspace/Users/maxim.hammer@databricks.com/impulse-app`. Deploy command: `databricks apps deploy impulse --source-code-path /Workspace/Users/maxim.hammer@databricks.com/impulse-app --profile fe-vm-maximhammer`

### Data Ingestion & Source Management

- [x] **Source data step (upload or map)** — Added `SOURCE_DATA` as the first wizard step with two modes: "Upload Raw Files" or "Existing Silver Tables". Backend models (`SourceDataConfig`, `SourceDataMode`), endpoints (`/api/set-source-data`, `/api/upload-files`), frontend component (`SourceDataStep`), and step validation all implemented.
- [x] **Manual file upload option** — File picker UI accepts MF4 files only (CSV/Parquet removed from scope). Users configure a UC Volume location (catalog/schema/volume) then upload MF4 files which are streamed to the Volume via Databricks SDK.
- [x] **Source Data as First step in Flow** — `WizardStep` enum now starts with `SOURCE_DATA`. Default state begins there. Step numbering updated across ChatPanel hints, PreviewPanel, and wizard step bar.
- [x] **Move uploads to UC Volume** — Implemented via `POST /api/upload-mf4/{session_id}` endpoint. Users specify catalog, schema, and volume name in the UI. Files are uploaded as multipart form data and streamed to `/Volumes/<catalog>/<schema>/<volume>/` using `WorkspaceClient.files.upload()`. Works in both local dev mode (profile auth) and deployed mode (user token or service principal).
- [x] **Dynamic catalog/schema dropdowns** — Source Data step uses cascading dropdowns that list available UC catalogs and schemas (via `/api/uc/catalogs` and `/api/uc/schemas`). Applies to both upload mode (volume location) and existing Silver tables mode. Also lists volumes for upload mode via `/api/uc/volumes`.
- [x] **Trigger ingest process on upload** — Integrated Jonathan's `timeseries_ingest_solution_accelerator` as a standalone Databricks job. After uploading MF4 files, users pick a Silver destination (catalog/schema) and click "Transform to Silver Layer". The app submits a one-time job run (`w.jobs.submit()`) with the full ingest task graph (detect → batch → MDF-to-Delta → RLE Silver → metadata). Progress is polled and displayed with a step-by-step tracker. On success, silver_catalog/silver_schema auto-populate and user can proceed.
  - Backend: `server/routes/ingest.py` (`POST /api/ingest/trigger`, `GET /api/ingest/status`)
  - Notebooks: `ingest/ingest_mdf/` (copied from Jonathan's repo, plus `a_setup_tables.py` for idempotent table creation)
  - Frontend: Redesigned `SourceDataStep` with 2-phase upload flow (upload → transform → done)
- [x] **Reuse Jonathan's ingest solution accelerator** — `github.com/jonathanb-db/timeseries_ingest_solution_accelerator` evaluated and integrated as Option A (standalone job). Notebooks copied to `ingest/` directory and deployed with the app. Produces all 5 Silver tables: channels, channel_tags, channel_metrics, container_tags, container_metrics.
  - **Known issue (fixed):** `asammdf==8.7.2` pulls `numpy>=2.4` which is ABI-incompatible with DBR 15.4's pre-installed pyarrow (compiled against NumPy 1.x). This crashes the Python kernel at startup (`_ARRAY_API not found`), surfaced as the misleading "Could not reach driver" error. Fix: `%pip install 'numpy<2' asammdf==8.7.2 binpacking` added directly in the notebooks that need it (`c_mdf_to_delta.py`, `f_container_metadata.py`) followed by `dbutils.library.restartPython()`. No task-level libraries or init scripts — fully self-contained and portable.
  - **SP identity:** `X-Forwarded-Access-Token` is a delegated token — API calls still identify as the SP, not the user. Jobs always run as the SP. `run_as` cannot be used because the SP is non-admin. The SP needs explicit UC grants on the target catalog/schema. See Technical Debt for the long-term fix (use stored user PAT instead).
  - **Job API:** Uses `jobs.create()` + `jobs.run_now()` (not `jobs.submit()`) to enable shared job clusters and `run_as`.

### Channel / Signal Discovery

- [x] **Silver layer channel discovery (replaces alias-only search)** — Channels are now discovered directly from the silver layer tables produced by ingest (`channel_tags` + `channel_metrics`). The full channel catalog (name, unit, sample count, min/max/mean, sample rate) is auto-fetched via `GET /api/channel-catalog/{session_id}` when entering the Channels step and injected into the LLM context. The agent uses domain knowledge to match user requests (e.g. "engine speed") to actual channel names (e.g. `nmot` with unit `rpm`) — no alias table needed. Code generator now emits `query.channel(channel_name="...")` instead of the non-existent `query.channel_with_alias()`.
- [x] **Data sources auto-populated after ingest** — When ingest succeeds, `data_sources` is auto-filled with the known silver layer table paths (`bronze_channels`, `channel_tags`, `channel_metrics`, `container_tags`, `container_metrics`). No mapping table (`IMPULSE_MAPPING_TABLE`) needed for the upload flow.
- [x] **Manual API for adding channels** — `ChannelBrowser` component in the Channels step shows all available channels from the silver layer with a search filter, unit badges, and min/max value ranges. Users can browse, filter by name/unit, check channels, and add them directly — no chat interaction needed. Complements the LLM-assisted flow for users who know exactly which channels they want.

### DAB Template / Framework Alignment (BLOCKS END-TO-END DEPLOY)

The `.template/` directory scaffolds a Databricks Asset Bundle that runs the Impulse report as a job. The template notebooks (`00_setup`, `03_orchestrator`, histogram pages) import from `mda_reporting` and `mda_query_engine`. **These imports are written for an older version of the framework and are fundamentally incompatible with the current `mda_framework_v2` source.**

**Import path mismatches:**

| Template imports (old) | Current framework path | Status |
|---|---|---|
| `mda_reporting.core.chapter.Chapter` | — | **Doesn't exist** (no Chapter class in framework) |
| `mda_reporting.core.config.ReportConfig` | `mda_reporting.config.config_parser` | **Wrong path + class name** |
| `mda_reporting.visualizations.histogram.*` | `mda_reporting.aggregations.histogram.*` | **Wrong path** (`visualizations` → `aggregations`) |
| `mda_reporting.visualizations.histogram2d.*` | `mda_reporting.aggregations.histogram2d.*` | **Wrong path** |
| `mda_reporting.visualizations.histogram3d.*` | — | **Doesn't exist** |
| `mda_reporting.visualizations.xy_plot.*` | — | **Doesn't exist** |
| `mda_reporting.visualizations.visual_types.*` | — | **Doesn't exist** |
| `mda_reporting.persistence.unity_catalog.UnityCatalogSink` | `mda_reporting.persist.report_storage` | **Wrong path + possibly renamed** |

**What needs to happen:**

- [x] **Audit the framework API** — Read the current `mda_framework_v2/src/mda_reporting/` source to understand the actual class names, module paths, and constructor signatures. Map every template import to its current equivalent (or mark as removed).
- [x] **Update `00_setup.py.txt`** — Fix all import paths. Remove imports for classes that no longer exist. Chapter removed (Report.add_page directly). Histogram subclasses → single Histogram class with agg_type. Histogram3D, XYPlot, visual_types removed (don't exist in framework).
- [x] **Update `03_orchestrator.ipynb.txt`** — Fixed Report constructor (needs name+spark), fixed config access (MdaConfig fields), replaced non-existent mda_reporting.utils.report_utils imports, updated report_utils function signatures.
- [x] **Update code generator** (`server/code_generator.py`) — Histogram → single class with agg_type, Chapter removed, add_visualization→add_aggregation, config JSON restructured to MdaConfig format.
- [x] **Update histogram/visualization page templates** — Chapter removed, HistogramDuration→Histogram(agg_type="duration"), add_visualization→add_aggregation.
- [x] **Update `report_utils.py.txt`** — Replaced all non-existent UnityCatalogSink methods with direct Spark/Delta operations. Functions now take (catalog, schema, table_prefix) instead of sink object.
- [x] **Update config JSON templates** — Restructured from old format to MdaConfig-compatible (source, unity_sink, query_engine, units_under_test, measurement_dimensions).
- [x] **Update pre/post processing notebooks** — ReportConfig→MdaConfig, VisualFactNames/VisualDimensionNames→AggregationType/EventType enums, sink methods→report_utils functions.
- [x] **Update 02_report.ipynb.txt** — Report(name, spark, config_path), report.query (not db.query), persist_results() (not write_report()).
- [x] **Update skill docs and frontend** — channel_with_alias→channel(), HistogramDuration→Histogram, add_visualization→add_aggregation in CodePreviewTab.tsx.
- [ ] **Test end-to-end** — After all updates, scaffold a report, deploy, and verify the job runs successfully on a cluster with the framework installed.

### Aggregation Types

- [x] **Unify aggregation model as union type** — Refactored `ReportState` to use `aggregations: list[AggregationDefinition]` with discriminated union (`histogram_1d | histogram_2d | statistics`). `HistogramDefinition` → `Histogram1DDefinition` with `agg_kind` discriminator. `HistogramsTab` → `AggregationsTab`. All backend/frontend references migrated.
- [x] **Delete aggregations** — `DELETE /api/aggregation/{session_id}/{name}`, `remove_aggregation` agent tool, trash icon on each card in `AggregationsTab`.
- [x] **Edit aggregations** — `PUT /api/aggregation/{session_id}/{name}`, edit icon on each 1D histogram card pre-fills HistogramBuilder form, submit overwrites.
- [x] **Histogram2D support** — `Histogram2DDefinition` model (done in Phase 1), `add_histogram_2d` agent tool, `POST /api/add-histogram-2d` route, code gen producing `Histogram2D(x_expr=..., y_expr=..., x_bins=..., y_bins=...)`, `Histogram2DBuilder` UI with two signal dropdowns and bin inputs, 2D card in `AggregationsTab`.
  - Remaining: Skill docs (`create-histogram-2d/`), Plotly heatmap visualization for gold layer results.
- [ ] **Statistics aggregation support** — Different model shape: no bins, multiple signals, stat labels. Framework class `Statistics` already exists.
  1. Model: `StatisticsDefinition` with `agg_kind: Literal["statistics"]`, fields: `signal_refs: list[str]`, `stat_labels: list[str]` (from `["min", "max", "mean", "median", "std", "count"]`), `event_signal_ref`, `signal_names: list[str] | None`, `description`
  2. Agent: new `add_statistics` tool. Step-gated to `AGGREGATIONS`.
  3. Code gen: new branch mapping to `Statistics(selections=[...], aggregation_labels=[...], event=...)`
  4. Skill: new `create-statistics/` skill
  5. Frontend: new `StatisticsBuilder` form (multi-select signals, checkbox stat labels). Display in `AggregationsTab` as table-style card.

### Visualization

- [ ] **Time series viewer — standalone view** — New top-level view (like VisualizeView) accessible from the landing screen as "Explore Time Series". Queries the Silver layer `channels` table directly (RLE intervals: `tstart, tend, value`), not the gold layer report results. Uses server-side LTTB downsampling for large datasets.
  1. **Backend — signal listing endpoint:** `GET /api/timeseries/signals?catalog=X&schema=Y` — query `channel_tags` + `channel_metrics` to list available signals with metadata (name, unit, sample count, duration). Needs container selector first: `GET /api/timeseries/containers?catalog=X&schema=Y` queries `container_metrics` for available measurement files.
  2. **Backend — data endpoint:** `GET /api/timeseries/data?catalog=X&schema=Y&container_id=Z&channel_id=C&x_min=T1&x_max=T2&n_points=1500` — query `channels` table for the signal's RLE intervals, expand `(tstart, tend, value)` → `[(tstart, value), (tend, value)]` step pairs, apply LTTB downsampling via `tsdownsample` to ~1500 points, return JSON array of `{t, v}` pairs.
  3. **Frontend — `TimeSeriesView.tsx`:** Container picker (catalog/schema dropdowns reuse existing UC browser, then container dropdown from the listing endpoint) → signal multi-select → Plotly `scattergl` chart with multiple traces. `onRelayout` handler debounces zoom/pan events, calls data endpoint with new viewport bounds, updates traces.
  4. **Multi-signal support:** Multiple signals on same time axis. Dual y-axis when units differ (e.g., RPM left axis, km/h right axis). Each trace independently fetched and downsampled.
  5. **Dependency:** `tsdownsample` (pip, Rust-backed LTTB — ~5ms for 3M→1500 points). Add to `requirements.txt`.
  6. **RLE handling note:** Silver data is intervals, not raw samples. Expansion to step pairs doubles point count but preserves the actual signal shape (step function). Downsampling happens after expansion.
- [ ] **Time series viewer — wizard integration** — Make the time series viewer available during report building, so users can preview signals while in the Channels step.
  1. Add a "Preview Signal" button next to each signal in `SignalsTab`. Opens a mini time series chart in a side panel or modal.
  2. Reuses the same `/api/timeseries/data` endpoint. Container selection comes from the report's vehicle config (if vehicles step is done) or defaults to first available container.
  3. Helps users verify they picked the right signal before defining aggregations.
- [ ] **Histogram2D heatmap visualization** — Extend the Visualize view to render 2D histogram results. Tied to the Histogram2D aggregation type work.
  1. Backend: new query in `visualize.py` joining `histogram2d_fact` + `histogram2d_dimension`. Schema: `x_bin_id, y_bin_id, hist_value, x_lower_bound, x_upper_bound, y_lower_bound, y_upper_bound, x_bin_name, y_bin_name`.
  2. Frontend: new `Heatmap2DChart.tsx` using Plotly `heatmap` trace type. X/Y axes are bin labels, color intensity = duration-weighted value. Color scale with unit label.
  3. Sidebar: list 2D histograms alongside 1D in the histogram selector (distinguish with an icon or tag).
- [ ] **Statistics table visualization** — Extend the Visualize view to render statistics results. Tied to the Statistics aggregation type work.
  1. Backend: new query in `visualize.py` joining `stats_fact` + `stats_dimension`. Schema: `signal_name, aggregation_label, value, event_instance_id`.
  2. Frontend: new `StatisticsTable.tsx` — formatted table with signals as rows, stat labels as columns (min/max/mean/median). Group by event instance if multiple. No chart needed — this is tabular data.
  3. Sidebar: list statistics alongside histograms in the aggregation selector.
- [ ] **Chart styling & theme** — Improve visual quality of all chart types.
  1. Custom color palette (consistent across all chart types, works in dark and light themes).
  2. Plotly theme config: gridline colors, tick label colors, hover label styling all derived from CSS variables. Create a shared `plotlyTheme.ts` that all chart components import.
  3. Axis labels auto-populated from dimension metadata (unit, signal name).
- [ ] **Chart interactivity improvements** — Better UX for exploring results.
  1. Enable Plotly modebar selectively: download PNG/SVG, zoom, pan, reset. Currently `displayModeBar: false`.
  2. Richer hover tooltips: show bin range, absolute value, and percentage simultaneously.
  3. Stacked bar mode option for 1D histograms when grouping by vehicle (currently only grouped bars).
  4. Expand/fullscreen single chart (click to enlarge in a modal or full-width view).
- [ ] **Configurable chart layout** — Let users arrange the visualization dashboard.
  1. Grid size selector (1-column, 2-column, 3-column).
  2. Drag-to-reorder charts within the grid.
  3. Persist layout preference per report (in Lakebase or local storage).

### Generated Assets & Transparency

- [ ] **Generate real assets and link them in app** — After deployment, show/link the actual notebooks, configs, and job runs produced (not just status)
- [ ] **View produced notebooks** — Let users browse the generated signal definitions, histogram pages, orchestrator, and config JSON directly in the UI
- [ ] **Jobs are deployed as bundles** — Already true, but the UI should surface the bundle structure and let users navigate to workspace artifacts

### Session & Persistence

- [ ] **Session save & resume** — Report-building sessions should persist across server restarts (currently in-memory only). Lakebase `saved_reports` exists but only stores final state, not conversation history.
- [ ] **Conversation history persistence** — Save chat messages alongside report state so users can resume mid-conversation

### Smart Recommender (Mercedes Feedback)

- [ ] **Smart analysis recommender** — Core feature request: engineers know something is wrong but currently hand-write Excel specs for data engineers to implement. The app should explore data based on engineer input and recommend what to analyze.
- [ ] **Guided exploration mode** — Given a problem description ("engine vibration at high RPM"), suggest relevant signals, appropriate histogram bins, and useful aggregations automatically
- [ ] **Use demo data for development** — Build and test the recommender against existing demo measurement data

### UX & Wizard Flow

- [ ] **Every step should have a skill** — Currently 5 skills exist but they don't cover every wizard step equally. The `visualize-histogram-1d` skill has a SKILL.md but no references.
- [ ] **Step-level manual controls** — Each step should offer both NL chat and manual UI controls (forms, dropdowns, tables) as parallel input methods
- [ ] **Better step validation feedback** — Clearer messaging when a step is incomplete

### Update README

- [ ] **Ensure README reflects all updates** — Edit/add/remove changed content. Ensure users can run app following instructions.
- [ ] **Document `app.yaml` configuration** — Explain each env var in the README so others deploying to a different workspace know what to change (warehouse ID, Lakebase host, secret scope, serving endpoint). Link to Databricks Apps configuration docs.
- [ ] **Document Lakebase setup for new deployments** — Deployers need clear instructions:
  1. Create a Lakebase autoscaling project (e.g. `databricks postgres create-project impulse`)
  2. Create the `impulse` database inside the project (the default `postgres` DB has a restricted public schema — `CREATE DATABASE impulse;`)
  3. The app SP is auto-granted a postgres role on project creation, but needs `GRANT ALL PRIVILEGES ON DATABASE impulse TO "<sp-uuid>"` and schema-level grants
  4. Create a Fernet encryption key and store it in a Databricks secret scope (`SECRET_SCOPE` / `SECRET_KEY_NAME` env vars in `app.yaml`)
  5. Set `LAKEBASE_HOST`, `LAKEBASE_PORT`, `LAKEBASE_DB`, `LAKEBASE_PROJECT` in `app.yaml`
  6. On first startup, `init_schema()` auto-creates the `user_settings` and `saved_reports` tables
  - **Better:** automate all of this in a setup script or have the app auto-create the database and grants on first run, so deployers only need to create the Lakebase project and set env vars.
- [ ] **Document User Authorization setup** — `X-Forwarded-Access-Token` (needed for deploy-as-user) requires enabling User Authorization on the app via the Databricks UI (Configure → Add scopes). Without it, users must save a PAT in Settings. Document both paths clearly.

### Technical Debt

- [ ] **Inconsistent auth model** — MF4 upload, ingest jobs, and UC browsing all use the forwarded OAuth token or SP credentials (no PAT needed). But Deploy & Run shells out to `databricks bundle deploy` CLI which requires a stored PAT. This split is confusing — the settings modal asks for a PAT that's only needed for one flow. Align everything to use the same auth: either migrate deploy to SDK-based calls (no CLI subprocess) or find a way to pass the forwarded token to the CLI.
- [ ] **Ingest jobs run as SP, require manual UC grants** — The `X-Forwarded-Access-Token` is a delegated token that still identifies as the app SP, so `jobs.create()` always creates jobs owned by the SP. This means the SP needs explicit UC grants (`USE CATALOG`, `ALL PRIVILEGES ON SCHEMA`) on whatever catalog/schema users choose for their Silver layer. This won't scale.
  - **Proper fix: User Authorization + Submit Run.** Databricks Apps support "User Authorization" (Public Preview) which lets the app act with the logged-in user's actual identity, not the SP. Steps: (1) Enable User Authorization in the App config and add required scopes. (2) Databricks will forward a real user token (not SP-delegated). (3) Switch from `jobs.create()`+`run_now()` back to `jobs.submit()` — Submit Run executes as the API caller's identity, while Run Now always uses the job's static `run_as`. (4) With the user's real token + `jobs.submit()`, the run shows as the user in the UI, UC permissions are the user's own, and no SP grants are needed.
  - **Alternative (simpler):** Use the user's stored PAT (from the Settings modal) to create ingest jobs via `jobs.submit()`, so they run as the user.
- [ ] **Agent model upgrade** — Currently Claude Haiku. Consider Sonnet/Opus for better reasoning on complex virtual signal expressions and recommendations.
- [ ] **MCP tool whitelist expansion** — Only ~20 of ~40 tools exposed due to 32-tool LLM limit. Evaluate dynamic tool selection or tool grouping.
- [ ] **Jonathans Ingest notebook w MDA references** — Still lots of harcoded references and defaults to mda..
- [x] **Ingest Notebooks & Job runs library issues** — `asammdf==8.7.2` requires `numpy>=2` which is ABI-incompatible with DBR 15.4's pre-installed pyarrow/pandas (compiled against NumPy 1.x). The Python kernel crashes at startup with `_ARRAY_API not found`, surfaced as the misleading "Could not reach driver" error. **Fixed by downgrading to `asammdf<8`** which supports numpy 1.x. Libraries are installed as task-level `Library(pypi=...)` on the job — no `%pip install` in notebooks, no init scripts, fully portable. Lazy import kept in `utils.py` so notebooks that don't need asammdf don't trigger the import.
- [ ] **Jonathans Ingest notebook** Clean upp comments and unnecessary code from the copied notebooks
- [ ] **Package and distribute Impulse framework (BLOCKS CUSTOMER DEPLOYMENT)** — The `mda_query_engine` and `mda_reporting` packages (`mda_framework_v2` repo) were never published to any registry. The old `00_setup` template referenced `bseries`/`mda-reporting` on a non-existent private PyPI. Current workaround: wheel built locally and uploaded to a hardcoded UC Volume path (`/Volumes/maximhammer_catalog/impulse/mf4_uploads/mda_framework_v2-0.0.4-py3-none-any.whl`). **This does not work for any other workspace or customer.** Proper fix:
  1. Publish the wheel to **public PyPI** or a **GitHub Packages** registry accessible from any Databricks workspace
  2. Update `00_setup.py.txt` to `%pip install mda-framework-v2==<version>` from the public registry
  3. Remove the hardcoded Volume path fallback
  4. The `mda_framework_version.json` template should only need a `version` field — no secret scope/key/pypi_uri needed once published publicly
  5. Alternatively, if the package must stay private: make the Volume path configurable via an env var in `app.yaml` and document that deployers must upload the wheel to their own Volume
- [ ] **Cloud-agnostic cluster node types in DAB template** — `.template/` hardcodes `i3.xlarge` (AWS). This breaks on Azure (`Standard_E8_v3`) and GCP. Fix: detect the cloud provider at scaffold time (via workspace client or env) and select an appropriate node type, or use `node_type_id: ""` with `autoscale` which lets Databricks pick. Alternatively, make the node type a template variable so it can be set per-target in `databricks.yml`.
- [ ] **Report Gen & Ideally Ingest jobs should run on Serverless** — 

### Mercedes Compatibility Review

The original app was built for Mercedes/YARP and had customer-specific features wired deep into the code. These have been externalized to `config.yaml` (optional `extensions` section) but the code paths that use them need review to ensure they still work when configured.

- [x] **Alias lookup flow** — Default path now uses silver layer channel discovery (no alias table needed). Alias-based lookup is opt-in for customers with alias infrastructure — see Channel / Signal Discovery TODOs.
- [x] **Vehicle mapping flow** — Upload flow now discovers vehicles from `container_tags` (`vehicle_key`). `_auto_resolve_data_sources` skips the mapping table when not configured and uses `_auto_populate_silver_data_sources()` instead. Mapping table path still exists as a fallback when `IMPULSE_MAPPING_TABLE` env var is set.
- [ ] **Remove `IMPULSE_MAPPING_TABLE` env var** — This is a global server-side env var that makes no sense for a multi-tenant app. The mapping table concept (per-vehicle table paths, custom column names) is only relevant for the "existing Silver layer" source data mode. Refactor:
  1. Remove the `IMPULSE_MAPPING_TABLE` env var and `_get_mapping_table()` helper entirely.
  2. Move mapping table support into the **"Connect to existing Silver layer"** UI flow as an optional per-session config: user can provide a mapping table path, or manually specify data source table paths.
  3. Clean out all mapping table fallback code from `fetch_vehicle_candidates`, `_auto_resolve_data_sources`, and `select_vehicles`.
  4. The upload flow should have zero references to mapping tables — it's fully self-contained.
- [ ] **Visualize vehicle join** — `visualize.py` joins against the mapping table for vehicle metadata. Needs to work without it.
- [ ] **Test with original Mercedes config** — Create a `config.mercedes.yaml` with the original values to verify the app still works for Thomas's deployment. Don't commit it, but document the values needed.
