#!/usr/bin/env bash
# Keep the TikTok captcha solver's outcome lines past worker deploys, then count them.
# Docker drops a container's log with the container, and every deploy recreates the worker, so
# the lines are appended to a file under the stack's data root first. Docker's timestamp makes
# each line unique, so saving the same log twice adds nothing. `make deploy` runs this before the
# worker stops; `make captcha-stats` runs it any time. Run from WSL at the repository root.
#
#     bash scripts/ops/captcha-outcomes.sh [env-file]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
env_file=${1:-.env.stage1.local}
data_root=$(grep -E "^THOTH_STAGE1_DATA_ROOT=" "$env_file" | head -1 | cut -d= -f2- | tr -d '\r')
[ -n "$data_root" ] || { echo "THOTH_STAGE1_DATA_ROOT is not set in $env_file" >&2; exit 1; }
saved="$data_root/ops/captcha-outcomes.log"
mkdir -p "$(dirname "$saved")"
touch "$saved"

# A failing `docker compose logs` stops here (set -e): a missed save must be loud.
log=$(docker compose --env-file "$env_file" -f compose.stage1.local.yml \
    -f compose.stage1.providers.yml -f compose.stage1.renderer.yml -f compose.stage1.web.yml \
    logs --no-color --no-log-prefix --timestamps worker)
fresh=$(printf '%s\n' "$log" | grep "tiktok captcha outcome" || true)
{ cat "$saved"; [ -z "$fresh" ] || printf '%s\n' "$fresh"; } | sort -u > "$saved.tmp"
mv "$saved.tmp" "$saved"

echo "$(wc -l < "$saved" | tr -d ' ') outcome lines in $saved"
sed 's/^.*tiktok captcha outcome //' "$saved" | sort | uniq -c | sort -rn
