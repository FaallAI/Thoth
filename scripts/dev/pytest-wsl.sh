#!/usr/bin/env bash
# Run the control-plane test suite from WSL. python/.venv is a Windows venv and cannot run here, so
# uv builds a throwaway environment with the project's runtime dependencies instead.
#
#     bash scripts/dev/pytest-wsl.sh [pytest args...]      # default: the whole suite
#
# Model-backed tests read their models from THOTH_TEST_*_MODEL_DIR (default ~/thoth-models/*);
# they fail, not skip, when a model is missing.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root/python"
mkdir -p "$HOME/thoth-tmp"

export THOTH_TEST_WHISPER_MODEL_DIR="${THOTH_TEST_WHISPER_MODEL_DIR:-$HOME/thoth-models/whisper-tiny}"
export THOTH_TEST_DIARIZATION_MODEL_DIR="${THOTH_TEST_DIARIZATION_MODEL_DIR:-$HOME/thoth-models/diarization}"
export THOTH_TEST_EMBEDDING_MODEL_DIR="${THOTH_TEST_EMBEDDING_MODEL_DIR:-$HOME/thoth-models/embedding}"
export THOTH_TEST_FACE_MODELS_DIR="${THOTH_TEST_FACE_MODELS_DIR:-$HOME/thoth-models/faces}"
export PYTHONPATH="$PWD/src"

[ "$#" -gt 0 ] || set -- tests

# The exact versions in uv.lock, as CI installs them: hand-kept pins here drifted from the lock
# (openai, camoufox, yt-dlp, pytest) and tested other code than the image runs (2026-11-26).
requirements="$HOME/thoth-tmp/locked-requirements.txt"
"$HOME/.local/bin/uv" export --frozen --no-hashes --no-emit-project --all-groups --extra acquisition \
    --format requirements-txt --quiet > "$requirements"

exec "$HOME/.local/bin/uv" run --no-project --python 3.12 --with-requirements "$requirements" \
    -- python -m pytest "$@" -q -p no:cacheprovider -p no:warnings --basetemp="$HOME/thoth-tmp/pt"
