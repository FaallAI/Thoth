#!/usr/bin/env bash
# Run the media store contract against a throwaway MinIO (the stack's own image), removed
# afterwards. A skipped MinIO test fails here (THOTH_REQUIRE_MINIO_TESTS=1).
#
#     bash scripts/dev/pytest-minio.sh [pytest args...]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image=pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372
name="thoth-test-minio-$$"
port=59000

docker run -d --rm --name "$name" -e MINIO_ROOT_USER=thoth-test \
    -e MINIO_ROOT_PASSWORD=thoth-test-secret -p "127.0.0.1:$port:9000" "$image" server /data >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$port/minio/health/live" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS "http://127.0.0.1:$port/minio/health/live" >/dev/null

[ "$#" -gt 0 ] || set -- tests/infrastructure/test_media_store.py
THOTH_TEST_MEDIA_S3_ENDPOINT="127.0.0.1:$port" \
THOTH_TEST_MEDIA_S3_ACCESS_KEY=thoth-test \
THOTH_TEST_MEDIA_S3_SECRET_KEY=thoth-test-secret \
THOTH_REQUIRE_MINIO_TESTS=1 \
    bash "$root/scripts/dev/pytest-wsl.sh" "$@"
