#!/usr/bin/env bash
# Sync local code to FEVM workspace and deploy the Impulse app.
#
# Usage:
#   .claude/deploy-fevm.sh                        # full: build + sync + deploy (default instance "impulse")
#   .claude/deploy-fevm.sh --instance feat-a       # deploy as separate app "impulse-feat-a"
#   .claude/deploy-fevm.sh --sync-only             # just sync files (no redeploy, no build)
#   .claude/deploy-fevm.sh --skip-build            # sync + deploy, skip frontend build
#   .claude/deploy-fevm.sh --instance feat-a --skip-build
set -euo pipefail

PROFILE="fe-vm-maximhammer"
BASE_APP_NAME="impulse"
BASE_WS_PATH="/Workspace/Users/maxim.hammer@databricks.com/impulse-app"

SYNC_ONLY=false
SKIP_BUILD=false
INSTANCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync-only)  SYNC_ONLY=true; SKIP_BUILD=true; shift ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --instance)   INSTANCE="$2"; shift 2 ;;
    *)            shift ;;
  esac
done

# Derive app name and workspace path from instance
if [ -n "$INSTANCE" ]; then
  APP_NAME="${BASE_APP_NAME}-${INSTANCE}"
  WS_PATH="${BASE_WS_PATH}-${INSTANCE}"
else
  APP_NAME="$BASE_APP_NAME"
  WS_PATH="$BASE_WS_PATH"
fi

echo "==> Instance: $APP_NAME"
echo "    Workspace path: $WS_PATH"

if [ "$SKIP_BUILD" = false ]; then
  echo "==> Building frontend..."
  cd "$(dirname "$0")/../frontend"
  npx tsc -b && npx vite build
  cd ..
fi

echo "==> Syncing to workspace..."
cd "$(dirname "$0")/.."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXCLUDE_FILE="$SCRIPT_DIR/../.databricksignore"
if [ -f "$EXCLUDE_FILE" ]; then
  databricks sync . "$WS_PATH" --profile "$PROFILE" --watch=false --exclude-from "$EXCLUDE_FILE"
else
  databricks sync . "$WS_PATH" --profile "$PROFILE" --watch=false
fi

# frontend/dist/ is gitignored (gitleaks false positive), so databricks sync skips it. Upload separately.
[ -d "frontend/dist" ] && databricks workspace import-dir frontend/dist "$WS_PATH/frontend/dist" --overwrite --profile "$PROFILE"

if [ "$SYNC_ONLY" = true ]; then
  echo "==> Sync complete (no redeploy). Files updated in workspace."
  echo "    Note: A full deploy is needed for changes to take effect."
  exit 0
fi

# Set all available User Authorization scopes for the OBO token.
# IMPORTANT: Scopes only persist if set during `apps create` or via the UI before first deploy.
# This update is a best-effort attempt — if it fails silently, scopes must be set via the UI
# or by recreating the app with --json '{"user_api_scopes": [...]}'.
echo "==> Configuring User Authorization scopes..."
ALL_SCOPES='{"user_api_scopes":["sql","files.files","dashboards.genie","catalog.catalogs:read","catalog.schemas:read","catalog.tables:read","catalog.catalogs","catalog.schemas","catalog.tables","serving.serving-endpoints","serving.serving-endpoints:read"]}'
if databricks apps update "$APP_NAME" \
    --json "$ALL_SCOPES" \
    --profile "$PROFILE" --output json > /dev/null 2>&1; then
  echo "    Scopes set: sql, files, catalog, serving, genie"
else
  echo "    WARNING: Could not set user_api_scopes. Ensure 'Databricks Apps - OBO User Authorization'"
  echo "    preview is enabled in Admin Settings for this workspace."
fi

echo "==> Deploying app '$APP_NAME'..."
databricks apps deploy "$APP_NAME" --source-code-path "$WS_PATH" --profile "$PROFILE" --no-wait

echo "==> Deploy triggered. Check status with:"
echo "    databricks apps get $APP_NAME --profile $PROFILE"
echo ""
echo "    The app URL will be shown once the deploy completes."
echo "    Run: databricks apps get $APP_NAME --profile $PROFILE --output json | python3 -c \"import sys,json; print(json.load(sys.stdin).get('url','pending...'))\""
