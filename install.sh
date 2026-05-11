#!/usr/bin/env bash
#
# Impulse app — customer install.
#
# What this does:
#   1. Prompts (or reads from .install.config) for UC catalog + schema where your
#      silver-layer data lives, and the workspace group that should get app access.
#   2. Runs `databricks bundle deploy` which creates: Lakebase instance, SQL
#      warehouse (Medium serverless, 10-min auto-stop), the app itself, all
#      bindings + grants for the app's service principal.
#   3. Grants the app's service principal USE CATALOG + USE SCHEMA + SELECT
#      on your silver-layer tables (current and future) via the bundle-created
#      warehouse.
#
# Prerequisites — your workspace admin must have done:
#   - Databricks Apps enabled
#   - Lakebase enabled
#   - Serverless SQL warehouses enabled
#   - You're authenticated to the target workspace (`databricks auth login`)
#   - You have CREATE permissions on the target catalog (or it pre-exists)
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
CATALOG=""
SCHEMA=""
END_USER_GROUP="users"
# shellcheck disable=SC1090
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

# Allow overrides via env vars (useful for CI / non-interactive).
CATALOG="${IMPULSE_CATALOG:-$CATALOG}"
SCHEMA="${IMPULSE_SCHEMA:-$SCHEMA}"
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
  if [ -n "$CATALOG" ]; then
    check "Target catalog exists: $CATALOG" \
      databricks catalogs get "$CATALOG" || failed=$((failed+1))
    if [ -n "$SCHEMA" ]; then
      check "Target schema exists: $CATALOG.$SCHEMA" \
        databricks schemas get "$CATALOG.$SCHEMA" || failed=$((failed+1))
    fi
  else
    echo "  (set IMPULSE_CATALOG to also probe the target catalog/schema)"
  fi
  echo ""
  if [ "$failed" -gt 0 ]; then
    echo "$failed check(s) failed. See INSTALL.md → Troubleshooting." >&2
    exit 1
  fi
  echo "All checks passed. Run ./install.sh without --check to deploy."
  exit 0
fi

echo "=== Customer values ==="
prompt CATALOG "Unity Catalog containing your silver-layer impulse tables"
prompt SCHEMA  "Schema within $CATALOG containing channel_metrics / container_metrics / channels"
prompt END_USER_GROUP "Workspace group to grant app + warehouse access to"

[ -z "$CATALOG" ] && { echo "ERROR: catalog required" >&2; exit 1; }
[ -z "$SCHEMA" ]  && { echo "ERROR: schema required" >&2; exit 1; }
[ -z "$END_USER_GROUP" ] && END_USER_GROUP="users"

# Persist for next run.
cat > "$CONFIG_FILE" <<EOF
CATALOG=$CATALOG
SCHEMA=$SCHEMA
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
echo "=== Bundle deploy ==="
echo "  app_name:       $APP_NAME"
echo "  catalog:        $CATALOG"
echo "  schema:         $SCHEMA"
echo "  end_user_group: $END_USER_GROUP"
echo ""

# DATABRICKS_BUNDLE_ENGINE=direct works around the bundled Terraform's expired
# GPG key (CLI bug; see TASKS.md). Drop this once the CLI ships a fixed key.
DATABRICKS_BUNDLE_ENGINE=direct databricks bundle deploy \
  --var catalog="$CATALOG" \
  --var schema="$SCHEMA" \
  --var end_user_group="$END_USER_GROUP"

# Post-deploy: grant the app SP UC access to the customer's silver-layer schema.
# DAB has no resource to grant on pre-existing UC objects (CLI #3556), so this
# is the one piece that lives in the script.

echo ""
echo "=== Post-deploy UC grants for app SP ==="

SP_ID=$(databricks apps get "$APP_NAME" -o json \
  | python3 -c "import sys, json; print(json.load(sys.stdin).get('service_principal_client_id', ''))")
echo "  SP: $SP_ID"
if [ -z "$SP_ID" ]; then
  echo "  ERROR: app $APP_NAME has no service_principal_client_id yet" >&2
  exit 1
fi

WAREHOUSE_ID=$(databricks warehouses list -o json \
  | APP_NAME="$APP_NAME" python3 -c "
import os, sys, json
target = os.environ['APP_NAME']
for w in json.load(sys.stdin):
    if w.get('name') == target:
        print(w['id'])
        break")
echo "  Warehouse: $WAREHOUSE_ID"
if [ -z "$WAREHOUSE_ID" ]; then
  echo "  ERROR: could not find the bundle-created warehouse named $APP_NAME" >&2
  exit 1
fi

# Use Python (single block, no shell escaping) to issue the 4 GRANTs against
# the bundle-created warehouse. Each statement is sent via the CLI's API
# proxy with a temp-file JSON payload — no shell-quoting hazards.
SP_ID="$SP_ID" CATALOG="$CATALOG" SCHEMA="$SCHEMA" WAREHOUSE_ID="$WAREHOUSE_ID" \
  python3 - <<'PY'
import json, os, subprocess, sys, tempfile

sp = os.environ["SP_ID"]
cat = os.environ["CATALOG"]
sch = os.environ["SCHEMA"]
wh  = os.environ["WAREHOUSE_ID"]

stmts = [
    # UC permissions are hierarchical — granting SELECT ON SCHEMA cascades
    # to all current and future tables in that schema. No need for the
    # Postgres-style ALL TABLES IN SCHEMA / FUTURE TABLES IN SCHEMA syntax.
    f"GRANT USE CATALOG ON CATALOG `{cat}` TO `{sp}`",
    f"GRANT USE SCHEMA ON SCHEMA `{cat}`.`{sch}` TO `{sp}`",
    f"GRANT SELECT ON SCHEMA `{cat}`.`{sch}` TO `{sp}`",
]

failed = 0
for sql in stmts:
    print(f"  -> {sql}")
    payload = {"warehouse_id": wh, "statement": sql, "wait_timeout": "30s"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    try:
        result = subprocess.run(
            ["databricks", "api", "post", "/api/2.0/sql/statements",
             "--json", f"@{path}", "-o", "json"],
            capture_output=True, text=True,
        )
    finally:
        os.unlink(path)
    if result.returncode != 0:
        print(f"     FAIL: {result.stderr.strip()[:200]}")
        failed += 1
        continue
    try:
        d = json.loads(result.stdout)
    except Exception:
        print(f"     FAIL: non-JSON response: {result.stdout.strip()[:200]}")
        failed += 1
        continue
    status = d.get("status", {})
    state = status.get("state", "?")
    err = status.get("error", {}).get("message", "")
    print(f"     {state}{(' — ' + err) if err else ''}")
    if state not in ("SUCCEEDED", "PENDING"):
        failed += 1

sys.exit(1 if failed else 0)
PY

# Final summary.
APP_URL=$(databricks apps get "$APP_NAME" -o json \
  | python3 -c "import sys, json; print(json.load(sys.stdin).get('url', 'pending — check workspace UI'))")

echo ""
echo "=== Install complete ==="
echo "  App URL: $APP_URL"
echo ""
echo "Reminder — end users also need (one-time, by your workspace admin):"
echo "  - USE CATALOG / USE SCHEMA / SELECT on $CATALOG.$SCHEMA"
echo "  - Membership in '$END_USER_GROUP' (the bundle already granted that group"
echo "    CAN_USE on the app + warehouse)"
