#!/usr/bin/env bash
# Run the Postgres-backed tests against a throwaway PostgreSQL 16.4 (the stack's own image),
# removed afterwards. A skipped Postgres test fails here (THOTH_REQUIRE_POSTGRES_TESTS=1).
#
#     bash scripts/dev/pytest-postgres.sh [pytest args...]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image=postgres:16.4-bookworm@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412
name="thoth-test-postgres-$$"
port=55432

docker run -d --rm --name "$name" -e POSTGRES_PASSWORD=thoth -p "127.0.0.1:$port:5432" "$image" >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do
    docker exec "$name" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1 && break
    sleep 1
done
docker exec "$name" pg_isready -h 127.0.0.1 -U postgres >/dev/null

[ "$#" -gt 0 ] || set -- $(cd "$root/python" && ls tests/*/*_postgres.py)
THOTH_TEST_EDITOR_DATABASE_URL="postgresql://postgres:thoth@127.0.0.1:$port/postgres" \
THOTH_REQUIRE_POSTGRES_TESTS=1 \
    bash "$root/scripts/dev/pytest-wsl.sh" "$@"
