# Stage 4 Reaction Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attribution answers `original` for a reaction that adds a new viewpoint or issue and is discussed, and for any reaction to a text or image post. Vision, Jev, and the new speech tools become required.

**Architecture:**
- **Frames and vision.** Scene cuts from ffmpeg pick up to six vision frames. The cover reading gains `reaction_shape`, `subject_media`, and per-frame `shows`.
- **Reaction step.** For a reaction-shaped post whose subject is a video, a new step in `SourceAttributor.identify`:
  - transcribes locally (faster-whisper);
  - splits speakers (sherpa-onnx);
  - asks Jev for a contribution score and a comment-discussion probability;
  - compares engagement with the owner's own videos.
- **Failures.** A required port that cannot work raises `AttributionError(code)`. The activity returns it as a typed failure, and the workflow fails `source_attribution_failed`.

**Tech Stack:**
- Python 3.12, Pydantic v2 strict models, Temporal Python SDK.
- ffmpeg, faster-whisper 1.2 (CTranslate2), sherpa-onnx 1.13 (onnxruntime).
- Agno over OpenRouter (vision), TypeSafe Jev over OpenRouter's Decisions API.
- pytest, respx.

**Spec:** `docs/superpowers/specs/2026-10-13-stage4-reaction-attribution-design.md`. It builds on `docs/superpowers/specs/2026-10-08-stage4-source-attribution-design.md`. Research: `docs/research/2026-10-13-reaction-as-original-research.md`.

## Global Constraints

**Rules from the operator:**
- Required tools fail loud (2026-10-11 and 2026-10-13). A missing tool, key, or model is an explicit error at worker start and at run time. **No test skips for a missing tool**: use `pytest.fail`.
- Jev and vision are required for all of Stage 4. The rules-only path without a key is removed.
- A vision or Jev failure at run time fails the workflow with `WorkflowFailure(code="source_attribution_failed", failed_stage="attribution", retryable=True)`. The code goes into the stage event `reason`.
- External-content failures still end `unresolved` with today's reason codes and never fail the workflow. These are discovery, candidate acquisition, candidate frames, the engagement baseline, and a missing repost report.
- An original reaction keeps its opening in Stage 5a (verdict `original`, so no trim).
- Where signed-out access is weaker, use a signed-in account with its proxy (2026-10-13). Profile discovery in `fallback` mode leases an account when the anonymous listing is thin (fewer than 10 videos), not only when it is blocked.
- Deploy precondition: TikTok, Instagram, and X source accounts with proxies imported, and their policy in `fallback` or `always`.

**Values and limits:**
- Decision rule: `original ⇔ P(contribution ≥ new_viewpoint) ≥ 0.5 ∧ comments exist ∧ P(comments_discuss_creator) ≥ 0.5 ∧ ratio known ∧ ratio ≥ 1.0`. All three thresholds are tuning, calibrated on goldens.
- At most 6 vision frames for the cover call. The finalist classification keeps 3.
- Transcription and diarization cover at most the first 180 s (`transcript_seconds`).
- Jev state: creator speech and subject speech clipped to 6,000 characters each, at most 12 comments.
- `SourceAttribution` stays schema version 1. Only `EvidenceKind` widens with `reaction`. Evidence details are at most 300 characters and never quote speech.
- Temporal history carries only IDs, verdicts, counts, and reason codes. No transcript, comment, or model answer leaves the activity.
- Model directories default to `/opt/thoth/models/whisper-large-v3-turbo` and `/opt/thoth/models/diarization`. The worker never downloads a model at run time.

**Repository rules:**
- Commits: one `git commit -m "<subject>"` of at most 72 characters, no body, no trailer, no AI attribution.
- Never stage `graphify-out/`, `build_log.txt`, `.superpowers`, `.understand-anything`, `.env.stage1.local*`, `dashboard/dist/`, or `design/`.
- No live traffic in tests: the conftest guard blocks non-loopback. Live capture is an operator gate (Task 12).
- Files with CRLF endings (`CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`, `compose.stage1.local.yml`, `.env.stage1.local.example`) are edited only through bytes-level scripts.

**Commands:**
- Test runner (run from `python/`):
  `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths> -p no:warnings`
- Ruff:
  `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check --fix src tests; ~/.local/bin/uvx ruff format src tests; ~/.local/bin/uvx ruff check .'`

## Review Focus

1. **A reaction with no audio stream, or only music** gives an empty transcript. The judge must still run on caption and text, and nothing may raise. Pinned in Task 6 (`test_a_video_without_audio_is_an_empty_transcript`) and Task 9 (`test_a_silent_reaction_is_judged_on_text_alone`).
2. **An `AttributionError` raised while finalists are in flight** must still discard every acquired finalist. Today's `finally` covers this; pinned in Task 3 (`test_a_failing_classification_still_discards_finalists`).
3. **Vision returns a `shows` list of the wrong length** (models often drop items). Every shot is then labelled `other`, and nothing raises. Pinned in Task 5 (`test_a_short_shows_list_labels_nothing`).
4. **The owner discovery lists the reaction itself, or only two other videos.** The ratio excludes the post and is `None` below 3 baseline videos. Pinned in Task 7 (`test_the_post_itself_is_not_its_own_baseline`).
5. **ffmpeg missing during repost sampling** used to degrade to `frames_failed`. It must now raise `ffmpeg_missing`. Pinned in Task 3 (`test_a_missing_ffmpeg_stops_attribution`).

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `python/pyproject.toml`, `python/uv.lock` | modify | `faster-whisper`, `sherpa-onnx` in the `acquisition` extra |
| `python/src/thoth_control_plane/config.py` | modify | `THOTH_WHISPER_MODEL_DIR`, `THOTH_DIARIZATION_MODEL_DIR` |
| `python/src/thoth_control_plane/domain/models.py` | modify | `ATTRIBUTION_REASONS` joined into `SOURCE_EVENT_REASONS` |
| `docker/fetch_speech_models.py` | create | download pinned models and verify their SHA-256 (Docker build and CI) |
| `Dockerfile`, `.github/workflows/container-image.yml`, `.github/workflows/yt-dlp-update.yml` | modify | bake turbo + diarization models; CI fetches tiny + diarization for tests |
| `python/src/thoth_control_plane/attribution/ports.py` | modify | `AttributionError`, speech types, new ports, `CoverReading` fields, `Assessment` |
| `python/src/thoth_control_plane/attribution/scenes.py` | create | shots from cuts, vision frame choice, shot labels |
| `python/src/thoth_control_plane/attribution/reaction.py` | create | speech split, engagement ratio, judge (pure) |
| `python/src/thoth_control_plane/attribution/adapters/frames.py` | modify | `FfmpegSceneDetector` |
| `python/src/thoth_control_plane/attribution/adapters/speech.py` | create | `WhisperTranscriber`, `SherpaDiarizer`, audio loading, model file lists |
| `python/src/thoth_control_plane/attribution/adapters/vision.py` | modify | new prompt and fields, 6 frames, raise instead of `None` |
| `python/src/thoth_control_plane/attribution/adapters/jev.py` | modify | one retry, raise instead of `None`, `assess()` |
| `python/src/thoth_control_plane/attribution/models.py` | modify | `EvidenceKind` gains `reaction` |
| `python/src/thoth_control_plane/attribution/service.py` | modify | required ports, error propagation, scene frames, reaction step |
| `python/src/thoth_control_plane/activities/source_attribution.py` | modify | typed failure, production wiring |
| `python/src/thoth_control_plane/workflows/source_investigation.py` | modify | `source_attribution_failed` |
| `python/src/thoth_control_plane/worker.py` | modify | attribution start checks |
| `python/tests/attribution/replay.py`, `capture_golden.py`, `test_golden.py` | modify | replay and record the new answers |
| `python/tests/fixtures/attribution/*.json`, `python/tests/fixtures/assembly/ocr/instagram_de{Hz54GT4ea,O6A2MSoAt}.json` | modify/create | recaptured goldens |
| `D:/thoth-tmp/bu/pt.sh` (outside the repo) | modify | test env gains the two packages and the test model directories |

---

### Task 1: Dependencies, settings, and reason codes

**Files:**
- Modify: `python/pyproject.toml` (the `acquisition` extra), `python/uv.lock`
- Modify: `python/src/thoth_control_plane/config.py:83-93`
- Modify: `python/src/thoth_control_plane/domain/models.py:385-417`
- Modify: `D:/thoth-tmp/bu/pt.sh`
- Test: `python/tests/domain/test_attribution_events.py` (create)

**Interfaces:**
- Produces: `Settings.THOTH_WHISPER_MODEL_DIR: Path`, `Settings.THOTH_DIARIZATION_MODEL_DIR: Path`; `domain.models.ATTRIBUTION_REASONS: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

```python
"""Attribution failure codes are closed event payload values."""

from __future__ import annotations

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
    from pathlib import Path

    from thoth_control_plane.config import Settings

    settings = Settings(THOTH_CONTROL_PLANE_API_KEY="test-only")  # type: ignore[call-arg]
    assert settings.THOTH_WHISPER_MODEL_DIR == Path("/opt/thoth/models/whisper-large-v3-turbo")
    assert settings.THOTH_DIARIZATION_MODEL_DIR == Path("/opt/thoth/models/diarization")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/domain/test_attribution_events.py -p no:warnings`
Expected: FAIL with `ImportError: cannot import name 'ATTRIBUTION_REASONS'`

- [ ] **Step 3: Implement**

In `domain/models.py`, after `ASSEMBLY_REASONS`:

```python
ATTRIBUTION_REASONS = frozenset(
    {
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
)
```

Then change the union at the end of `SOURCE_EVENT_REASONS` from `| ASSEMBLY_REASONS` to `| ASSEMBLY_REASONS | ATTRIBUTION_REASONS`.

In `config.py`, after `THOTH_SOURCE_ATTRIBUTION_ENABLED`:

```python
    # Speech models baked into the image (spec 2026-10-13); never downloaded at run time.
    THOTH_WHISPER_MODEL_DIR: Path = Path("/opt/thoth/models/whisper-large-v3-turbo")
    THOTH_DIARIZATION_MODEL_DIR: Path = Path("/opt/thoth/models/diarization")
```

Use the existing `Path` import if `config.py` has one; otherwise add `from pathlib import Path`.

In `pyproject.toml`, append to the `acquisition` list: `"faster-whisper>=1.2,<2", "sherpa-onnx>=1.13,<2"`. Then refresh the lock from WSL:

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uv lock'
```

Append ` --with faster-whisper --with sherpa-onnx` after `--with numpy` in `D:/thoth-tmp/bu/pt.sh`. Prefix the `python -m pytest` command with these two exports (the directories are filled in Task 2):

```bash
THOTH_TEST_WHISPER_MODEL_DIR=$HOME/thoth-models/whisper-tiny THOTH_TEST_DIARIZATION_MODEL_DIR=$HOME/thoth-models/diarization
```

- [ ] **Step 4: Run test to verify it passes**

Run: the Step 2 command.
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add python/pyproject.toml python/uv.lock python/src/thoth_control_plane/config.py python/src/thoth_control_plane/domain/models.py python/tests/domain/test_attribution_events.py
git commit -m "feat(attribution): speech dependencies, model paths, failure codes"
```

---

### Task 2: Pinned speech models for the image and CI

**Files:**
- Create: `docker/fetch_speech_models.py`
- Modify: `Dockerfile` (after the second `uv sync`; extend the import check and the `USER thoth` test block)
- Modify: `.github/workflows/container-image.yml` and `.github/workflows/yt-dlp-update.yml` (one step before `uv run pytest`)
- Test: `python/tests/deployment/test_speech_models.py` (create)

**Interfaces:**
- Produces: `python docker/fetch_speech_models.py --whisper {tiny,large-v3-turbo} --out <dir>`. It writes `<out>/whisper-<size>/` (CTranslate2 files) and `<out>/diarization/{segmentation,embedding}.onnx`, verifies each pinned SHA-256, and exits non-zero on any mismatch.

- [ ] **Step 1: Resolve the pins (network, dev tooling only)**

Record the commit of each Hugging Face repo and the GitHub release assets:

```bash
for repo in Systran/faster-whisper-tiny mobiuslabsgmbh/faster-whisper-large-v3-turbo; do
  curl -s "https://huggingface.co/api/models/$repo/revision/main" | python -c "import sys,json;print('$repo', json.load(sys.stdin)['sha'])"
done
```

The assets are:
- `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2` (use `model.onnx` inside it);
- `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx`.

Download each file once into `D:/thoth-tmp/bu/models/` and record its `sha256sum`: the two `model.bin` files, the segmentation `model.onnx`, and the embedding onnx.

- [ ] **Step 2: Write the failing test**

```python
"""The speech-model fetcher pins every file and refuses a mismatch."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "docker" / "fetch_speech_models.py"


def _module():
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/deployment/test_speech_models.py -p no:warnings`
Expected: FAIL (`FileNotFoundError` for the script).

- [ ] **Step 4: Implement the fetcher**

Fill the pins with the values from Step 1. `huggingface_hub` ships with faster-whisper.

```python
"""Fetch the pinned speech models: whisper (CTranslate2) and the two diarization ONNX files.

Run by the Docker build (large-v3-turbo) and by CI (tiny, for tests). Every file is pinned by
revision or URL and verified by SHA-256; a mismatch exits non-zero (operator, 2026-10-13:
models are baked, never downloaded at run time).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

WHISPER = {
    "tiny": {
        "repo": "Systran/faster-whisper-tiny",
        "revision": "<40-hex from Step 1>",
        "model_sha256": "<64-hex from Step 1>",
    },
    "large-v3-turbo": {
        "repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "revision": "<40-hex from Step 1>",
        "model_sha256": "<64-hex from Step 1>",
    },
}
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
DIARIZATION = {
    "segmentation.onnx": {
        "url": f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
        "member": "sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
        "sha256": "<64-hex of model.onnx from Step 1>",
    },
    "embedding.onnx": {
        "url": f"{RELEASES}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx",
        "member": None,
        "sha256": "<64-hex from Step 1>",
    },
}


def verify(path: Path, expected: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        sys.exit(f"checksum mismatch for {path.name}")


def fetch_whisper(size: str, out: Path) -> None:
    from huggingface_hub import snapshot_download

    pin = WHISPER[size]
    target = out / f"whisper-{size}"
    snapshot_download(pin["repo"], revision=pin["revision"], local_dir=target)
    verify(target / "model.bin", pin["model_sha256"])


def fetch_diarization(out: Path) -> None:
    target = out / "diarization"
    target.mkdir(parents=True, exist_ok=True)
    for name, asset in DIARIZATION.items():
        with tempfile.TemporaryDirectory() as scratch:
            download = Path(scratch) / "download"
            with urllib.request.urlopen(asset["url"], timeout=120) as response:  # noqa: S310
                download.write_bytes(response.read())
            if asset["member"] is not None:
                with tarfile.open(download) as archive:
                    member = archive.extractfile(asset["member"])
                    if member is None:
                        sys.exit(f"{asset['member']} missing from the archive")
                    (target / name).write_bytes(member.read())
            else:
                shutil.copyfile(download, target / name)
        verify(target / name, asset["sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper", choices=sorted(WHISPER), required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    fetch_whisper(arguments.whisper, arguments.out)
    fetch_diarization(arguments.out)
```

- [ ] **Step 5: Run the test, then fetch the test models into WSL**

Run: the Step 3 command.
Expected: 2 passed.

Then fetch the models the adapter tests use:

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uv run --no-project --python 3.12 --with faster-whisper python ../docker/fetch_speech_models.py --whisper tiny --out $HOME/thoth-models'
```

Expected: `$HOME/thoth-models/whisper-tiny/model.bin` and `$HOME/thoth-models/diarization/{segmentation,embedding}.onnx` exist.

- [ ] **Step 6: Wire the image and CI**

In `Dockerfile`, after the second `uv sync`:

```dockerfile
COPY --chown=thoth:thoth docker/fetch_speech_models.py /opt/thoth/bin/fetch_speech_models.py
RUN /opt/thoth/python/.venv/bin/python /opt/thoth/bin/fetch_speech_models.py \
        --whisper large-v3-turbo --out /opt/thoth/models \
    && chown -R thoth:thoth /opt/thoth/models
```

Add `faster_whisper, sherpa_onnx` to the existing `python -c "import scrapling, thoth_control_plane, cv2, rapidocr, openai"` check. In the `USER thoth` block, add:

```dockerfile
    && test -r /opt/thoth/models/whisper-large-v3-turbo/model.bin \
    && test -r /opt/thoth/models/diarization/segmentation.onnx \
    && test -r /opt/thoth/models/diarization/embedding.onnx \
```

In both workflows, add a step before the `uv run pytest` step, with the same `working-directory` as the test step:

```yaml
      - name: Fetch speech test models
        run: uv run python ../docker/fetch_speech_models.py --whisper tiny --out "$RUNNER_TEMP/models"
```

Add to the pytest step's `env`:

```yaml
          THOTH_TEST_WHISPER_MODEL_DIR: ${{ runner.temp }}/models/whisper-tiny
          THOTH_TEST_DIARIZATION_MODEL_DIR: ${{ runner.temp }}/models/diarization
```

Then lint the workflows (memory: a parse error yields a run with zero jobs):

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && (command -v actionlint || ~/.local/bin/actionlint) >/dev/null && actionlint .github/workflows/*.yml'
```

Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add docker/fetch_speech_models.py Dockerfile .github/workflows/container-image.yml .github/workflows/yt-dlp-update.yml python/tests/deployment/test_speech_models.py
git commit -m "build: bake pinned whisper and diarization models"
```

---

### Task 3: Vision and Jev required; errors stop attribution

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/ports.py`
- Modify: `python/src/thoth_control_plane/attribution/adapters/vision.py`
- Modify: `python/src/thoth_control_plane/attribution/adapters/jev.py`
- Modify: `python/src/thoth_control_plane/attribution/service.py`
- Modify: `python/tests/attribution/replay.py`, `python/tests/attribution/test_service.py`, `python/tests/attribution/test_remote_adapters.py`
- Check: every fixture in `python/tests/fixtures/attribution/` has non-null `cover` and `decisions` (synthetic included). One without them gets both from its hand-written case, with a ledger ruling.

**Interfaces:**
- Produces:
  - `ports.AttributionError(code: str)` with `.code`.
  - `VisionReader.read_cover(...) -> CoverReading` and `.classify(...) -> VisualKind`: they never return `None`; they raise `AttributionError("vision_unavailable")`.
  - `DecisionModel.decide(...) -> Decisions`: raises `AttributionError("decision_unavailable")` after one retry.
  - `AttributionPorts(frames, matcher, text, discoverer, acquirer, vision, decisions)`: all required, in that order.
- Consumes: `attribution.adapters.frames.ToolMissing(code)`.

- [ ] **Step 1: Write the failing tests**

In `test_service.py`, delete these tests:
- `test_without_a_decision_key_one_found_handle_is_the_credit`
- `test_without_a_decision_key_a_caption_mention_alone_is_no_credit`
- `test_port_failures_degrade_instead_of_failing`

Add:

```python
from thoth_control_plane.attribution.ports import AttributionError


class _RaisingVision:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def read_cover(self, frames: Any) -> Any:
        raise AttributionError("vision_unavailable")

    async def classify(self, frames: Any) -> Any:
        raise AttributionError("vision_unavailable")


class _RaisingDecisions:
    async def decide(self, evidence: Any, handles: Any) -> Any:
        raise AttributionError("decision_unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("port", "code"), [("vision", "vision_unavailable"), ("decisions", "decision_unavailable")]
)
async def test_a_failing_vision_or_decision_stops_attribution(port: str, code: str) -> None:
    ports = replay_ports(_case())
    fake = _RaisingVision(ports.vision) if port == "vision" else _RaisingDecisions()
    object.__setattr__(ports, port, fake)

    with pytest.raises(AttributionError) as raised:
        await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)
    assert raised.value.code == code


@pytest.mark.asyncio
async def test_a_failing_classification_still_discards_finalists() -> None:
    case = _case(matches={}, unmatchable=["repost"])  # unmeasured: the genre check runs
    ports = replay_ports(case)
    object.__setattr__(ports, "vision", _RaisingVision(ports.vision))
    object.__setattr__(ports.vision, "read_cover", ReplayVisionCover(case))

    with pytest.raises(AttributionError):
        await SourceAttributor(ports, Tuning(finalist_concurrency=1)).identify(
            "wf_ref", parse_report(_report()), VIDEO
        )
    assert ports.acquirer.discarded == ports.acquirer.acquired


@pytest.mark.asyncio
async def test_a_missing_ffmpeg_stops_attribution() -> None:
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    class _NoFfmpeg:
        async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> Any:
            raise ToolMissing("ffmpeg_missing")

    ports = replay_ports(_case())
    object.__setattr__(ports, "frames", _NoFfmpeg())

    with pytest.raises(AttributionError) as raised:
        await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)
    assert raised.value.code == "ffmpeg_missing"
```

`ReplayVisionCover` goes into `replay.py`. It is a bound coroutine that returns the case's cover, so only `classify` raises:

```python
def ReplayVisionCover(case: dict[str, Any]):  # noqa: N802 - a factory used like a method
    async def read_cover(frames: Sequence[Frame]) -> CoverReading:
        return CoverReading(**case["cover"])

    return read_cover
```

In `test_remote_adapters.py`:
- replace `test_jev_failures_return_none` with the version below, asserting the raise and the retry;
- change `test_vision_classifies_and_degrades_to_none` so the 500 answer raises `AttributionError("vision_unavailable")`.

```python
async def test_jev_failures_raise_after_one_retry(response: httpx.Response) -> None:
    route = respx.post(JEV_URL).mock(return_value=response)

    with pytest.raises(AttributionError) as raised:
        await JevDecisionModel("synthetic-jev-key").decide({}, [SOURCE])
    assert raised.value.code == "decision_unavailable"
    assert route.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: FAIL with `ImportError: cannot import name 'AttributionError'`.

- [ ] **Step 3: Implement**

`ports.py`. Add the error and tighten the return types:

```python
class AttributionError(Exception):
    """A required tool, model, or provider could not do its job: never a degraded verdict.

    Operator, 2026-10-13: vision and Jev are required, and a failure is an explicit error that
    fails the workflow. External content (discovery, candidates) still degrades.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
```

Then change the port signatures to `read_cover(...) -> CoverReading`, `classify(...) -> VisualKind`, and `decide(...) -> Decisions`. Rewrite the module docstring's first paragraph: "A port that cannot do its job raises `AttributionError`; a port about external content may raise anything else, and the service degrades that evidence or candidate."

`adapters/vision.py`, in `_run`:

```python
        try:
            run = await agent.arun(input=prompt, images=images)
        except Exception as error:
            raise AttributionError("vision_unavailable") from error
        if not isinstance(run.content, schema):
            raise AttributionError("vision_unavailable")
        return run.content
```

`read_cover` returns `await self._run(...)`, and `classify` returns `(await self._run(...)).kind`. The return types drop `| None`.

`adapters/jev.py`. Add a shared `_post` with one retry, and make `decide` use it:

```python
ATTEMPTS = 2

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(ATTEMPTS):
            try:
                async with self._session() as client:
                    response = await client.post(
                        JEV_URL,
                        json=body,
                        headers={"Authorization": f"Bearer {self._key}"},
                        timeout=TIMEOUT_SECONDS,
                    )
                response.raise_for_status()
                return response.json()["answers"]
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                if attempt + 1 == ATTEMPTS:
                    logger.warning("jev decision unavailable after retry")
                    raise AttributionError("decision_unavailable") from None
        raise AssertionError("unreachable")
```

In `decide`, replace the `try/except` with:

```python
        answers = await self._post(
            {"model": JEV_MODEL, "state": evidence, "questions": questions}
        )
        try:
            return _parse(answers, handles)
        except (ValueError, KeyError, TypeError):
            raise AttributionError("decision_unavailable") from None
```

`service.py`:
- `AttributionPorts`: drop the `= None` defaults on `vision` and `decisions`.
- `_guard`: add `except AttributionError: raise` before `except Exception`, and map `ToolMissing`:

```python
    async def _guard(self, awaitable: Awaitable[T], what: str) -> T | None:
        try:
            return await awaitable
        except asyncio.CancelledError:
            raise
        except AttributionError:
            raise
        except ToolMissing as missing:
            raise AttributionError(missing.code) from missing
        except Exception:
            logger.warning("source attribution %s unavailable; continuing without it", what)
            return None
```

- Vision and decisions are called directly, not through `_guard`. `_cover` becomes `return await self._ports.vision.read_cover(frames[:3]) if frames else None`. `_check` calls `kind = await self._ports.vision.classify(frames[:3])` without the `if self._ports.vision is not None` guard.
- `_credit`: delete the `if self._ports.decisions is not None:` wrapper and the rules-only tail, starting at the `# Without the model only an on-screen handle...` comment. The decision is now `decided = await self._ports.decisions.decide(state, options)`. Keep the text-rule branch first.
- Remove `ambiguous` from `_Credit` and the `ambiguous_credit` branch in `identify`. Only the rules path set it, so its reason code becomes unreachable.

`replay.py`:
- `replay_ports` always builds `ReplayVision(case["cover"], case.get("classify", {}))` and `ReplayDecisions(case["decisions"])`.
- `ReplayVision.read_cover` returns `CoverReading(**self._cover)`.
- Hand cases in `test_service.py` that passed `decisions=None` or `vision=False` are already deleted. Fix any remaining one by giving it a decision.

- [ ] **Step 4: Run tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution tests/activities -p no:warnings`
Expected: all pass. `test_production_ports_follow_the_configured_keys` may fail on the key-less branch; Task 11 rewrites it, so mark it with a ledger ruling now if needed and leave the fix to Task 11.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/attribution python/tests/attribution
git commit -m "feat(attribution): vision and Jev are required; failures raise"
```

---

### Task 4: Scene cuts and vision frame choice

**Files:**
- Create: `python/src/thoth_control_plane/attribution/scenes.py`
- Modify: `python/src/thoth_control_plane/attribution/adapters/frames.py` (add `FfmpegSceneDetector`)
- Modify: `python/src/thoth_control_plane/attribution/ports.py` (add `SceneDetector`)
- Test: `python/tests/attribution/test_scenes.py` (create), `python/tests/attribution/test_local_adapters.py`

**Interfaces:**
- Produces:
  - `scenes.Shot(start: float, end: float, shows: str = "other")` (frozen dataclass).
  - `scenes.shots(cuts: Sequence[float], end: float) -> list[Shot]`.
  - `scenes.vision_frames(frames: Sequence[Frame], shots: Sequence[Shot]) -> list[Frame]`.
  - `scenes.label(shots: Sequence[Shot], sent: Sequence[Frame], shows: Sequence[str]) -> list[Shot]`.
  - `ports.SceneDetector.cuts(video: Path) -> list[float]`.
  - `FfmpegSceneDetector(ffmpeg: str = "ffmpeg")`.
  - Constants `MAX_VISION_FRAMES = 6`, `MIN_SHOT = 1.0`, `SCENE_THRESHOLD = 0.3`.

- [ ] **Step 1: Write the failing tests**

`tests/attribution/test_scenes.py`:

```python
"""Shots from scene cuts, and the frames the vision call sees."""

from __future__ import annotations

from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.attribution.scenes import Shot, label, shots, vision_frames


def _frames(count: int) -> list[Frame]:
    return [Frame(float(n), f"r:{n}".encode()) for n in range(count)]


def test_cuts_split_the_video_and_short_shots_merge() -> None:
    assert shots([3.0, 3.4, 20.0], 30.0) == [Shot(0.0, 3.4), Shot(3.4, 20.0), Shot(20.0, 30.0)]
    assert shots([], 12.0) == [Shot(0.0, 12.0)]


def test_vision_sees_the_cover_and_the_middle_of_the_longest_shots() -> None:
    frames = _frames(70)
    cut = shots([3.0, 40.0, 41.5, 60.0], 70.0)

    seconds = [frame.second for frame in vision_frames(frames, cut)]

    # 0 s and 1 s always; then the middles of the longest shots (21.5, 65, 1.5 dropped as a dup
    # of the cover shot only when its middle falls on 0 or 1).
    assert seconds[:2] == [0.0, 1.0]
    assert 21.0 in seconds or 22.0 in seconds
    assert len(seconds) <= 6
    assert seconds == sorted(seconds)


def test_a_clip_then_talk_reaction_is_seen_in_both_shots() -> None:
    frames = _frames(70)
    seconds = [f.second for f in vision_frames(frames, shots([3.0], 70.0))]

    assert any(s < 3.0 for s in seconds) and any(s > 30.0 for s in seconds)


def test_labels_follow_the_frame_inside_each_shot() -> None:
    cut = shots([3.0], 70.0)
    sent = [Frame(0.0, b""), Frame(1.0, b""), Frame(36.0, b"")]

    labelled = label(cut, sent, ["subject", "subject", "creator"])

    assert [shot.shows for shot in labelled] == ["subject", "creator"]


def test_a_short_shows_list_labels_nothing() -> None:
    cut = shots([3.0], 70.0)
    sent = [Frame(0.0, b""), Frame(36.0, b"")]

    assert [s.shows for s in label(cut, sent, ["creator"])] == ["other", "other"]
```

In `test_local_adapters.py`:

```python
@pytest.mark.asyncio
async def test_scene_detector_finds_the_cut_between_two_shots(ffmpeg: str, tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegSceneDetector

    video = tmp_path / "two.mp4"
    subprocess.run(
        [
            ffmpeg, "-v", "error",
            "-f", "lavfi", "-i", "testsrc=s=320x240:d=2:r=25",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2:r=25",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )

    cuts = await FfmpegSceneDetector(ffmpeg).cuts(video)

    assert len(cuts) == 1 and 1.9 <= cuts[0] <= 2.1


@pytest.mark.asyncio
async def test_scene_detector_without_ffmpeg_is_tool_missing(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegSceneDetector, ToolMissing

    with pytest.raises(ToolMissing) as raised:
        await FfmpegSceneDetector("/nonexistent/ffmpeg").cuts(tmp_path / "x.mp4")
    assert raised.value.code == "ffmpeg_missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_scenes.py tests/attribution/test_local_adapters.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: thoth_control_plane.attribution.scenes`.

- [ ] **Step 3: Implement**

`attribution/scenes.py`:

```python
"""Shots from scene cuts, the frames the vision call sees, and the label of each shot.

The cover call used to see only the first three seconds, so a reaction that opens on the
clip it shows looked like a plain repost (research 2026-10-13). Frames now come from the
cover and the middle of the longest shots.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from thoth_control_plane.attribution.ports import Frame

MAX_VISION_FRAMES = 6
MIN_SHOT = 1.0
COVER_SECONDS = (0.0, 1.0)


@dataclass(frozen=True)
class Shot:
    start: float
    end: float
    shows: str = "other"


def shots(cuts: Sequence[float], end: float) -> list[Shot]:
    bounds = [0.0, *sorted(c for c in cuts if 0.0 < c < end), end]
    merged: list[Shot] = []
    for start, stop in zip(bounds, bounds[1:], strict=False):
        if merged and stop - start < MIN_SHOT:
            merged[-1] = Shot(merged[-1].start, stop)
        else:
            merged.append(Shot(start, stop))
    return merged


def vision_frames(frames: Sequence[Frame], cut: Sequence[Shot]) -> list[Frame]:
    if not frames:
        return []
    chosen = {frame.second: frame for frame in frames if frame.second in COVER_SECONDS}
    for shot in sorted(cut, key=lambda s: s.end - s.start, reverse=True):
        if len(chosen) >= MAX_VISION_FRAMES:
            break
        middle = (shot.start + shot.end) / 2
        nearest = min(frames, key=lambda frame: abs(frame.second - middle))
        chosen.setdefault(nearest.second, nearest)
    return [chosen[second] for second in sorted(chosen)][:MAX_VISION_FRAMES]


def label(cut: Sequence[Shot], sent: Sequence[Frame], shows: Sequence[str]) -> list[Shot]:
    """Each shot takes the label of the last sent frame inside it; a list of the wrong length
    labels nothing (models drop items)."""
    if len(shows) != len(sent):
        return [replace(shot, shows="other") for shot in cut]
    labelled = []
    for shot in cut:
        inside = [s for f, s in zip(sent, shows, strict=True) if shot.start <= f.second < shot.end]
        labelled.append(replace(shot, shows=inside[-1] if inside else "other"))
    return labelled
```

Running `test_vision_sees_the_cover_and_the_middle_of_the_longest_shots` against this code tells you which middles are chosen. If the assertion's comment about `1.5` is wrong, rewrite the comment to state the observed order. Keep the asserted properties.

`ports.py`:

```python
class SceneDetector(Protocol):
    async def cuts(self, video: Path) -> list[float]: ...
```

`adapters/frames.py`:

```python
SCENE_THRESHOLD = 0.3
PTS_TIME = re.compile(rb"pts_time:(\d+(?:\.\d+)?)")


class FfmpegSceneDetector:
    """Shot cuts from ffmpeg's scene score, printed to stdout by the metadata filter."""

    def __init__(self, ffmpeg: str = "ffmpeg") -> None:
        self._ffmpeg = ffmpeg

    async def cuts(self, video: Path) -> list[float]:
        from thoth_control_plane.attribution.ports import AttributionError

        argv = [
            self._ffmpeg, "-v", "error", "-i", str(video), "-an",
            "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',metadata=print:file=-",
            "-f", "null", "-",
        ]
        try:
            code, output = await _run(argv, "ffmpeg_missing", capture=True)
        except FrameError:
            raise AttributionError("scene_detection_failed") from None
        if code != 0:
            raise AttributionError("scene_detection_failed")
        return [float(match.group(1)) for match in PTS_TIME.finditer(output)]
```

Add `import re` at the top of `frames.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: the Step 2 command.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/attribution/scenes.py python/src/thoth_control_plane/attribution/adapters/frames.py python/src/thoth_control_plane/attribution/ports.py python/tests/attribution/test_scenes.py python/tests/attribution/test_local_adapters.py
git commit -m "feat(attribution): pick vision frames from ffmpeg scene cuts"
```

---

### Task 5: Reaction fields in the cover reading; scene frames in the service

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/ports.py` (`CoverReading`)
- Modify: `python/src/thoth_control_plane/attribution/adapters/vision.py` (prompt, `COVER_FRAMES = 6`)
- Modify: `python/src/thoth_control_plane/attribution/service.py` (`AttributionPorts.scenes`, `_cover`)
- Modify: `python/tests/attribution/replay.py` (`ReplayScenes`)
- Test: `python/tests/attribution/test_service.py`, `python/tests/attribution/test_remote_adapters.py`

**Interfaces:**
- Consumes: `scenes.shots`, `scenes.vision_frames`, `scenes.label`, `SceneDetector` (Task 4).
- Produces:
  - `CoverReading.reaction_shape: ReactionShape = "none"`, `subject_media: SubjectMedia = "none"`, `shows: list[ShotLabel] = []`.
  - `AttributionPorts(..., vision, decisions, scenes)`.
  - `SourceAttributor._cover(frames, video) -> tuple[CoverReading | None, list[Shot]]`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_vision_sees_frames_from_every_long_shot() -> None:
    case = _case(cuts=[1.5])
    case["frames"]["repost"] = _frames(40)
    ports = replay_ports(case)

    await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)

    seconds = ports.vision.cover_seconds
    assert seconds[:2] == [0.0, 1.0] and any(s > 10 for s in seconds) and len(seconds) <= 6


def test_a_cover_reading_without_reaction_fields_is_not_a_reaction() -> None:
    reading = CoverReading(headline="x")
    assert (reading.reaction_shape, reading.subject_media, reading.shows) == ("none", "none", [])
```

In `test_remote_adapters.py`, extend `test_vision_reads_the_cover_from_jpeg_frames`: the mocked completion returns `reaction_shape`, `subject_media`, and `shows`, and the test asserts that they parse. Send 6 frames and assert 6 `image_url` parts reach the request.

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: FAIL (`cover_seconds` and the new fields do not exist).

- [ ] **Step 3: Implement**

`ports.py`:

```python
ReactionShape = Literal[
    "none", "screenshot", "picture_in_picture", "green_screen", "split_screen", "clip_then_talk"
]
SubjectMedia = Literal["video", "text", "image", "none", "unknown"]
ShotLabel = Literal["creator", "subject", "both", "other"]
```

Add these fields to `CoverReading`:

```python
    reaction_shape: ReactionShape = Field(
        default="none",
        description=(
            "none: an ordinary video; screenshot: a screenshot of another post fills the frame; "
            "picture_in_picture: a person in a small window over another video; green_screen: a "
            "person in front of another post or video; split_screen: two videos side by side or "
            "stacked; clip_then_talk: another video plays, then a person talks about it"
        ),
    )
    subject_media: SubjectMedia = Field(
        default="none",
        description="What the reacted-to post is: video, text, image; none when not a reaction",
    )
    shows: list[ShotLabel] = Field(
        default_factory=list,
        max_length=6,
        description=(
            "For each image in order: creator (the person making this video), subject (the "
            "other post or video), both, or other"
        ),
    )
```

In `_clip`, unknown literal values must not reject the whole reading. Before returning, coerce:
- an unknown `reaction_shape` to `"none"`;
- an unknown `subject_media` to `"unknown"`;
- each `shows` entry outside the literal to `"other"`, truncated to 6 entries.

`vision.py`:
- `COVER_FRAMES = 6`.
- `read_cover` sends `frames[:COVER_FRAMES]`; `classify` keeps `MAX_FRAMES = 3`.
- Extend `COVER_PROMPT`: "Also say whether this video reacts to another post: a screenshot of it, the other video inside this one, or a person talking about it. Say what that other post is (video, text, image) and, for each image in order, whether it shows the creator of this video, the other post, both, or neither."

`service.py`:
- Add `scenes: SceneDetector` as the last field of `AttributionPorts`.
- `_cover` becomes:

```python
    async def _cover(
        self, frames: list[Frame], video: Path | None
    ) -> tuple[CoverReading | None, list[Shot]]:
        if not frames or video is None:
            return None, []
        end = frames[-1].second + 1.0 / self._tuning.frame_fps
        cut = shots(await self._ports.scenes.cuts(video), end)
        sent = vision_frames(frames, cut)
        cover = await self._ports.vision.read_cover(sent)
        return cover, label(cut, sent, cover.shows)
```

`identify` unpacks `cover, labelled = await self._cover(frames, video)`. Task 9 consumes `labelled`.

`replay.py`:

```python
class ReplayScenes:
    def __init__(self, cuts: list[float]) -> None:
        self._cuts = cuts

    async def cuts(self, video: Path) -> list[float]:
        return list(self._cuts)
```

Also:
- `replay_ports` passes `scenes=ReplayScenes(case.get("cuts", []))`.
- `ReplayVision.read_cover` records `self.cover_seconds = [frame_key(f)[1] for f in frames]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: all pass. Every golden replays unchanged: no recorded cover has `reaction_shape`, so all default to `none`.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/attribution python/tests/attribution
git commit -m "feat(attribution): reaction shape, subject, and shot labels from vision"
```

---

### Task 6: Local transcription and speaker turns

**Files:**
- Create: `python/src/thoth_control_plane/attribution/adapters/speech.py`
- Modify: `python/src/thoth_control_plane/attribution/ports.py` (speech types and ports)
- Test: `python/tests/attribution/test_speech_adapters.py` (create)

**Interfaces:**
- Produces:
  - `ports.Segment(start: float, end: float, text: str)`, `ports.Transcript(language: str, segments: tuple[Segment, ...])`, `ports.Turn(start: float, end: float, speaker: int)`. All are frozen dataclasses.
  - `ports.Transcriber.transcribe(video: Path, *, seconds: float) -> Transcript`.
  - `ports.Diarizer.turns(video: Path, *, seconds: float) -> list[Turn]`.
  - `speech.WhisperTranscriber(model_dir: Path)`, `speech.SherpaDiarizer(model_dir: Path)`.
  - `speech.WHISPER_FILES = ("model.bin", "config.json", "tokenizer.json")`, `speech.DIARIZATION_FILES = ("segmentation.onnx", "embedding.onnx")`.
  - `speech.missing(directory: Path, names: Sequence[str]) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
"""faster-whisper and sherpa-onnx on clips made by ffmpeg; a missing model is an error."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.attribution.ports import AttributionError

FFMPEG = shutil.which("ffmpeg")


def _required(variable: str) -> Path:
    # Operator, 2026-10-11/13: a missing tool or model fails the test, never a skip.
    value = os.environ.get(variable)
    if not value or not Path(value).is_dir():
        pytest.fail(f"{variable} must point to the fetched test models (plan Task 2)")
    return Path(value)


@pytest.fixture
def whisper_dir() -> Path:
    return _required("THOTH_TEST_WHISPER_MODEL_DIR")


@pytest.fixture
def diarization_dir() -> Path:
    return _required("THOTH_TEST_DIARIZATION_MODEL_DIR")


def _clip(tmp_path: Path, *, audio: bool) -> Path:
    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    video = tmp_path / ("silent.mp4" if audio else "mute.mp4")
    argv = [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=3:r=25"]
    if audio:
        argv += ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3", "-shortest"]
    subprocess.run([*argv, "-pix_fmt", "yuv420p", str(video)], check=True)
    return video


@pytest.mark.asyncio
async def test_silence_is_an_empty_transcript_and_no_turns(
    tmp_path: Path, whisper_dir: Path, diarization_dir: Path
) -> None:
    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber

    video = _clip(tmp_path, audio=True)

    transcript = await WhisperTranscriber(whisper_dir).transcribe(video, seconds=180)
    turns = await SherpaDiarizer(diarization_dir).turns(video, seconds=180)

    assert transcript.segments == () and turns == []


@pytest.mark.asyncio
async def test_a_video_without_audio_is_an_empty_transcript(
    tmp_path: Path, whisper_dir: Path, diarization_dir: Path
) -> None:
    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber

    video = _clip(tmp_path, audio=False)

    assert (await WhisperTranscriber(whisper_dir).transcribe(video, seconds=180)).segments == ()
    assert await SherpaDiarizer(diarization_dir).turns(video, seconds=180) == []


@pytest.mark.asyncio
async def test_a_missing_model_directory_is_its_own_code(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber

    video = tmp_path / "x.mp4"
    with pytest.raises(AttributionError) as whisper:
        await WhisperTranscriber(tmp_path / "none").transcribe(video, seconds=180)
    with pytest.raises(AttributionError) as diarization:
        await SherpaDiarizer(tmp_path / "none").turns(video, seconds=180)
    assert (whisper.value.code, diarization.value.code) == (
        "whisper_model_missing",
        "diarization_model_missing",
    )


@pytest.mark.asyncio
async def test_an_unreadable_video_is_a_transcription_failure(
    tmp_path: Path, whisper_dir: Path
) -> None:
    from thoth_control_plane.attribution.adapters.speech import WhisperTranscriber

    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")

    with pytest.raises(AttributionError) as raised:
        await WhisperTranscriber(whisper_dir).transcribe(broken, seconds=180)
    assert raised.value.code == "transcription_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_speech_adapters.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: ...adapters.speech`.

- [ ] **Step 3: Implement**

`ports.py`:

```python
@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    language: str
    segments: tuple[Segment, ...] = ()


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: int


class Transcriber(Protocol):
    async def transcribe(self, video: Path, *, seconds: float) -> Transcript: ...


class Diarizer(Protocol):
    async def turns(self, video: Path, *, seconds: float) -> list[Turn]: ...
```

`adapters/speech.py`:

```python
"""Local speech: faster-whisper transcripts and sherpa-onnx speaker turns, CPU only.

Both models are baked into the image and loaded once per worker; a missing package or model
file is an `AttributionError` (operator, 2026-10-13). Audio is decoded with PyAV, which
faster-whisper ships with; a video without an audio stream yields no speech.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.attribution.ports import AttributionError, Segment, Transcript, Turn

SAMPLE_RATE = 16_000
WHISPER_FILES = ("model.bin", "config.json", "tokenizer.json")
DIARIZATION_FILES = ("segmentation.onnx", "embedding.onnx")
CLUSTER_THRESHOLD = 0.5


def missing(directory: Path, names: Sequence[str]) -> bool:
    return not all((directory / name).is_file() for name in names)


def _audio(video: Path, seconds: float, failure: str) -> Any:
    import numpy as np

    try:
        import av
        from faster_whisper import decode_audio

        with av.open(str(video)) as container:
            if not container.streams.audio:
                return np.zeros(0, dtype=np.float32)
        audio = decode_audio(str(video), sampling_rate=SAMPLE_RATE)
    except ImportError:
        raise AttributionError("whisper_missing") from None
    except Exception as error:
        raise AttributionError(failure) from error
    return audio[: int(seconds * SAMPLE_RATE)]


class WhisperTranscriber:
    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir
        self._model: Any = None
        self._lock = asyncio.Lock()

    async def transcribe(self, video: Path, *, seconds: float) -> Transcript:
        async with self._lock:  # ponytail: one transcription per worker; per-core pool if needed
            return await asyncio.to_thread(self._transcribe, video, seconds)

    def _load(self) -> Any:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise AttributionError("whisper_missing") from None
        if missing(self._dir, WHISPER_FILES):
            raise AttributionError("whisper_model_missing")
        if self._model is None:
            self._model = WhisperModel(
                str(self._dir), device="cpu", compute_type="int8", local_files_only=True
            )
        return self._model

    def _transcribe(self, video: Path, seconds: float) -> Transcript:
        model = self._load()
        audio = _audio(video, seconds, "transcription_failed")
        if audio.size == 0:
            return Transcript("")
        try:
            segments, info = model.transcribe(audio, vad_filter=True, beam_size=5)
            parts = tuple(
                Segment(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()
            )
        except Exception as error:
            raise AttributionError("transcription_failed") from error
        return Transcript(info.language, parts)


class SherpaDiarizer:
    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir
        self._engine: Any = None
        self._lock = asyncio.Lock()

    async def turns(self, video: Path, *, seconds: float) -> list[Turn]:
        async with self._lock:
            return await asyncio.to_thread(self._turns, video, seconds)

    def _load(self) -> Any:
        try:
            import sherpa_onnx
        except ImportError:
            raise AttributionError("diarization_missing") from None
        if missing(self._dir, DIARIZATION_FILES):
            raise AttributionError("diarization_model_missing")
        if self._engine is None:
            config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(self._dir / "segmentation.onnx")
                    )
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(self._dir / "embedding.onnx")
                ),
                clustering=sherpa_onnx.FastClusteringConfig(
                    num_clusters=-1, threshold=CLUSTER_THRESHOLD
                ),
                min_duration_on=0.3,
                min_duration_off=0.5,
            )
            if not config.validate():
                raise AttributionError("diarization_model_missing")
            self._engine = sherpa_onnx.OfflineSpeakerDiarization(config)
        return self._engine

    def _turns(self, video: Path, seconds: float) -> list[Turn]:
        engine = self._load()
        audio = _audio(video, seconds, "diarization_failed")
        if audio.size == 0:
            return []
        try:
            result = engine.process(audio).sort_by_start_time()
        except Exception as error:
            raise AttributionError("diarization_failed") from error
        return [Turn(r.start, r.end, int(r.speaker)) for r in result]
```

If sherpa-onnx rejects 3 s of silence with an exception, rather than returning no segments, treat audio below its window as empty. Record the observed behaviour as a ruling, and add a guard: when `audio.size < SAMPLE_RATE * 2`, return `[]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: the Step 2 command.
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/attribution/adapters/speech.py python/src/thoth_control_plane/attribution/ports.py python/tests/attribution/test_speech_adapters.py
git commit -m "feat(attribution): local transcripts and speaker turns"
```

---

### Task 7: Pure reaction logic

**Files:**
- Create: `python/src/thoth_control_plane/attribution/reaction.py`
- Modify: `python/src/thoth_control_plane/attribution/ports.py` (`Assessment`)
- Test: `python/tests/attribution/test_reaction.py` (create)

**Interfaces:**
- Consumes: `scenes.Shot` (Task 4), and `Transcript`, `Segment`, `Turn` (Task 6).
- Produces:
  - `ports.Assessment(contribution: float, discussion: float | None)` (frozen dataclass).
  - `reaction.Speech(creator: str, subject: str)`.
  - `reaction.ReactionCall(original: bool, reason: str)`.
  - `reaction.split_speech(transcript: Transcript, turns: Sequence[Turn], cut: Sequence[Shot]) -> Speech`.
  - `reaction.engagement_ratio(post_id: str, engagement: Mapping[str, int], videos: Sequence[DiscoveredVideo]) -> float | None`.
  - `reaction.judge(assessment: Assessment, ratio: float | None, *, contribution: float, discussion: float, engagement: float) -> ReactionCall`.
  - `reaction.MIN_BASELINE = 3`.

- [ ] **Step 1: Write the failing tests**

```python
"""Who said what, how a post did against its account, and the operator's decision rule."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.ports import Assessment, Segment, Transcript, Turn
from thoth_control_plane.attribution.reaction import (
    ReactionCall,
    engagement_ratio,
    judge,
    split_speech,
)
from thoth_control_plane.attribution.scenes import Shot

CLIP = Shot(0.0, 10.0, "subject")
TALK = Shot(10.0, 40.0, "creator")
TRANSCRIPT = Transcript(
    "id",
    (
        Segment(1.0, 8.0, "kata orang di video aslinya"),
        Segment(12.0, 30.0, "menurut saya ini masalah baru"),
    ),
)
TURNS = [Turn(0.5, 9.0, 0), Turn(11.0, 35.0, 1)]


def test_the_speaker_of_the_creator_shots_is_the_creator() -> None:
    speech = split_speech(TRANSCRIPT, TURNS, [CLIP, TALK])

    assert speech.creator == "menurut saya ini masalah baru"
    assert speech.subject == "kata orang di video aslinya"


def test_a_voice_over_takes_the_speaker_who_talks_most() -> None:
    speech = split_speech(TRANSCRIPT, TURNS, [Shot(0.0, 40.0, "subject")])

    assert speech.creator == "menurut saya ini masalah baru"


def test_without_turns_all_speech_is_the_creators() -> None:
    assert split_speech(TRANSCRIPT, [], [CLIP, TALK]).subject == ""


def _video(post_id: str, **engagement: int) -> DiscoveredVideo:
    return DiscoveredVideo.model_validate(
        {
            "post_id": post_id,
            "owner_handle": "kreator",
            "canonical_url": f"https://www.tiktok.com/@kreator/video/{post_id}",
            "engagement": engagement,
        }
    )


def test_the_ratio_compares_plays_with_the_median_of_other_videos() -> None:
    videos = [_video("11111", play=100), _video("22222", play=300), _video("33333", play=200)]

    assert engagement_ratio("99999", {"play": 400}, videos) == pytest.approx(2.0)


def test_the_post_itself_is_not_its_own_baseline() -> None:
    videos = [_video("99999", play=400), _video("11111", play=100), _video("22222", play=300)]

    assert engagement_ratio("99999", {"play": 400}, videos) is None  # two others: too few


def test_likes_stand_in_when_plays_are_hidden() -> None:
    videos = [_video(str(n) * 5, like=10) for n in range(1, 4)]

    assert engagement_ratio("99999", {"like": 5}, videos) == pytest.approx(0.5)


THRESHOLDS: dict[str, Any] = {"contribution": 0.5, "discussion": 0.5, "engagement": 1.0}


@pytest.mark.parametrize(
    ("assessment", "ratio", "expected"),
    [
        (Assessment(0.8, 0.7), 2.0, ReactionCall(True, "original_reaction")),
        (Assessment(0.3, 0.7), 2.0, ReactionCall(False, "no_new_contribution")),
        (Assessment(0.8, None), 2.0, ReactionCall(False, "no_comments")),
        (Assessment(0.8, 0.2), 2.0, ReactionCall(False, "comments_not_about_creator")),
        (Assessment(0.8, 0.7), None, ReactionCall(False, "engagement_unknown")),
        (Assessment(0.8, 0.7), 0.6, ReactionCall(False, "engagement_below_baseline")),
    ],
)
def test_each_condition_alone_keeps_a_reaction_a_repost(
    assessment: Assessment, ratio: float | None, expected: ReactionCall
) -> None:
    assert judge(assessment, ratio, **THRESHOLDS) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_reaction.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: ...attribution.reaction`.

- [ ] **Step 3: Implement**

`ports.py`:

```python
@dataclass(frozen=True)
class Assessment:
    """Jev's answer: P(contribution ≥ new viewpoint), and P(comments discuss the creator)."""

    contribution: float
    discussion: float | None
```

`attribution/reaction.py`:

```python
"""The reaction rule (operator, 2026-10-11/13), pure: who spoke, how the post did, the call.

A reaction is an original when it adds a new viewpoint or issue AND its comments discuss the
creator's take AND it beat its account's usual engagement. Anything unmeasured keeps it a
repost, so attribution goes on to look for the video it shows.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.ports import Assessment, Transcript, Turn
from thoth_control_plane.attribution.scenes import Shot

CREATOR_LABELS = frozenset({"creator", "both"})
MIN_BASELINE = 3


@dataclass(frozen=True)
class Speech:
    creator: str
    subject: str


@dataclass(frozen=True)
class ReactionCall:
    original: bool
    reason: str


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def split_speech(transcript: Transcript, turns: Sequence[Turn], cut: Sequence[Shot]) -> Speech:
    if not turns:
        return Speech(" ".join(s.text for s in transcript.segments), "")
    on_camera: Counter[int] = Counter()
    total: Counter[int] = Counter()
    for turn in turns:
        total[turn.speaker] += turn.end - turn.start
        for shot in cut:
            if shot.shows in CREATOR_LABELS:
                on_camera[turn.speaker] += _overlap(turn.start, turn.end, shot.start, shot.end)
    ranked = on_camera if any(value > 0 for value in on_camera.values()) else total
    creator = ranked.most_common(1)[0][0]
    mine: list[str] = []
    theirs: list[str] = []
    for segment in transcript.segments:
        best = max(turns, key=lambda t: _overlap(segment.start, segment.end, t.start, t.end))
        speaking = _overlap(segment.start, segment.end, best.start, best.end) > 0
        (mine if not speaking or best.speaker == creator else theirs).append(segment.text)
    return Speech(" ".join(mine), " ".join(theirs))


def engagement_ratio(
    post_id: str, engagement: Mapping[str, int], videos: Sequence[DiscoveredVideo]
) -> float | None:
    others = [video for video in videos if video.post_id != post_id]
    for key in ("play", "like"):
        own = engagement.get(key)
        baseline = [video.engagement[key] for video in others if key in video.engagement]
        if own is None or len(baseline) < MIN_BASELINE:
            continue
        median = statistics.median(baseline)
        return own / median if median > 0 else None
    return None


def judge(
    assessment: Assessment,
    ratio: float | None,
    *,
    contribution: float,
    discussion: float,
    engagement: float,
) -> ReactionCall:
    if assessment.contribution < contribution:
        return ReactionCall(False, "no_new_contribution")
    if assessment.discussion is None:
        return ReactionCall(False, "no_comments")
    if assessment.discussion < discussion:
        return ReactionCall(False, "comments_not_about_creator")
    if ratio is None:
        return ReactionCall(False, "engagement_unknown")
    if ratio < engagement:
        return ReactionCall(False, "engagement_below_baseline")
    return ReactionCall(True, "original_reaction")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: the Step 2 command.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/attribution/reaction.py python/src/thoth_control_plane/attribution/ports.py python/tests/attribution/test_reaction.py
git commit -m "feat(attribution): speech split, engagement ratio, reaction rule"
```

---

### Task 8: Jev assessment

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/adapters/jev.py`
- Modify: `python/src/thoth_control_plane/attribution/ports.py` (`DecisionModel.assess`)
- Test: `python/tests/attribution/test_remote_adapters.py`

**Interfaces:**
- Consumes: `JevDecisionModel._post` (Task 3), `ports.Assessment` (Task 7).
- Produces: `DecisionModel.assess(state: dict[str, object], *, with_comments: bool) -> Assessment`. It raises `AttributionError("decision_unavailable")`.
- Constant: `jev.CONTRIBUTION_LEVELS` (5 strings, index 3 = new viewpoint, 4 = new issue).

- [ ] **Step 1: Write the failing tests**

```python
CONTRIBUTION = {
    "type": "score",
    "score": 3.4,
    "confidence": 0.8,
    "probabilities": {"0": 0.0, "1": 0.05, "2": 0.15, "3": 0.5, "4": 0.3},
}


@pytest.mark.asyncio
@respx.mock
async def test_jev_assesses_contribution_and_discussion() -> None:
    route = respx.post(JEV_URL).mock(
        return_value=_answers(
            contribution=CONTRIBUTION,
            comments_discuss_creator={"type": "noul", "noul": 0.7},
        )
    )

    assessment = await JevDecisionModel("synthetic-jev-key").assess(
        {"creator_speech": "x"}, with_comments=True
    )

    assert assessment == Assessment(contribution=pytest.approx(0.8), discussion=0.7)
    questions = json.loads(route.calls.last.request.content)["questions"]
    assert questions["contribution"]["type"] == "score"
    assert questions["contribution"]["criteria"] == list(CONTRIBUTION_LEVELS)


@pytest.mark.asyncio
@respx.mock
async def test_without_comments_jev_is_not_asked_about_them() -> None:
    route = respx.post(JEV_URL).mock(return_value=_answers(contribution=CONTRIBUTION))

    assessment = await JevDecisionModel("synthetic-jev-key").assess({}, with_comments=False)

    assert assessment.discussion is None
    assert "comments_discuss_creator" not in json.loads(route.calls.last.request.content)["questions"]


@pytest.mark.asyncio
@respx.mock
async def test_a_malformed_score_is_decision_unavailable() -> None:
    respx.post(JEV_URL).mock(return_value=_answers(contribution={"type": "score"}))

    with pytest.raises(AttributionError) as raised:
        await JevDecisionModel("synthetic-jev-key").assess({}, with_comments=False)
    assert raised.value.code == "decision_unavailable"
```

Import `Assessment` from `attribution.ports` and `CONTRIBUTION_LEVELS` from `adapters.jev`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_remote_adapters.py -p no:warnings`
Expected: FAIL (`ImportError: CONTRIBUTION_LEVELS`).

- [ ] **Step 3: Implement**

```python
CONTRIBUTION = (
    "This post reacts to another post. Judge only what the creator adds in their own speech "
    "and text (creator_speech, caption), not what the other post says (subject_speech). "
    "Where does the creator's contribution fall?"
)
CONTRIBUTION_LEVELS = (
    "replays the other post with no comment of their own",
    "summarizes or retells the other post",
    "gives a plain opinion or feeling about it",
    "argues a new viewpoint on it",
    "raises a new issue or new information beyond it",
)
NEW_VIEWPOINT = 3
DISCUSSES_CREATOR = (
    "Do these comments discuss the creator's own take (agree, disagree, argue with or quote "
    "the creator), rather than only the event shown in the other post?"
)

    async def assess(self, state: dict[str, object], *, with_comments: bool) -> Assessment:
        questions: dict[str, Any] = {
            "contribution": {
                "type": "score",
                "instructions": CONTRIBUTION,
                "criteria": list(CONTRIBUTION_LEVELS),
            }
        }
        if with_comments:
            questions["comments_discuss_creator"] = {
                "type": "noul",
                "instructions": DISCUSSES_CREATOR,
            }
        answers = await self._post({"model": JEV_MODEL, "state": state, "questions": questions})
        try:
            levels = answers["contribution"]["probabilities"]
            contribution = sum(
                float(levels[str(index)])
                for index in range(NEW_VIEWPOINT, len(CONTRIBUTION_LEVELS))
            )
            discussion = (
                float(answers["comments_discuss_creator"]["noul"]) if with_comments else None
            )
        except (ValueError, KeyError, TypeError):
            raise AttributionError("decision_unavailable") from None
        return Assessment(min(1.0, max(0.0, contribution)), discussion)
```

`ports.DecisionModel` gains:

```python
    async def assess(self, state: dict[str, object], *, with_comments: bool) -> Assessment: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: the Step 2 command.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/attribution/adapters/jev.py python/src/thoth_control_plane/attribution/ports.py python/tests/attribution/test_remote_adapters.py
git commit -m "feat(attribution): Jev scores a reaction's contribution"
```

---

### Task 9: The reaction step in the service

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/models.py` (`EvidenceKind` gains `"reaction"`)
- Modify: `python/src/thoth_control_plane/attribution/service.py`
- Modify: `python/tests/attribution/replay.py` (`ReplayTranscriber`, `ReplayDiarizer`, `ReplayDecisions.assess`)
- Test: `python/tests/attribution/test_service.py`

**Interfaces:**
- Consumes: Tasks 4–8.
- Produces:
  - `AttributionPorts(..., scenes, transcriber: Transcriber, diarizer: Diarizer)`, all required.
  - `Tuning` gains `transcript_seconds: float = 180.0`, `reaction_contribution: float = 0.5`, `reaction_discussion: float = 0.5`, `reaction_engagement: float = 1.0`.
  - Replay case keys: `cuts`, `transcript` (`{"language", "segments": [[start, end, text]]}`), `turns` (`[[start, end, speaker]]`), `assessment` (`{"contribution", "discussion"}`), and `discovery.by_handle[<owner>]` for the baseline.

- [ ] **Step 1: Write the failing tests**

```python
REACTION_COVER = {
    "headline": "",
    "scene": "a woman talks to the camera after a news clip",
    "icon": "",
    "reaction_shape": "clip_then_talk",
    "subject_media": "video",
    "shows": ["subject", "subject", "creator", "creator"],
}
OWNER_VIDEOS = [
    {
        "post_id": str(500 + n),
        "owner_handle": "detikjatim",
        "canonical_url": f"https://www.tiktok.com/@detikjatim/video/{500 + n}",
        "engagement": {"play": 1000},
    }
    for n in range(5)
]


def _reaction_case(**overrides: Any) -> dict[str, Any]:
    case = _case(
        cover=REACTION_COVER,
        cuts=[3.0],
        transcript={
            "language": "id",
            "segments": [[0.5, 2.5, "klip aslinya"], [5.0, 30.0, "ini isu baru"]],
        },
        turns=[[0.0, 3.0, 0], [4.0, 35.0, 1]],
        assessment={"contribution": 0.8, "discussion": 0.7},
    )
    case["frames"]["repost"] = _frames(40)
    case["discovery"] = {
        "by_handle": {SOURCE: case["discovery"]["videos"], "detikjatim": OWNER_VIDEOS}
    }
    case.update(overrides)
    return case


def _reaction_report(**engagement: int) -> dict[str, Any]:
    report = _report()
    report["post"]["engagement"] = engagement or {"play": 5000}
    report["comments"] = [
        {"comment_id": "1", "author": "a.b", "text": "setuju sama kakaknya", "likes": 3}
    ]
    return report


@pytest.mark.asyncio
async def test_a_reaction_that_adds_and_is_discussed_is_an_original() -> None:
    outcome, ports = await _identify(_reaction_case(), _reaction_report())

    assert outcome.attribution.verdict == "original"
    assert outcome.original is None and ports.acquirer.acquired == []
    reaction = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert len(reaction) == 1 and "original_reaction" in reaction[0]
    assert "isu baru" not in reaction[0]  # no speech in the artifact
    state = ports.decisions.assessed[0]
    assert state["creator_speech"] == "ini isu baru"
    assert state["subject_speech"] == "klip aslinya"


@pytest.mark.asyncio
async def test_a_reaction_to_a_text_post_is_an_original_without_transcription() -> None:
    case = _reaction_case(cover={**REACTION_COVER, "subject_media": "text"})

    outcome, ports = await _identify(case, _reaction_report())

    assert outcome.attribution.verdict == "original"
    assert ports.transcriber.calls == 0 and ports.decisions.assessed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"assessment": {"contribution": 0.2, "discussion": 0.9}}, "no_new_contribution"),
        ({"assessment": {"contribution": 0.9, "discussion": 0.1}}, "comments_not_about_creator"),
    ],
)
async def test_a_reaction_judged_a_repost_goes_on_to_find_its_video(
    change: dict[str, Any], reason: str
) -> None:
    outcome, _ = await _identify(_reaction_case(**change), _reaction_report())

    assert outcome.attribution.verdict == "replaced"
    details = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert reason in details[0]


@pytest.mark.asyncio
async def test_no_comments_or_no_baseline_keeps_it_a_repost() -> None:
    quiet = _reaction_report()
    quiet["comments"] = []
    unknown = _reaction_case()
    unknown["discovery"]["by_handle"]["detikjatim"] = []

    first, _ = await _identify(_reaction_case(), quiet)
    second, _ = await _identify(unknown, _reaction_report())

    assert first.attribution.verdict == second.attribution.verdict == "replaced"


@pytest.mark.asyncio
async def test_a_silent_reaction_is_judged_on_text_alone() -> None:
    case = _reaction_case(transcript={"language": "", "segments": []}, turns=[])

    outcome, ports = await _identify(case, _reaction_report())

    assert ports.decisions.assessed[0]["creator_speech"] == ""
    assert outcome.attribution.verdict == "original"  # the recorded assessment decides


@pytest.mark.asyncio
async def test_a_non_reaction_never_transcribes() -> None:
    _, ports = await _identify(_case())

    assert ports.transcriber.calls == 0 and ports.decisions.assessed == []


@pytest.mark.asyncio
async def test_a_failing_transcription_stops_attribution() -> None:
    case = _reaction_case(transcript="raise:transcription_failed")

    with pytest.raises(AttributionError) as raised:
        await _identify(case, _reaction_report())
    assert raised.value.code == "transcription_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_service.py -p no:warnings`
Expected: FAIL (replay ports lack `transcriber`; verdicts differ).

- [ ] **Step 3: Implement the replay ports**

In `replay.py`:

```python
class ReplayTranscriber:
    def __init__(self, recorded: Any) -> None:
        self._recorded = recorded
        self.calls = 0

    async def transcribe(self, video: Path, *, seconds: float) -> Transcript:
        self.calls += 1
        if isinstance(self._recorded, str) and self._recorded.startswith("raise:"):
            raise AttributionError(self._recorded.removeprefix("raise:"))
        if self._recorded is None:
            raise AssertionError("this case recorded no transcript")
        return Transcript(
            self._recorded["language"],
            tuple(Segment(*segment) for segment in self._recorded["segments"]),
        )


class ReplayDiarizer:
    def __init__(self, recorded: list[list[Any]] | None) -> None:
        self._recorded = recorded

    async def turns(self, video: Path, *, seconds: float) -> list[Turn]:
        if self._recorded is None:
            raise AssertionError("this case recorded no turns")
        return [Turn(start, end, int(speaker)) for start, end, speaker in self._recorded]
```

`ReplayDecisions` gains `self.assessed: list[dict[str, object]] = []` and:

```python
    async def assess(self, state: dict[str, object], *, with_comments: bool) -> Assessment:
        self.assessed.append(state)
        recorded = self._assessment or {"contribution": 0.0, "discussion": None}
        return Assessment(
            recorded["contribution"], recorded["discussion"] if with_comments else None
        )
```

Its constructor takes `assessment: dict[str, Any] | None`. `replay_ports` passes `case.get("assessment")`, `transcriber=ReplayTranscriber(case.get("transcript"))`, and `diarizer=ReplayDiarizer(case.get("turns"))`.

- [ ] **Step 4: Implement the service step**

`models.py`: add `"reaction"` to `EvidenceKind`.

`service.py`. Add the ports and tuning from the Interfaces block. In `identify`, after `evidence = _text_evidence(...)` and before `on_screen = ...`:

```python
        if cover is not None and video is not None and cover.reaction_shape != "none":
            if await self._reaction(report, video, cover, labelled, lines, evidence):
                return self._finish(workflow_id, report, "original", evidence, confidence="high")
```

The method:

```python
    async def _reaction(
        self,
        report: SourceReport,
        video: Path,
        cover: CoverReading,
        labelled: list[Shot],
        lines: list[str],
        evidence: list[AttributionEvidence],
    ) -> bool:
        """Spec 2026-10-13: is this reaction an original? Unmeasured parts keep it a repost."""
        shape = cover.reaction_shape
        if cover.subject_media in ("text", "image"):
            evidence.append(
                AttributionEvidence(
                    kind="reaction", detail=f"{shape} reaction to a {cover.subject_media} post"
                )
            )
            return True
        seconds = self._tuning.transcript_seconds
        transcript = await self._ports.transcriber.transcribe(video, seconds=seconds)
        turns = await self._ports.diarizer.turns(video, seconds=seconds)
        speech = split_speech(transcript, turns, labelled)
        comments = [comment.text for comment in report.comments][:12]
        assessment = await self._ports.decisions.assess(
            {
                "caption": report.post.text[:2000],
                "frame_text": " | ".join(lines)[:2000],
                "headline": cover.headline,
                "scene": cover.scene,
                "reaction_shape": shape,
                "creator_speech": speech.creator[:6000],
                "subject_speech": speech.subject[:6000],
                "comments": comments,
            },
            with_comments=bool(comments),
        )
        platform = report.source.platform
        videos = (
            await self._guard(
                self._ports.discoverer.discover(platform, report.post.owner_handle), "baseline"
            )
            if self._ports.discoverer.supports(platform)
            else None
        )
        ratio = engagement_ratio(report.post.post_id, report.post.engagement, videos or [])
        call = judge(
            assessment,
            ratio,
            contribution=self._tuning.reaction_contribution,
            discussion=self._tuning.reaction_discussion,
            engagement=self._tuning.reaction_engagement,
        )
        discussion = "-" if assessment.discussion is None else f"{assessment.discussion:.2f}"
        engagement = "-" if ratio is None else f"{ratio:.1f}x"
        evidence.append(
            AttributionEvidence(
                kind="reaction",
                detail=(
                    f"{shape}, {cover.subject_media} subject, contribution "
                    f"{assessment.contribution:.2f}, discussion {discussion}, engagement "
                    f"{engagement}: {call.reason}"
                )[:300],
                confidence=assessment.contribution,
            )
        )
        return call.original
```

Add the imports: `Shot` from `scenes`; `split_speech`, `engagement_ratio`, `judge` from `reaction`; `Transcriber`, `Diarizer` from `ports`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: all pass. Every existing golden replays unchanged, because none has a reaction shape yet.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/attribution python/tests/attribution
git commit -m "feat(attribution): reactions that add and are discussed are originals"
```

---

### Task 9a: A thin anonymous listing leases a signed-in account

Operator, 2026-10-13: "where a feature is weaker signed out, use the login option with a proxy". The engagement baseline needs at least 4 videos, but X signed out lists about 5 posts, and TikTok blocks the server IP. Today `fallback` mode leases an account only after an empty, blocked listing.

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/adapters/discovery.py` (`ProfileDiscoverer.discover`)
- Modify: `python/src/thoth_control_plane/attribution/service.py` (warn on an unknown baseline)
- Test: `python/tests/attribution/test_discovery.py`, `python/tests/attribution/test_service.py`

**Interfaces:**
- Produces: `discovery.THIN_LISTING = 10`. `ProfileDiscoverer.discover` keeps its signature.

- [ ] **Step 1: Write the failing tests**

Read the fakes at the top of `test_discovery.py` first, and write these tests with them:

```python
def _videos(count: int) -> list[DiscoveredVideo]:
    return [
        VIDEO.model_copy(
            update={
                "post_id": str(7677137235434687000 + n),
                "canonical_url": f"https://www.tiktok.com/@{SOURCE}/video/{7677137235434687000 + n}",
            }
        )
        for n in range(count)
    ]


@pytest.mark.asyncio
async def test_fallback_leases_an_account_when_the_anonymous_listing_is_thin() -> None:
    fake = FakeDiscovery(_result(_videos(5)), _result(_videos(30)))  # X signed out: ~5 posts
    leases = FakeLeases("fallback")

    assert len(await _discover(fake, leases)) == 30
    assert (fake.built_with, leases.released) == ([None, ACCESS], ["success"])


@pytest.mark.asyncio
async def test_a_thin_listing_without_an_account_is_still_returned() -> None:
    fake = FakeDiscovery(_result(_videos(5)), _result([]))

    assert len(await _discover(fake, FakeLeases("fallback", available=False))) == 5


@pytest.mark.asyncio
async def test_the_longer_listing_wins() -> None:
    fake = FakeDiscovery(_result(_videos(6)), _result(_videos(2)))
    leases = FakeLeases("fallback")

    assert len(await _discover(fake, leases)) == 6
    assert leases.released == ["success"]
```

The existing `test_fallback_keeps_an_anonymous_success_without_an_account` lists one video, which is now a thin listing. Change its anonymous result to `_result(_videos(10))` and its assertion to `len(...) == 10`. It still asserts `built_with == [None]` and no release: a full listing never leases.

In `test_service.py`, in `test_no_comments_or_no_baseline_keeps_it_a_repost`, add `caplog` and assert that a warning containing `reaction baseline unavailable` is logged for the unknown-baseline case.

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_discovery.py tests/attribution/test_service.py -p no:warnings`
Expected: FAIL (the thin listing is returned without a lease; no warning).

- [ ] **Step 3: Implement**

```python
# X shows about 5 posts signed out; a signed-in listing is fuller (operator, 2026-10-13).
THIN_LISTING = 10

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        mode: Mode = await self._leases.mode(platform) if self._leases else "anonymous"
        anonymous: DiscoveryResult | None = None
        if mode != "always":
            anonymous = await self._run(platform, handle, None)
            thin = 0 < len(anonymous.videos) < THIN_LISTING
            blocked = not anonymous.videos and anonymous.reason in RETRY_REASONS
            if mode == "anonymous" or not (thin or blocked):
                return _videos(anonymous)
        assert self._leases is not None  # a leasing mode implies a lease source
        lease = await self._leases.lease(platform)
        if lease is None:
            logger.info("no source account for discovery platform=%s mode=%s", platform, mode)
            if anonymous is not None and anonymous.videos:
                return _videos(anonymous)
            if mode == "always":
                return _videos(await self._run(platform, handle, None))
            raise DiscoveryBlocked(f"{platform} discovery blocked and no source account to lease")
        outcome: Outcome | None = None
        try:
            result = await self._run(platform, handle, lease.access)
            if result.videos:
                outcome = "success"
            elif result.reason in RETRY_REASONS:
                outcome = "blocked"
        finally:
            await self._leases.release(lease, outcome)
        logger.info("discovery used a source account platform=%s outcome=%s", platform, outcome)
        if anonymous is not None and len(anonymous.videos) > len(result.videos):
            return _videos(anonymous)
        return _videos(result)
```

In `service._reaction`, after computing `ratio`:

```python
        if ratio is None:
            logger.warning("reaction baseline unavailable platform=%s", platform)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: the Step 2 command.
Expected: all pass, including the seven existing discovery tests.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/attribution/adapters/discovery.py python/src/thoth_control_plane/attribution/service.py python/tests/attribution/test_discovery.py python/tests/attribution/test_service.py
git commit -m "feat(discovery): lease an account when the signed-out listing is thin"
```

---

### Task 10: Typed failure through the activity and the workflow

**Files:**
- Modify: `python/src/thoth_control_plane/activities/source_attribution.py`
- Modify: `python/src/thoth_control_plane/workflows/source_investigation.py:178-182, 316-357`
- Test: `python/tests/activities/test_source_attribution.py`, `python/tests/workflows/test_source_investigation.py`

**Interfaces:**
- Consumes: `AttributionError` (Task 3), `ATTRIBUTION_REASONS` (Task 1).
- Produces:
  - `SourceAttributionActivityResult.failure: ReasonCode | None = None`. When it is set, `verdict == "unresolved"` and both artifacts are `None`.
  - `_event(verdict, elapsed_ms, status, reason=None)`.
  - Workflow failure `source_attribution_failed`, stage `attribution`, `retryable=True`.

- [ ] **Step 1: Write the failing tests**

In `tests/activities/test_source_attribution.py`:

```python
@pytest.mark.asyncio
async def test_a_required_tool_failure_is_a_typed_failure(tmp_path: Path) -> None:
    class _Failing:
        async def identify(self, workflow_id: str, report: Any, video: Any) -> Any:
            raise AttributionError("decision_unavailable")

    _write_report(tmp_path)  # the file's existing helper that writes a v3 report
    activity_fn = build_source_attribution_activity(_settings(tmp_path), attributor=_Failing())

    result = await activity_fn(SourceAttributionActivityInput(workflow_id="wf_test"))

    assert result.failure == "decision_unavailable"
    assert result.attribution is None
    assert result.events[0].payload["reason"] == "decision_unavailable"
    assert not (tmp_path / "reports" / "wf_test" / "source-attribution.json").exists()
```

Use the file's own helper names for writing the report and building settings; read the top of the file first.

In `tests/workflows/test_source_investigation.py`, add a `failing_attribute` activity next to `fake_attribute`. It returns `SourceAttributionActivityResult(verdict="unresolved", failure="vision_unavailable", events=[...failed event with reason...])`. Add the test:

```python
@pytest.mark.asyncio
async def test_a_failed_attribution_fails_the_workflow_with_its_reason(
    workflow_env: WorkflowEnvironment,
) -> None:
    async with Worker(
        workflow_env.client,
        task_queue="test",
        workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, failing_attribute],
    ):
        handle = await workflow_env.client.start_workflow(
            SourceInvestigationWorkflow.run,
            args=[_assembled()],
            id="wf_test_attribution_failed",
            task_queue="test",
        )
        result = await handle.result()
        events = await handle.query(SourceInvestigationWorkflow.source_events)

    assert result.status == "failed" and result.failure is not None
    assert (result.failure.code, result.failure.failed_stage) == (
        "source_attribution_failed",
        "attribution",
    )
    assert any(e.payload.get("reason") == "vision_unavailable" for e in events)
```

`_assembled()` turns assembly on. Assembly must never run after a failed attribution, so the worker does not register an assemble activity: if it ran, the workflow would hang on an unregistered activity, and that also fails the test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/activities/test_source_attribution.py tests/workflows/test_source_investigation.py -p no:warnings`
Expected: FAIL (`failure` is not a field).

- [ ] **Step 3: Implement**

Activity:
- `SourceAttributionActivityResult` gains `failure: ReasonCode | None = None`, with `ReasonCode` imported from `attribution.models`.
- `_event` gains `reason: str | None = None` and adds `"reason": reason` to the payload when it is set.
- In `_run`, before the generic `except Exception`:

```python
    except AttributionError as error:
        logger.warning("source attribution stopped: %s", error.code)
        elapsed = int((time.monotonic() - started) * 1000)
        return SourceAttributionActivityResult(
            verdict="unresolved",
            failure=error.code,
            events=[_event("unresolved", elapsed, "failed", error.code)],
        )
```

Workflow:
- `_attribute` returns `bool`: `True` on success, on cancel, and on `ActivityError` (today's behaviour), and `False` when `result.failure is not None`. In the failure case, extend the events, record `STAGE_COMPLETED`, and return before storing artifacts.
- In `run`:

```python
                if input_.attribute_source:
                    attributed = await self._attribute()
                    if self._cancel_requested:
                        self._transition(WorkflowStatus.CANCELLED)
                        self._record_event(EventKind.WORKFLOW_CANCELLED)
                        return self._summary()
                    if not attributed:
                        self._failure = WorkflowFailure(
                            code="source_attribution_failed",
                            message="Source attribution failed",
                            failed_stage="attribution",
                            retryable=True,
                        )
                        self._transition(WorkflowStatus.FAILED)
                        self._record_event(EventKind.WORKFLOW_FAILED)
                        return self._summary()
```

Update the `_attribute` docstring: "a failed tool, model, or provider fails the workflow; external content never does."

- [ ] **Step 4: Run tests to verify they pass**

Run: the Step 2 command.
Expected: all pass, including every existing workflow test.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/activities/source_attribution.py python/src/thoth_control_plane/workflows/source_investigation.py python/tests/activities/test_source_attribution.py python/tests/workflows/test_source_investigation.py
git commit -m "feat(attribution): a required-tool failure fails the workflow"
```

---

### Task 11: Production wiring and the worker start check

**Files:**
- Modify: `python/src/thoth_control_plane/activities/source_attribution.py` (`build_production_ports`)
- Modify: `python/src/thoth_control_plane/worker.py` (`check_media_tools`)
- Modify: `python/src/thoth_control_plane/config.py` (the `openrouter_api_key` docstring: no rules-only fallback any more)
- Test: `python/tests/activities/test_source_attribution.py`, `python/tests/test_worker.py`

**Interfaces:**
- Consumes: every adapter (Tasks 3–8), `speech.WHISPER_FILES`, `speech.DIARIZATION_FILES`, `speech.missing`.
- Produces:
  - `build_production_ports(settings, artifact_root)`: raises `SettingsValidationError("openrouter_key_missing")` without a key.
  - `check_media_tools(settings)`: checks attribution when `THOTH_SOURCE_ATTRIBUTION_ENABLED`, and assembly when `THOTH_CONTENT_ASSEMBLY_ENABLED`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_worker.py`:

```python
def _attribution_settings(tmp_path: Path, **overrides: Any) -> Settings:
    whisper = tmp_path / "whisper"
    diarization = tmp_path / "diarization"
    whisper.mkdir()
    diarization.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (whisper / name).write_bytes(b"x")
    for name in ("segmentation.onnx", "embedding.onnx"):
        (diarization / name).write_bytes(b"x")
    values: dict[str, Any] = {
        "THOTH_CONTROL_PLANE_API_KEY": "test-only",
        "THOTH_SOURCE_ATTRIBUTION_ENABLED": True,
        "THOTH_OPENROUTER_API_KEY": "synthetic-key",
        "THOTH_WHISPER_MODEL_DIR": whisper,
        "THOTH_DIARIZATION_MODEL_DIR": diarization,
    }
    return Settings(**{**values, **overrides})  # type: ignore[arg-type]


def test_attribution_starts_with_every_tool_present(tmp_path: Path) -> None:
    worker.check_media_tools(_attribution_settings(tmp_path))


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"THOTH_OPENROUTER_API_KEY": None}, "openrouter_key_missing"),
        ({"THOTH_FFMPEG": "/nonexistent/ffmpeg"}, "ffmpeg_missing"),
        ({"THOTH_FFPROBE": "/nonexistent/ffprobe"}, "ffprobe_missing"),
        ({"THOTH_WHISPER_MODEL_DIR": Path("/nonexistent")}, "whisper_model_missing"),
        ({"THOTH_DIARIZATION_MODEL_DIR": Path("/nonexistent")}, "diarization_model_missing"),
    ],
)
def test_attribution_refuses_to_start_without_a_tool(
    tmp_path: Path, change: dict[str, Any], code: str
) -> None:
    with pytest.raises(SettingsValidationError, match=code):
        worker.check_media_tools(_attribution_settings(tmp_path, **change))


@pytest.mark.parametrize(
    ("module", "code"),
    [
        ("faster_whisper", "whisper_missing"),
        ("sherpa_onnx", "diarization_missing"),
        ("rapidocr", "rapidocr_missing"),
        ("cv2", "opencv_missing"),
    ],
)
def test_attribution_refuses_to_start_without_a_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str, code: str
) -> None:
    real = worker.find_spec
    monkeypatch.setattr(worker, "find_spec", lambda name: None if name == module else real(name))

    with pytest.raises(SettingsValidationError, match=code):
        worker.check_media_tools(_attribution_settings(tmp_path))
```

Existing worker tests that call `run_worker` or `check_media_tools` with default settings now need `THOTH_SOURCE_ATTRIBUTION_ENABLED=False`, or a monkeypatched check. Set it in the test settings. Do not loosen the check.

In `tests/activities/test_source_attribution.py`, rewrite `test_production_ports_follow_the_configured_keys`:
- with a key, the ports hold `AgnoVisionReader`, `JevDecisionModel`, `FfmpegSceneDetector`, `WhisperTranscriber`, and `SherpaDiarizer`;
- without a key, `build_production_ports` raises `SettingsValidationError` matching `openrouter_key_missing`.

Extend `test_provider_keys_never_reach_an_adapter_repr_or_the_ports` over the new ports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/test_worker.py tests/activities/test_source_attribution.py -p no:warnings`
Expected: FAIL.

- [ ] **Step 3: Implement**

`worker.py`:

```python
def _require_binaries(settings: Settings) -> None:
    for code, binary in (
        ("ffmpeg_missing", settings.THOTH_FFMPEG),
        ("ffprobe_missing", settings.THOTH_FFPROBE),
    ):
        if shutil.which(binary) is None:
            raise SettingsValidationError(code)
    if find_spec("rapidocr") is None:
        raise SettingsValidationError("rapidocr_missing")
    if find_spec("cv2") is None:
        raise SettingsValidationError("opencv_missing")


def check_media_tools(settings: Settings) -> None:
    """Refuse to start without a tool, key, or model a stage on this worker needs.

    Operator, 2026-10-11 and 2026-10-13: a missing tool is an explicit error, never a silent
    degradation; vision and Jev are required for attribution.
    """
    from thoth_control_plane.attribution.adapters.speech import (
        DIARIZATION_FILES,
        WHISPER_FILES,
        missing,
    )

    if settings.THOTH_SOURCE_ATTRIBUTION_ENABLED:
        if settings.openrouter_api_key is None:
            raise SettingsValidationError("openrouter_key_missing")
        _require_binaries(settings)
        if find_spec("faster_whisper") is None:
            raise SettingsValidationError("whisper_missing")
        if missing(settings.THOTH_WHISPER_MODEL_DIR, WHISPER_FILES):
            raise SettingsValidationError("whisper_model_missing")
        if find_spec("sherpa_onnx") is None:
            raise SettingsValidationError("diarization_missing")
        if missing(settings.THOTH_DIARIZATION_MODEL_DIR, DIARIZATION_FILES):
            raise SettingsValidationError("diarization_model_missing")
    if settings.THOTH_CONTENT_ASSEMBLY_ENABLED:
        _require_binaries(settings)
```

`build_production_ports`:

```python
def build_production_ports(settings: Settings, artifact_root: Path) -> AttributionPorts:
    openrouter = settings.openrouter_api_key
    if openrouter is None:
        raise SettingsValidationError("openrouter_key_missing")
    store = _account_store(settings)
    return AttributionPorts(
        frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
        matcher=OrbMatcher(),
        text=RapidOcrReader(),
        discoverer=ProfileDiscoverer(leases=StoreLeases(store) if store is not None else None),
        acquirer=RunnerAcquirer(build_production_acquisition_runner(settings), artifact_root),
        vision=AgnoVisionReader(openrouter, settings.THOTH_SOURCE_VISION_MODEL),
        decisions=JevDecisionModel(openrouter),
        scenes=FfmpegSceneDetector(settings.THOTH_FFMPEG),
        transcriber=WhisperTranscriber(settings.THOTH_WHISPER_MODEL_DIR),
        diarizer=SherpaDiarizer(settings.THOTH_DIARIZATION_MODEL_DIR),
    )
```

`build_source_attribution_activity` builds ports eagerly. Any test that builds the source worker without a key must pass `attributor=` or a key; fix those call sites. A worker started without a key already stops at `check_media_tools`.

- [ ] **Step 4: Run tests to verify they pass, then the full suite**

Run: the Step 2 command, then `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests -p no:warnings`
Expected: all pass. The skips are only the existing Playwright, Postgres, and live skips.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/activities/source_attribution.py python/src/thoth_control_plane/worker.py python/src/thoth_control_plane/config.py python/tests
git commit -m "feat(worker): attribution needs its key, tools, and speech models"
```

---

### Task 12: Golden capture and replay (live capture is an operator gate)

**Files:**
- Modify: `python/tests/attribution/capture_golden.py`, `python/tests/attribution/test_capture.py`
- Modify: `python/tests/attribution/test_golden.py` (`DEPARTURES` gains `reaction_original`)
- Modify/Create: `python/tests/fixtures/attribution/*.json`
- Modify: `python/tests/fixtures/assembly/ocr/instagram_deHz54GT4ea.json`, `.../instagram_deO6A2MSoAt.json`

**Interfaces:**
- Consumes: the replay keys of Task 9.
- Produces: fixtures with `cuts`, `transcript`, `turns`, `assessment`, and repost comments (text only, `card: null`).

- [ ] **Step 1: Write the failing test (offline)**

In `test_capture.py`, extend the existing record test. Use recording fakes for `scenes`, `transcriber`, `diarizer`, and `decisions.assess`, and assert that the fixture holds:
- `cuts`;
- `transcript.segments` as `[start, end, text]`;
- `turns` as `[start, end, speaker]`;
- `assessment`;
- the repost's comments with their text and no `card`.

Assert that a second replay through `replay_ports(fixture)` reproduces the verdict.

- [ ] **Step 2: Run it to verify it fails**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_capture.py -p no:warnings`
Expected: FAIL (keys missing).

- [ ] **Step 3: Implement the recording**

In `capture_golden.py`:
- Add `_Scenes`, `_Transcriber`, `_Diarizer` recorders in the pattern of `_Frames`.
- `_Decisions.assess` stores `store.assessment = vars(answer)`.
- `record_case` writes:
  - `"cuts"`;
  - `"transcript": {"language": t.language, "segments": [[s.start, s.end, s.text] for s in t.segments]}`, or `None`;
  - `"turns"` as `[[t.start, t.end, t.speaker] for t in turns]`, or `None`;
  - `"assessment"`.
- `_plain(report)` keeps comments with `card` set to `None` for the repost only (`keep_comments=True`). Candidates keep today's trimming.
- `--expect-verdict` stays as it is.

Add `"reaction_original"` to `DEPARTURES` in `test_golden.py`. Scout replaced these posts with the subject; the Python verdict departs on purpose.

- [ ] **Step 4: Run it to verify it passes; commit**

Run: the Step 2 command.
Expected: pass.

```bash
git add python/tests/attribution
git commit -m "test(attribution): record reaction answers in golden captures"
```

- [ ] **Step 5: HARD STOP — operator gate for the live capture**

Stop here. Ask the operator to authorize the live capture: the 7 reaction cases plus a recapture of every existing live Stage 4 golden.

The capture needs an image that holds the new packages and models. Build it locally in WSL with `docker build -t thoth-capture:reaction .` from the branch, and point `D:/thoth-tmp/bu/s4/capture.sh` at that tag.

- [ ] **Step 6: Capture (after authorization)**

| Case | `--expect-verdict` | `--expect-source-url` | `--departure` |
|---|---|---|---|
| tiktok ZSbEKefJp | `replaced` | the X post `NaraSenyap/status/2109917400854634989` | — |
| tiktok ZSbEKFuP7 | `replaced` | the X post `gretaamelia7/status/2109671629206990893` | — |
| tiktok ZSbEKVVra | `replaced` | the canonical URL of tiktok ZSbEKps8X | — |
| instagram DeWlWJmyKxP | `original` | — | `reaction_original` |
| instagram DeOUJ60SHeI | `original` | — | `reaction_original` |
| instagram DeHz54GT4ea | `original` | — | `reaction_original` |
| instagram DeO6A2MSoAt | `original` | — | `reaction_original` |

Every existing live golden (deRDs6DCX07, kabinetketiduran, officialinews) is recaptured with its current expected verdict. The cover each of them records must say `reaction_shape: none`. If it does not, stop and report to the operator.

In the same container, measure speed with a throwaway `D:/thoth-tmp/bu/s6/bench_speech.py`. For each reaction video, record the seconds spent per second of audio for:
- faster-whisper large-v3-turbo int8;
- sherpa-onnx with whisper turbo ONNX int8.

If turbo runs below 1× realtime, also measure `medium` and report all three to the operator. Check the creator/subject split by hand on the four `original` cases.

- [ ] **Step 7: Calibrate and replay**

Run `tests/attribution/test_golden.py`. If a case misses its verdict:
- First adjust the three reaction thresholds in `Tuning`, within [0.3, 0.8] and [0.8, 1.5]. Record a ledger ruling with the recorded values per case.
- If no threshold set separates the cases, stop and report to the operator. Do not change expected verdicts.

Then update the two Stage 5a OCR fixtures. In `instagram_deHz54GT4ea.json` and `instagram_deO6A2MSoAt.json`:
- set `"trim_allowed": false`;
- set `"expected"` to the replayed `{outcome: "clean", trim_start: 0.0, blur_count: 0}`.

Run `tests/assembly/test_ocr_golden.py`.

- [ ] **Step 8: Commit**

```bash
git add python/tests/fixtures/attribution python/tests/fixtures/assembly/ocr python/src/thoth_control_plane/attribution/service.py
git commit -m "test(attribution): reaction goldens; original reactions keep openings"
```

---

### Task 13: Documentation

**Files:**
- Modify (CRLF, bytes-level script): `CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`
- Modify: `docs/superpowers/specs/2026-10-08-stage4-source-attribution-design.md`. Its section 7 gains one line pointing to the 2026-10-13 spec, section 7, for vision and Jev.
- Modify: `.env.stage1.local.example` (CRLF), with the two model directory variables commented, defaults shown.

- [ ] **Step 1: Write the entries**

The CHANGELOG entry "2026-10-1x - Stage 4: reactions that count as originals" lists:
- the new behaviour, the required-tool change, and the golden results;
- the calibrated thresholds;
- the speed measurement;
- the suite count.

It ends with **Next steps**: push, merge, deploy (separate gates), then Stage 5b, then the parked items.

The roadmap gets one status paragraph.

- [ ] **Step 2: Verify and commit**

Run: `file CHANGELOG.md docs/python-scout-migration-roadmap.md .env.stage1.local.example`
Expected: still `with CRLF line terminators`.

```bash
git add CHANGELOG.md docs/python-scout-migration-roadmap.md docs/superpowers/specs/2026-10-08-stage4-source-attribution-design.md .env.stage1.local.example
git commit -m "docs: record Stage 4 reaction attribution"
```
