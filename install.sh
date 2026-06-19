#!/usr/bin/env bash
#
# Impulse app — customer install.
#
# What this does:
#   1. Prompts (or reads from .install.config) for the workspace group that
#      should get access to the app + warehouse.
#   2. Runs `databricks bundle deploy` which creates: Lakebase instance, SQL
#      warehouse (Medium serverless, 10-min auto-stop), the app itself, all
#      bindings + grants for the app's service principal.
#   3. Note: the app reads your silver-layer data as the *logged-in user* (via
#      their OBO token), so the app's service principal needs no UC grants —
#      each end user's own UC permissions govern what they can query. The
#      catalog + schema holding the silver tables are chosen in the app UI at
#      runtime, so they are not collected here.
#
# Prerequisites — your workspace admin must have done:
#   - Databricks Apps enabled
#   - Lakebase enabled
#   - Serverless SQL warehouses enabled
#   - You're authenticated to the target workspace (`databricks auth login`)
#
# Local tools required on the machine running this script:
#   - Databricks CLI (>= 0.290)
#   - Node.js + npm (>= 18) — to build the React frontend
#   - Python 3
#
# Re-run safe: if you've installed before, this updates the existing deploy.
# Resource names are derived from `app_name` in databricks.yml (default
# `impulse-v3`).

set -euo pipefail

CHECK_ONLY=false
if [ "${1:-}" = "--check" ]; then
  CHECK_ONLY=true
  shift
fi

CONFIG_FILE=".install.config"

# Persisted values from a previous run, if any.
END_USER_GROUP="users"
# shellcheck disable=SC1090
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

# Allow overrides via env vars (useful for CI / non-interactive).
END_USER_GROUP="${IMPULSE_END_USER_GROUP:-$END_USER_GROUP}"

prompt() {
  local var="$1" desc="$2" current="${!1:-}"
  if [ -t 0 ]; then
    local def_msg=""
    [ -n "$current" ] && def_msg=" [$current]"
    read -r -p "  $desc$def_msg: " input
    eval "$var=\"\${input:-$current}\""
  fi
}

check() {
  local label="$1"
  shift
  printf "  %-48s " "$label"
  if "$@" >/dev/null 2>&1; then
    echo "OK"
    return 0
  else
    echo "FAIL"
    return 1
  fi
}

if [ "$CHECK_ONLY" = true ]; then
  echo "=== Workspace prereq check ==="
  failed=0
  check "auth (databricks current-user me)" \
    databricks current-user me || failed=$((failed+1))
  check "Apps API enabled" \
    databricks apps list || failed=$((failed+1))
  check "Lakebase API enabled" \
    databricks database list-database-instances || failed=$((failed+1))
  check "SQL warehouses API" \
    databricks warehouses list || failed=$((failed+1))
  check "Serving endpoints (FMAPI)" \
    databricks serving-endpoints list || failed=$((failed+1))
  check "npm installed (for frontend build)" \
    command -v npm || failed=$((failed+1))
  check "psql installed (for Lakebase role provisioning)" \
    command -v psql || failed=$((failed+1))
  echo ""
  if [ "$failed" -gt 0 ]; then
    echo "$failed check(s) failed. See INSTALL.md → Troubleshooting." >&2
    exit 1
  fi
  echo "All checks passed. Run ./install.sh without --check to deploy."
  exit 0
fi

echo "=== Customer values ==="
prompt END_USER_GROUP "Workspace group to grant app + warehouse access to"

[ -z "$END_USER_GROUP" ] && END_USER_GROUP="users"

# Persist for next run.
cat > "$CONFIG_FILE" <<EOF
END_USER_GROUP=$END_USER_GROUP
EOF

# Resolve app_name from databricks.yml. Plain regex to avoid a pyyaml
# dependency on the customer's local Python.
APP_NAME=$(python3 - <<'PY'
import re
text = open("databricks.yml").read()
m = re.search(r"app_name:\s*[^\n]*?\n\s+default:\s*(\S+)", text, re.S)
print(m.group(1).strip() if m else "impulse-v3")
PY
)
if [ -z "$APP_NAME" ]; then
  echo "ERROR: could not resolve app_name from databricks.yml" >&2
  exit 1
fi

echo ""
echo "=== Build frontend ==="
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm not found on PATH. Install Node.js (>=18) and re-run." >&2
  exit 1
fi
if [ ! -d "frontend/node_modules" ]; then
  echo "  Installing npm deps (one-time, ~30s)..."
  (cd frontend && npm install --silent)
fi
echo "  Building production bundle..."
(cd frontend && npm run build)

echo ""
echo "=== Bundle deploy ==="
echo "  app_name:       $APP_NAME"
echo "  end_user_group: $END_USER_GROUP"
echo ""

# DATABRICKS_BUNDLE_ENGINE=direct works around the bundled Terraform's expired
# GPG key (CLI bug; see TASKS.md). Drop this once the CLI ships a fixed key.
DATABRICKS_BUNDLE_ENGINE=direct databricks bundle deploy \
  --var end_user_group="$END_USER_GROUP"

# No post-deploy UC grants needed: the app reads silver-layer data exclusively
# via the logged-in user's OBO token (X-Forwarded-Access-Token; see
# server/mcp_tools.py:execute_sql, which has no service-principal fallback), so
# UC access is governed by each end user's own permissions — the app's service
# principal never queries the silver tables. This also means the *deploying*
# user needs no GRANT authority on the customer's catalog/schema. End users do
# still need USE CATALOG / USE SCHEMA / SELECT on the schema themselves — see the
# reminder printed at the end of this script.

echo ""
echo "=== Provision Lakebase role for the app's service principal ==="
# Lakebase is NOT bound as an app `database` resource (see databricks.yml): that
# bind makes the Apps control plane grant the app SP CONNECT/CREATE on the
# Postgres DB, which 403s for a non-admin deployer. We do it directly instead —
# the deploying identity created the instance, so it owns `databricks_postgres`
# (databricks_superuser) and can provision the app SP's role itself. The app
# (server/db.py) connects via the SDK with its own SP credential afterwards.
if ! command -v psql >/dev/null 2>&1; then
  echo "ERROR: psql not found on PATH. Install the PostgreSQL client and re-run." >&2
  exit 1
fi

APP_SP_CLIENT_ID=$(databricks apps get "$APP_NAME" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('service_principal_client_id',''))")
[ -z "$APP_SP_CLIENT_ID" ] && { echo "ERROR: could not resolve app service principal client id" >&2; exit 1; }

LAKEBASE_HOST=""
for _ in $(seq 1 40); do
  LAKEBASE_HOST=$(databricks database get-database-instance "$APP_NAME" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('read_write_dns','') or '')")
  [ -n "$LAKEBASE_HOST" ] && break
  sleep 15
done
[ -z "$LAKEBASE_HOST" ] && { echo "ERROR: Lakebase instance '$APP_NAME' has no read_write_dns yet" >&2; exit 1; }

PG_TOKEN=$(databricks database generate-database-credential \
  --json "{\"request_id\":\"$(uuidgen)\",\"instance_names\":[\"$APP_NAME\"]}" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
PG_USER=$(databricks current-user me -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('userName',''))")
[ -z "$PG_TOKEN" ] && { echo "ERROR: could not generate a Lakebase credential" >&2; exit 1; }

echo "  Granting app SP $APP_SP_CLIENT_ID CONNECT/CREATE on databricks_postgres..."
PGPASSWORD="$PG_TOKEN" psql \
  "host=$LAKEBASE_HOST port=5432 dbname=databricks_postgres user=$PG_USER sslmode=require" \
  -v ON_ERROR_STOP=1 -q <<SQL
CREATE EXTENSION IF NOT EXISTS databricks_auth;
SELECT databricks_create_role('$APP_SP_CLIENT_ID', 'SERVICE_PRINCIPAL');
GRANT CONNECT, CREATE ON DATABASE databricks_postgres TO "$APP_SP_CLIENT_ID";
SQL
echo "  Done — app SP can now connect to Lakebase."

echo ""
echo "=== Starting app ==="
# `bundle deploy` creates the app shell and uploads source; `bundle run`
# triggers an actual app deployment (= start compute + serve traffic). The
# command waits until the app reports "started successfully".
DATABRICKS_BUNDLE_ENGINE=direct databricks bundle run impulse_app \
  --var end_user_group="$END_USER_GROUP"

# Final summary.
APP_URL=$(databricks apps get "$APP_NAME" -o json \
  | python3 -c "import sys, json; print(json.load(sys.stdin).get('url', 'pending — check workspace UI'))")

echo ""
echo "=== Install complete ==="
echo "  App URL: $APP_URL"
echo ""
echo "Reminder — end users also need (one-time, by your workspace admin):"
echo "  - USE CATALOG / USE SCHEMA / SELECT on the catalog + schema that holds"
echo "    your silver-layer impulse tables (whichever you point the app at)"
echo "  - Membership in '$END_USER_GROUP' (the bundle already granted that group"
echo "    CAN_USE on the app + warehouse)"
