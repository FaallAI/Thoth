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
    -f compose.stage1.providers.yml -f compose.stage1.renderer.yml -f compose.stage1.web.yml)
step() { echo "== $*"; }

step preflight
[ -n "$(value THOTH_WEB_IMAGE)" ] || { echo "THOTH_WEB_IMAGE is not pinned" >&2; exit 1; }
docker run --rm -v "$root:$root:ro" -v "$(dirname "$provider_env"):$(dirname "$provider_env"):ro" \
    -v "$data_root:$data_root:ro" -w "$root" --user 0 "$image" \
    /opt/thoth/python/.venv/bin/thoth-control operations stage1-local-preflight \
    --env-file "$env_file" --provider-env-file "$provider_env" 2>&1 | tail -5
step config
"${compose[@]}" config --quiet && echo "config ok"
"${compose[@]}" config --images
step migrate
"${compose[@]}" run --rm --no-deps api thoth-control editor migrate 2>&1 | tail -3
step backfill-runs
"${compose[@]}" run --rm --no-deps api thoth-control workflow backfill 2>&1 | tail -1
step stop-worker
"${compose[@]}" stop worker
# The artifact volume is no longer mounted (spec 2026-10-17, render storage). While its host
# folder still exists, every import below reaches it through a one-off mount; each import is
# idempotent, so an emptied folder only prints zero counts. The host folder belongs to the
# container user, so its presence is the test, never a listing of its files.
on_volume=(run --rm --no-deps -v "$data_root/artifacts:/var/lib/thoth/artifacts" api)
if [ -d "$data_root/artifacts" ]; then
    step import-reports
    # The importer exits 1 on invalid files or an unavailable store; capture that so the
    # message below prints instead of set -e ending the script silently.
    import_rc=0
    import_line=$("${compose[@]}" "${on_volume[@]}" thoth-control reports import \
        --artifact-root /var/lib/thoth/artifacts 2>&1 | tail -1) || import_rc=$?
    echo "$import_line"
    if [ "$import_rc" -ne 0 ]; then
        echo "report import failed (exit $import_rc); the old worker stays stopped — decide, then re-run" >&2
        exit 1
    fi
    case "$import_line" in
        *" invalid=0") ;;
        *) echo "report import not clean; the old worker stays stopped — decide, then re-run" >&2
           exit 1 ;;
    esac
fi
step media-store
mkdir -p "$data_root/minio"
"${compose[@]}" up -d --wait minio 2>&1 | tail -3
if [ -d "$data_root/artifacts" ]; then
    for mode in "" "--archive"; do
        step "import-media${mode:+ $mode}"
        # Same guard as the report import: a failed or unclean import leaves the old worker
        # stopped. `$mode` is unquoted on purpose: empty means the plain media import.
        media_rc=0
        media_line=$("${compose[@]}" "${on_volume[@]}" thoth-control media import $mode \
            --artifact-root /var/lib/thoth/artifacts 2>&1 | tail -1) || media_rc=$?
        echo "$media_line"
        if [ "$media_rc" -ne 0 ]; then
            echo "media import failed (exit $media_rc); the old worker stays stopped — decide, then re-run" >&2
            exit 1
        fi
        case "$media_line" in
            *" invalid=0 mismatch=0") ;;
            *) echo "media import not clean; the old worker stays stopped — decide, then re-run" >&2
               exit 1 ;;
        esac
    done
fi
step up
"${compose[@]}" up -d --wait 2>&1 | tail -12
step status
"${compose[@]}" ps --format '{{.Service}} {{.Status}}'
