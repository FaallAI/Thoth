#!/usr/bin/env bash
# Deploy the Stage 1 local stack on the image pinned in .env.stage1.local (THOTH_IMAGE, by digest).
# Run from WSL, where Docker lives. Prints statuses only; never resolves or prints secrets.
#
#     bash scripts/ops/deploy-stage1.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
env_file=.env.stage1.local
value() { grep -E "^$1=" "$env_file" | head -1 | cut -d= -f2- | tr -d '\r'; }
image=$(value THOTH_IMAGE)
provider_env=$(value THOTH_STAGE1_PROVIDER_ENV_FILE)
data_root=$(value THOTH_STAGE1_DATA_ROOT)
compose=(docker compose --env-file "$env_file" -f compose.stage1.local.yml
    -f compose.stage1.providers.yml -f compose.stage1.renderer.yml)
step() { echo "== $*"; }

step preflight
docker run --rm -v "$root:$root:ro" -v "$(dirname "$provider_env"):$(dirname "$provider_env"):ro" \
    -v "$data_root:$data_root:ro" -w "$root" --user 0 "$image" \
    /opt/thoth/python/.venv/bin/thoth-control operations stage1-local-preflight \
    --env-file "$env_file" --provider-env-file "$provider_env" 2>&1 | tail -5
step config
"${compose[@]}" config --quiet && echo "config ok"
"${compose[@]}" config --images
step migrate
"${compose[@]}" run --rm --no-deps api thoth-control editor migrate 2>&1 | tail -3
step up
"${compose[@]}" up -d --wait 2>&1 | tail -12
step status
"${compose[@]}" ps --format '{{.Service}} {{.Status}}'
