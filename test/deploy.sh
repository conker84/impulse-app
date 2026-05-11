#!/usr/bin/env bash
# Sync local code to a Databricks workspace and deploy the Impulse app.
#
# Usage:
#   test/deploy.sh                # full: build + sync + deploy
#   test/deploy.sh --sync-only    # just sync files (no redeploy, no build)
#   test/deploy.sh --skip-build   # sync + deploy, skip frontend build
#
# app.yaml is the single source of truth: `name:` -> deployed app name,
# `profile:` -> Databricks CLI profile to deploy with. The shell env var
# DATABRICKS_PROFILE is honored only as an explicit override (with a warning).
set -euo pipefail

# Resolve repo root and read app.yaml — single source of truth
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_YAML="$REPO_ROOT/app.yaml"
if [ ! -f "$APP_YAML" ]; then
  echo "ERROR: $APP_YAML not found" >&2
  exit 1
fi

read -r APP_NAME APP_YAML_PROFILE <<< "$(python3 -c "
import sys, yaml
y = yaml.safe_load(open('$APP_YAML')) or {}
print(y.get('name', ''), y.get('profile', ''))
")"

if [ -z "$APP_NAME" ]; then
  echo "ERROR: app.yaml is missing a top-level 'name:' field. Add e.g. 'name: impulse-stla'." >&2
  exit 1
fi
if [ -z "$APP_YAML_PROFILE" ]; then
  echo "ERROR: app.yaml is missing a top-level 'profile:' field. Add e.g. 'profile: fevm-demo-stla'." >&2
  exit 1
fi

if [ -n "${DATABRICKS_PROFILE:-}" ] && [ "$DATABRICKS_PROFILE" != "$APP_YAML_PROFILE" ]; then
  echo "WARNING: shell DATABRICKS_PROFILE='$DATABRICKS_PROFILE' overrides app.yaml profile='$APP_YAML_PROFILE'" >&2
  PROFILE="$DATABRICKS_PROFILE"
else
  PROFILE="$APP_YAML_PROFILE"
fi

# Resolve current user email from the CLI profile
USER_JSON=$(databricks current-user me --profile "$PROFILE" -o json 2>/dev/null) || true
USER_EMAIL=$(echo "$USER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])" 2>/dev/null) || true
if [ -z "$USER_EMAIL" ]; then
  echo "ERROR: Could not resolve user email from profile '$PROFILE'" >&2
  exit 1
fi

WS_PATH="/Workspace/Users/${USER_EMAIL}/${APP_NAME}-app"

SYNC_ONLY=false
SKIP_BUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync-only)  SYNC_ONLY=true; SKIP_BUILD=true; shift ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    *)            shift ;;
  esac
done

echo "==> Profile: $PROFILE (user: $USER_EMAIL)"
echo "    App: $APP_NAME (from app.yaml)"
echo "    Workspace path: $WS_PATH"

if [ "$SKIP_BUILD" = false ]; then
  echo "==> Building frontend..."
  cd "$REPO_ROOT/frontend"
  npx tsc -b && npx vite build
  cd "$REPO_ROOT"
fi

echo "==> Syncing to workspace..."
cd "$REPO_ROOT"
# app.yaml and profiles.yaml are gitignored (customer-specific) but required at runtime —
# force-include them so databricks sync ships them despite the gitignore match.
databricks sync . "$WS_PATH" --profile "$PROFILE" --watch=false \
  --include "app.yaml" --include "profiles.yaml"

# frontend/dist/ is gitignored (gitleaks false positive), so databricks sync skips it. Upload separately.
[ -d "frontend/dist" ] && databricks workspace import-dir frontend/dist "$WS_PATH/frontend/dist" --overwrite --profile "$PROFILE"

if [ "$SYNC_ONLY" = true ]; then
  echo "==> Sync complete (no redeploy). Files updated in workspace."
  echo "    Note: A full deploy is needed for changes to take effect."
  exit 0
fi

USER_API_SCOPES='["sql","dashboards.genie","files.files","catalog.connections","catalog.catalogs:read","catalog.schemas:read","catalog.tables:read","serving.serving-endpoints"]'

# Create app if it doesn't exist yet
if ! databricks apps get "$APP_NAME" --profile "$PROFILE" -o json > /dev/null 2>&1; then
  echo "==> Creating app '$APP_NAME'..."
  databricks apps create --profile "$PROFILE" --no-wait \
    --json "{\"name\":\"$APP_NAME\",\"user_api_scopes\":$USER_API_SCOPES}"
  echo "    Waiting for app compute to leave STARTING..."
  while :; do
    state=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('compute_status',{}).get('state',''))" 2>/dev/null || true)
    [ "$state" != "STARTING" ] && break
    sleep 15
  done
fi

# Always ensure user authorization scopes are set (they can get wiped by UI/API changes)
echo "==> Ensuring user authorization scopes..."
databricks api patch /api/2.0/apps/"$APP_NAME" --profile "$PROFILE" \
  --json "{\"user_api_scopes\":$USER_API_SCOPES}" > /dev/null

echo "==> Deploying app '$APP_NAME'..."
databricks apps deploy "$APP_NAME" --source-code-path "$WS_PATH" --profile "$PROFILE" --no-wait

echo "==> Deploy triggered. Check status with:"
echo "    databricks apps get $APP_NAME --profile $PROFILE"
echo ""
echo "    The app URL will be shown once the deploy completes."
echo "    Run: databricks apps get $APP_NAME --profile $PROFILE --output json | python3 -c \"import sys,json; print(json.load(sys.stdin).get('url','pending...'))\""
