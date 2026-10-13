"""The speech-model fetcher pins every file and refuses a mismatch."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "docker" / "fetch_speech_models.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fetch_speech_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_model_is_pinned_by_revision_and_checksum() -> None:
    module = _module()
    for size in ("tiny", "large-v3-turbo"):
        whisper = module.WHISPER[size]
        assert len(whisper["revision"]) == 40
        assert len(whisper["model_sha256"]) == 64
    for asset in module.DIARIZATION.values():
        assert asset["url"].startswith("https://github.com/k2-fsa/sherpa-onnx/releases/download/")
        assert len(asset["sha256"]) == 64


def test_a_checksum_mismatch_stops_the_fetch(tmp_path: Path) -> None:
    module = _module()
    target = tmp_path / "file.bin"
    target.write_bytes(b"not the model")
    with pytest.raises(SystemExit):
        module.verify(target, "0" * 64)
