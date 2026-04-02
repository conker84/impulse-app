#!/usr/bin/env bash
# Sync local code to FEVM workspace and deploy the Impulse app.
#
# Usage:
#   test/deploy-fevm.sh                        # full: build + sync + deploy
#   test/deploy-fevm.sh --instance feat-a       # deploy as separate app "impulse-feat-a"
#   test/deploy-fevm.sh --sync-only             # just sync files (no redeploy, no build)
#   test/deploy-fevm.sh --skip-build            # sync + deploy, skip frontend build
#
# Set DATABRICKS_PROFILE to target a specific workspace profile.
# Falls back to [DEFAULT] profile in ~/.databrickscfg.
set -euo pipefail

PROFILE="${DATABRICKS_PROFILE:-}"
if [ -z "$PROFILE" ]; then
  # Fall back to [DEFAULT] profile in ~/.databrickscfg
  PROFILE=$(awk -F'[][]' '/^\[/{p=$2} /^host/{if(p=="DEFAULT"){print p; exit}}' ~/.databrickscfg 2>/dev/null || true)
  if [ -z "$PROFILE" ]; then
    echo "ERROR: Set DATABRICKS_PROFILE or configure a [DEFAULT] profile in ~/.databrickscfg" >&2
    exit 1
  fi
fi

# Resolve current user email from the CLI profile
USER_JSON=$(databricks current-user me --profile "$PROFILE" -o json 2>/dev/null) || true
USER_EMAIL=$(echo "$USER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])" 2>/dev/null) || true
if [ -z "$USER_EMAIL" ]; then
  echo "ERROR: Could not resolve user email from profile '$PROFILE'" >&2
  exit 1
fi

BASE_APP_NAME="impulse"
BASE_WS_PATH="/Workspace/Users/${USER_EMAIL}/impulse-app"

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

echo "==> Profile: $PROFILE (user: $USER_EMAIL)"
echo "    App: $APP_NAME"
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

USER_API_SCOPES='["sql","sql.statement-execution","dashboards.genie","files.files","serving.serving-endpoints","serving.serving-endpoints-data-plane","vectorsearch.vector-search-indexes","vectorsearch.vector-search-endpoints","catalog.connections","catalog.catalogs","catalog.schemas","catalog.tables"]'

# Create app with scopes if it doesn't exist yet; otherwise just deploy
if ! databricks apps get "$APP_NAME" --profile "$PROFILE" -o json > /dev/null 2>&1; then
  echo "==> Creating app '$APP_NAME' with user authorization scopes..."
  databricks apps create --profile "$PROFILE" --no-wait \
    --json "{\"name\":\"$APP_NAME\",\"user_api_scopes\":$USER_API_SCOPES}"
  echo "    Waiting for app to be ready..."
  databricks apps get "$APP_NAME" --profile "$PROFILE" > /dev/null 2>&1
  sleep 10
fi

echo "==> Deploying app '$APP_NAME'..."
databricks apps deploy "$APP_NAME" --source-code-path "$WS_PATH" --profile "$PROFILE" --no-wait

echo "==> Deploy triggered. Check status with:"
echo "    databricks apps get $APP_NAME --profile $PROFILE"
echo ""
echo "    The app URL will be shown once the deploy completes."
echo "    Run: databricks apps get $APP_NAME --profile $PROFILE --output json | python3 -c \"import sys,json; print(json.load(sys.stdin).get('url','pending...'))\""
