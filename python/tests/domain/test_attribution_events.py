"""Attribution failure codes are closed event payload values."""

from __future__ import annotations

from pathlib import Path

import pytest

from thoth_control_plane.domain.models import ATTRIBUTION_REASONS, SourceProgressEvent

CODES = {
    "openrouter_key_missing",
    "vision_unavailable",
    "decision_unavailable",
    "scene_detection_failed",
    "transcription_failed",
    "diarization_failed",
    "whisper_missing",
    "whisper_model_missing",
    "diarization_missing",
    "diarization_model_missing",
    "ffmpeg_missing",
    "ffprobe_missing",
    "rapidocr_missing",
    "opencv_missing",
}


def test_every_attribution_code_is_an_event_reason() -> None:
    assert ATTRIBUTION_REASONS == CODES
    for code in CODES:
        event = SourceProgressEvent(
            kind="stage.failed",
            payload={"stage": "attribution", "status": "failed", "reason": code},
        )
        assert event.payload["reason"] == code


def test_an_unknown_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        SourceProgressEvent(kind="stage.failed", payload={"stage": "attribution", "reason": "nope"})


def test_model_directories_default_to_the_image_paths() -> None:
    from thoth_control_plane.config import Settings

    settings = Settings(THOTH_CONTROL_PLANE_API_KEY="test-only")  # type: ignore[call-arg]
    assert Path("/opt/thoth/models/whisper-large-v3-turbo") == settings.THOTH_WHISPER_MODEL_DIR
    assert Path("/opt/thoth/models/diarization") == settings.THOTH_DIARIZATION_MODEL_DIR
