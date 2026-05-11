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

# Resolve app_name from databricks.yml (default in the bundle variable).
APP_NAME=$(python3 -c "
import yaml
v = yaml.safe_load(open('databricks.yml')).get('variables', {}).get('app_name', {})
print(v.get('default', 'impulse-v3'))
")

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

SP_ID=$(databricks apps get "$APP_NAME" -o json | python3 -c "
import sys, json
print(json.load(sys.stdin)['service_principal_client_id'])
")
echo "  SP: $SP_ID"

WAREHOUSE_ID=$(databricks warehouses list -o json | python3 -c "
import sys, json
for w in json.load(sys.stdin):
    if w.get('name') == '$APP_NAME':
        print(w['id'])
        break
")
echo "  Warehouse: $WAREHOUSE_ID"

if [ -z "$WAREHOUSE_ID" ]; then
  echo "  ERROR: could not find the bundle-created warehouse named $APP_NAME" >&2
  exit 1
fi

run_sql() {
  local sql="$1"
  echo "  -> $sql"
  databricks api post /api/2.0/sql/statements --json "$(python3 -c "
import json, sys
print(json.dumps({
    'warehouse_id': '$WAREHOUSE_ID',
    'statement': sys.argv[1],
    'wait_timeout': '30s',
}))
" "$sql")" -o json | python3 -c "
import sys, json
d = json.load(sys.stdin)
state = d.get('status', {}).get('state', '?')
err = d.get('status', {}).get('error', {}).get('message', '')
print(f'     {state}{(\" — \" + err) if err else \"\"}')
if state not in ('SUCCEEDED', 'PENDING'):
    sys.exit(1)
"
}

run_sql "GRANT USE CATALOG ON CATALOG \`$CATALOG\` TO \`$SP_ID\`"
run_sql "GRANT USE SCHEMA ON SCHEMA \`$CATALOG\`.\`$SCHEMA\` TO \`$SP_ID\`"
run_sql "GRANT SELECT ON ALL TABLES IN SCHEMA \`$CATALOG\`.\`$SCHEMA\` TO \`$SP_ID\`"
run_sql "GRANT SELECT ON FUTURE TABLES IN SCHEMA \`$CATALOG\`.\`$SCHEMA\` TO \`$SP_ID\`"

# Final summary.
APP_URL=$(databricks apps get "$APP_NAME" -o json | python3 -c "
import sys, json
print(json.load(sys.stdin).get('url', 'pending — check workspace UI'))
")

echo ""
echo "=== Install complete ==="
echo "  App URL: $APP_URL"
echo ""
echo "Reminder — end users also need (one-time, by your workspace admin):"
echo "  - USE CATALOG / USE SCHEMA / SELECT on $CATALOG.$SCHEMA"
echo "  - Membership in '$END_USER_GROUP' (the bundle already granted that group"
echo "    CAN_USE on the app + warehouse)"
