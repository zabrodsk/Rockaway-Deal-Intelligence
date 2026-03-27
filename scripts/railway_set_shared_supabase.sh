#!/usr/bin/env bash

set -euo pipefail

if [[ -n "${RAILWAY_BIN:-}" ]]; then
  railway_cli="$RAILWAY_BIN"
elif command -v railway >/dev/null 2>&1; then
  railway_cli="$(command -v railway)"
elif [[ -x /tmp/railway-bin/railway ]]; then
  railway_cli="/tmp/railway-bin/railway"
else
  echo "Railway CLI not found. Install it or set RAILWAY_BIN." >&2
  exit 1
fi

: "${SUPABASE_URL:?Set SUPABASE_URL before running this script.}"
: "${SUPABASE_SERVICE_ROLE_KEY:?Set SUPABASE_SERVICE_ROLE_KEY before running this script.}"

optional_args=()
if [[ -n "${SUPABASE_SOURCE_FILES_BUCKET:-}" ]]; then
  optional_args+=("SUPABASE_SOURCE_FILES_BUCKET=$SUPABASE_SOURCE_FILES_BUCKET")
fi

for service in startup-ranker-web startup-ranker-worker; do
  args=(
    variable set
    -s "$service"
    --skip-deploys
    "SUPABASE_URL=$SUPABASE_URL"
    "SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY"
  )
  if (( ${#optional_args[@]} > 0 )); then
    args+=("${optional_args[@]}")
  fi
  "$railway_cli" "${args[@]}"
done

echo "Updated Supabase variables for startup-ranker-web and startup-ranker-worker."
echo "Deploy or redeploy the services after verifying the linked Railway project is correct."
