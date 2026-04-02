# Impulse — Databricks App

A full-stack web application for creating **Impulse framework** data reports through a guided, natural-language interface. Users describe their report requirements in plain English and the app scaffolds, deploys, and runs the report as a Databricks job. Report definitions are persisted in Lakebase so they can be loaded and re-deployed later.

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

### Step 1: Create the app (first time only)

```bash
databricks apps create impulse --profile <your-profile>
```

This provisions compute and a service principal for the app. Note the `service_principal_client_id` from the output — you'll need it for permissions.

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

Verify the environment variables match your workspace:

| Variable | Description |
|----------|-------------|
| `DATABRICKS_WAREHOUSE_ID` | Your SQL Warehouse ID |
| `SERVING_ENDPOINT` | Foundation Model API endpoint name |
| `LAKEBASE_HOST` | Endpoint host from `list-endpoints` output |
| `LAKEBASE_DB` | `impulse` |
| `LAKEBASE_PROJECT` | `impulse` |
| `SECRET_SCOPE` | Databricks secret scope for Fernet key (default `impulse`) |
| `SECRET_KEY_NAME` | Secret key name within the scope (default `fernet-key`) |
| `INGEST_NODE_TYPE` | Instance type for ingest job clusters (e.g. `i3.xlarge`) |

### Step 5: Grant service principal permissions

| Resource | Permission | How to grant |
|----------|-----------|--------------|
| SQL Warehouse | CAN USE | Warehouse permissions in workspace admin UI |
| Foundation Model API endpoint | CAN QUERY | Endpoint permissions in workspace admin UI |
| Lakebase database | OAuth role + ALL PRIVILEGES | See Step 2 |
| Secret scope `impulse` | READ | `databricks secrets put-acl` (see Step 3) |
| Unity Catalog tables | SELECT | `GRANT SELECT ON TABLE ... TO <sp-name>` |

### Step 6: Build and deploy

```bash
# Install dependencies
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..

# Deploy (uses databricks sync + apps deploy)
# Commit all changes first — databricks sync only syncs git-tracked files!
git add -A && git commit -m "deploy"
test/deploy-fevm.sh
```

The deploy script:
1. Builds the frontend (TypeScript + Vite)
2. Syncs source code to the workspace via `databricks sync`
3. Uploads the built frontend separately (it's `.gitignore`d)
4. Deploys the app via `databricks apps deploy`

Use `--skip-build` for backend-only changes, `--sync-only` for just syncing files.

The app URL will be shown in the output, e.g.: `https://impulse-<hash>.databricksapps.com`

### Redeployment (after code changes)

```bash
git add -A && git commit -m "update"
test/deploy-fevm.sh              # full rebuild
test/deploy-fevm.sh --skip-build # backend-only
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

> **Note:** Serving endpoint scopes (`serving.serving-endpoints`, `serving.serving-endpoints-data-plane`) are NOT included — they break the OAuth consent flow. FMAPI calls use the app service principal instead.

> **Important:** Scopes should be set when the app is first created. The deploy script (`test/deploy-fevm.sh`) handles this automatically.

To set scopes manually:
```bash
databricks apps update <app-name> --json '{"user_api_scopes":["sql","dashboards.genie","files.files","catalog.connections","catalog.catalogs:read","catalog.schemas:read","catalog.tables:read"]}'
```

### Local Development Auth

When running locally, all operations use your `~/.databrickscfg` profile. No Lakebase, no PAT storage, no settings UI.

## Impulse Framework

The app depends on the Impulse framework library which is developed in a separate repository. A pre-built wheel is bundled at `.template/template/lib/` and automatically included in every scaffolded report project.

**Updating the framework version:**

1. Build a new wheel in the framework repo: `uv build --wheel`
2. Replace the old `.whl` in `.template/template/lib/`
3. Update the wheel filename in `.template/template/resources/jobs.yml.tmpl`
4. Commit and redeploy

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse ID |
| `SERVING_ENDPOINT` | Default LLM endpoint (users can override in Settings) |
| `DATABRICKS_PROFILE` | CLI profile (local mode only) |
| `LAKEBASE_HOST` | Lakebase endpoint host (app mode only) |
| `LAKEBASE_PORT` | Lakebase port (default `5432`) |
| `LAKEBASE_DB` | Lakebase database name |
| `LAKEBASE_PROJECT` | Lakebase project name |
| `SECRET_SCOPE` | Databricks secret scope for Fernet key (default `impulse`) |
| `SECRET_KEY_NAME` | Secret key name within the scope (default `fernet-key`) |
| `INGEST_NODE_TYPE` | EC2 instance type for ingest job clusters |

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
