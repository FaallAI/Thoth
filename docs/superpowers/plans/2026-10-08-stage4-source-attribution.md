# Stage 4 Source Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a workflow runs with intent `identify_original`, Thoth decides whether the post is
the original and, when it is not, finds and acquires the original, recording a typed
`SourceAttribution` with cited evidence.

**Architecture:** A new package `thoth_control_plane.attribution` holds pure decision code
(credit rules, candidate filters, frame-hash matching) and a `SourceAttributor` that talks to the
outside world only through ports. Adapters implement the ports: ffmpeg frames, `imagehash`
hashes, RapidOCR text, Agno over Novita for vision, TypeSafe Jev over HTTP for typed decisions,
and the Stage 3 discoverers and acquisition runner. A new Temporal activity `attribute_source`
runs the attributor after a successful `identify_original` acquisition. A workflow input flag
gates it, so in-flight workflows replay unchanged.

**Tech Stack:** Python 3.12, Pydantic v2, Temporal (`temporalio`), httpx, `agno` 3.1.1 with
`openai` (OpenAI-compatible client), `imagehash` 4.3.2, `rapidocr` 3.9.2 with `onnxruntime`
1.30.0, ffmpeg, pytest with pytest-asyncio and respx.

**Spec:** `docs/superpowers/specs/2026-10-08-stage4-source-attribution-design.md`
(operator-approved 2026-10-08). Read it before Task 1. Its research inputs are
`docs/research/2026-10-08-stage4-source-intelligence-ideas.md` and
`docs/research/2026-10-08-stage4-source-intelligence-research.md`.

## Global Constraints

**Branch and stability**
- Branch `feat/stage4-source-attribution` from `master`. Do not push, merge, or deploy.
- No live request in the test suite. HTTP is mocked with respx; the conftest offline guard stays.
- Task 11 is a HARD STOP: a live capture the operator authorizes separately.

**Language and commits**
- Chat to the operator: Indonesian. Code, comments, docs, and commit messages: English.
- Each commit is exactly one `git commit -m "<subject>"`, at most 72 characters, no body, no
  trailer, never `Co-Authored-By` or any AI attribution.
- Never stage `graphify-out/`, `build_log.txt`, `.superpowers/`, `.understand-anything/`,
  `.env.stage1.local*`, `dashboard/dist/`, or the untracked `design/` files.
- `docs/superpowers/` is gitignored: stage files there with `git add -f`.

**Files and line endings**
- CRLF files: `python/pyproject.toml`, `python/uv.lock` (changed by `uv lock` only), `Dockerfile`,
  `.env.stage1.providers.example`, `docs/python-control-plane.md`,
  `docs/operations/stage1-local-docker.md`, `CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`.
  Edit them only through `D:/thoth-tmp/bu/s4/crlf.py` (Task 1, Step 1). Never use a text-mode
  Python write on them.
- Every other touched file is LF; the Edit and Write tools are fine.
- Temporary files live under `D:/thoth-tmp`.

**Code rules (from the spec)**
- Optional dependencies (`imagehash`, `PIL`, `rapidocr`, `agno`, `openai`) are imported inside
  adapter methods, never at module top. `thoth_control_plane.activities.source_attribution` must
  import without the `acquisition` extra, because the workflow module imports it.
- Temporal history carries only IDs, verdicts, counts, and reason codes. Prompts, model
  outputs, OCR text, and frames stay inside the activity.
- Log messages carry enums and counts only, never a handle, URL, key, or model output.
- `SourceAttributor.identify` raises only on cancellation; every port failure degrades.
- New Pydantic fields carry defaults so earlier artifacts and histories stay readable.
- Provider keys: `THOTH_NOVITA_API_KEY` (vision), `THOTH_TYPESAFE_API_KEY` (Jev). Vision model
  default `qwen/qwen3-vl-30b-a3b-instruct`. Novita base URL `https://api.novita.ai/openai/v1`.
  Jev endpoint `https://api.typesafe.ai/v1/systemone`, model `jev-1.13`.

**Commands**
- Tests (WSL; the wrapper gains the new libraries in Task 1, Step 2):
  `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths> -p no:warnings`
  run from `C:/Users/mfr/Documents/MyTools/CLIPPER/python`.
- Ruff: `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check . && ~/.local/bin/uvx ruff format --check .'`
- Run `ruff format` on new files before each commit:
  `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format <paths>'`

## Review Focus

1. Flat or black frames (fade-ins, title cards) hash alike and would "match" any video. They
   must never count as a match. Pinned by `test_hasher_ignores_flat_frames` (Task 5) and
   `test_flat_repost_frames_leave_the_match_unmeasured` (Task 7).
2. A repost with no video (photo, carousel, text post) must still get a verdict, not a crash.
   Pinned by `test_a_repost_without_video_replaces_with_low_confidence` (Task 7).
3. The repost's own handle (its watermark, its caption) must never be taken as the source
   credit. Pinned by `test_credit_options_never_offer_the_reposting_account` (Task 2) and
   `test_self_credit_is_never_a_credit` (Task 7).
4. Candidate cleanup must stay inside the artifact root: a malformed candidate ID is refused,
   and a media file outside the root is never read. Pinned by
   `test_discard_removes_only_a_candidate_directory_inside_the_root` (Task 8).
5. A provider outage (Jev 5xx, vision error, discovery or acquisition raising) degrades instead
   of failing. Pinned by `test_jev_failures_return_none` (Task 6) and
   `test_port_failures_degrade_instead_of_failing` (Task 7).

---

### Task 1: Dependencies, settings, image libraries, and the provider file

**Files:**
- Create: `D:/thoth-tmp/bu/s4/crlf.py` (tooling, outside the repository)
- Modify: `D:/thoth-tmp/bu/pt.sh` (tooling, outside the repository)
- Modify: `python/src/thoth_control_plane/config.py`
- Modify (CRLF): `python/pyproject.toml`, `python/uv.lock` (through `uv lock`), `Dockerfile`,
  `.env.stage1.providers.example`, `docs/python-control-plane.md`,
  `docs/operations/stage1-local-docker.md`
- Modify: `python/src/thoth_control_plane/operations/stage1_provider_preflight.py`
- Test: `python/tests/test_config.py`, `python/tests/deployment/test_stage1_provider_preflight.py`

**Interfaces:**
- Produces: `Settings.THOTH_FFMPEG: str = "ffmpeg"`,
  `Settings.THOTH_SOURCE_VISION_MODEL: str = "qwen/qwen3-vl-30b-a3b-instruct"`,
  `Settings.THOTH_SOURCE_ATTRIBUTION_ENABLED: bool = True`,
  `Settings.novita_api_key -> str | None`, `Settings.typesafe_api_key -> str | None`.

- [ ] **Step 1: Create the branch and the CRLF edit helper**

```bash
cd C:/Users/mfr/Documents/MyTools/CLIPPER && git checkout -b feat/stage4-source-attribution
```

Write `D:/thoth-tmp/bu/s4/crlf.py` with the Write tool:

```python
"""Byte-preserving text edits for CRLF or LF files; each old string must occur exactly once."""

from pathlib import Path

ROOT = Path("C:/Users/mfr/Documents/MyTools/CLIPPER")


def edit(rel: str, pairs: list[tuple[str, str]]) -> None:
    path = ROOT / rel
    data = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in data
    text = data.replace("\r\n", "\n")
    for old, new in pairs:
        assert text.count(old) == 1, (rel, old[:60], text.count(old))
        text = text.replace(old, new)
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print("edited", rel, "crlf" if crlf else "lf")
```

- [ ] **Step 2: Give the test wrapper the new libraries**

Rewrite `D:/thoth-tmp/bu/pt.sh` with the Write tool (LF, one line). It is the existing command
plus `--with imagehash --with rapidocr --with onnxruntime --with openai --with numpy`:

```bash
cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && mkdir -p $HOME/thoth-tmp && PYTHONPATH=$PWD/src ~/.local/bin/uv run --no-project --python 3.12 --with pytest --with pydantic --with typer --with httpx --with pytest-asyncio --with temporalio --with pydantic-settings --with fastapi --with psycopg[binary] --with sqlalchemy --with alembic --with boto3 --with python-multipart --with pyjwt --with respx --with agno --with pillow --with pyyaml --with cryptography --with imagehash --with rapidocr --with onnxruntime --with openai --with numpy -- python -m pytest "$@" -q -p no:cacheprovider --basetemp=$HOME/thoth-tmp/pt
```

- [ ] **Step 3: Write the failing settings tests**

Append to `python/tests/test_config.py`:

```python
def test_attribution_settings_default_to_no_keys_and_an_enabled_feature() -> None:
    configured = settings(THOTH_NOVITA_API_KEY=None, THOTH_TYPESAFE_API_KEY=None)

    assert (configured.novita_api_key, configured.typesafe_api_key) == (None, None)
    assert configured.THOTH_SOURCE_ATTRIBUTION_ENABLED is True
    assert configured.THOTH_SOURCE_VISION_MODEL == "qwen/qwen3-vl-30b-a3b-instruct"
    assert configured.THOTH_FFMPEG == "ffmpeg"


def test_attribution_keys_are_stripped_and_a_blank_key_is_absent() -> None:
    configured = settings(THOTH_NOVITA_API_KEY=" nv-synthetic ", THOTH_TYPESAFE_API_KEY="  ")

    assert configured.novita_api_key == "nv-synthetic"
    assert configured.typesafe_api_key is None
```

Append to `python/tests/deployment/test_stage1_provider_preflight.py`:

```python
def test_provider_file_accepts_the_optional_typesafe_key(tmp_path: Path) -> None:
    candidate = _provider_file(
        _outside_repository(tmp_path),
        VALID_CONTENT + "THOTH_TYPESAFE_API_KEY=synthetic-typesafe-canary\n",
    )

    check_stage1_provider_file(candidate, repository_root=tmp_path / "repo")


@pytest.mark.parametrize("key", ["", "replace-with-local-secret", "short"])
def test_provider_file_rejects_a_placeholder_typesafe_key(tmp_path: Path, key: str) -> None:
    candidate = _provider_file(
        _outside_repository(tmp_path), VALID_CONTENT + f"THOTH_TYPESAFE_API_KEY={key}\n"
    )

    with pytest.raises(Stage1PreflightError) as failure:
        check_stage1_provider_file(candidate, repository_root=tmp_path / "repo")
    assert "THOTH_TYPESAFE_API_KEY" in str(failure.value)
    if key:
        assert key not in str(failure.value)
```

- [ ] **Step 4: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/test_config.py tests/deployment/test_stage1_provider_preflight.py -p no:warnings`
Expected: FAIL — `novita_api_key` is not an attribute, and the provider file rejects
`THOTH_TYPESAFE_API_KEY` as an unrecognized variable.

- [ ] **Step 5: Add the settings**

In `python/src/thoth_control_plane/config.py`, after the line
`    THOTH_ACCOUNT_VAULT_KEY: SecretStr | None = None` add:

```python
    # Stage 4 source attribution. Without a key, that half of the evidence is skipped.
    THOTH_FFMPEG: str = "ffmpeg"
    THOTH_NOVITA_API_KEY: SecretStr | None = None
    THOTH_SOURCE_VISION_MODEL: str = "qwen/qwen3-vl-30b-a3b-instruct"
    THOTH_TYPESAFE_API_KEY: SecretStr | None = None
    # Read by the API when it starts an identify_original workflow; a kill switch.
    THOTH_SOURCE_ATTRIBUTION_ENABLED: bool = True
```

After the `account_vault_key` property (it ends with
`return self.THOTH_ACCOUNT_VAULT_KEY.get_secret_value().strip() or None`) add:

```python

    @property
    def novita_api_key(self) -> str | None:
        """The vision provider key, or None when attribution runs without vision."""
        return _secret(self.THOTH_NOVITA_API_KEY)

    @property
    def typesafe_api_key(self) -> str | None:
        """The Jev decision key, or None when attribution decides by rules alone."""
        return _secret(self.THOTH_TYPESAFE_API_KEY)
```

At the end of the module add:

```python


def _secret(value: SecretStr | None) -> str | None:
    return (value.get_secret_value().strip() or None) if value is not None else None
```

- [ ] **Step 6: Admit the optional key in the provider file**

In `python/src/thoth_control_plane/operations/stage1_provider_preflight.py`:

1. In the module docstring, replace
   `* exactly two variables, both required — a wider file is usually an accidental copy`
   with `* two required variables and one optional key — a wider file is usually an accidental copy`.
2. After `REQUIRED_PROVIDER_VARIABLES = (PROVIDER_KEY_VARIABLE, PROVIDER_OCR_MODEL_VARIABLE)` add:

```python
PROVIDER_TYPESAFE_VARIABLE = "THOTH_TYPESAFE_API_KEY"
OPTIONAL_PROVIDER_VARIABLES = (PROVIDER_TYPESAFE_VARIABLE,)
```

3. In `_parse_provider_file`, replace the unrecognized-variable block with:

```python
        if name not in REQUIRED_PROVIDER_VARIABLES + OPTIONAL_PROVIDER_VARIABLES:
            raise Stage1PreflightError(
                "the provider env file contains an unrecognized variable; "
                f"it admits only {' and '.join(REQUIRED_PROVIDER_VARIABLES)}, "
                f"and optionally {PROVIDER_TYPESAFE_VARIABLE}"
            )
```

4. Replace `_check_values` from `    key = values[PROVIDER_KEY_VARIABLE]` through the end of the
   key check (the `raise` that names `PROVIDER_KEY_VARIABLE`) with:

```python
    _check_key(PROVIDER_KEY_VARIABLE, values[PROVIDER_KEY_VARIABLE])
    if PROVIDER_TYPESAFE_VARIABLE in values:
        typesafe = values[PROVIDER_TYPESAFE_VARIABLE]
        if any(character < " " or character == "\x7f" for character in typesafe):
            raise Stage1PreflightError(
                f"{PROVIDER_TYPESAFE_VARIABLE} must not contain control characters"
            )
        _check_key(PROVIDER_TYPESAFE_VARIABLE, typesafe)
```

and add below `_check_values`:

```python


def _check_key(name: str, key: str) -> None:
    lowered = key.lower()
    if (
        len(key) < MINIMUM_KEY_LENGTH
        or any(character.isspace() for character in key)
        or any(marker in lowered for marker in PLACEHOLDER_MARKERS)
    ):
        raise Stage1PreflightError(f"{name} must be a real provider key, not empty or a placeholder")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/test_config.py tests/deployment/test_stage1_provider_preflight.py -p no:warnings`
Expected: PASS, with the earlier provider-file tests still green.

- [ ] **Step 8: Add the dependencies and the image libraries**

Write `D:/thoth-tmp/bu/s4/task1_crlf.py` with the Write tool, then run `python D:/thoth-tmp/bu/s4/task1_crlf.py`:

```python
import sys

sys.path.insert(0, "D:/thoth-tmp/bu/s4")
from crlf import edit  # noqa: E402

edit("python/pyproject.toml", [(
    'acquisition = ["scrapling[fetchers]>=0.4.15,<0.5", "yt-dlp==2026.8.19"]',
    'acquisition = ["scrapling[fetchers]>=0.4.15,<0.5", "yt-dlp==2026.8.19", '
    '"imagehash>=4.3,<5", "rapidocr>=3.9,<4", "onnxruntime>=1.30,<2", "openai>=3,<4"]',
)])
edit("Dockerfile", [
    (
        "    && apt-get install --yes --no-install-recommends ca-certificates ffmpeg tini \\\n",
        "    && apt-get install --yes --no-install-recommends ca-certificates ffmpeg tini \\\n"
        "        libgl1 libglib2.0-0 \\\n",
    ),
    (
        '        "import scrapling, thoth_control_plane" \\\n',
        '        "import scrapling, thoth_control_plane, imagehash, rapidocr, openai" \\\n',
    ),
])
edit(".env.stage1.providers.example", [
    (
        "# The preflight rejects a placeholder key, an in-repository path, any third\n",
        "# The preflight rejects a placeholder key, an in-repository path, any other\n",
    ),
    (
        "THOTH_SUBTITLE_OCR_MODEL=deepseek/deepseek-ocr\n",
        "THOTH_SUBTITLE_OCR_MODEL=deepseek/deepseek-ocr\n"
        "# Optional: the TypeSafe Jev key for source attribution decisions.\n"
        "# THOTH_TYPESAFE_API_KEY=replace-with-local-secret\n",
    ),
])
edit("docs/operations/stage1-local-docker.md", [(
    "The file holds exactly `THOTH_NOVITA_API_KEY` and `THOTH_SUBTITLE_OCR_MODEL`. A wider file is",
    "The file holds exactly `THOTH_NOVITA_API_KEY` and `THOTH_SUBTITLE_OCR_MODEL`, plus the\n"
    "optional `THOTH_TYPESAFE_API_KEY` that source attribution uses. A wider file is",
)])
edit("docs/python-control-plane.md", [(
    "| `THOTH_TEMPORAL_TARGET` |",
    "| `THOTH_NOVITA_API_KEY` | Python worker | Optional secret vision key for source attribution"
    " (Novita, OpenAI-compatible). Without it attribution skips cover vision and finalist"
    " classification. |\n"
    "| `THOTH_SOURCE_VISION_MODEL` | Python worker | Vision model for source attribution; default"
    " `qwen/qwen3-vl-30b-a3b-instruct`. |\n"
    "| `THOTH_TYPESAFE_API_KEY` | Python worker | Optional secret TypeSafe Jev key for typed"
    " attribution decisions. Without it attribution decides by deterministic credit rules. |\n"
    "| `THOTH_FFMPEG` | Python worker | ffmpeg executable for attribution frames; default"
    " `ffmpeg`, `/usr/bin/ffmpeg` in the image. |\n"
    "| `THOTH_SOURCE_ATTRIBUTION_ENABLED` | FastAPI | Default `true`. `false` starts"
    " `identify_original` workflows without the attribution stage. |\n"
    "| `THOTH_TEMPORAL_TARGET` |",
)])
```

Then lock, upgrading `agno` within its range:

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && ~/.local/bin/uv lock --project python --upgrade-package agno && ~/.local/bin/uv lock --project python --locked >/dev/null 2>&1; echo EXIT=$?'
git -C C:/Users/mfr/Documents/MyTools/CLIPPER diff --stat -- python/uv.lock
grep -n -A1 'name = "agno"' C:/Users/mfr/Documents/MyTools/CLIPPER/python/uv.lock
```

Expected: `EXIT=0`. `uv.lock` gains `imagehash`, `rapidocr`, `onnxruntime`, `openai`, and their
dependencies, and `agno` moves from 3.0.1 to 3.1.1. Read the diff stat. If anything other than
these packages and their dependencies moves, ledger a ruling.

- [ ] **Step 9: Run the wider suite that the agno upgrade could touch**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/spikes tests/application tests/test_config.py tests/deployment -p no:warnings`
Expected: PASS (the Agno spike adapter keeps passing on 3.1.1).

- [ ] **Step 10: Commit**

```bash
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/config.py python/src/thoth_control_plane/operations/stage1_provider_preflight.py python/tests/test_config.py python/tests/deployment/test_stage1_provider_preflight.py python/pyproject.toml python/uv.lock Dockerfile .env.stage1.providers.example docs/python-control-plane.md docs/operations/stage1-local-docker.md
git commit -m "feat(attribution): add attribution settings and dependencies"
```

---

### Task 2: Attribution models and credit rules

**Files:**
- Create: `python/src/thoth_control_plane/attribution/__init__.py`
- Create: `python/src/thoth_control_plane/attribution/models.py`
- Create: `python/src/thoth_control_plane/attribution/credit.py`
- Test: `python/tests/attribution/__init__.py` (empty), `python/tests/attribution/test_models.py`,
  `python/tests/attribution/test_credit.py`

**Interfaces:**
- Produces (models): `Platform`, `Verdict`, `MAX_EVIDENCE = 50`, `AttributionEvidence(kind,
  detail, confidence=None)`, `AttributedPost(platform, canonical_url, owner_handle)`,
  `SourceAttribution(schema_version=1, workflow_id, input, verdict, source=None,
  confidence="low", reason=None, evidence=[], candidates={})`.
- Produces (credit): `normalize(handle) -> str`, `text_rule_credit(text) -> tuple[str,
  Platform] | None`, `text_handles(text) -> list[str]`, `frame_handles(lines) -> list[str]`,
  `credit_options(caption_handles, frame_handles, owner) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`python/tests/attribution/test_models.py`:

```python
"""The attribution artifact: a source exactly when replaced, bounded evidence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from thoth_control_plane.attribution.models import (
    AttributedPost,
    AttributionEvidence,
    SourceAttribution,
)

REPOST = "https://www.tiktok.com/@detikjatim/video/7677496203042360594"


def _post(url: str = REPOST, owner: str = "detikjatim") -> AttributedPost:
    return AttributedPost(platform="tiktok", canonical_url=url, owner_handle=owner)


def test_a_source_is_present_exactly_when_replaced() -> None:
    SourceAttribution(workflow_id="wf_a", input=_post(), verdict="original")
    with pytest.raises(ValidationError):
        SourceAttribution(workflow_id="wf_a", input=_post(), verdict="replaced")
    with pytest.raises(ValidationError):
        SourceAttribution(workflow_id="wf_a", input=_post(), verdict="original", source=_post())


def test_evidence_is_bounded_and_the_artifact_round_trips() -> None:
    attribution = SourceAttribution(
        workflow_id="wf_a",
        input=_post(),
        verdict="unresolved",
        reason="no_credit",
        evidence=[AttributionEvidence(kind="frame_text", detail="@vincentius.christ76")],
        candidates={"discovered": 3},
    )

    assert SourceAttribution.model_validate_json(attribution.model_dump_json()) == attribution
    with pytest.raises(ValidationError):
        AttributionEvidence(kind="caption", detail="x" * 301)
    with pytest.raises(ValidationError):
        SourceAttribution(workflow_id="wf_a", input=_post(), verdict="unresolved", reason="No")
```

`python/tests/attribution/test_credit.py`:

```python
"""Credits read from captions and frame text."""

from __future__ import annotations

from thoth_control_plane.attribution import credit


def test_caption_conventions_name_the_account_and_platform() -> None:
    assert credit.text_rule_credit("Viral [📸 @user.name] lokasi") == ("user.name", "instagram")
    assert credit.text_rule_credit("cr tt/@abc_def") == ("abc_def", "tiktok")
    assert credit.text_rule_credit("📸 @ig.user tt/tt.user") == ("ig.user", "instagram")
    assert credit.text_rule_credit("📸 @akun") is None
    assert credit.text_rule_credit("scott/plain text") is None


def test_caption_handles_skip_a_reply_target_and_placeholders() -> None:
    text = "Membalas @fan.account video dari @vincentius.christ76. dan @akun @Vincentius.Christ76"

    assert credit.text_handles(text) == ["vincentius.christ76"]
    assert credit.text_handles("mail me at a@b.com") == []


def test_frame_text_yields_at_handles_and_bare_watermark_usernames() -> None:
    lines = ["♪ vincentius.christ76   detikjatim", "www.tiktok.com", "0:15 / 1:30", "@DetikJatim"]

    assert credit.frame_handles(lines) == ["vincentius.christ76", "DetikJatim"]


def test_credit_options_never_offer_the_reposting_account() -> None:
    options = credit.credit_options(
        ["Vincentius.Christ76"], ["vincentius.christ76", "detikjatim", "detik_jatim"], "detikjatim"
    )

    assert options == ["Vincentius.Christ76"]
    assert credit.credit_options([], ["detik.jatim"], "detikjatim") == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.attribution'`.

- [ ] **Step 3: Write the models and the credit rules**

`python/src/thoth_control_plane/attribution/__init__.py`:

```python
"""Source attribution: is a post the original, and if not, which post is (Stage 4)."""
```

`python/src/thoth_control_plane/attribution/models.py`:

```python
"""What Thoth decided about a post's origin, with the evidence it cites.

The artifact holds handles, public post URLs, bounded prose, and counts. It never holds a CDN
URL, a cookie, a proxy, a prompt, or raw model output.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from thoth_control_plane.domain.models import OpaqueId, StrictModel

Platform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
Verdict = Literal["original", "replaced", "unresolved"]
EvidenceKind = Literal[
    "caption", "frame_text", "cover_vision", "text_rule", "decision", "visual_match"
]
Handle = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
MAX_EVIDENCE = 50


class AttributionEvidence(StrictModel):
    kind: EvidenceKind
    detail: Annotated[str, Field(min_length=1, max_length=300)]
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None


class AttributedPost(StrictModel):
    platform: Platform
    canonical_url: HttpUrl
    owner_handle: Handle


class SourceAttribution(StrictModel):
    schema_version: Literal[1] = 1
    workflow_id: OpaqueId
    input: AttributedPost
    verdict: Verdict
    source: AttributedPost | None = None
    confidence: Literal["high", "low"] = "low"
    reason: ReasonCode | None = None
    evidence: list[AttributionEvidence] = Field(default_factory=list, max_length=MAX_EVIDENCE)
    candidates: dict[ReasonCode, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_exactly_when_replaced(self) -> SourceAttribution:
        if (self.verdict == "replaced") != (self.source is not None):
            raise ValueError("a source is present exactly when the verdict is replaced")
        return self
```

`python/src/thoth_control_plane/attribution/credit.py`:

```python
"""Credits read from text: caption conventions, handles, and which handles may be a credit.

Pure functions over strings. A handle is returned without its "@", in the case it was written,
and comes only from the text it was found in. Ported from Scout's `trace_source.ts`
(`detectCameraCredit`, `detectTiktokCredit`) and `lib/source_credit.ts` (reply mentions).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from thoth_control_plane.attribution.models import Platform

AT_HANDLE = re.compile(r"(?<![\w@])@([A-Za-z0-9._]{2,30})")
BARE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._]{1,28}[a-z0-9]")
DOMAIN_SUFFIX = re.compile(r"\.(com|net|org|id|co|tv|me|io|app)$")
CAMERA_CREDIT = re.compile(
    r"(?:📸|📷|🎥|🎬|🎞️|📹)\s*(?:cr\.?|credit|by)?\s*[:-]?\s*@([A-Za-z0-9._]{2,30})",
    re.IGNORECASE,
)
TIKTOK_CREDIT = re.compile(r"\btt\s*[/:]\s*@?([A-Za-z0-9._]{2,30})", re.IGNORECASE)
REPLY_PREFIX = re.compile(r"(?:reply(?:ing)?\s+to|membalas|balasan\s+untuk)\s*$", re.IGNORECASE)
TOKEN_EDGES = "♪•|:,;()[]\"'"
PLACEHOLDERS = frozenset(
    {
        "akun", "akunnya", "namaakun", "pengguna", "penggunanya", "user", "username",
        "unknown", "tidakdiketahui", "na", "none", "null", "nil", "anonim", "anonymous",
        "contoh", "example",
    }
)
MAX_OPTIONS = 20


def normalize(handle: str) -> str:
    """The comparison key: no "@", lowercase, no dots, underscores, dashes, or spaces."""
    return re.sub(r"[\s._-]", "", handle.lstrip("@").lower())


def text_rule_credit(text: str) -> tuple[str, Platform] | None:
    """A caption convention naming both the account and the platform; camera beats `tt/`."""
    rules: tuple[tuple[re.Pattern[str], Platform], ...] = (
        (CAMERA_CREDIT, "instagram"),
        (TIKTOK_CREDIT, "tiktok"),
    )
    for pattern, platform in rules:
        match = pattern.search(text)
        if match and normalize(match.group(1)) not in PLACEHOLDERS:
            return match.group(1).rstrip("."), platform
    return None


def text_handles(text: str) -> list[str]:
    """`@handles` in a caption, skipping a reply target and placeholders."""
    found = [
        match.group(1).rstrip(".")
        for match in AT_HANDLE.finditer(text)
        if not REPLY_PREFIX.search(text[: match.start()])
    ]
    return _usable(found)


def frame_handles(lines: Iterable[str]) -> list[str]:
    """Handles burned into frames: `@handles`, and bare watermark usernames."""
    found: list[str] = []
    for line in lines:
        found += [match.group(1).rstrip(".") for match in AT_HANDLE.finditer(line)]
        for token in line.split():
            bare = token.strip(TOKEN_EDGES)
            if _bare_handle(bare):
                found.append(bare)
    return _usable(found)


def credit_options(
    caption_handles: Sequence[str], found_in_frames: Sequence[str], owner: str
) -> list[str]:
    """Every distinct handle that could be the source credit; never the reposting account."""
    owner_key = normalize(owner)
    usable = _usable([*caption_handles, *found_in_frames])
    return [handle for handle in usable if normalize(handle) != owner_key][:MAX_OPTIONS]


def _bare_handle(token: str) -> bool:
    """A watermark username: lowercase, a letter, and a digit, dot, or underscore; not a domain."""
    return (
        BARE_TOKEN.fullmatch(token) is not None
        and re.search(r"[a-z]", token) is not None
        and re.search(r"[0-9._]", token) is not None
        and DOMAIN_SUFFIX.search(token) is None
    )


def _usable(handles: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    usable: list[str] = []
    for handle in handles:
        key = normalize(handle)
        if len(key) < 2 or key in PLACEHOLDERS or key in seen:
            continue
        seen.add(key)
        usable.append(handle)
    return usable
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: PASS (6 tests).

- [ ] **Step 5: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/attribution tests/attribution && ~/.local/bin/uvx ruff check src/thoth_control_plane/attribution tests/attribution'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/attribution python/tests/attribution
git commit -m "feat(attribution): add attribution models and credit rules"
```

---

### Task 3: Frame-hash matching and burned-in speech detection

**Files:**
- Create: `python/src/thoth_control_plane/attribution/matching.py`
- Test: `python/tests/attribution/test_matching.py`

**Interfaces:**
- Produces: `FrameHash(second: float, value: int)`, `TextBox(text: str, top: float, bottom:
  float)` (positions as fractions of frame height), `distance(a, b) -> int`,
  `match_share(repost, candidate, max_distance) -> float | None`,
  `looks_like_burned_in_speech(frames: Sequence[Sequence[TextBox]], *, min_share=0.6,
  min_distinct=3) -> bool`.

- [ ] **Step 1: Write the failing tests**

`python/tests/attribution/test_matching.py`:

```python
"""Frame-hash matching and burned-in speech detection, without any model."""

from __future__ import annotations

from thoth_control_plane.attribution.matching import (
    FrameHash,
    TextBox,
    distance,
    looks_like_burned_in_speech,
    match_share,
)

A, B, C = 0x0F0F0F0F0F0F0F0F, 0xF0F0F0F0F0F0F0F0, 0x00FF00FF00FF00FF
FAR = 0xAAAAAAAAAAAAAAAA


def _hashes(*values: int) -> list[FrameHash]:
    return [FrameHash(float(second), value) for second, value in enumerate(values)]


def test_distance_counts_differing_bits() -> None:
    assert distance(A, A) == 0
    assert distance(A, B) == 64
    assert distance(A, A ^ 0b111) == 3


def test_a_cut_of_the_original_matches_fully_and_another_video_does_not() -> None:
    repost = _hashes(A, B, C)
    original = _hashes(FAR, A ^ 0b11, B, C, FAR)

    assert match_share(repost, original, max_distance=10) == 1.0
    assert match_share(repost, _hashes(FAR, FAR ^ 1), max_distance=10) == 0.0
    assert match_share(repost, _hashes(A), max_distance=10) == 1 / 3


def test_no_frames_on_either_side_is_unmeasured() -> None:
    assert match_share([], _hashes(A), max_distance=10) is None
    assert match_share(_hashes(A), [], max_distance=10) is None


def test_changing_lower_text_is_speech_and_a_static_lower_third_is_not() -> None:
    speech = [
        [TextBox("kata pertama", 0.70, 0.76)],
        [TextBox("kata kedua", 0.70, 0.76)],
        [TextBox("kata ketiga", 0.70, 0.76)],
        [],
    ]
    lower_third = [[TextBox("DETIK JATIM", 0.85, 0.90)] for _ in range(5)]
    headline = [[TextBox(f"BREAKING {n}", 0.05, 0.10)] for n in range(5)]

    assert looks_like_burned_in_speech(speech) is True
    assert looks_like_burned_in_speech(lower_third) is False
    assert looks_like_burned_in_speech(headline) is False
    assert looks_like_burned_in_speech([]) is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_matching.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `thoth_control_plane.attribution.matching`.

- [ ] **Step 3: Write the matching module**

`python/src/thoth_control_plane/attribution/matching.py`:

```python
"""Visual signals that need no model: frame-hash matching and burned-in speech detection.

A repost is a cut of the original's footage, so most of its frames reappear in the original.
Frames are compared as an unordered bag of 64-bit perceptual hashes, in the manner of Meta's
vPDQ. Hashing itself lives in `adapters/frames.py`; this module only compares numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

LOWER_BAND = 0.55


@dataclass(frozen=True)
class FrameHash:
    second: float
    value: int


@dataclass(frozen=True)
class TextBox:
    """One OCR line; `top` and `bottom` are fractions of the frame height."""

    text: str
    top: float
    bottom: float


def distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def match_share(
    repost: Sequence[FrameHash], candidate: Sequence[FrameHash], max_distance: int
) -> float | None:
    """The share of the repost's frames found in the candidate; None when a side has none."""
    if not repost or not candidate:
        return None
    # ponytail: O(n*m) comparisons, a few thousand for short clips; index by hash band if long
    hits = sum(
        1
        for frame in repost
        if any(distance(frame.value, other.value) <= max_distance for other in candidate)
    )
    return hits / len(repost)


def looks_like_burned_in_speech(
    frames: Sequence[Sequence[TextBox]], *, min_share: float = 0.6, min_distinct: int = 3
) -> bool:
    """Changing text in the lower part of most frames: the captions of a reaction upload.

    A lower-third (a name, a credit bar) repeats one string, so it is not speech, and a
    headline at the top is not in the lower band.
    """
    if not frames:
        return False
    lines = [
        " ".join(box.text for box in boxes if (box.top + box.bottom) / 2 >= LOWER_BAND).strip()
        for boxes in frames
    ]
    spoken = [line.lower() for line in lines if line]
    return len(spoken) / len(frames) >= min_share and len(set(spoken)) >= min_distinct
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_matching.py -p no:warnings`
Expected: PASS (4 tests).

- [ ] **Step 5: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/attribution tests/attribution && ~/.local/bin/uvx ruff check src/thoth_control_plane/attribution tests/attribution'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/attribution/matching.py python/tests/attribution/test_matching.py
git commit -m "feat(attribution): match reposts to originals by frame hashes"
```

---

### Task 4: Candidate filtering and ordering

**Files:**
- Create: `python/src/thoth_control_plane/attribution/candidates.py`
- Test: `python/tests/attribution/test_candidates.py`

**Interfaces:**
- Consumes: `credit.normalize` (Task 2); `DiscoveredVideo` from `acquisition/models.py`.
- Produces: `DEFAULT_CURATED_FILE: Path`, `load_curated(path=DEFAULT_CURATED_FILE) ->
  frozenset[str]` (normalized handles), `parse_time(value: str | None) -> datetime | None`,
  `plausible(video, repost_time, repost_duration) -> bool`, `shortlist(videos, *, repost_owner,
  curated, repost_time, repost_duration) -> tuple[list[DiscoveredVideo], dict[str, int]]` with
  count keys `excluded_account` and `filtered_window`.

- [ ] **Step 1: Write the failing tests**

`python/tests/attribution/test_candidates.py`:

```python
"""Free metadata filters: the plausibility window, excluded accounts, and the order to try."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.candidates import (
    DEFAULT_CURATED_FILE,
    load_curated,
    shortlist,
)

REPOST_TIME = datetime(2026, 8, 24, 7, 26, 32, tzinfo=UTC)
SOURCE = "vincentius.christ76"


def _video(
    n: int,
    published: str | None,
    duration: float | None = 124.0,
    plays: int = 0,
    owner: str = SOURCE,
) -> DiscoveredVideo:
    post_id = str(7677137235434687000 + n)
    return DiscoveredVideo(
        post_id=post_id,
        owner_handle=owner,
        canonical_url=f"https://www.tiktok.com/@{owner}/video/{post_id}",
        published_at=published,
        duration_seconds=duration,
        engagement={"play": plays},
    )


def _kept(videos: list[DiscoveredVideo]) -> tuple[list[int], dict[str, int]]:
    kept, counts = shortlist(
        videos,
        repost_owner="detikjatim",
        curated=frozenset({"curatedaggregator"}),
        repost_time=REPOST_TIME,
        repost_duration=90.0,
    )
    return [int(video.post_id) - 7677137235434687000 for video in kept], counts


def test_the_window_keeps_only_plausible_sources() -> None:
    kept, counts = _kept(
        [
            _video(1, "2026-08-24T10:00:00Z"),  # after the repost
            _video(2, "2026-08-23T08:13:31Z"),  # 23 hours before: plausible
            _video(3, "2026-08-08T00:00:00Z"),  # more than 14 days before
            _video(4, "2026-08-23T09:00:00Z", duration=80.0),  # shorter than 90% of 90 s
            _video(5, None, duration=None),  # unknown values pass
        ]
    )

    assert kept == [2, 5]
    assert counts == {"filtered_window": 3}


def test_closest_before_the_repost_comes_first_then_most_played() -> None:
    kept, _ = _kept(
        [
            _video(1, "2026-08-20T00:00:00Z", plays=9),
            _video(2, "2026-08-23T00:00:00Z", plays=1),
            _video(3, None, plays=100),
            _video(4, None, plays=500),
        ]
    )

    assert kept == [2, 1, 4, 3]


def test_the_reposting_and_curated_accounts_are_excluded() -> None:
    kept, counts = _kept(
        [
            _video(1, "2026-08-23T00:00:00Z", owner="detik_jatim"),
            _video(2, "2026-08-23T00:00:00Z", owner="curated.aggregator"),
            _video(3, "2026-08-23T00:00:00Z"),
        ]
    )

    assert kept == [3]
    assert counts == {"excluded_account": 2}


def test_the_curated_list_reads_every_shape_and_degrades_to_empty(tmp_path: Path) -> None:
    listed = tmp_path / "list.json"
    listed.write_text(json.dumps(["@One.Account", "https://www.instagram.com/two_acc/?hl=id"]))
    keyed = tmp_path / "keyed.json"
    keyed.write_text(json.dumps({"accounts": ["three"]}))

    assert load_curated(listed) == frozenset({"oneaccount", "twoacc"})
    assert load_curated(keyed) == frozenset({"three"})
    assert load_curated(tmp_path / "missing.json") == frozenset()


def test_the_default_curated_file_is_the_scout_list() -> None:
    repository = Path(__file__).resolve().parents[3]

    assert DEFAULT_CURATED_FILE == repository / "scout" / "config" / "ig_accounts.json"
    assert DEFAULT_CURATED_FILE.is_file()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_candidates.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `thoth_control_plane.attribution.candidates`.

- [ ] **Step 3: Write the candidates module**

`python/src/thoth_control_plane/attribution/candidates.py`:

```python
"""Which of the credited account's videos deserve a closer look, in the order to try them.

Everything here uses metadata discovery already returned, so it costs nothing. The window and
ratios come from Scout's `lib/main_gate.ts` (`isPlausibleSource`).
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.credit import normalize

logger = logging.getLogger(__name__)

# The same relative place in the repository and in the image (/opt/thoth/scout/config).
# Stage 10 moves this list into Python when Scout retires.
DEFAULT_CURATED_FILE = (
    Path(__file__).resolve().parents[4] / "scout" / "config" / "ig_accounts.json"
)
MAX_SOURCE_AGE = timedelta(days=14)
MIN_DURATION_RATIO = 0.9


def load_curated(path: Path = DEFAULT_CURATED_FILE) -> frozenset[str]:
    """Curated aggregator accounts, normalized; an unreadable list excludes nobody."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("curated account list unavailable; no account is excluded as aggregator")
        return frozenset()
    entries = data.get("accounts", []) if isinstance(data, dict) else data
    handles: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        text = re.sub(r"^https?://(www\.)?instagram\.com/", "", str(entry).strip(), flags=re.I)
        key = normalize(re.split(r"[/?#]", text, maxsplit=1)[0])
        if key:
            handles.add(key)
    return frozenset(handles)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def plausible(
    video: DiscoveredVideo, repost_time: datetime | None, repost_duration: float | None
) -> bool:
    """Published shortly before the repost and not shorter than it; unknown values pass."""
    published = parse_time(video.published_at)
    if repost_time is not None and published is not None:
        gap = repost_time - published
        if gap <= timedelta(0) or gap > MAX_SOURCE_AGE:
            return False
    duration = video.duration_seconds
    return not (repost_duration and duration and duration < repost_duration * MIN_DURATION_RATIO)


def shortlist(
    videos: Iterable[DiscoveredVideo],
    *,
    repost_owner: str,
    curated: frozenset[str],
    repost_time: datetime | None,
    repost_duration: float | None,
) -> tuple[list[DiscoveredVideo], dict[str, int]]:
    """The plausible videos, closest before the repost first, then the most played."""
    owner = normalize(repost_owner)
    counts: Counter[str] = Counter()
    kept: list[DiscoveredVideo] = []
    for video in videos:
        account = normalize(video.owner_handle)
        if account == owner or account in curated:
            counts["excluded_account"] += 1
        elif not plausible(video, repost_time, repost_duration):
            counts["filtered_window"] += 1
        else:
            kept.append(video)
    kept.sort(key=lambda video: _order(video, repost_time))
    return kept, dict(counts)


def _order(video: DiscoveredVideo, repost_time: datetime | None) -> tuple[float, int]:
    published = parse_time(video.published_at)
    gap = (
        (repost_time - published).total_seconds()
        if repost_time is not None and published is not None
        else math.inf
    )
    return gap, -video.engagement.get("play", 0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_candidates.py -p no:warnings`
Expected: PASS (5 tests).

- [ ] **Step 5: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/attribution tests/attribution && ~/.local/bin/uvx ruff check src/thoth_control_plane/attribution tests/attribution'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/attribution/candidates.py python/tests/attribution/test_candidates.py
git commit -m "feat(attribution): shortlist candidates by free metadata"
```

---

### Task 5: Ports and the local adapters (ffmpeg, imagehash, RapidOCR)

**Files:**
- Create: `python/src/thoth_control_plane/attribution/ports.py`
- Create: `python/src/thoth_control_plane/attribution/adapters/__init__.py`
- Create: `python/src/thoth_control_plane/attribution/adapters/frames.py`
- Create: `python/src/thoth_control_plane/attribution/adapters/ocr.py`
- Test: `python/tests/attribution/test_local_adapters.py`

**Interfaces:**
- Consumes: `TextBox` (Task 3); `Platform` (Task 2); `DiscoveredVideo`, `SourceReport`.
- Produces (ports): `Frame(second: float, jpeg: bytes)`; `CoverReading(headline, scene, icon)`
  and `VisualClass(kind)` Pydantic models; `VisualKind = Literal["footage", "commentary",
  "unknown"]`; `Decisions(is_repost, handle, handle_probability, platform,
  platform_probability)`; `AcquiredCandidate(candidate_id, report, video)`; protocols
  `FrameSource.frames(video, *, fps, seconds=None) -> list[Frame]`, `FrameHasher.hash(frame) ->
  int | None`, `TextReader.read(frame) -> list[TextBox]`, `VisionReader.read_cover(frames) ->
  CoverReading | None` and `.classify(frames) -> VisualKind | None`, `DecisionModel.decide(
  evidence, handles) -> Decisions | None`, `Discoverer.supports(platform) -> bool` and
  `.discover(platform, handle) -> list[DiscoveredVideo]`, `CandidateAcquirer.acquire(
  candidate_id, url) -> AcquiredCandidate | None` and `.discard(candidate_id) -> None`.
- Produces (adapters): `FfmpegFrameSource(ffmpeg="ffmpeg", width=360)`, `FrameError`,
  `ImageHasher()`, `RapidOcrReader()`.

- [ ] **Step 1: Write the ports module**

`python/src/thoth_control_plane/attribution/ports.py`:

```python
"""What the attribution service needs from the outside world; adapters implement it.

Every port may fail. The service treats a raised exception as "this piece of evidence or this
candidate is unavailable" and never lets it fail the attribution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import Platform

VisualKind = Literal["footage", "commentary", "unknown"]


@dataclass(frozen=True)
class Frame:
    second: float
    jpeg: bytes = field(repr=False)


class CoverReading(BaseModel):
    """What the vision model reads off a cover: bounded prose, never a decision."""

    headline: str = Field(
        default="", max_length=300, description="Text printed on the image, verbatim; empty if none"
    )
    scene: str = Field(default="", max_length=300, description="One sentence: what the video shows")
    icon: str = Field(
        default="",
        max_length=200,
        description="Any app or platform logo you see and where it is; empty if none",
    )


class VisualClass(BaseModel):
    kind: VisualKind = Field(
        description=(
            "footage: raw footage of an event; commentary: a person talking about it, a news "
            "anchor, a slideshow, or a reaction; unknown: cannot tell"
        )
    )


@dataclass(frozen=True)
class Decisions:
    is_repost: float
    handle: str | None
    handle_probability: float
    platform: Platform | None
    platform_probability: float


@dataclass(frozen=True)
class AcquiredCandidate:
    candidate_id: str
    report: SourceReport
    video: Path | None


class FrameSource(Protocol):
    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        ...


class FrameHasher(Protocol):
    def hash(self, frame: Frame) -> int | None: ...


class TextReader(Protocol):
    async def read(self, frame: Frame) -> list[TextBox]: ...


class VisionReader(Protocol):
    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None: ...

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None: ...


class DecisionModel(Protocol):
    async def decide(
        self, evidence: dict[str, object], handles: Sequence[str]
    ) -> Decisions | None: ...


class Discoverer(Protocol):
    def supports(self, platform: Platform) -> bool: ...

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]: ...


class CandidateAcquirer(Protocol):
    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None: ...

    async def discard(self, candidate_id: str) -> None: ...
```

- [ ] **Step 2: Write the failing adapter tests**

`python/tests/attribution/test_local_adapters.py`:

```python
"""The local adapters: ffmpeg frames, perceptual hashes, and RapidOCR text."""

from __future__ import annotations

import io
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.attribution.ports import Frame

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


def _jpeg(image: object, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)  # type: ignore[attr-defined]
    return buffer.getvalue()


def _noise(seed: int) -> object:
    from PIL import Image

    rng = random.Random(seed)
    small = Image.new("L", (36, 64))
    small.putdata([rng.randrange(256) for _ in range(36 * 64)])
    return small.resize((360, 640)).convert("RGB")


def test_hasher_ignores_flat_frames() -> None:
    pytest.importorskip("imagehash")
    from PIL import Image

    from thoth_control_plane.attribution.adapters.frames import ImageHasher

    black = Frame(0.0, _jpeg(Image.new("RGB", (360, 640), "black")))
    assert ImageHasher().hash(black) is None


def test_hasher_matches_a_reencoded_frame_with_a_new_credit_bar() -> None:
    pytest.importorskip("imagehash")
    from PIL import ImageDraw

    from thoth_control_plane.attribution.adapters.frames import ImageHasher
    from thoth_control_plane.attribution.matching import distance

    original = _noise(1)
    repost = original.copy()  # type: ignore[attr-defined]
    ImageDraw.Draw(repost).rectangle((0, 0, 360, 90), fill="white")
    hasher = ImageHasher()
    first = hasher.hash(Frame(0.0, _jpeg(original)))
    reposted = hasher.hash(Frame(0.0, _jpeg(repost, quality=60)))
    other = hasher.hash(Frame(0.0, _jpeg(_noise(2))))

    assert first is not None and reposted is not None and other is not None
    assert distance(first, reposted) <= 10 < distance(first, other)


@needs_ffmpeg
@pytest.mark.asyncio
async def test_ffmpeg_samples_frames_by_second(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    video = tmp_path / "clip.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
         "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )
    source = FfmpegFrameSource(FFMPEG)  # type: ignore[arg-type]

    frames = await source.frames(video, fps=1.0)
    assert [frame.second for frame in frames][:3] == [0.0, 1.0, 2.0]
    assert all(frame.jpeg.startswith(b"\xff\xd8") for frame in frames)
    assert all(frame.second < 2 for frame in await source.frames(video, fps=1.0, seconds=1.0))


@needs_ffmpeg
@pytest.mark.asyncio
async def test_ffmpeg_failure_raises_a_frame_error(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FrameError

    with pytest.raises(FrameError):
        await FfmpegFrameSource(FFMPEG).frames(tmp_path / "missing.mp4", fps=1.0)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_rapidocr_reads_a_handle_with_its_vertical_position() -> None:
    pytest.importorskip("rapidocr")
    from PIL import Image, ImageDraw, ImageFont

    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    image = Image.new("RGB", (720, 1280), "white")
    ImageDraw.Draw(image).text(
        (60, 1000), "@vincentius.christ76", fill="black", font=ImageFont.load_default(size=56)
    )

    boxes = await RapidOcrReader().read(Frame(0.0, _jpeg(image)))

    found = [box for box in boxes if "christ76" in box.text.replace(" ", "")]
    assert found, [box.text for box in boxes]
    assert 0.7 < found[0].top < found[0].bottom < 0.9
```

- [ ] **Step 3: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_local_adapters.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `thoth_control_plane.attribution.adapters`. The
two ffmpeg tests SKIP in WSL (no ffmpeg there); they run in CI.

- [ ] **Step 4: Write the local adapters**

`python/src/thoth_control_plane/attribution/adapters/__init__.py`:

```python
"""Port implementations; each imports its optional library inside its methods."""
```

`python/src/thoth_control_plane/attribution/adapters/frames.py`:

```python
"""Frames from ffmpeg and their perceptual hashes; both local and model-free."""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

from thoth_control_plane.attribution.ports import Frame

TIMEOUT_SECONDS = 120.0
# The kept window for hashing: the outer bands hold credit bars and headlines.
CROP = (0.1, 0.2, 0.9, 0.8)
# Below this luminance spread a frame is a fade, a black card, or a flat title: no signal.
FLAT_STDDEV = 8.0


class FrameError(Exception):
    """ffmpeg could not sample the video."""


class FfmpegFrameSource:
    def __init__(self, ffmpeg: str = "ffmpeg", width: int = 360) -> None:
        self._ffmpeg = ffmpeg
        self._width = width

    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        with tempfile.TemporaryDirectory(prefix="thoth-frames-") as directory:
            pattern = Path(directory) / "f%05d.jpg"
            limit = ["-t", f"{seconds:g}"] if seconds else []
            argv = [
                self._ffmpeg, "-nostdin", "-v", "error", *limit, "-i", str(video),
                "-vf", f"fps={fps:g},scale={self._width}:-2", "-q:v", "4", str(pattern),
            ]
            process = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            try:
                code = await asyncio.wait_for(process.wait(), TIMEOUT_SECONDS)
            except TimeoutError:
                raise FrameError("ffmpeg_timeout") from None
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if code != 0:
                raise FrameError("ffmpeg_failed")
            files = sorted(Path(directory).glob("f*.jpg"))
            return [Frame(index / fps, path.read_bytes()) for index, path in enumerate(files)]


class ImageHasher:
    def hash(self, frame: Frame) -> int | None:
        """The pHash of the frame's center, or None for a frame with no visual signal."""
        import imagehash
        from PIL import Image, ImageStat

        with Image.open(io.BytesIO(frame.jpeg)) as image:
            gray = image.convert("L")
        width, height = gray.size
        left, top, right, bottom = CROP
        center = gray.crop(
            (int(width * left), int(height * top), int(width * right), int(height * bottom))
        )
        if ImageStat.Stat(center).stddev[0] < FLAT_STDDEV:
            return None
        return int(str(imagehash.phash(center)), 16)
```

`python/src/thoth_control_plane/attribution/adapters/ocr.py`:

```python
"""Text boxes from RapidOCR (PaddleOCR models on ONNX Runtime), on the CPU."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

MAX_TEXT = 200


class RapidOcrReader:
    def __init__(self) -> None:
        self._engine: Any = None

    async def read(self, frame: Frame) -> list[TextBox]:
        return await asyncio.to_thread(self._read, frame.jpeg)

    def _read(self, jpeg: bytes) -> list[TextBox]:
        from PIL import Image

        with Image.open(io.BytesIO(jpeg)) as image:
            height = image.height
        result = self._get()(jpeg)
        if result.boxes is None or result.txts is None:
            return []
        boxes: list[TextBox] = []
        for quad, text in zip(result.boxes, result.txts, strict=False):
            ys = [float(point[1]) for point in quad]
            boxes.append(TextBox(str(text)[:MAX_TEXT], min(ys) / height, max(ys) / height))
        return boxes

    def _get(self) -> Any:
        if self._engine is None:
            from rapidocr import RapidOCR

            # RapidOCR logs every model load at INFO; keep the worker log to warnings.
            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            self._engine = RapidOCR()
        return self._engine
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_local_adapters.py -p no:warnings`
Expected: 3 passed, 2 skipped (ffmpeg). If the RapidOCR test reads the text with a different
spacing, adjust only the assertion's normalization and ledger it.

- [ ] **Step 6: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/attribution tests/attribution && ~/.local/bin/uvx ruff check src/thoth_control_plane/attribution tests/attribution'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/attribution/ports.py python/src/thoth_control_plane/attribution/adapters python/tests/attribution/test_local_adapters.py
git commit -m "feat(attribution): add ports and local frame, hash, and OCR adapters"
```

---

### Task 6: Remote adapters (Jev, Agno vision) and the profile discoverer

**Files:**
- Create: `python/src/thoth_control_plane/attribution/adapters/jev.py`
- Create: `python/src/thoth_control_plane/attribution/adapters/vision.py`
- Create: `python/src/thoth_control_plane/attribution/adapters/discovery.py`
- Test: `python/tests/attribution/test_remote_adapters.py`

**Interfaces:**
- Consumes: ports from Task 5; `ProfileDiscovery`, `DiscoveryResult` from
  `acquisition/models.py`; `ScraplingDiscoveryBrowser` (`acquisition/discovery.py`),
  `InstagramProfileDiscovery`, `XProfileDiscovery`, `YouTubeChannelDiscovery`.
- Produces: `JevDecisionModel(api_key, client=None)` with `JEV_URL`, `JEV_MODEL`;
  `AgnoVisionReader(api_key, model, *, base_url=NOVITA_BASE_URL)`; `ProfileDiscoverer(
  factories=None)`.

- [ ] **Step 1: Write the failing tests**

`python/tests/attribution/test_remote_adapters.py`:

```python
"""Remote adapters over mocked HTTP: Jev decisions, Agno vision, and profile discovery."""

from __future__ import annotations

import io
import json
from typing import Any

import httpx
import pytest
import respx

from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.attribution.adapters.discovery import ProfileDiscoverer
from thoth_control_plane.attribution.adapters.jev import JEV_MODEL, JEV_URL, JevDecisionModel
from thoth_control_plane.attribution.ports import CoverReading, Decisions, Frame

SOURCE = "vincentius.christ76"


def _answers(**answers: Any) -> httpx.Response:
    return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers})


IS_REPOST = {"type": "noul", "noul": 0.93}
PLATFORM = {
    "type": "choice",
    "choice": "tiktok",
    "probabilities": {"tiktok": 0.9, "unknown": 0.1},
    "confidence": 0.8,
}


@pytest.mark.asyncio
@respx.mock
async def test_jev_asks_typed_questions_and_reads_the_answers() -> None:
    handle = {
        "type": "choice",
        "choice": SOURCE,
        "probabilities": {SOURCE: 0.88, "none": 0.12},
        "confidence": 0.7,
    }
    route = respx.post(JEV_URL).mock(
        return_value=_answers(is_repost=IS_REPOST, credited_handle=handle, credited_platform=PLATFORM)
    )

    decisions = await JevDecisionModel("synthetic-jev-key").decide({"caption": "x"}, [SOURCE])

    assert decisions == Decisions(
        is_repost=0.93,
        handle=SOURCE,
        handle_probability=0.88,
        platform="tiktok",
        platform_probability=0.9,
    )
    request = route.calls.last.request
    body = json.loads(request.content)
    assert (body["model"], body["state"]) == (JEV_MODEL, {"caption": "x"})
    assert set(body["questions"]["credited_handle"]["criteria"]) == {SOURCE, "none"}
    assert request.headers["authorization"] == "Bearer synthetic-jev-key"


@pytest.mark.asyncio
@respx.mock
async def test_jev_without_handles_asks_no_handle_question() -> None:
    unknown = {"type": "choice", "choice": "unknown", "probabilities": {"unknown": 1}}
    route = respx.post(JEV_URL).mock(
        return_value=_answers(is_repost=IS_REPOST, credited_platform=unknown)
    )

    decisions = await JevDecisionModel("synthetic-jev-key").decide({}, [])

    assert decisions == Decisions(0.93, None, 0.0, None, 1.0)
    assert "credited_handle" not in json.loads(route.calls.last.request.content)["questions"]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"answers": {}}),
    ],
)
async def test_jev_failures_return_none(response: httpx.Response) -> None:
    respx.post(JEV_URL).mock(return_value=response)

    assert await JevDecisionModel("synthetic-jev-key").decide({}, [SOURCE]) is None


def _tiny_jpeg() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(buffer, format="JPEG")
    return buffer.getvalue()


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


@pytest.mark.asyncio
@respx.mock
async def test_vision_reads_the_cover_from_jpeg_frames() -> None:
    pytest.importorskip("openai")
    from thoth_control_plane.attribution.adapters.vision import NOVITA_BASE_URL, AgnoVisionReader

    reading = {"headline": "BANJIR", "scene": "a flooded street", "icon": "a note, bottom left"}
    route = respx.post(f"{NOVITA_BASE_URL}/chat/completions").mock(
        return_value=_completion(json.dumps(reading))
    )
    reader = AgnoVisionReader("synthetic-novita-key", "qwen/qwen3-vl-30b-a3b-instruct")

    assert await reader.read_cover([Frame(0.0, _tiny_jpeg())]) == CoverReading(**reading)
    body = route.calls.last.request.content.decode()
    assert "data:image/jpeg;base64" in body
    assert "qwen/qwen3-vl-30b-a3b-instruct" in body


@pytest.mark.asyncio
@respx.mock
async def test_vision_classifies_and_degrades_to_none() -> None:
    pytest.importorskip("openai")
    from thoth_control_plane.attribution.adapters.vision import NOVITA_BASE_URL, AgnoVisionReader

    route = respx.post(f"{NOVITA_BASE_URL}/chat/completions")
    reader = AgnoVisionReader("synthetic-novita-key", "qwen/qwen3-vl-30b-a3b-instruct")
    frames = [Frame(0.0, _tiny_jpeg())]

    route.mock(return_value=_completion(json.dumps({"kind": "commentary"})))
    assert await reader.classify(frames) == "commentary"
    route.mock(return_value=httpx.Response(500, json={"error": "down"}))
    assert await reader.classify(frames) is None


class _FakeDiscovery:
    def __init__(self, video: DiscoveredVideo) -> None:
        self.requests: list[ProfileDiscovery] = []
        self._video = video

    async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
        self.requests.append(request)
        return DiscoveryResult(
            kind="profile", videos=[self._video], pages=1, exhausted=True, drops=DiscoveryDrops()
        )


@pytest.mark.asyncio
async def test_profile_discoverer_routes_by_platform() -> None:
    video = DiscoveredVideo(
        post_id="7677137235434687752",
        owner_handle=SOURCE,
        canonical_url=f"https://www.tiktok.com/@{SOURCE}/video/7677137235434687752",
    )
    fake = _FakeDiscovery(video)
    discoverer = ProfileDiscoverer({"tiktok": lambda: fake})

    assert await discoverer.discover("tiktok", SOURCE) == [video]
    assert (fake.requests[0].handle, fake.requests[0].limit) == (SOURCE, 30)
    assert discoverer.supports("tiktok") is True
    assert ProfileDiscoverer().supports("threads") is False
    assert {p for p in ("tiktok", "instagram", "x", "youtube") if ProfileDiscoverer().supports(p)} == {
        "tiktok", "instagram", "x", "youtube"
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_remote_adapters.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `thoth_control_plane.attribution.adapters.discovery`.

- [ ] **Step 3: Write the Jev adapter**

`python/src/thoth_control_plane/attribution/adapters/jev.py`:

```python
"""Typed decisions from TypeSafe Jev over plain HTTP; no SDK, never prose.

Jev answers typed questions about one state with calibrated probabilities: `noul` (a yes
probability) and `choice` (one of the declared options). The handle question only ever offers
handles the evidence contains, so the answer cannot invent an account.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, get_args

import httpx

from thoth_control_plane.attribution.models import Platform
from thoth_control_plane.attribution.ports import Decisions

logger = logging.getLogger(__name__)

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13"
TIMEOUT_SECONDS = 10.0
NONE_OPTION = "none"
IS_REPOST = (
    "Does this evidence show that the post re-uploads a video made by another account? "
    "Signs: a credit or watermark naming another username, a repost or 'credit' caption."
)
CREDITED_HANDLE = (
    "Which handle is credited as the original creator of the video? "
    "Choose none when no handle is credited as the source."
)
CREDITED_PLATFORM = (
    "On which platform was the credited original posted? Use the platform icon description, "
    "the watermark text, and the caption."
)
PLATFORM_OPTIONS = {
    "tiktok": "TikTok: a TikTok logo, a music note, or a TikTok watermark",
    "instagram": "Instagram: a camera or Reels logo, or an Instagram credit",
    "x": "X or Twitter: an X or bird logo",
    "youtube": "YouTube: a red play-button logo",
    "threads": "Threads: an @-shaped Threads logo",
    "unknown": "the evidence does not show the platform",
}
PLATFORMS: frozenset[str] = frozenset(get_args(Platform))


class JevDecisionModel:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._client = client

    async def decide(
        self, evidence: dict[str, object], handles: Sequence[str]
    ) -> Decisions | None:
        questions: dict[str, Any] = {
            "is_repost": {"type": "noul", "instructions": IS_REPOST},
            "credited_platform": {
                "type": "choice",
                "instructions": CREDITED_PLATFORM,
                "criteria": PLATFORM_OPTIONS,
            },
        }
        if handles:
            criteria = {handle: f"@{handle} is credited as the original creator" for handle in handles}
            criteria[NONE_OPTION] = "no handle is credited as the original creator"
            questions["credited_handle"] = {
                "type": "choice",
                "instructions": CREDITED_HANDLE,
                "criteria": criteria,
            }
        try:
            async with self._session() as client:
                response = await client.post(
                    JEV_URL,
                    json={"model": JEV_MODEL, "state": evidence, "questions": questions},
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=TIMEOUT_SECONDS,
                )
            response.raise_for_status()
            return _parse(response.json()["answers"], handles)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("jev decision unavailable; attribution decides by rules")
            return None

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient() as client:
            yield client


def _parse(answers: dict[str, Any], handles: Sequence[str]) -> Decisions:
    is_repost = min(1.0, max(0.0, float(answers["is_repost"]["noul"])))
    platform_answer = answers["credited_platform"]
    platform = str(platform_answer["choice"])
    platform_probability = float(platform_answer["probabilities"][platform])
    handle: str | None = None
    handle_probability = 0.0
    handle_answer = answers.get("credited_handle")
    if handle_answer is not None:
        choice = str(handle_answer["choice"])
        if choice != NONE_OPTION and choice in handles:
            handle = choice
            handle_probability = float(handle_answer["probabilities"][choice])
    return Decisions(
        is_repost=is_repost,
        handle=handle,
        handle_probability=handle_probability,
        platform=platform if platform in PLATFORMS else None,  # type: ignore[arg-type]
        platform_probability=platform_probability,
    )
```

- [ ] **Step 4: Write the vision adapter**

`python/src/thoth_control_plane/attribution/adapters/vision.py`:

```python
"""Structured vision answers through Agno over Novita's OpenAI-compatible endpoint.

Agno sends anonymous telemetry by default; it is switched off here. The model is asked for
prose (a headline, a scene, an icon description) or one class, never for a platform name or an
account: those decisions belong to Jev and the code.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from thoth_control_plane.attribution.ports import CoverReading, Frame, VisualClass, VisualKind

logger = logging.getLogger(__name__)

NOVITA_BASE_URL = "https://api.novita.ai/openai/v1"
TIMEOUT_SECONDS = 60.0
MAX_FRAMES = 3
COVER_PROMPT = (
    "These are the cover and the first frames of a short video. Copy the text printed on the "
    "image, describe the scene in one sentence, and describe any app or platform logo you see "
    "and where it is. Answer in JSON."
)
CLASSIFY_PROMPT = (
    "These are frames of a short video. Is it raw footage of an event, or commentary (a person "
    "talking to the camera about it, a news anchor, a slideshow, or a reaction)? Answer in JSON."
)
Schema = TypeVar("Schema", bound=BaseModel)


class AgnoVisionReader:
    def __init__(self, api_key: str, model: str, *, base_url: str = NOVITA_BASE_URL) -> None:
        self._key = api_key
        self._model = model
        self._base_url = base_url

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None:
        return await self._run(CoverReading, COVER_PROMPT, frames)

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None:
        result = await self._run(VisualClass, CLASSIFY_PROMPT, frames)
        return result.kind if result is not None else None

    async def _run(
        self, schema: type[Schema], prompt: str, frames: Sequence[Frame]
    ) -> Schema | None:
        from agno.agent import Agent
        from agno.media import Image
        from agno.models.openai.like import OpenAILike

        agent = Agent(
            model=OpenAILike(
                id=self._model,
                api_key=self._key,
                base_url=self._base_url,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
            ),
            output_schema=schema,
            use_json_mode=True,
            telemetry=False,
        )
        images = [Image(content=frame.jpeg, mime_type="image/jpeg") for frame in frames[:MAX_FRAMES]]
        try:
            run = await agent.arun(input=prompt, images=images)
        except Exception:
            logger.warning("vision read unavailable; attribution continues without it")
            return None
        return run.content if isinstance(run.content, schema) else None
```

- [ ] **Step 5: Write the profile discoverer**

`python/src/thoth_control_plane/attribution/adapters/discovery.py`:

```python
"""The Stage 3 profile discoverers behind one call. Threads has no profile discovery yet."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from thoth_control_plane.acquisition.models import DiscoveredVideo, ProfileDiscovery
from thoth_control_plane.attribution.models import Platform

PROFILE_LIMIT = 30


def _tiktok() -> Any:
    from thoth_control_plane.acquisition.discovery import ScraplingDiscoveryBrowser

    return ScraplingDiscoveryBrowser()


def _instagram() -> Any:
    from thoth_control_plane.acquisition.instagram_discovery import InstagramProfileDiscovery

    return InstagramProfileDiscovery()


def _x() -> Any:
    from thoth_control_plane.acquisition.x_discovery import XProfileDiscovery

    return XProfileDiscovery()


def _youtube() -> Any:
    from thoth_control_plane.acquisition.youtube_discovery import YouTubeChannelDiscovery

    return YouTubeChannelDiscovery()


DEFAULT_FACTORIES: Mapping[str, Callable[[], Any]] = {
    "tiktok": _tiktok,
    "instagram": _instagram,
    "x": _x,
    "youtube": _youtube,
}


class ProfileDiscoverer:
    def __init__(self, factories: Mapping[str, Callable[[], Any]] | None = None) -> None:
        self._factories = factories if factories is not None else DEFAULT_FACTORIES

    def supports(self, platform: Platform) -> bool:
        return platform in self._factories

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        result = await self._factories[platform]().discover(
            ProfileDiscovery(handle=handle, limit=PROFILE_LIMIT)
        )
        return list(result.videos)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_remote_adapters.py -p no:warnings`
Expected: PASS (8 tests). If Agno 3.1.1 builds the request differently (for example the
image part or the JSON mode), adapt only the adapter to keep the asserted behavior and ledger a
ruling with what Agno did.

- [ ] **Step 7: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/attribution tests/attribution && ~/.local/bin/uvx ruff check src/thoth_control_plane/attribution tests/attribution'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/attribution/adapters python/tests/attribution/test_remote_adapters.py
git commit -m "feat(attribution): add Jev, vision, and profile discovery adapters"
```

---

### Task 7: The SourceAttributor service

**Files:**
- Create: `python/src/thoth_control_plane/attribution/service.py`
- Create: `python/tests/attribution/replay.py` (case-driven ports, shared with Task 10)
- Test: `python/tests/attribution/test_service.py`

**Interfaces:**
- Consumes: everything from Tasks 2 to 5.
- Produces: `Tuning` (frozen dataclass: `hash_fps=1.0`, `credit_seconds=3.0`,
  `reaction_frames=10`, `max_distance=10`, `match_threshold=0.6`, `repost_threshold=0.5`,
  `handle_threshold=0.5`, `max_finalists=3`, `finalist_concurrency=2`);
  `AttributionPorts(frames, hasher, text, discoverer, acquirer, vision=None, decisions=None)`;
  `AttributionOutcome(attribution, original=None)`; `SourceAttributor(ports, tuning=Tuning(),
  curated=frozenset())` with `.ports` and `async identify(workflow_id, report, video) ->
  AttributionOutcome`. Candidate IDs are `f"{workflow_id}-c{n}"`, n from 1 in shortlist order.
- Produces (tests): `replay.replay_ports(case: dict) -> AttributionPorts` and
  `replay.parse_report(data: dict) -> SourceReport`.

Spec reading recorded here: section 5 says "a credited finalist without a match but within the
plausibility window is `replaced`, confidence `low`". This plan reads "without a match" as "the
match could not be measured" (the repost has no hashable frames). A finalist whose measured
`match_share` is below the threshold is a different video and is rejected `no_match`. Section
5's tiers collapse here: every candidate comes from the credited account, the repost's own
account and aggregators are excluded by `shortlist`, so no tier code is needed.

- [ ] **Step 1: Write the replay ports**

`python/tests/attribution/replay.py`:

```python
"""Ports that answer from a recorded case; the service tests and golden fixtures share them.

A case maps frame keys to frames. A video path's stem names its key; a frame's JPEG bytes carry
`"<key>:<second>"`, so the hasher and the OCR reader can find what was recorded for it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import Platform
from thoth_control_plane.attribution.ports import (
    AcquiredCandidate,
    CoverReading,
    Decisions,
    Frame,
    VisualKind,
)
from thoth_control_plane.attribution.service import AttributionPorts


def parse_report(data: dict[str, Any]) -> SourceReport:
    return SourceReport.model_validate_json(json.dumps(data))


def frame_key(frame: Frame) -> tuple[str, float]:
    key, second = frame.jpeg.decode().rsplit(":", 1)
    return key, float(second)


class ReplayFrames:
    def __init__(self, frames: dict[str, list[dict[str, Any]]]) -> None:
        self._frames = frames
        self.calls: list[str] = []

    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        self.calls.append(video.stem)
        if video.stem not in self._frames:
            raise FileNotFoundError(video.stem)
        return [
            Frame(entry["second"], f"{video.stem}:{entry['second']}".encode())
            for entry in self._frames[video.stem]
            if seconds is None or entry["second"] < seconds
        ]


class ReplayHasher:
    def __init__(self, frames: dict[str, list[dict[str, Any]]]) -> None:
        self._hashes = {
            (key, entry["second"]): entry.get("hash")
            for key, entries in frames.items()
            for entry in entries
        }

    def hash(self, frame: Frame) -> int | None:
        value = self._hashes.get(frame_key(frame))
        return int(value, 16) if value else None


class ReplayText:
    def __init__(self, frames: dict[str, list[dict[str, Any]]]) -> None:
        self._boxes = {
            (key, entry["second"]): entry.get("boxes", [])
            for key, entries in frames.items()
            for entry in entries
        }
        self.calls = 0

    async def read(self, frame: Frame) -> list[TextBox]:
        self.calls += 1
        return [TextBox(text, top, bottom) for text, top, bottom in self._boxes.get(frame_key(frame), [])]


class ReplayVision:
    def __init__(self, cover: dict[str, str] | None, classify: dict[str, str]) -> None:
        self._cover = cover
        self._classify = classify
        self.calls = 0

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None:
        self.calls += 1
        return CoverReading(**self._cover) if self._cover is not None else None

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None:
        self.calls += 1
        return self._classify.get(frame_key(frames[0])[0], "footage")  # type: ignore[return-value]


class ReplayDecisions:
    def __init__(self, decisions: dict[str, Any]) -> None:
        self._decisions = decisions
        self.calls: list[tuple[dict[str, object], list[str]]] = []

    async def decide(self, evidence: dict[str, object], handles: Sequence[str]) -> Decisions | None:
        self.calls.append((evidence, list(handles)))
        return Decisions(**self._decisions)


class ReplayDiscoverer:
    def __init__(self, discovery: dict[str, Any] | None) -> None:
        self._discovery = discovery
        self.calls: list[tuple[str, str]] = []

    def supports(self, platform: Platform) -> bool:
        return platform != "threads"

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        self.calls.append((platform, handle))
        if self._discovery is None:
            raise RuntimeError("discovery unavailable")
        return [
            DiscoveredVideo.model_validate_json(json.dumps(video))
            for video in self._discovery["videos"]
        ]


class ReplayAcquirer:
    def __init__(self, acquired: dict[str, dict[str, Any]]) -> None:
        self._acquired = acquired
        self.acquired: list[str] = []
        self.discarded: list[str] = []

    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None:
        self.acquired.append(candidate_id)
        entry = self._acquired.get(url)
        if entry is None:
            return None
        video = Path(f"{entry['frames']}.mp4") if entry.get("frames") else None
        return AcquiredCandidate(candidate_id, parse_report(entry["report"]), video)

    async def discard(self, candidate_id: str) -> None:
        self.discarded.append(candidate_id)


def replay_ports(case: dict[str, Any]) -> AttributionPorts:
    frames = case["frames"]
    return AttributionPorts(
        frames=ReplayFrames(frames),
        hasher=ReplayHasher(frames),
        text=ReplayText(frames),
        discoverer=ReplayDiscoverer(case.get("discovery")),
        acquirer=ReplayAcquirer(case.get("acquired", {})),
        vision=ReplayVision(case.get("cover"), case.get("classify", {}))
        if case.get("vision", True)
        else None,
        decisions=ReplayDecisions(case["decisions"]) if case.get("decisions") else None,
    )
```

- [ ] **Step 2: Write the failing service tests**

`python/tests/attribution/test_service.py`:

```python
"""The attribution service end to end over replayed ports."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.attribution.replay import ReplayDecisions, parse_report, replay_ports
from thoth_control_plane.attribution.service import SourceAttributor, Tuning

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "tiktok" / "source_report_v3.json")
    .read_text(encoding="utf-8")
)
REPOST_URL = "https://www.tiktok.com/@detikjatim/video/7677496203042360594"
SOURCE = "vincentius.christ76"
REPOST_HASHES = ["0f0f0f0f0f0f0f0f", "f0f0f0f0f0f0f0f0", "00ff00ff00ff00ff"]
OTHER_HASHES = ["aaaaaaaaaaaaaaaa", "5555555555555555"]
VIDEO = Path("repost.mp4")


def _url(n: int) -> str:
    return f"https://www.tiktok.com/@{SOURCE}/video/{7677137235434687000 + n}"


def _report(
    *,
    owner: str = "detikjatim",
    url: str = REPOST_URL,
    text: str = "",
    published: str | None = "2026-08-24T07:26:32Z",
    duration: float = 90.0,
    video: bool = True,
) -> dict[str, Any]:
    data = copy.deepcopy(FIXTURE)
    data["source"]["canonical_url"] = url
    data["post"].update(
        owner_handle=owner, text=text, published_at=published, post_id=url.rsplit("/", 1)[1]
    )
    data["comments"] = []
    if video:
        data["media"][0]["duration_seconds"] = duration
    else:
        data["media"] = []
    return data


def _frames(hashes: list[str | None], boxes: dict[int, list[Any]] | None = None) -> list[dict]:
    return [
        {"second": float(n), "hash": value, "boxes": (boxes or {}).get(n, [])}
        for n, value in enumerate(hashes)
    ]


def _video(n: int, published: str) -> dict[str, Any]:
    return {
        "post_id": str(7677137235434687000 + n),
        "owner_handle": SOURCE,
        "canonical_url": _url(n),
        "published_at": published,
        "duration_seconds": 124.0,
        "engagement": {"play": 1},
    }


def _case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "frames": {
            "repost": _frames(REPOST_HASHES, {0: [["♪ vincentius.christ76   detikjatim", 0.88, 0.93]]}),
            "original": _frames([*REPOST_HASHES, *OTHER_HASHES]),
            "other": _frames(OTHER_HASHES),
        },
        "cover": {"headline": "BANJIR DI JATIM", "scene": "a flooded street", "icon": "a note"},
        "decisions": {
            "is_repost": 0.95,
            "handle": SOURCE,
            "handle_probability": 0.9,
            "platform": "tiktok",
            "platform_probability": 0.9,
        },
        "discovery": {
            "videos": [
                _video(1, "2026-08-24T10:00:00Z"),  # after the repost: filtered
                _video(2, "2026-08-22T09:00:00Z"),  # two days before: second
                _video(3, "2026-08-23T08:13:31Z"),  # 23 hours before: first, the original
            ]
        },
        "acquired": {
            _url(3): {"report": _report(owner=SOURCE, url=_url(3)), "frames": "original"},
            _url(2): {"report": _report(owner=SOURCE, url=_url(2)), "frames": "other"},
        },
    }
    case.update(overrides)
    return case


async def _identify(case: dict[str, Any], report: dict[str, Any] | None = None, **tuning: Any):
    ports = replay_ports(case)
    attributor = SourceAttributor(ports, Tuning(**tuning))
    video = VIDEO if (report or {}).get("media", [1]) else None
    outcome = await attributor.identify("wf_ref", parse_report(report or _report()), video)
    return outcome, ports


@pytest.mark.asyncio
async def test_the_reference_pair_resolves_to_the_credited_original() -> None:
    outcome, ports = await _identify(_case(), finalist_concurrency=1)
    attribution = outcome.attribution

    assert (attribution.verdict, attribution.confidence) == ("replaced", "high")
    assert attribution.source is not None and str(attribution.source.canonical_url) == _url(3)
    assert outcome.original is not None and outcome.original.candidate_id == "wf_ref-c1"
    assert ports.acquirer.acquired == ["wf_ref-c1"]  # early exit: c2 is never fetched
    assert attribution.candidates == {
        "discovered": 3,
        "filtered_window": 1,
        "matched": 1,
        "not_evaluated": 1,
    }
    details = {item.detail for item in attribution.evidence}
    assert {"@vincentius.christ76", "credit @vincentius.christ76"} <= details
    assert ports.decisions.calls[0][1] == [SOURCE]


@pytest.mark.asyncio
async def test_with_concurrency_two_the_extra_finalist_is_discarded() -> None:
    outcome, ports = await _identify(_case())

    assert outcome.attribution.verdict == "replaced"
    assert ports.acquirer.acquired == ["wf_ref-c1", "wf_ref-c2"]
    assert ports.acquirer.discarded == ["wf_ref-c2"]
    assert outcome.attribution.candidates["no_match"] == 1


@pytest.mark.asyncio
async def test_without_a_decision_key_one_found_handle_is_the_credit() -> None:
    outcome, _ = await _identify(_case(decisions=None))
    assert (outcome.attribution.verdict, outcome.attribution.confidence) == ("replaced", "high")

    two = _case(decisions=None)
    two["frames"]["repost"][0]["boxes"] = [["@vincentius.christ76 @other.acc1", 0.88, 0.93]]
    ambiguous, _ = await _identify(two)
    assert (ambiguous.attribution.verdict, ambiguous.attribution.reason) == (
        "unresolved",
        "ambiguous_credit",
    )


@pytest.mark.asyncio
async def test_a_caption_convention_overrides_the_model() -> None:
    _, ports = await _identify(_case(), _report(text="Lokasi [📸 @ig.creator]"))

    assert ports.discoverer.calls == [("instagram", "ig.creator")]


@pytest.mark.asyncio
async def test_no_credit_decides_original_or_unresolved_by_the_repost_probability() -> None:
    quiet = _case()
    quiet["frames"]["repost"][0]["boxes"] = []
    quiet["decisions"] = {**quiet["decisions"], "handle": None, "handle_probability": 0.0}

    quiet["decisions"]["is_repost"] = 0.1
    original, _ = await _identify(quiet)
    assert (original.attribution.verdict, original.attribution.confidence) == ("original", "high")

    quiet["decisions"]["is_repost"] = 0.9
    unresolved, _ = await _identify(quiet)
    assert (unresolved.attribution.verdict, unresolved.attribution.reason) == (
        "unresolved",
        "no_credit",
    )


@pytest.mark.asyncio
async def test_a_threads_credit_or_a_failed_discovery_is_unresolved() -> None:
    threads = _case()
    threads["decisions"] = {**threads["decisions"], "platform": "threads"}
    outcome, _ = await _identify(threads)
    assert outcome.attribution.reason == "discovery_unsupported"

    failed, _ = await _identify(_case(discovery=None))
    assert failed.attribution.reason == "discovery_failed"


@pytest.mark.asyncio
async def test_commentary_and_reaction_finalists_are_skipped() -> None:
    commentary, ports = await _identify(_case(classify={"original": "commentary"}))
    assert (commentary.attribution.verdict, commentary.attribution.reason) == (
        "unresolved",
        "no_match",
    )
    assert commentary.attribution.candidates["commentary"] == 1
    assert sorted(ports.acquirer.discarded) == ["wf_ref-c1", "wf_ref-c2"]

    speaking = _case()
    speaking["frames"]["original"] = _frames(
        [*REPOST_HASHES, *OTHER_HASHES],
        {n: [[f"kata ke {n}", 0.70, 0.76]] for n in range(5)},
    )
    reaction, _ = await _identify(speaking)
    assert reaction.attribution.candidates["reaction"] == 1


@pytest.mark.asyncio
async def test_a_repost_without_video_replaces_with_low_confidence() -> None:
    outcome, ports = await _identify(_case(), _report(video=False, text="via @vincentius.christ76"))

    assert (outcome.attribution.verdict, outcome.attribution.confidence) == ("replaced", "low")
    assert "repost" not in ports.frames.calls


@pytest.mark.asyncio
async def test_flat_repost_frames_leave_the_match_unmeasured() -> None:
    flat = _case()
    flat["frames"]["repost"] = _frames(
        [None, None, None], {0: [["♪ vincentius.christ76   detikjatim", 0.88, 0.93]]}
    )

    outcome, _ = await _identify(flat)

    assert (outcome.attribution.verdict, outcome.attribution.confidence) == ("replaced", "low")
    assert outcome.attribution.candidates["unmeasured"] == 2  # both finalists, none measurable


@pytest.mark.asyncio
async def test_self_credit_is_never_a_credit() -> None:
    own = _case()
    own["frames"]["repost"][0]["boxes"] = [["@detikjatim", 0.88, 0.93]]
    own["decisions"] = {**own["decisions"], "handle": None, "is_repost": 0.2}

    outcome, ports = await _identify(own)

    assert ports.decisions.calls[0][1] == []
    assert outcome.attribution.verdict == "original"


class _Raising(ReplayDecisions):
    async def decide(self, evidence: dict[str, object], handles: Any) -> Any:
        raise RuntimeError("jev down")


@pytest.mark.asyncio
async def test_port_failures_degrade_instead_of_failing() -> None:
    case = _case()
    case["acquired"] = {_url(2): case["acquired"][_url(2)]}  # the original cannot be acquired
    ports = replay_ports(case)
    object.__setattr__(ports, "decisions", _Raising(case["decisions"]))

    outcome = await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)

    assert (outcome.attribution.verdict, outcome.attribution.reason) == ("unresolved", "no_match")
    assert outcome.attribution.candidates["acquisition_failed"] == 1
```

- [ ] **Step 3: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_service.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `thoth_control_plane.attribution.service`.

- [ ] **Step 4: Write the service**

`python/src/thoth_control_plane/attribution/service.py`:

```python
"""S1 to S6 of source attribution: is this post the original, and if not, which post is?

`SourceAttributor.identify` reads evidence from the repost, decides the credit, discovers the
credited account's videos, filters them by free metadata, matches frames, and acquires at most a
few finalists, stopping at the first measured match. Every port failure degrades one piece of
evidence or one candidate; `identify` raises only on cancellation.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution import credit
from thoth_control_plane.attribution.candidates import parse_time, shortlist
from thoth_control_plane.attribution.matching import (
    FrameHash,
    TextBox,
    looks_like_burned_in_speech,
    match_share,
)
from thoth_control_plane.attribution.models import (
    MAX_EVIDENCE,
    AttributedPost,
    AttributionEvidence,
    Platform,
    SourceAttribution,
    Verdict,
)
from thoth_control_plane.attribution.ports import (
    AcquiredCandidate,
    CandidateAcquirer,
    CoverReading,
    DecisionModel,
    Discoverer,
    Frame,
    FrameHasher,
    FrameSource,
    TextReader,
    VisionReader,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class Tuning:
    """Provisional until the golden-fixture capture calibrates them (plan Task 11)."""

    hash_fps: float = 1.0
    credit_seconds: float = 3.0
    reaction_frames: int = 10
    max_distance: int = 10
    match_threshold: float = 0.6
    repost_threshold: float = 0.5
    handle_threshold: float = 0.5
    max_finalists: int = 3
    finalist_concurrency: int = 2


@dataclass(frozen=True)
class AttributionPorts:
    frames: FrameSource
    hasher: FrameHasher
    text: TextReader
    discoverer: Discoverer
    acquirer: CandidateAcquirer
    vision: VisionReader | None = None
    decisions: DecisionModel | None = None


@dataclass(frozen=True)
class AttributionOutcome:
    attribution: SourceAttribution
    original: AcquiredCandidate | None = None


@dataclass(frozen=True)
class _Credit:
    handle: str | None
    platform: Platform | None
    repost_probability: float
    by_model: bool
    ambiguous: bool = False


@dataclass
class _Finalist:
    video: DiscoveredVideo
    candidate_id: str
    checked: bool = False
    acquired: AcquiredCandidate | None = None
    share: float | None = None
    rejected: str | None = None


class SourceAttributor:
    def __init__(
        self,
        ports: AttributionPorts,
        tuning: Tuning = Tuning(),
        curated: frozenset[str] = frozenset(),
    ) -> None:
        self._ports = ports
        self._tuning = tuning
        self._curated = curated

    @property
    def ports(self) -> AttributionPorts:
        return self._ports

    async def identify(
        self, workflow_id: str, report: SourceReport, video: Path | None
    ) -> AttributionOutcome:
        frames = await self._frames(video)
        lines: list[str] = []
        for frame in frames:
            if frame.second < self._tuning.credit_seconds:
                lines += [box.text for box in await self._read(frame)]
        cover = await self._cover(frames)
        owner = report.post.owner_handle
        caption_handles = credit.text_handles(report.post.text)
        found_in_frames = credit.frame_handles(lines)
        options = credit.credit_options(caption_handles, found_in_frames, owner)
        evidence = _text_evidence(caption_handles, found_in_frames, owner, cover)
        decided = await self._credit(report, options, lines, cover, evidence)

        if decided.handle is None:
            if decided.ambiguous:
                return self._finish(
                    workflow_id, report, "unresolved", evidence, reason="ambiguous_credit"
                )
            repost = decided.repost_probability >= self._tuning.repost_threshold
            return self._finish(
                workflow_id,
                report,
                "unresolved" if repost else "original",
                evidence,
                reason="no_credit" if repost else None,
                confidence="high" if decided.by_model else "low",
            )

        platform: Platform = decided.platform or report.source.platform
        counts: Counter[str] = Counter()
        if not self._ports.discoverer.supports(platform):
            return self._finish(
                workflow_id, report, "unresolved", evidence, reason="discovery_unsupported"
            )
        videos = await self._guard(
            self._ports.discoverer.discover(platform, decided.handle), "discovery"
        )
        if videos is None:
            return self._finish(
                workflow_id, report, "unresolved", evidence, reason="discovery_failed"
            )
        counts["discovered"] = len(videos)
        repost_duration = next(
            (m.duration_seconds for m in report.media if m.kind == "video" and m.duration_seconds),
            None,
        )
        kept, dropped = shortlist(
            videos,
            repost_owner=owner,
            curated=self._curated,
            repost_time=parse_time(report.post.published_at),
            repost_duration=repost_duration,
        )
        counts.update(dropped)
        if not kept:
            return self._finish(
                workflow_id,
                report,
                "unresolved",
                evidence,
                reason="no_plausible_candidate",
                counts=counts,
            )

        finalists = [
            _Finalist(video, f"{workflow_id}-c{index}")
            for index, video in enumerate(kept[: self._tuning.max_finalists], start=1)
        ]
        winner = await self._evaluate(finalists, self._hashes(frames))
        for finalist in finalists:
            counts[_outcome(finalist)] += 1
            if finalist is not winner and finalist.acquired is not None:
                await self._guard(self._ports.acquirer.discard(finalist.candidate_id), "discard")
        if winner is None or winner.acquired is None:
            return self._finish(
                workflow_id, report, "unresolved", evidence, reason="no_match", counts=counts
            )

        acquired = winner.acquired
        evidence.append(
            AttributionEvidence(
                kind="visual_match",
                detail=f"match_share={winner.share:.2f}"
                if winner.share is not None
                else "match_unmeasured",
                confidence=winner.share,
            )
        )
        source = AttributedPost(
            platform=acquired.report.source.platform,
            canonical_url=acquired.report.source.canonical_url,
            owner_handle=acquired.report.post.owner_handle,
        )
        attribution = self._attribution(
            workflow_id,
            report,
            "replaced",
            evidence,
            source=source,
            confidence="high" if winner.share is not None else "low",
            counts=counts,
        )
        return AttributionOutcome(attribution, original=acquired)

    async def _credit(
        self,
        report: SourceReport,
        options: list[str],
        lines: list[str],
        cover: CoverReading | None,
        evidence: list[AttributionEvidence],
    ) -> _Credit:
        owner_key = credit.normalize(report.post.owner_handle)
        rule = credit.text_rule_credit(report.post.text)
        if rule is not None and credit.normalize(rule[0]) != owner_key:
            handle, platform = rule
            evidence.append(AttributionEvidence(kind="text_rule", detail=f"@{handle} on {platform}"))
            return _Credit(handle, platform, 1.0, by_model=False)
        if self._ports.decisions is not None:
            state: dict[str, object] = {
                "caption": report.post.text[:2000],
                "frame_text": " | ".join(lines)[:2000],
                "headline": cover.headline if cover else "",
                "scene": cover.scene if cover else "",
                "platform_icon": cover.icon if cover else "",
                "reposting_account": report.post.owner_handle,
                "reposting_platform": report.source.platform,
                "handles_found": list(options),
            }
            decided = await self._guard(self._ports.decisions.decide(state, options), "decision")
            if decided is not None:
                evidence.append(
                    AttributionEvidence(
                        kind="decision",
                        detail=f"repost probability {decided.is_repost:.2f}",
                        confidence=decided.is_repost,
                    )
                )
                handle = (
                    decided.handle
                    if decided.handle_probability >= self._tuning.handle_threshold
                    else None
                )
                if handle is not None:
                    evidence.append(
                        AttributionEvidence(
                            kind="decision",
                            detail=f"credit @{handle}",
                            confidence=decided.handle_probability,
                        )
                    )
                return _Credit(handle, decided.platform, decided.is_repost, by_model=True)
        if len(options) == 1:
            return _Credit(options[0], None, 1.0, by_model=False)
        return _Credit(
            None, None, 1.0 if options else 0.0, by_model=False, ambiguous=len(options) > 1
        )

    async def _evaluate(
        self, finalists: list[_Finalist], repost_hashes: list[FrameHash]
    ) -> _Finalist | None:
        step = max(1, self._tuning.finalist_concurrency)
        for start in range(0, len(finalists), step):
            batch = finalists[start : start + step]
            await asyncio.gather(*(self._check(finalist, repost_hashes) for finalist in batch))
            if any(f.rejected is None and f.share is not None for f in batch):
                break
        accepted = [f for f in finalists if f.checked and f.rejected is None]
        measured = [f for f in accepted if f.share is not None]
        if measured:
            return max(measured, key=lambda f: f.share or 0.0)
        return accepted[0] if accepted else None

    async def _check(self, finalist: _Finalist, repost_hashes: list[FrameHash]) -> None:
        finalist.checked = True
        acquired = await self._guard(
            self._ports.acquirer.acquire(finalist.candidate_id, str(finalist.video.canonical_url)),
            "acquisition",
        )
        if acquired is None:
            finalist.rejected = "acquisition_failed"
            return
        finalist.acquired = acquired
        frames = await self._frames(acquired.video)
        if repost_hashes:
            share = match_share(repost_hashes, self._hashes(frames), self._tuning.max_distance)
            if share is None:
                finalist.rejected = "no_video"
                return
            finalist.share = share
            if share < self._tuning.match_threshold:
                finalist.rejected = "no_match"
                return
        if self._ports.vision is not None and frames:
            kind = await self._guard(self._ports.vision.classify(frames[:3]), "vision")
            if kind == "commentary":
                finalist.rejected = "commentary"
                return
        readings: list[Sequence[TextBox]] = []
        for frame in frames[: self._tuning.reaction_frames]:
            readings.append(await self._read(frame))
        if looks_like_burned_in_speech(readings):
            finalist.rejected = "reaction"

    async def _frames(self, video: Path | None) -> list[Frame]:
        if video is None:
            return []
        frames = await self._guard(
            self._ports.frames.frames(video, fps=self._tuning.hash_fps), "frames"
        )
        return frames or []

    async def _read(self, frame: Frame) -> list[TextBox]:
        return await self._guard(self._ports.text.read(frame), "ocr") or []

    async def _cover(self, frames: list[Frame]) -> CoverReading | None:
        if self._ports.vision is None or not frames:
            return None
        return await self._guard(self._ports.vision.read_cover(frames[:3]), "vision")

    def _hashes(self, frames: list[Frame]) -> list[FrameHash]:
        hashes: list[FrameHash] = []
        for frame in frames:
            try:
                value = self._ports.hasher.hash(frame)
            except Exception:
                logger.warning("source attribution hash unavailable for one frame")
                continue
            if value is not None:
                hashes.append(FrameHash(frame.second, value))
        return hashes

    async def _guard(self, awaitable: Awaitable[T], what: str) -> T | None:
        try:
            return await awaitable
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("source attribution %s unavailable; continuing without it", what)
            return None

    def _attribution(
        self,
        workflow_id: str,
        report: SourceReport,
        verdict: Verdict,
        evidence: list[AttributionEvidence],
        *,
        source: AttributedPost | None = None,
        confidence: Literal["high", "low"] = "low",
        reason: str | None = None,
        counts: Counter[str] | None = None,
    ) -> SourceAttribution:
        return SourceAttribution(
            workflow_id=workflow_id,
            input=AttributedPost(
                platform=report.source.platform,
                canonical_url=report.source.canonical_url,
                owner_handle=report.post.owner_handle,
            ),
            verdict=verdict,
            source=source,
            confidence=confidence,
            reason=reason,
            evidence=evidence[:MAX_EVIDENCE],
            candidates=dict(counts or {}),
        )

    def _finish(
        self,
        workflow_id: str,
        report: SourceReport,
        verdict: Verdict,
        evidence: list[AttributionEvidence],
        **fields: object,
    ) -> AttributionOutcome:
        return AttributionOutcome(
            self._attribution(workflow_id, report, verdict, evidence, **fields)  # type: ignore[arg-type]
        )


def _outcome(finalist: _Finalist) -> str:
    if not finalist.checked:
        return "not_evaluated"
    if finalist.rejected is not None:
        return finalist.rejected
    return "matched" if finalist.share is not None else "unmeasured"


def _text_evidence(
    caption_handles: list[str],
    found_in_frames: list[str],
    owner: str,
    cover: CoverReading | None,
) -> list[AttributionEvidence]:
    owner_key = credit.normalize(owner)
    evidence = [
        AttributionEvidence(kind="caption", detail=f"@{handle}")
        for handle in caption_handles
        if credit.normalize(handle) != owner_key
    ]
    evidence += [
        AttributionEvidence(kind="frame_text", detail=f"@{handle}")
        for handle in found_in_frames
        if credit.normalize(handle) != owner_key
    ]
    if cover is not None:
        for label, text in (("headline", cover.headline), ("icon", cover.icon)):
            if text.strip():
                evidence.append(
                    AttributionEvidence(kind="cover_vision", detail=f"{label}: {text.strip()}"[:300])
                )
    return evidence
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: PASS (all attribution tests; ffmpeg ones skip).

- [ ] **Step 6: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/attribution tests/attribution && ~/.local/bin/uvx ruff check src/thoth_control_plane/attribution tests/attribution'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/attribution/service.py python/tests/attribution/replay.py python/tests/attribution/test_service.py
git commit -m "feat(attribution): decide the original and pick it by frame match"
```

---

### Task 8: The `attribute_source` activity

**Files:**
- Create: `python/src/thoth_control_plane/activities/source_attribution.py`
- Modify: `python/src/thoth_control_plane/activities/__init__.py`
- Modify: `python/src/thoth_control_plane/domain/models.py` (event payload key `verdict`)
- Modify: `python/src/thoth_control_plane/worker.py` (register the activity)
- Test: `python/tests/activities/test_source_attribution.py`

**Interfaces:**
- Consumes: `SourceAttributor`, `AttributionPorts`, `AttributionOutcome` (Task 7); the
  adapters (Tasks 5 and 6); `build_production_acquisition_runner`, `AcquisitionRunner`
  (`activities/source_investigation.py`); `load_curated` (Task 4).
- Produces: `SourceAttributionActivityInput(workflow_id)`;
  `SourceAttributionActivityResult(verdict, attribution=None, original_report=None,
  events=[])`; `RunnerAcquirer(runner, artifact_root)`; `build_production_ports(settings,
  artifact_root) -> AttributionPorts`; `build_source_attribution_activity(settings, *,
  attributor=None)`; module activity `attribute_source`. Artifacts: kind `source_attribution`
  at `reports/<workflow_id>/source-attribution.json`, kind `original_source_report` at
  `reports/<candidate_id>/source-report.json`. Event payload `{"stage": "attribution",
  "status": "succeeded" | "failed", "elapsed_ms": int, "verdict": verdict}`.

- [ ] **Step 1: Write the failing tests**

`python/tests/activities/test_source_attribution.py`:

```python
"""The attribute_source activity: read the repost report, persist the attribution."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.models import AcquisitionResult, SourceReport
from thoth_control_plane.activities.source_attribution import (
    RunnerAcquirer,
    SourceAttributionActivityInput,
    _run,
    build_production_ports,
)
from thoth_control_plane.attribution.models import AttributedPost, SourceAttribution
from thoth_control_plane.attribution.ports import AcquiredCandidate
from thoth_control_plane.attribution.service import AttributionOutcome
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.models import SourceProgressEvent

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tiktok" / "source_report_v3.json"
WORKFLOW = "wf_attr"
ORIGINAL = "https://www.tiktok.com/@vincentius.christ76/video/7677137235434687752"


def _report(workflow_id: str = WORKFLOW) -> SourceReport:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["workflow_id"] = workflow_id
    data["media"][0]["location"] = f"reports/{workflow_id}/media/tiktok-1234567890.mp4"
    return SourceReport.model_validate_json(json.dumps(data))


def _persist(root: Path, report: SourceReport, *, with_video: bool = True) -> None:
    folder = root / "reports" / WORKFLOW
    folder.mkdir(parents=True)
    (folder / "source-report.json").write_text(report.model_dump_json(), encoding="utf-8")
    if with_video:
        (root / report.media[0].location).parent.mkdir(parents=True, exist_ok=True)
        (root / report.media[0].location).write_bytes(b"\x00" * 2000)


class FakeAttributor:
    def __init__(self, outcome: AttributionOutcome | None = None, error: Exception | None = None):
        self.outcome = outcome
        self.error = error
        self.calls: list[tuple[str, SourceReport, Path | None]] = []

    async def identify(self, workflow_id: str, report: SourceReport, video: Path | None) -> Any:
        self.calls.append((workflow_id, report, video))
        if self.error is not None:
            raise self.error
        return self.outcome


def _replaced(original: SourceReport) -> AttributionOutcome:
    attribution = SourceAttribution(
        workflow_id=WORKFLOW,
        input=AttributedPost(
            platform="tiktok",
            canonical_url="https://www.tiktok.com/@creator/video/1234567890",
            owner_handle="creator",
        ),
        verdict="replaced",
        source=AttributedPost(
            platform="tiktok", canonical_url=ORIGINAL, owner_handle="vincentius.christ76"
        ),
        confidence="high",
    )
    return AttributionOutcome(attribution, AcquiredCandidate(f"{WORKFLOW}-c1", original, None))


@pytest.mark.asyncio
async def test_a_replaced_verdict_persists_both_artifacts(tmp_path: Path) -> None:
    report = _report()
    _persist(tmp_path, report)
    attributor = FakeAttributor(_replaced(_report(f"{WORKFLOW}-c1")))

    result = await _run(SourceAttributionActivityInput(workflow_id=WORKFLOW), tmp_path, attributor)

    assert result.verdict == "replaced"
    assert attributor.calls[0][2] == (tmp_path / report.media[0].location).resolve()
    assert result.attribution is not None and result.original_report is not None
    assert result.attribution.kind == "source_attribution"
    assert result.attribution.location == f"reports/{WORKFLOW}/source-attribution.json"
    written = (tmp_path / result.attribution.location).read_bytes()
    assert result.attribution.checksum == f"sha256:{sha256(written).hexdigest()}"
    assert SourceAttribution.model_validate_json(written).verdict == "replaced"
    assert result.original_report.kind == "original_source_report"
    assert result.original_report.location == f"reports/{WORKFLOW}-c1/source-report.json"
    assert (tmp_path / result.original_report.location).is_file()
    assert [event.payload for event in result.events] == [
        {
            "stage": "attribution",
            "status": "succeeded",
            "elapsed_ms": result.events[0].payload["elapsed_ms"],
            "verdict": "replaced",
        }
    ]


@pytest.mark.asyncio
async def test_a_missing_video_file_is_passed_as_none(tmp_path: Path) -> None:
    _persist(tmp_path, _report(), with_video=False)
    attributor = FakeAttributor(_replaced(_report(f"{WORKFLOW}-c1")))

    await _run(SourceAttributionActivityInput(workflow_id=WORKFLOW), tmp_path, attributor)

    assert attributor.calls[0][2] is None


@pytest.mark.asyncio
async def test_an_unreadable_report_is_unresolved_without_artifacts(tmp_path: Path) -> None:
    folder = tmp_path / "reports" / WORKFLOW
    folder.mkdir(parents=True)
    (folder / "source-report.json").write_text('{"legacy": true}', encoding="utf-8")
    attributor = FakeAttributor()

    result = await _run(SourceAttributionActivityInput(workflow_id=WORKFLOW), tmp_path, attributor)

    assert (result.verdict, result.attribution, result.original_report) == ("unresolved", None, None)
    assert result.events[0].payload["status"] == "failed"
    assert attributor.calls == []


@pytest.mark.asyncio
async def test_an_attributor_error_is_unresolved(tmp_path: Path) -> None:
    _persist(tmp_path, _report())

    result = await _run(
        SourceAttributionActivityInput(workflow_id=WORKFLOW),
        tmp_path,
        FakeAttributor(error=RuntimeError("secret detail must not leak")),
    )

    assert result.verdict == "unresolved"
    assert "secret detail" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_the_runner_acquirer_returns_the_candidate_and_its_video(tmp_path: Path) -> None:
    candidate = f"{WORKFLOW}-c1"
    report = _report(candidate)
    (tmp_path / report.media[0].location).parent.mkdir(parents=True)
    (tmp_path / report.media[0].location).write_bytes(b"\x00" * 2000)

    async def runner(workflow_id: str, url: str, root: Path) -> AcquisitionResult:
        assert (workflow_id, url, root) == (candidate, ORIGINAL, tmp_path)
        return AcquisitionResult(report=report)

    acquired = await RunnerAcquirer(runner, tmp_path).acquire(candidate, ORIGINAL)

    assert acquired is not None and acquired.candidate_id == candidate
    assert acquired.video == (tmp_path / report.media[0].location).resolve()


@pytest.mark.asyncio
async def test_discard_removes_only_a_candidate_directory_inside_the_root(tmp_path: Path) -> None:
    async def runner(*_: Any) -> AcquisitionResult:
        raise AssertionError("not called")

    keep = tmp_path / "reports" / WORKFLOW
    gone = tmp_path / "reports" / f"{WORKFLOW}-c2"
    for folder in (keep, gone):
        folder.mkdir(parents=True)
        (folder / "x").write_bytes(b"1")
    acquirer = RunnerAcquirer(runner, tmp_path)

    await acquirer.discard(f"{WORKFLOW}-c2")
    await acquirer.discard("../outside")
    await acquirer.discard("")

    assert keep.is_dir() and not gone.exists()


def test_production_ports_follow_the_configured_keys(tmp_path: Path) -> None:
    common = {"THOTH_CONTROL_PLANE_API_KEY": "k", "THOTH_CONTROL_PLANE_ARTIFACT_ROOT": tmp_path}
    without = build_production_ports(
        Settings(**common, THOTH_NOVITA_API_KEY=None, THOTH_TYPESAFE_API_KEY=None), tmp_path
    )
    with_keys = build_production_ports(
        Settings(
            **common,
            THOTH_NOVITA_API_KEY="nv-synthetic-key",
            THOTH_TYPESAFE_API_KEY="ts-synthetic-key",
        ),
        tmp_path,
    )

    assert (without.vision, without.decisions) == (None, None)
    assert with_keys.vision is not None and with_keys.decisions is not None


def test_provider_keys_never_reach_an_adapter_repr_or_the_ports(tmp_path: Path) -> None:
    # Spec section 8: keys live only inside the two adapters; nothing the activity persists or
    # returns is built from an adapter, so a key that is absent from their repr cannot leak.
    ports = build_production_ports(
        Settings(
            THOTH_CONTROL_PLANE_API_KEY="k",
            THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path,
            THOTH_NOVITA_API_KEY="nv-canary-0123456789",
            THOTH_TYPESAFE_API_KEY="ts-canary-0123456789",
        ),
        tmp_path,
    )

    rendered = repr(ports)
    assert "nv-canary" not in rendered and "ts-canary" not in rendered


def test_the_verdict_is_a_closed_event_payload_value() -> None:
    SourceProgressEvent(
        kind="stage.completed",
        payload={"stage": "attribution", "status": "succeeded", "verdict": "original"},
    )
    with pytest.raises(ValueError):
        SourceProgressEvent(
            kind="stage.completed", payload={"stage": "attribution", "verdict": "@someone"}
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/activities/test_source_attribution.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `thoth_control_plane.activities.source_attribution`.

- [ ] **Step 3: Allow the `verdict` event key**

In `python/src/thoth_control_plane/domain/models.py`:

1. In `SOURCE_EVENT_PAYLOAD_KEYS`, after `"no_account_available",` add `"verdict",`.
2. After the `SOURCE_EVENT_STATUSES = ...` line add:

```python
SOURCE_ATTRIBUTION_VERDICTS = frozenset({"original", "replaced", "unresolved"})
```

3. In `SourceProgressEvent.validate_payload`, after the `status` check add:

```python
        if "verdict" in payload and payload["verdict"] not in SOURCE_ATTRIBUTION_VERDICTS:
            raise ValueError("source event verdict is unsupported")
```

- [ ] **Step 4: Write the activity**

`python/src/thoth_control_plane/activities/source_attribution.py`:

```python
"""The `attribute_source` activity: attribute a persisted repost report, persist the result.

It reads `reports/<workflow_id>/source-report.json` (only a Stage 3 report, schema v3, is
accepted), runs the attributor, and writes the attribution and, when found, the original's
report. A failure anywhere is verdict `unresolved` with a failed event: the repost acquisition
always stands. Only IDs, the verdict, and elapsed milliseconds reach Temporal history.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import Field
from temporalio import activity

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.activities.source_investigation import (
    AcquisitionRunner,
    build_production_acquisition_runner,
)
from thoth_control_plane.attribution.adapters.discovery import ProfileDiscoverer
from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, ImageHasher
from thoth_control_plane.attribution.adapters.jev import JevDecisionModel
from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader
from thoth_control_plane.attribution.adapters.vision import AgnoVisionReader
from thoth_control_plane.attribution.candidates import load_curated
from thoth_control_plane.attribution.ports import AcquiredCandidate
from thoth_control_plane.attribution.service import (
    AttributionOutcome,
    AttributionPorts,
    SourceAttributor,
)
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import ArtifactRef
from thoth_control_plane.domain.models import (
    OPAQUE_ID_PATTERN,
    OpaqueId,
    SourceProgressEvent,
    StrictModel,
)

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30.0
ATTRIBUTION_FILE = "source-attribution.json"
REPORT_FILE = "source-report.json"
Verdict = Literal["original", "replaced", "unresolved"]


class SourceAttributionActivityInput(StrictModel):
    workflow_id: OpaqueId


class SourceAttributionActivityResult(StrictModel):
    verdict: Verdict
    attribution: ArtifactRef | None = None
    original_report: ArtifactRef | None = None
    events: list[SourceProgressEvent] = Field(default_factory=list)


class Attributor(Protocol):
    async def identify(
        self, workflow_id: str, report: SourceReport, video: Path | None
    ) -> AttributionOutcome: ...


def _video(report: SourceReport, artifact_root: Path) -> Path | None:
    root = artifact_root.resolve()
    for media in report.media:
        if media.kind == "video":
            path = (artifact_root / media.location).resolve()
            return path if path.is_relative_to(root) and path.is_file() else None
    return None


class RunnerAcquirer:
    """Acquire candidates through the production runner, each under its own report key."""

    def __init__(self, runner: AcquisitionRunner, artifact_root: Path) -> None:
        self._runner = runner
        self._root = artifact_root

    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None:
        result = await self._runner(candidate_id, url, self._root)
        if result.report is None:
            return None
        return AcquiredCandidate(candidate_id, result.report, _video(result.report, self._root))

    async def discard(self, candidate_id: str) -> None:
        if not re.fullmatch(OPAQUE_ID_PATTERN, candidate_id):
            return
        reports = (self._root / "reports").resolve()
        target = (reports / candidate_id).resolve()
        if target.parent == reports:
            await asyncio.to_thread(shutil.rmtree, target, True)


def build_production_ports(settings: Settings, artifact_root: Path) -> AttributionPorts:
    novita = settings.novita_api_key
    typesafe = settings.typesafe_api_key
    return AttributionPorts(
        frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
        hasher=ImageHasher(),
        text=RapidOcrReader(),
        discoverer=ProfileDiscoverer(),
        acquirer=RunnerAcquirer(build_production_acquisition_runner(settings), artifact_root),
        vision=AgnoVisionReader(novita, settings.THOTH_SOURCE_VISION_MODEL) if novita else None,
        decisions=JevDecisionModel(typesafe) if typesafe else None,
    )


def _write(artifact_root: Path, location: PurePosixPath, content: bytes) -> None:
    path = artifact_root / location
    part = path.with_name(path.name + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        part.write_bytes(content)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def _artifact(kind: str, label: str, location: PurePosixPath, content: bytes) -> ArtifactRef:
    digest = sha256(content).hexdigest()
    return ArtifactRef(
        artifact_id=f"art_{kind}_{digest[:20]}",
        kind=kind,
        label=label,
        media_type="application/json",
        location=location.as_posix(),
        checksum=f"sha256:{digest}",
        size_bytes=len(content),
    )


def _event(verdict: Verdict, elapsed_ms: int, status: Literal["succeeded", "failed"]) -> SourceProgressEvent:
    return SourceProgressEvent(
        kind="stage.completed" if status == "succeeded" else "stage.failed",
        payload={
            "stage": "attribution",
            "status": status,
            "elapsed_ms": elapsed_ms,
            "verdict": verdict,
        },
    )


async def _heartbeat() -> None:
    while True:
        if activity.in_activity():
            activity.heartbeat()
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def _run(
    input_: SourceAttributionActivityInput, artifact_root: Path, attributor: Attributor
) -> SourceAttributionActivityResult:
    started = time.monotonic()

    def failed() -> SourceAttributionActivityResult:
        elapsed = int((time.monotonic() - started) * 1000)
        return SourceAttributionActivityResult(
            verdict="unresolved", events=[_event("unresolved", elapsed, "failed")]
        )

    folder = PurePosixPath("reports") / input_.workflow_id
    try:
        report = SourceReport.model_validate_json((artifact_root / folder / REPORT_FILE).read_bytes())
    except (OSError, ValueError):
        logger.warning("source attribution skipped; no stage 3 report for this workflow")
        return failed()

    heartbeat = asyncio.create_task(_heartbeat())
    try:
        outcome = await attributor.identify(
            input_.workflow_id, report, _video(report, artifact_root)
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("source attribution failed; the repost report stands")
        return failed()
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

    try:
        content = outcome.attribution.model_dump_json(indent=2).encode("utf-8")
        location = folder / ATTRIBUTION_FILE
        _write(artifact_root, location, content)
        attribution = _artifact("source_attribution", "Source attribution", location, content)
        original = None
        if outcome.original is not None:
            original_location = (
                PurePosixPath("reports") / outcome.original.candidate_id / REPORT_FILE
            )
            original_content = outcome.original.report.model_dump_json(indent=2).encode("utf-8")
            _write(artifact_root, original_location, original_content)
            original = _artifact(
                "original_source_report",
                "Original source report",
                original_location,
                original_content,
            )
    except OSError:
        logger.warning("source attribution artifact could not be written")
        return failed()

    verdict = outcome.attribution.verdict
    elapsed = int((time.monotonic() - started) * 1000)
    return SourceAttributionActivityResult(
        verdict=verdict,
        attribution=attribution,
        original_report=original,
        events=[_event(verdict, elapsed, "succeeded")],
    )


@activity.defn(name="attribute_source")
async def attribute_source(
    input_: SourceAttributionActivityInput,
) -> SourceAttributionActivityResult:
    """Activity-name reference for workflow definitions and direct local use."""
    configured = build_source_attribution_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


def build_source_attribution_activity(
    settings: Settings, *, attributor: Attributor | None = None
) -> Callable[[SourceAttributionActivityInput], Awaitable[SourceAttributionActivityResult]]:
    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    selected = attributor or SourceAttributor(
        build_production_ports(settings, artifact_root), curated=load_curated()
    )

    @activity.defn(name="attribute_source")
    async def configured_source_attribution_activity(
        input_: SourceAttributionActivityInput,
    ) -> SourceAttributionActivityResult:
        return await _run(input_, artifact_root, selected)

    return configured_source_attribution_activity
```

- [ ] **Step 5: Export and register it**

In `python/src/thoth_control_plane/activities/__init__.py`, add the import block:

```python
from thoth_control_plane.activities.source_attribution import (
    SourceAttributionActivityInput,
    SourceAttributionActivityResult,
    attribute_source,
    build_source_attribution_activity,
)
```

and add `"SourceAttributionActivityInput"`, `"SourceAttributionActivityResult"`,
`"attribute_source"`, and `"build_source_attribution_activity"` to `__all__` in sorted position.

In `python/src/thoth_control_plane/worker.py`, add `build_source_attribution_activity` to the
`from thoth_control_plane.activities import (...)` list, and in `build_source_investigation_worker`
replace the `activities=[...]` value with:

```python
        activities=[
            build_source_investigation_activity(settings, runner=runner, capability=capability),
            build_source_attribution_activity(settings),
        ],
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/activities tests/test_worker.py tests/domain -p no:warnings`
Expected: PASS.

- [ ] **Step 7: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src tests/activities && ~/.local/bin/uvx ruff check src tests/activities'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/activities python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/worker.py python/tests/activities/test_source_attribution.py
git commit -m "feat(attribution): add the attribute_source activity"
```

---

### Task 9: Workflow and gateway wiring

**Files:**
- Modify: `python/src/thoth_control_plane/domain/models.py` (`SourceInvestigationWorkflowInput`)
- Modify: `python/src/thoth_control_plane/workflows/source_investigation.py`
- Modify: `python/src/thoth_control_plane/infrastructure/temporal_gateway.py`
- Test: `python/tests/workflows/test_source_investigation.py`

**Interfaces:**
- Consumes: `attribute_source`, `SourceAttributionActivityInput`,
  `SourceAttributionActivityResult` (Task 8); `Settings.THOTH_SOURCE_ATTRIBUTION_ENABLED`
  (Task 1).
- Produces: `SourceInvestigationWorkflowInput.attribute_source: bool = False`;
  `TemporalWorkflowGateway(client, *, activity_mode="python", attribute_source=False)`.

- [ ] **Step 1: Write the failing workflow tests**

Append to `python/tests/workflows/test_source_investigation.py` (add the imports at the top):

```python
from thoth_control_plane.activities.source_attribution import (
    SourceAttributionActivityInput,
    SourceAttributionActivityResult,
)

ATTRIBUTION_RELEASE: asyncio.Event | None = None


def _attribution_artifact(workflow_id: str, kind: str, name: str) -> dict[str, object]:
    return {
        "artifact_id": f"art_{kind}_001",
        "kind": kind,
        "label": "Attribution artifact",
        "media_type": "application/json",
        "location": f"reports/{workflow_id}/{name}",
        "checksum": "sha256:" + "b" * 64,
    }


@activity.defn(name="attribute_source")
async def fake_attribute(input_: SourceAttributionActivityInput) -> SourceAttributionActivityResult:
    return SourceAttributionActivityResult.model_validate(
        {
            "verdict": "replaced",
            "attribution": _attribution_artifact(
                input_.workflow_id, "source_attribution", "source-attribution.json"
            ),
            "original_report": _attribution_artifact(
                f"{input_.workflow_id}-c1", "original_source_report", "source-report.json"
            ),
            "events": [
                {
                    "kind": "stage.completed",
                    "payload": {
                        "stage": "attribution",
                        "status": "succeeded",
                        "elapsed_ms": 5,
                        "verdict": "replaced",
                    },
                }
            ],
        }
    )


@activity.defn(name="attribute_source")
async def crashing_attribute(input_: SourceAttributionActivityInput) -> SourceAttributionActivityResult:
    raise RuntimeError("attribution detail must not enter history")


@activity.defn(name="attribute_source")
async def blocking_attribute(input_: SourceAttributionActivityInput) -> SourceAttributionActivityResult:
    assert ATTRIBUTION_RELEASE is not None
    await ATTRIBUTION_RELEASE.wait()
    return SourceAttributionActivityResult(verdict="unresolved")


def _attributed(request: WorkflowRequest = VALID_IDENTIFY_REQUEST) -> SourceInvestigationWorkflowInput:
    return workflow_input(request).model_copy(update={"attribute_source": True})


@pytest.mark.asyncio
async def test_identify_original_appends_the_attribution_artifacts(
    workflow_env: WorkflowEnvironment,
) -> None:
    async with Worker(
        workflow_env.client,
        task_queue="test",
        workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run,
            args=[_attributed()],
            id="wf_test_attribution",
            task_queue="test",
        )

    assert result.status == "succeeded"
    assert [artifact.kind for artifact in result.artifacts] == [
        "source_report",
        "source_attribution",
        "original_source_report",
    ]


@pytest.mark.asyncio
async def test_a_failing_attribution_keeps_the_repost_result(
    workflow_env: WorkflowEnvironment,
) -> None:
    async with Worker(
        workflow_env.client,
        task_queue="test",
        workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, crashing_attribute],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run,
            args=[_attributed()],
            id="wf_test_attribution_failure",
            task_queue="test",
        )

    assert result.status == "succeeded"
    assert [artifact.kind for artifact in result.artifacts] == ["source_report"]
    assert "attribution detail" not in str(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_cancel_during_attribution_finishes_as_cancelled(
    workflow_env: WorkflowEnvironment,
) -> None:
    global ATTRIBUTION_RELEASE
    ATTRIBUTION_RELEASE = asyncio.Event()
    async with Worker(
        workflow_env.client,
        task_queue="test",
        workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, blocking_attribute],
    ):
        handle = await workflow_env.client.start_workflow(
            SourceInvestigationWorkflow.run,
            args=[_attributed()],
            id="wf_test_attribution_cancel",
            task_queue="test",
        )
        for _ in range(100):
            events = await handle.query(SourceInvestigationWorkflow.workflow_events)
            if any(event.stage and event.stage.name == "attribution" for event in events):
                break
            await asyncio.sleep(0.01)
        await handle.signal(SourceInvestigationWorkflow.request_cancel)
        await wait_for_status(handle, "cancelled")
        ATTRIBUTION_RELEASE.set()


@pytest.mark.asyncio
async def test_the_gateway_requests_attribution_when_enabled(
    workflow_env: WorkflowEnvironment,
) -> None:
    async with Worker(
        workflow_env.client,
        task_queue=TASK_QUEUE,
        workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute],
    ):
        gateway = TemporalWorkflowGateway(workflow_env.client, attribute_source=True)
        summary = await gateway.start(
            VALID_IDENTIFY_REQUEST,
            actor=Actor(actor_id="owner", actor_type="user"),
            idempotency_key="attribution-001",
        )
        result = await workflow_env.client.get_workflow_handle_for(
            SourceInvestigationWorkflow.run, summary.workflow_id
        ).result()

    assert [artifact.kind for artifact in result.artifacts][1:] == [
        "source_attribution",
        "original_source_report",
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/workflows/test_source_investigation.py -p no:warnings`
Expected: FAIL — `SourceInvestigationWorkflowInput` has no field `attribute_source`, and
`TemporalWorkflowGateway` takes no `attribute_source`.

- [ ] **Step 3: Add the input flag**

In `python/src/thoth_control_plane/domain/models.py`, in `SourceInvestigationWorkflowInput`, after
`    activity_mode: SourceActivityMode = "python"` add:

```python
    # Absent from histories started before Stage 4, so those replay without the new stage.
    attribute_source: bool = False
```

- [ ] **Step 4: Run the attribution stage in the workflow**

In `python/src/thoth_control_plane/workflows/source_investigation.py`:

1. Inside `with workflow.unsafe.imports_passed_through():`, after the
   `from thoth_control_plane.activities.source_investigation import (...)` block, add:

```python
    from thoth_control_plane.activities.source_attribution import (
        SourceAttributionActivityInput,
        attribute_source,
    )
```

2. Replace

```python
        if input_.intent == "identify_original":
            self._transition(WorkflowStatus.SUCCEEDED)
```

with

```python
        if input_.intent == "identify_original":
            if input_.attribute_source and input_.activity_mode != "legacy_scout":
                await self._attribute()
                if self._cancel_requested:
                    self._transition(WorkflowStatus.CANCELLED)
                    self._record_event(EventKind.WORKFLOW_CANCELLED)
                    return self._summary()
            self._transition(WorkflowStatus.SUCCEEDED)
```

3. Add this method after `_execute_legacy_activity`:

```python
    async def _attribute(self) -> None:
        """Attribute the acquired post; a failed attribution never fails the workflow."""
        self._record_event(
            EventKind.STAGE_STARTED, stage=StageProgress(name="attribution", progress=0.0)
        )
        task = asyncio.create_task(
            workflow.execute_activity(
                attribute_source,
                SourceAttributionActivityInput(workflow_id=self._workflow_id),
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        )
        await workflow.wait_condition(lambda: self._cancel_requested or task.done())
        if self._cancel_requested and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ActivityError):
                await task
            return
        try:
            result = await task
        except ActivityError:
            self._record_event(
                EventKind.STAGE_COMPLETED, stage=StageProgress(name="attribution", progress=1.0)
            )
            return
        self._source_events.extend(result.events)
        self._event_sequence += len(result.events)
        for artifact in (result.attribution, result.original_report):
            if artifact is not None:
                self._artifacts.append(artifact)
                self._record_event(EventKind.ARTIFACT_CREATED, artifact=artifact)
                self._event_sequence += 1
        self._updated_at = workflow.now()
        self._record_event(
            EventKind.STAGE_COMPLETED, stage=StageProgress(name="attribution", progress=1.0)
        )
```

- [ ] **Step 5: Pass the setting through the gateway**

In `python/src/thoth_control_plane/infrastructure/temporal_gateway.py`:

```python
    def __init__(
        self,
        client: Client,
        *,
        activity_mode: SourceActivityMode = "python",
        attribute_source: bool = False,
    ) -> None:
        self._client = client
        self._activity_mode = activity_mode
        self._attribute_source = attribute_source
```

In `connect`, replace the `return` with:

```python
        return cls(
            client,
            activity_mode=settings.source_investigation_activity_mode,
            attribute_source=settings.THOTH_SOURCE_ATTRIBUTION_ENABLED,
        )
```

In `start`, inside `SourceInvestigationWorkflowInput(...)`, add
`attribute_source=self._attribute_source,` after `activity_mode=self._activity_mode,`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/workflows tests/infrastructure tests/api -p no:warnings`
Expected: PASS, with every earlier workflow test unchanged.

- [ ] **Step 7: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src tests/workflows && ~/.local/bin/uvx ruff check src tests/workflows'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/workflows/source_investigation.py python/src/thoth_control_plane/infrastructure/temporal_gateway.py python/tests/workflows/test_source_investigation.py
git commit -m "feat(attribution): run attribution after an identify acquisition"
```

---

### Task 10: Golden fixture harness and capture tool

**Files:**
- Create: `python/tests/attribution/capture_golden.py` (operator tool, not collected)
- Create: `python/tests/attribution/test_golden.py`
- Create: `python/tests/attribution/test_capture.py`
- Create: `python/tests/fixtures/attribution/synthetic_reference.json`

**Interfaces:**
- Consumes: `replay_ports`, `parse_report` (Task 7); `build_production_ports` (Task 8);
  `SourceAttributor`, `Tuning`, `AttributionPorts`.
- Produces: `capture_golden.CAPTURE_TUNING`, `capture_golden.record_case(ports, report, video,
  *, case, expected, scout, departure=None) -> dict`, and a CLI
  `python -m tests.attribution.capture_golden --url --case --out --expect-verdict
  [--expect-source-url] [--scout-main-url] [--departure]`.

Fixture format (one JSON file per case):

```text
case            name
synthetic       true only for the synthetic case
report          the repost SourceReport v3 (comments and cards dropped)
repost_frames   the frame key of the repost video, or null when it has none
frames          {key: [{second, hash (16 hex) | null, boxes: [[text, top, bottom]]}]}
cover           CoverReading | null
classify        {frame key: footage | commentary | unknown}
decisions       Decisions | null (null means no Jev key)
discovery       {videos: [DiscoveredVideo]} | null (null means discovery failed)
acquired        {candidate url: {report, frames}}
expected        {verdict, source_url | null, confidence?}  -- the operator's ground truth
scout           {main_url | null, note}  -- what Scout made main for the same post
departure       a section-10 departure id when Python and Scout differ on purpose
```

- [ ] **Step 1: Write the synthetic fixture**

Write `python/tests/fixtures/attribution/synthetic_reference.json` with this Python script,
run once (`python D:/thoth-tmp/bu/s4/make_synthetic.py`):

```python
import json
from pathlib import Path

ROOT = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/python/tests")
base = json.loads((ROOT / "fixtures/tiktok/source_report_v3.json").read_text(encoding="utf-8"))
SOURCE = "vincentius.christ76"
REPOST_URL = "https://www.tiktok.com/@detikjatim/video/7677496203042360594"
ORIGINAL_URL = f"https://www.tiktok.com/@{SOURCE}/video/7677137235434687752"
OTHER_URL = f"https://www.tiktok.com/@{SOURCE}/video/7677000000000000001"


def report(owner, url, published, duration):
    data = json.loads(json.dumps(base))
    data["source"]["canonical_url"] = url
    data["post"].update(owner_handle=owner, post_id=url.rsplit("/", 1)[1], text="",
                        published_at=published)
    data["media"][0]["duration_seconds"] = duration
    data["comments"] = []
    return data


def frames(hashes, boxes=None):
    return [{"second": float(n), "hash": h, "boxes": (boxes or {}).get(n, [])}
            for n, h in enumerate(hashes)]


repost = ["0f0f0f0f0f0f0f0f", "f0f0f0f0f0f0f0f0", "00ff00ff00ff00ff"]
other = ["aaaaaaaaaaaaaaaa", "5555555555555555"]
case = {
    "case": "synthetic_reference",
    "synthetic": True,
    "report": report("detikjatim", REPOST_URL, "2026-08-24T07:26:32Z", 90.0),
    "repost_frames": "repost",
    "frames": {
        "repost": frames(repost, {0: [["♪ vincentius.christ76   detikjatim", 0.88, 0.93]]}),
        "original": frames(repost + other),
        "other": frames(other),
    },
    "cover": {"headline": "BANJIR DI JATIM", "scene": "a flooded street", "icon": "a note"},
    "classify": {},
    "decisions": {"is_repost": 0.95, "handle": SOURCE, "handle_probability": 0.9,
                  "platform": "tiktok", "platform_probability": 0.9},
    "discovery": {"videos": [
        {"post_id": "7677000000000000001", "owner_handle": SOURCE, "canonical_url": OTHER_URL,
         "published_at": "2026-08-22T09:00:00Z", "duration_seconds": 124.0,
         "engagement": {"play": 1}},
        {"post_id": "7677137235434687752", "owner_handle": SOURCE, "canonical_url": ORIGINAL_URL,
         "published_at": "2026-08-23T08:13:31Z", "duration_seconds": 124.0,
         "engagement": {"play": 77400}},
    ]},
    "acquired": {
        ORIGINAL_URL: {"report": report(SOURCE, ORIGINAL_URL, "2026-08-23T08:13:31Z", 124.0),
                       "frames": "original"},
        OTHER_URL: {"report": report(SOURCE, OTHER_URL, "2026-08-22T09:00:00Z", 124.0),
                    "frames": "other"},
    },
    "expected": {"verdict": "replaced", "source_url": ORIGINAL_URL, "confidence": "high"},
    "scout": {"main_url": None,
              "note": "Scout ends in MainCandidateNotFoundError on this pair "
                      "(docs/superpowers/specs/2026-08-26-source-video-identification-design.md)"},
    "departure": "visual_match",
}
target = ROOT / "fixtures/attribution/synthetic_reference.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes((json.dumps(case, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
print("wrote", target)
```

- [ ] **Step 2: Write the failing golden and capture tests**

`python/tests/attribution/test_golden.py`:

```python
"""Every golden case replays offline to its expected attribution (ADR 0001 parity)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.attribution.replay import parse_report, replay_ports
from thoth_control_plane.attribution.service import SourceAttributor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attribution"
CASES = sorted(FIXTURES.glob("*.json"))
DEPARTURES = {
    "repost_first",
    "visual_match",
    "no_story_search",
    "constrained_credit",
    "logo_by_decision",
    "scout_not_run",
}


def _video(case: dict[str, Any]) -> Path | None:
    key = case.get("repost_frames")
    return Path(f"{key}.mp4") if key and key in case["frames"] else None


@pytest.mark.asyncio
@pytest.mark.parametrize("path", CASES, ids=lambda path: path.stem)
async def test_a_golden_case_replays_to_its_expected_attribution(path: Path) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    report = parse_report(case["report"])

    outcome = await SourceAttributor(replay_ports(case)).identify("wf_golden", report, _video(case))

    attribution = outcome.attribution
    expected = case["expected"]
    assert attribution.verdict == expected["verdict"]
    source = str(attribution.source.canonical_url) if attribution.source else None
    assert source == expected.get("source_url")
    if "confidence" in expected:
        assert attribution.confidence == expected["confidence"]
    python_main = expected.get("source_url") or str(report.source.canonical_url)
    assert python_main == case["scout"]["main_url"] or case.get("departure") in DEPARTURES


def test_there_is_at_least_the_synthetic_case() -> None:
    assert any(path.stem == "synthetic_reference" for path in CASES)
```

`python/tests/attribution/test_capture.py`:

```python
"""The capture tool records what the ports answered; a recorded case replays identically."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.attribution.capture_golden import record_case
from tests.attribution.replay import parse_report, replay_ports
from thoth_control_plane.attribution.service import SourceAttributor

SYNTHETIC = Path(__file__).resolve().parents[1] / "fixtures" / "attribution" / "synthetic_reference.json"


@pytest.mark.asyncio
async def test_a_recorded_case_replays_to_the_same_attribution() -> None:
    source = json.loads(SYNTHETIC.read_text(encoding="utf-8"))
    report = parse_report(source["report"])

    recorded = await record_case(
        replay_ports(source),
        report,
        Path("repost.mp4"),
        case="roundtrip",
        expected=source["expected"],
        scout=source["scout"],
        departure="visual_match",
    )

    assert json.loads(json.dumps(recorded)) == recorded  # plain JSON only
    replayed = await SourceAttributor(replay_ports(recorded)).identify(
        "wf_golden", parse_report(recorded["report"]), Path(f"{recorded['repost_frames']}.mp4")
    )
    assert replayed.attribution.verdict == "replaced"
    assert set(recorded["acquired"]) == set(source["acquired"])  # wide tuning saw both
```

- [ ] **Step 3: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_golden.py tests/attribution/test_capture.py -p no:warnings`
Expected: `test_golden.py` PASSES on the synthetic case (the service already exists);
`test_capture.py` FAILS with `ModuleNotFoundError` for `tests.attribution.capture_golden`.
The golden pass is expected here: it proves the harness, not new behavior.

- [ ] **Step 4: Write the capture tool**

`python/tests/attribution/capture_golden.py`:

```python
"""Record one golden attribution case from live traffic (operator-authorized; plan Task 11).

Run only inside the capture container. It acquires the repost, runs attribution through
recording ports with a wide tuning (more finalists, no early exit), then fills the hash and OCR
boxes of every frame it saw and a visual class per candidate, so a replay can use any tuning.
The fixture holds no key, no URL query, and no CDN address.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution.models import Platform
from thoth_control_plane.attribution.ports import (
    AcquiredCandidate,
    CoverReading,
    Decisions,
    Frame,
    VisualKind,
)
from thoth_control_plane.attribution.service import AttributionPorts, SourceAttributor, Tuning

CAPTURE_TUNING = Tuning(max_finalists=5, finalist_concurrency=1, match_threshold=1.01)
WORKFLOW = "wf_golden"


def _plain(report: SourceReport) -> dict[str, Any]:
    trimmed = report.model_copy(update={"comments": [], "post_card": None, "profile_card": None})
    return json.loads(trimmed.model_dump_json())


class _Store:
    def __init__(self) -> None:
        self.frames: dict[str, list[Frame]] = {}
        self.cover: CoverReading | None = None
        self.decisions: Decisions | None = None
        self.discovery: list[DiscoveredVideo] | None = None
        self.discovery_called = False
        self.acquired: dict[str, tuple[SourceReport, str | None]] = {}


class _Frames:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        frames = await self._inner.frames(video, fps=fps, seconds=seconds)
        if seconds is None:
            self._store.frames[video.stem] = frames
        return frames


class _Vision:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None:
        self._store.cover = await self._inner.read_cover(frames)
        return self._store.cover

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None:
        return await self._inner.classify(frames)


class _Decisions:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def decide(self, evidence: dict[str, object], handles: Sequence[str]) -> Decisions | None:
        self._store.decisions = await self._inner.decide(evidence, handles)
        return self._store.decisions


class _Discoverer:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    def supports(self, platform: Platform) -> bool:
        return self._inner.supports(platform)

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        self._store.discovery_called = True
        self._store.discovery = await self._inner.discover(platform, handle)
        return self._store.discovery


class _Acquirer:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None:
        acquired = await self._inner.acquire(candidate_id, url)
        if acquired is not None:
            key = acquired.video.stem if acquired.video is not None else None
            self._store.acquired[url] = (acquired.report, key)
        return acquired

    async def discard(self, candidate_id: str) -> None:
        return None  # keep every candidate until its frames are recorded


async def record_case(
    ports: AttributionPorts,
    report: SourceReport,
    video: Path | None,
    *,
    case: str,
    expected: dict[str, Any],
    scout: dict[str, Any],
    departure: str | None = None,
) -> dict[str, Any]:
    store = _Store()
    recording = replace(
        ports,
        frames=_Frames(ports.frames, store),
        discoverer=_Discoverer(ports.discoverer, store),
        acquirer=_Acquirer(ports.acquirer, store),
        vision=_Vision(ports.vision, store) if ports.vision is not None else None,
        decisions=_Decisions(ports.decisions, store) if ports.decisions is not None else None,
    )
    await SourceAttributor(recording, CAPTURE_TUNING).identify(WORKFLOW, report, video)

    frames: dict[str, list[dict[str, Any]]] = {}
    for key, recorded in store.frames.items():
        entries = []
        for frame in recorded:
            value = ports.hasher.hash(frame)
            boxes = await ports.text.read(frame)
            entries.append(
                {
                    "second": frame.second,
                    "hash": f"{value:016x}" if value is not None else None,
                    "boxes": [[box.text, round(box.top, 4), round(box.bottom, 4)] for box in boxes],
                }
            )
        frames[key] = entries
    classify: dict[str, str] = {}
    if ports.vision is not None:
        for _, key in store.acquired.values():
            if key is not None and store.frames.get(key):
                classify[key] = await ports.vision.classify(store.frames[key][:3]) or "unknown"
    return {
        "case": case,
        "synthetic": False,
        "report": _plain(report),
        "repost_frames": video.stem if video is not None else None,
        "frames": frames,
        "cover": store.cover.model_dump() if store.cover is not None else None,
        "classify": classify,
        "decisions": vars(store.decisions) if store.decisions is not None else None,
        "discovery": (
            {"videos": [json.loads(video.model_dump_json()) for video in store.discovery]}
            if store.discovery is not None
            else None
        ),
        "acquired": {
            url: {"report": _plain(acquired_report), "frames": key}
            for url, (acquired_report, key) in store.acquired.items()
        },
        "expected": expected,
        "scout": scout,
        **({"departure": departure} if departure else {}),
    }


async def _main(arguments: argparse.Namespace) -> None:
    from thoth_control_plane.activities.source_attribution import _video, build_production_ports
    from thoth_control_plane.activities.source_investigation import (
        build_production_acquisition_runner,
    )
    from thoth_control_plane.config import Settings

    with tempfile.TemporaryDirectory(prefix="thoth-golden-") as directory:
        root = Path(directory)
        settings = Settings(  # type: ignore[call-arg]
            THOTH_CONTROL_PLANE_API_KEY="capture-only", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=root
        )
        result = await build_production_acquisition_runner(settings)(WORKFLOW, arguments.url, root)
        if result.report is None:
            raise SystemExit("repost acquisition failed")
        expected: dict[str, Any] = {
            "verdict": arguments.expect_verdict,
            "source_url": arguments.expect_source_url,
        }
        fixture = await record_case(
            build_production_ports(settings, root),
            result.report,
            _video(result.report, root),
            case=arguments.case,
            expected=expected,
            scout={"main_url": arguments.scout_main_url, "note": arguments.scout_note},
            departure=arguments.departure,
        )
    Path(arguments.out).write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("recorded", arguments.case, "frames:", {k: len(v) for k, v in fixture["frames"].items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-verdict", required=True, choices=["original", "replaced", "unresolved"])
    parser.add_argument("--expect-source-url", default=None)
    parser.add_argument("--scout-main-url", default=None)
    parser.add_argument("--scout-note", default="")
    parser.add_argument("--departure", default=None)
    asyncio.run(_main(parser.parse_args()))
```

`vars(store.decisions)` works because `Decisions` is a frozen dataclass without slots; it
returns the five fields as plain values.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format tests/attribution && ~/.local/bin/uvx ruff check tests/attribution'
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/tests/attribution python/tests/fixtures/attribution
git commit -m "test(attribution): add the golden fixture harness and capture tool"
```

---

### Task 11: HARD STOP — live capture of the golden cases and calibration

This task sends live requests to TikTok, Instagram, X, or YouTube, to Novita, and to TypeSafe.
It runs only after the operator authorizes it in the conversation. Ask, stop, and wait.

**Files:**
- Create: `python/tests/fixtures/attribution/<case>.json` (one per captured case)
- Modify (only if calibration needs it): `python/src/thoth_control_plane/attribution/service.py`
  (`Tuning` defaults) and `python/tests/attribution/test_service.py`

- [ ] **Step 1: Ask for authorization and the cases**

Ask the operator, in Indonesian, for:
1. authorization for the live capture;
2. whether `THOTH_TYPESAFE_API_KEY` is in the provider file (the capture runs without Jev
   if not, and records `decisions: null`);
3. the cases, each with its ground truth. Case 1 is fixed: repost
   `https://www.tiktok.com/@detikjatim/video/7677496203042360594`, original
   `https://www.tiktok.com/@vincentius.christ76/video/7677137235434687752`, Scout main `null`,
   departure `visual_match`. The operator picks cases 2 to 5 to fit spec section 9: an
   Instagram repost credited with `📸 @user`; an original with no credit; a repost whose credited
   account lacks the video; a credited account whose nearest candidate is a commentary upload.

- [ ] **Step 2: Run each capture**

For each case, run (one line, from Git Bash; `<...>` are the operator's values):

```bash
wsl -e bash -lc 'ENV=/mnt/c/Users/mfr/Documents/MyTools/CLIPPER/.env.stage1.local; IMG=$(grep -E "^THOTH_IMAGE=" $ENV | cut -d= -f2- | tr -d "\r"); PROV=$(grep -E "^THOTH_STAGE1_PROVIDER_ENV_FILE=" $ENV | cut -d= -f2- | tr -d "\r"); mkdir -p /mnt/d/thoth-tmp/bu/s4/golden; docker run --rm --user 0 --env-file "$PROV" -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python:/py:ro -v /mnt/d/thoth-tmp/bu/s4/golden:/out -e PYTHONPATH=/py/src:/py -w /py "$IMG" bash -lc "apt-get update -qq >/dev/null && apt-get install -y -qq libgl1 libglib2.0-0 >/dev/null && uv pip install -q --python /opt/thoth/python/.venv/bin/python imagehash==4.3.2 rapidocr==3.9.2 onnxruntime==1.30.0 openai agno==3.1.1 && python -m tests.attribution.capture_golden --url <URL> --case <name> --out /out/<name>.json --expect-verdict <verdict> <--expect-source-url URL> <--scout-main-url URL> <--departure id>" 2>&1 | tail -3' | sed -E 's#https?://[^ "]+#<url>#g'
```

Expected: `recorded <name> frames: {...}`. The deployed image does not carry the new
libraries yet, so this disposable container installs them at start. Never print the provider
file or the environment.

- [ ] **Step 3: Check the fixtures hold no secret**

```bash
python - <<'PY'
import json, pathlib, re
golden = pathlib.Path("D:/thoth-tmp/bu/s4/golden")
for path in sorted(golden.glob("*.json")):
    text = path.read_text(encoding="utf-8")
    json.loads(text)
    leaks = [p for p in (r"sk-[A-Za-z0-9]", r"Bearer ", r"[?&](signature|x-expires|tk|policy)=",
                         r"tiktokcdn|fbcdn|googlevideo|cdninstagram|twimg\.com/amplify")
             if re.search(p, text)]
    print(path.name, "ok" if not leaks else f"LEAK {leaks}")
PY
```

Expected: `ok` for every file. A `LEAK` stops the task: fix the capture sanitization with a
test, recapture, and ledger it.

- [ ] **Step 4: Replay and calibrate**

Copy the fixtures into `python/tests/fixtures/attribution/` and run:

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/attribution/test_golden.py -p no:warnings`

Expected: every case passes. When a case fails because a provisional `Tuning` default is wrong
for real data (for example `max_distance`, `match_threshold`, `repost_threshold`), change only
that default, first adding a service test that pins the new value against the case's recorded
numbers (RED), then the default (GREEN), then the whole attribution suite. Ledger each change
as a ruling with the case and the recorded number that drove it. A failure that a threshold
cannot explain is a bug: debug it, do not tune it away.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add python/tests/fixtures/attribution python/src/thoth_control_plane/attribution/service.py python/tests/attribution/test_service.py
git commit -m "test(attribution): record the live golden attribution cases"
```

---

### Task 12: Verification and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-10-08-stage4-source-attribution-design.md` (status line)
- Modify (CRLF): `CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`
- Modify: `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` (CRLF,
  gitignored)

- [ ] **Step 1: Run every suite**

```bash
cd C:/Users/mfr/Documents/MyTools/CLIPPER/python
MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pgtest.sh tests -rA -p no:warnings > D:/thoth-tmp/stage4-suite.txt 2>&1; echo EXIT=$?
for s in PASSED FAILED SKIPPED ERROR; do echo "$s $(grep -c "^$s" D:/thoth-tmp/stage4-suite.txt)"; done
```

Expected: 0 failed and 0 errors. A transient Temporal test-server start error is re-run alone
before it is believed.

- [ ] **Step 2: Run Ruff and refresh the graph**

Run the Ruff command from Global Constraints (expected: clean), then `graphify update .` from
the repository root. Never stage `graphify-out/`.

- [ ] **Step 3: Update the spec status line**

Replace the spec's `Status:` line with:

```markdown
Status: written spec approved by the operator on 2026-10-08; implemented on branch
`feat/stage4-source-attribution` (see `docs/superpowers/plans/2026-10-08-stage4-source-attribution.md`).
```

- [ ] **Step 4: Write the CHANGELOG section and the status notes**

Write the section to `D:/thoth-tmp/bu/s4/changelog-section.md` (LF):
- Heading: `## <today> - Stage 4: source attribution in Python`.
- What shipped, each item with its commit hash from `git log --oneline master..HEAD`: settings
  and dependencies; models and credit rules; frame matching; candidate shortlist; ports and
  adapters; the service; the activity; the workflow and gateway wiring; the golden harness and
  captured cases.
- Verification: suite counts, Ruff, and the golden cases (case names and verdicts only).
- Calibration rulings from Task 11, if any.
- Departures from Scout (spec section 10).
- `Next steps`:
  - The operator reviews the branch. Push, merge, and deploy each need their own authorization.
  - Deploy: the image gains `libgl1` and `libglib2.0-0`; add `THOTH_TYPESAFE_API_KEY` to the
    provider file if Jev is wanted; `THOTH_SOURCE_ATTRIBUTION_ENABLED` defaults to `true`.
  - The live smoke joins the final acceptance (ADR 0001).
  - Follow-ups (spec section 12): Stage 8 story search; Stage 5 final OCR; per-post cache; the
    TikTok original-sound shortcut; Threads profile discovery; cover-hash ordering.
  - The parked backlog stays on offer: interactive login, login-only capabilities, vault key
    rotation, the Creator Studio backlog.

Insert it into `CHANGELOG.md` before the first `## ` heading, keeping CRLF:

```bash
python - <<'PY'
from pathlib import Path

path = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/CHANGELOG.md")
data = path.read_bytes()
assert data.endswith(b"\r\n")
text = data.decode("utf-8").replace("\r\n", "\n")
section = Path("D:/thoth-tmp/bu/s4/changelog-section.md").read_text(encoding="utf-8")
at = text.index("\n## ") + 1
text = text[:at] + section.rstrip("\n") + "\n\n" + text[at:]
path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
PY
```

Append a short "Stage 4 status" entry to `docs/python-scout-migration-roadmap.md` and to the
checkpoint `progress.md`: what shipped, a pointer to the CHANGELOG section, and the same next
steps. Use the same script shape with
`text = text.rstrip("\n") + "\n\n" + entry.rstrip("\n") + "\n"`.

- [ ] **Step 5: Commit and stop**

```bash
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git add -f docs/superpowers/specs/2026-10-08-stage4-source-attribution-design.md
git add CHANGELOG.md docs/python-scout-migration-roadmap.md
git status --short
git commit -m "docs: record stage 4 source attribution"
```

Before committing, check that `git status --short` shows nothing from the never-stage list.
Then stop and report to the operator in Indonesian: the commits, the suites, the golden cases,
the rulings, and a **Next steps** section.
