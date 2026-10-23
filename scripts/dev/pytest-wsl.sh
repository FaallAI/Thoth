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
export PYTHONPATH="$PWD/src"

[ "$#" -gt 0 ] || set -- tests

exec "$HOME/.local/bin/uv" run --no-project --python 3.12 \
    --with pytest --with pytest-asyncio --with pydantic --with pydantic-settings --with typer \
    --with httpx --with respx --with temporalio --with fastapi --with python-multipart \
    --with 'psycopg[binary]' --with sqlalchemy --with alembic --with 'minio>=7.2.20,<8' --with boto3 --with pyjwt \
    --with agno --with 'openai<3' --with pillow --with pyyaml --with cryptography --with 'authlib>=1.6,<2' --with itsdangerous \
    --with rapidocr --with onnxruntime --with numpy --with tokenizers --with faster-whisper \
    --with sherpa-onnx --with camoufox==0.5.8 --with yt-dlp==2026.10.21 \
    -- python -m pytest "$@" -q -p no:cacheprovider -p no:warnings --basetemp="$HOME/thoth-tmp/pt"
