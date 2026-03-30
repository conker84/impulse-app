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

### Generated Assets & Transparency

- [ ] **Generate real assets and link them in app** — After deployment, show/link the actual notebooks, configs, and job runs produced (not just status), maybe separate assets tab
- [ ] **View produced notebooks** — Let users browse the generated signal definitions, histogram pages, orchestrator, and config JSON directly in the UI
- [ ] **Jobs are deployed as bundles** — Already true, but the UI should surface the bundle structure and let users navigate to workspace artifacts

### UX & Wizard Flow

- [ ] **Every step should have a skill** — Currently 5 skills exist but they don't cover every wizard step equally. The `visualize-histogram-1d` skill has a SKILL.md but no references.
- [ ] **Step-level manual controls** — Each step should offer both NL chat and manual UI controls (forms, dropdowns, tables) as parallel input methods
- [ ] **Better step validation feedback** — Clearer messaging when a step is incomplete
- [ ] **Complex asks should be working** — "I would like to perform an air temperature analysis during highway drives at high RPM operating bands. Show me all relevant channels for this analysis" in chat to select the right channels. Core feature request: engineers know something is wrong but currently hand-write Excel specs for data engineers to implement. The app should explore data based on engineer input and recommend what to analyze. Given a problem description ("engine vibration at high RPM"), suggest relevant signals, appropriate histogram bins, and useful aggregations automatically
- [ ] **Report save and resume** — can and should reports be savable at any point not just after final job kick off

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
- [ ] **Ingest jobs run as SP, require manual UC grants** — The `X-Forwarded-Access-Token` is a delegated token that still identifies as the app SP, so `jobs.create()` always creates jobs owned by the SP. This means the SP needs explicit UC grants (`USE CATALOG`, `ALL PRIVILEGES ON SCHEMA`) on whatever catalog/schema users choose for their Silver layer. This won't scale. **Also:** the SP needs CAN_READ on the `ingest/` workspace directory to access notebook tasks — this permission can get lost when `databricks sync` recreates the directory tree. Currently granted manually; should be automated in the deploy script or use user token for job creation instead.
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
- [ ] **Multi user scale** — Settings, dynamic values, jobs etc should all work with multi simultanious users

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
