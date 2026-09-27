# Stage 2 TikTok Comments and Card Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the headless visit's comments and real TikTok card crops as checksummed
artifacts recorded in `TikTokSourceReport` schema v2.

**Architecture:** A new `acquisition/cards.py` validates each in-memory PNG crop with the
standard library, writes it atomically under `reports/<workflow_id>/cards/`, and returns
path-only `CardArtifact` records. `TikTokAcquisitionService` calls it on both success paths just
before building the report. The activity's persistence-failure cleanup also removes recorded card
files. Golden fixtures come from one sanitized live capture of the Python headless visit.

**Tech Stack:** Python 3.12, Pydantic v2 (`StrictModel`), pytest with pytest-asyncio (auto mode),
standard library only (`struct`, `zlib`, `hashlib`, `os.replace`), and ruff.

**Spec:** `docs/superpowers/specs/2026-09-27-tiktok-stage2-comments-cards-design.md`

## Global Constraints

- Cards are real TikTok crops only. Never add a synthetic or Rust-rendered fallback. A card that cannot be validated or written is absent (`card=None`).
- Comments and cards never fail acquisition. Failure codes and retryability are unchanged from Stage 1.
- Stage 2 stops at the source report. Do not touch the dashboard, Studio, the Content Set, or Rust.
- The report accepts `schema_version` 1 or 2 and writes 2. Every new field defaults to empty, so v1 reports still validate.
- No image bytes, remote URLs, or avatar URLs are serialized. `CardArtifact.location` is a safe relative POSIX path.
- Card paths: `reports/<workflow_id>/cards/comment-<comment_id>.png` and `reports/<workflow_id>/cards/profile.png`.
- Card limits: `MAX_CARD_BYTES` is 2 MiB, width is 31..4096, height is 13..4096, and bytes-per-pixel must be at least `0.02`.
- Logging: at most one `warning` line per acquisition, carrying counts only (written, rejected, failed). No comment text, handle, id, or path ever reaches logs, events, or Temporal history.
- The repository is public:
  - Never commit raw comments, handles, post ids, URLs, or PNG crops.
  - Raw capture output stays under `D:/thoth-tmp`.
  - Never print the contents of `D:/thoth-tmp/bu/links.txt`, any fixture `url.txt`, or raw capture JSON.
- The offline test guard in `python/tests/conftest.py` must not be weakened. The one live capture in Task 6 runs outside pytest.
- Commits: exactly one `git commit -m "<subject>"` per commit, subject no longer than 72 characters, no body, no trailer, no AI attribution.
- Stage files explicitly by path.
  - Never stage `graphify-out/`, `build_log.txt`, `.superpowers/`, or `.env.stage1.local.bak-*`.
  - `docs/superpowers/` is gitignored; add plan and spec files with `git add -f`.
- `CHANGELOG.md` and `docs/python-scout-migration-roadmap.md` are CRLF. Edit them with Python binary reads and writes only.
- No push, deploy, Issue #5 post, or live smoke is authorized by this plan.
- Python tests run in WSL: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths>` (run from any directory; the script `cd`s into `python/`).
  - rtk compresses test output. Pipe through `tail` and read the summary line.
- Line length is 100 (ruff).

## Rulings recorded while planning

- **Sanitizer location.** The spec names `python/scripts/sanitize_tiktok_comment_capture.py`. The plan puts it in
  `python/src/thoth_control_plane/operations/tiktok_comment_fixture.py` instead.
  - Why: tests import it the same way as the other `operations/` modules, and it runs as
    `python -m thoth_control_plane.operations.tiktok_comment_fixture`.
  - Cost if wrong: one file move.
- **Warning emission.** The spec's single warning line is emitted only when at least one card was
  rejected or failed. A fully successful acquisition logs nothing.
  - Why: AGENTS.md reserves `warn` for degradation.
  - Cost if wrong: one `if`.
- **Shared constraint types.** `MAX_COMMENTS` moves from `browser.py` to `models.py`, because the
  report model now enforces the cap and `browser.py` already imports from `models.py`. The comment
  field constraints and the safe relative path check become shared annotated types, so
  `ReportComment` and `CardArtifact` cannot drift from `TikTokComment` and `MaterializedMedia`.
- **When cards are written.** Cards are written only on the two paths that return a report.
  - A path that ends in failure writes no card files, so it leaves no orphans.
  - A retry overwrites the same deterministic names. A card from an earlier attempt whose comment
    disappears in a later attempt stays on disk, but no report references it.

## Review Focus

1. **Cancellation during a card write.** A `CancelledError` raised inside `os.replace` must remove the
   `.part` file and still propagate. Pinned in Task 2 (`test_write_card_removes_part_file_when_replace_fails`).
2. **Unusable crop bytes.** Truncated or non-PNG bytes, such as a 20-byte prefix or a GIF header, drop the
   card, keep the comment, and never raise out of `persist_cards`. Pinned in Task 2
   (`test_png_size_rejects_non_png_or_truncated`, `test_persist_cards_keeps_every_comment_and_drops_only_bad_cards`).
3. **Headless exception, then TikWM rescue.** The report has no comments, no profile card, and no
   `cards/` directory. Pinned in Task 3 (`test_headless_exception_rescue_has_no_comments_or_cards`).
4. **Headless comments, then TikWM failure.** No card file is left behind. Pinned in Task 3
   (`test_failed_tikwm_after_headless_comments_writes_no_cards`).
5. **Log privacy.** The dropped-card warning carries counts only. Pinned in Task 2 by asserting the exact
   message list.

---

## File Structure

- **Modify** `python/src/thoth_control_plane/acquisition/models.py`:
  - add the shared constraint types, `MAX_COMMENTS`, `MAX_CARD_BYTES`, `CardArtifact` and `ReportComment`;
  - bring the report to schema v2.
- **Modify** `python/src/thoth_control_plane/acquisition/browser.py`: import `MAX_COMMENTS` from `models.py` instead of defining it.
- **Create** `python/src/thoth_control_plane/acquisition/cards.py`: PNG validation, atomic card writes, and `persist_cards`.
- **Modify** `python/src/thoth_control_plane/acquisition/service.py`: `_build_report` takes comments and the profile card; both success paths call `persist_cards`.
- **Modify** `python/src/thoth_control_plane/activities/source_investigation.py`: cleanup also removes recorded card files.
- **Create** `python/src/thoth_control_plane/operations/tiktok_comment_fixture.py`: deterministic capture sanitizer and CLI.
- **Create** `python/tests/fixtures/tiktok/comments/post-1.json`, `post-2.json` and `post-3.json`: sanitized golden captures.
- **Tests:**
  - modify `python/tests/acquisition/test_models.py`, `python/tests/acquisition/test_service.py` and `python/tests/activities/test_source_investigation.py`;
  - create `python/tests/acquisition/test_cards.py` and `python/tests/operations/test_tiktok_comment_fixture.py`.
- **Docs:**
  - `docs/python-scout-migration-roadmap.md` (target diagram);
  - `CHANGELOG.md`;
  - the program checkpoint `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` (gitignored).
- **Throwaway, never committed:** `D:/thoth-tmp/bu/capture_comments.py`, `D:/thoth-tmp/bu/capture_comments.sh`, and `D:/thoth-tmp/bu/check_fixture_leak.py`.

---

### Task 1: Report schema v2

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/models.py`
- Modify: `python/src/thoth_control_plane/acquisition/browser.py:41` (the `MAX_COMMENTS = 50` line) and its `models` import block (lines 27-34)
- Test: `python/tests/acquisition/test_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (in `thoth_control_plane.acquisition.models`):
  - `MAX_COMMENTS: int = 50`
  - `MAX_CARD_BYTES: int = 2 * 1024 * 1024`
  - `class CardArtifact(StrictModel)` with fields:
    - `location: PurePosixPath` (safe relative)
    - `media_type: Literal["image/png"] = "image/png"`
    - `bytes: int` (1..MAX_CARD_BYTES)
    - `checksum: Checksum`
    - `width: int` (>0)
    - `height: int` (>0)
  - `class ReportComment(StrictModel)` with fields:
    - `comment_id: str`
    - `author: str`
    - `text: str`
    - `likes: int = 0`
    - `card: CardArtifact | None = None`
  - `TikTokSourceReport` gains:
    - `schema_version: Literal[1, 2] = 2`
    - `comments: list[ReportComment]` (default `[]`, at most 50)
    - `profile_card: CardArtifact | None = None`

- [ ] **Step 1: Write the failing tests**

Add these imports to `python/tests/acquisition/test_models.py`:
- `import json`, if it is missing.
- `CardArtifact`, `MAX_CARD_BYTES` and `ReportComment`, added to the existing
  `from thoth_control_plane.acquisition.models import (...)` list.

`Path` and `PurePosixPath` are already imported by the file. Then append:

```python
FIXTURE_REPORT = (
    Path(__file__).resolve().parent.parent / "fixtures" / "tiktok" / "normalized_report.json"
)


def _fixture_report() -> TikTokSourceReport:
    return TikTokSourceReport.model_validate_json(FIXTURE_REPORT.read_text(encoding="utf-8"))


def _card(location: str = "reports/wf_contract_001/cards/comment-12345.png") -> CardArtifact:
    return CardArtifact(
        location=PurePosixPath(location),
        bytes=4_000,
        checksum="sha256:" + "b" * 64,
        width=300,
        height=80,
    )


def test_v1_report_still_validates_with_empty_enrichment() -> None:
    report = _fixture_report()
    assert report.schema_version == 1
    assert report.comments == []
    assert report.profile_card is None


def test_new_reports_default_to_schema_v2() -> None:
    assert TikTokSourceReport.model_fields["schema_version"].default == 2


def test_v2_report_round_trips_comments_and_cards() -> None:
    report = _fixture_report().model_copy(
        update={
            "schema_version": 2,
            "comments": [
                ReportComment(
                    comment_id="12345", author="user_001", text="hello 😂", likes=3, card=_card()
                ),
                ReportComment(comment_id="12346", author="user_002", text="no card"),
            ],
            "profile_card": _card("reports/wf_contract_001/cards/profile.png"),
        }
    )
    restored = TikTokSourceReport.model_validate_json(report.model_dump_json())
    assert restored == report
    assert restored.comments[1].card is None


@pytest.mark.parametrize(
    "location", ["/reports/wf/cards/profile.png", "reports/../../outside/profile.png"]
)
def test_card_artifact_rejects_unsafe_locations(location: str) -> None:
    with pytest.raises(ValidationError):
        _card(location)


@pytest.mark.parametrize("size", [0, MAX_CARD_BYTES + 1])
def test_card_artifact_rejects_out_of_range_sizes(size: int) -> None:
    with pytest.raises(ValidationError):
        CardArtifact(
            location=PurePosixPath("reports/wf/cards/profile.png"),
            bytes=size,
            checksum="sha256:" + "b" * 64,
            width=300,
            height=80,
        )


def test_report_rejects_more_than_fifty_comments() -> None:
    payload = json.loads(_fixture_report().model_dump_json())
    payload["comments"] = [
        {"comment_id": str(10_000 + index), "author": "user_001", "text": "x"}
        for index in range(51)
    ]
    with pytest.raises(ValidationError):
        TikTokSourceReport.model_validate_json(json.dumps(payload))


def test_report_comment_rejects_image_bytes() -> None:
    with pytest.raises(ValidationError):
        ReportComment.model_validate(
            {"comment_id": "12345", "author": "user_001", "text": "x", "card_png": b"\x89PNG"}
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_models.py 2>&1 | tail -5`
Expected: collection ERROR, `ImportError: cannot import name 'CardArtifact'`.

- [ ] **Step 3: Implement the models**

In `models.py`, change the pydantic import to include `AfterValidator`:

```python
from pydantic import AfterValidator, Field, HttpUrl, SecretStr, field_validator, model_validator
```

Delete `field_validator` from that import if ruff reports it unused after this step.

After the imports, before `class AcquisitionStrategy`, add:

```python
MAX_COMMENTS = 50
MAX_CARD_BYTES = 2 * 1024 * 1024


def _safe_relative_location(location: PurePosixPath) -> PurePosixPath:
    if location.is_absolute() or ".." in location.parts:
        raise ValueError("artifact location must be a safe relative path")
    return location


SafeRelativeLocation = Annotated[PurePosixPath, AfterValidator(_safe_relative_location)]
TikTokNumericId = Annotated[str, Field(pattern=r"^[0-9]{5,32}$")]
TikTokHandle = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
CommentText = Annotated[str, Field(min_length=1, max_length=2_000)]
```

In `MaterializedMedia`:
- change `location: PurePosixPath` to `location: SafeRelativeLocation`;
- delete its `validate_location` validator method (the `@field_validator("location")` block).

Replace the field annotations of `TikTokComment` with the shared types:

```python
class TikTokComment(StrictModel):
    comment_id: TikTokNumericId
    author: TikTokHandle
    text: CommentText
    likes: Annotated[int, Field(ge=0)] = 0
    # Real TikTok card crop (PNG); never a synthetic render, never serialized.
    card_png: bytes | None = Field(default=None, exclude=True, repr=False)
```

Directly above `class TikTokSourceReport`, add:

```python
class CardArtifact(StrictModel):
    """A real TikTok card crop persisted beside the report; never a synthetic render."""

    location: SafeRelativeLocation
    media_type: Literal["image/png"] = "image/png"
    bytes: Annotated[int, Field(ge=1, le=MAX_CARD_BYTES)]
    checksum: Checksum
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class ReportComment(StrictModel):
    comment_id: TikTokNumericId
    author: TikTokHandle
    text: CommentText
    likes: Annotated[int, Field(ge=0)] = 0
    card: CardArtifact | None = None
```

Replace `TikTokSourceReport` with:

```python
class TikTokSourceReport(StrictModel):
    # Version 1 reports (Stage 1 evidence) carry no comments or cards and still validate.
    schema_version: Literal[1, 2] = 2
    workflow_id: OpaqueId
    source: TikTokSource
    post: TikTokPost
    media: Annotated[list[MaterializedMedia], Field(min_length=1, max_length=1)]
    outcome: AcquisitionOutcome
    comments: list[ReportComment] = Field(default_factory=list, max_length=MAX_COMMENTS)
    profile_card: CardArtifact | None = None
```

In `browser.py`:
- delete the line `MAX_COMMENTS = 50`;
- add `MAX_COMMENTS,` as the first name in the `from thoth_control_plane.acquisition.models import (` block.

`tests/acquisition/test_browser.py` imports `MAX_COMMENTS` from `browser` and keeps working.

- [ ] **Step 4: Run the acquisition and activity tests to verify they pass**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/operations/test_tiktok_parity.py 2>&1 | tail -5`
Expected: all passed, 0 failed. `test_tiktok_parity.py` proves Stage 1 v1 evidence still loads.

- [ ] **Step 5: Lint and commit**

Run: `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check src tests && ~/.local/bin/uvx ruff format --check src tests'`
Expected: `All checks passed!` and `... files already formatted`. If format fails, run `uvx ruff format` on the touched files and re-check.

```bash
git add python/src/thoth_control_plane/acquisition/models.py python/src/thoth_control_plane/acquisition/browser.py python/tests/acquisition/test_models.py
git commit -m "feat: add tiktok source report v2 with comments and card artifacts"
```

---

### Task 2: Card writer

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/cards.py`
- Test: `python/tests/acquisition/test_cards.py`

**Interfaces:**
- Consumes (from Task 1): `MAX_CARD_BYTES`, `BrowserSnapshot`, `CardArtifact`, `ReportComment`, `TikTokComment`.
- Produces (in `thoth_control_plane.acquisition.cards`):
  - `MIN_CARD_BPP: float = 0.02`
  - `class CardRejected(ValueError)`
  - `png_size(data: bytes) -> tuple[int, int]`, which raises `CardRejected`
  - `card_problem(width: int, height: int, size: int) -> str | None`, returning `"size"`, `"dimensions"`, `"flat"`, or `None`
  - `write_card(data: bytes, artifact_root: Path, location: PurePosixPath) -> CardArtifact`, which raises `CardRejected` or `OSError`
  - `persist_cards(snapshot: BrowserSnapshot | None, workflow_id: str, artifact_root: Path) -> tuple[list[ReportComment], CardArtifact | None]`
- Produces (in `tests.acquisition.test_cards`): `make_png(width: int, height: int, *, flat: bool = False) -> bytes`.
  Task 3 imports it.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_cards.py`:

```python
"""Real TikTok card crops persisted as checksummed report artifacts."""

import asyncio
import hashlib
import json
import logging
import random
import struct
import zlib
from pathlib import PurePosixPath

import pytest

from thoth_control_plane.acquisition import cards
from thoth_control_plane.acquisition.cards import (
    CardRejected,
    card_problem,
    persist_cards,
    png_size,
    write_card,
)
from thoth_control_plane.acquisition.models import MAX_CARD_BYTES, BrowserSnapshot, TikTokComment

SOURCE_URL = "https://www.tiktok.com/@creator/video/1234567890"
CARD_ROOT = PurePosixPath("reports/wf_cards_001/cards")
CARD_LOCATION = CARD_ROOT / "comment-12345.png"


def make_png(width: int, height: int, *, flat: bool = False) -> bytes:
    """A valid RGB PNG: noisy pixels stay large like a real card, flat ones compress away."""
    rng = random.Random(width * 10_007 + height)
    row = width * 3
    raw = b"".join(b"\x00" + (bytes(row) if flat else rng.randbytes(row)) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _snapshot(comments: list[TikTokComment], profile: bytes | None = None) -> BrowserSnapshot:
    return BrowserSnapshot(final_url=SOURCE_URL, comments=comments, profile_card_png=profile)


def test_png_size_reads_ihdr_dimensions() -> None:
    assert png_size(make_png(300, 80)) == (300, 80)


@pytest.mark.parametrize(
    "data",
    [b"", b"\x89PNG\r\n\x1a\n", b"GIF89a" + bytes(40), make_png(300, 80)[:20]],
    ids=["empty", "signature-only", "gif", "truncated-ihdr"],
)
def test_png_size_rejects_non_png_or_truncated(data: bytes) -> None:
    with pytest.raises(CardRejected):
        png_size(data)


@pytest.mark.parametrize(
    ("width", "height", "size", "problem"),
    [
        (300, 80, 6_000, None),
        (31, 13, 100, None),
        (300, 80, 0, "size"),
        (300, 80, MAX_CARD_BYTES + 1, "size"),
        (30, 80, 6_000, "dimensions"),
        (300, 12, 6_000, "dimensions"),
        (4_097, 80, 60_000, "dimensions"),
        (300, 4_097, 60_000, "dimensions"),
        (400, 100, 799, "flat"),
        (400, 100, 800, None),
    ],
)
def test_card_problem(width: int, height: int, size: int, problem: str | None) -> None:
    assert card_problem(width, height, size) == problem


def test_write_card_is_atomic_and_checksummed(tmp_path) -> None:
    data = make_png(300, 80)
    artifact = write_card(data, tmp_path, CARD_LOCATION)
    assert (tmp_path / CARD_LOCATION).read_bytes() == data
    assert artifact.location == CARD_LOCATION
    assert artifact.media_type == "image/png"
    assert artifact.bytes == len(data)
    assert artifact.checksum == "sha256:" + hashlib.sha256(data).hexdigest()
    assert (artifact.width, artifact.height) == (300, 80)
    assert list(tmp_path.rglob("*.part")) == []


def test_write_card_retry_overwrites_the_same_name(tmp_path) -> None:
    write_card(make_png(300, 80), tmp_path, CARD_LOCATION)
    second = make_png(320, 90)
    write_card(second, tmp_path, CARD_LOCATION)
    assert [path.name for path in (tmp_path / CARD_ROOT).iterdir()] == ["comment-12345.png"]
    assert (tmp_path / CARD_LOCATION).read_bytes() == second


def test_write_card_rejects_a_flat_crop_without_writing(tmp_path) -> None:
    with pytest.raises(CardRejected):
        write_card(make_png(400, 100, flat=True), tmp_path, CARD_LOCATION)
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    "error", [OSError("disk full"), asyncio.CancelledError()], ids=["oserror", "cancelled"]
)
def test_write_card_removes_part_file_when_replace_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    def failing_replace(*args, **kwargs):
        raise error

    monkeypatch.setattr(cards.os, "replace", failing_replace)
    with pytest.raises(type(error)):
        write_card(make_png(300, 80), tmp_path, CARD_LOCATION)
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_persist_cards_keeps_every_comment_and_drops_only_bad_cards(tmp_path, caplog) -> None:
    snapshot = _snapshot(
        [
            TikTokComment(
                comment_id="11111", author="alpha", text="first", likes=2, card_png=make_png(300, 80)
            ),
            TikTokComment(
                comment_id="22222",
                author="beta",
                text="second",
                card_png=make_png(400, 100, flat=True),
            ),
            TikTokComment(comment_id="33333", author="gamma", text="third", card_png=b"not a png"),
            TikTokComment(comment_id="44444", author="delta", text="fourth"),
        ],
        profile=make_png(500, 200),
    )
    with caplog.at_level(logging.WARNING, logger=cards.__name__):
        comments, profile = persist_cards(snapshot, "wf_cards_001", tmp_path)

    assert [comment.comment_id for comment in comments] == ["11111", "22222", "33333", "44444"]
    assert [comment.author for comment in comments] == ["alpha", "beta", "gamma", "delta"]
    assert comments[0].likes == 2
    assert comments[0].card is not None
    assert comments[0].card.location == CARD_ROOT / "comment-11111.png"
    assert [comment.card for comment in comments[1:]] == [None, None, None]
    assert profile is not None
    assert profile.location == CARD_ROOT / "profile.png"
    assert sorted(path.name for path in (tmp_path / CARD_ROOT).iterdir()) == [
        "comment-11111.png",
        "profile.png",
    ]
    assert [record.getMessage() for record in caplog.records] == [
        "tiktok card crops: written=2 rejected=2 failed=0"
    ]


def test_persist_cards_drops_a_card_whose_write_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    def failing_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cards.os, "replace", failing_replace)
    snapshot = _snapshot(
        [TikTokComment(comment_id="11111", author="alpha", text="first", card_png=make_png(300, 80))]
    )
    with caplog.at_level(logging.WARNING, logger=cards.__name__):
        comments, profile = persist_cards(snapshot, "wf_cards_001", tmp_path)

    assert [comment.comment_id for comment in comments] == ["11111"]
    assert comments[0].card is None
    assert profile is None
    assert [record.getMessage() for record in caplog.records] == [
        "tiktok card crops: written=0 rejected=0 failed=1"
    ]


def test_persist_cards_is_silent_when_every_card_is_written(tmp_path, caplog) -> None:
    snapshot = _snapshot(
        [TikTokComment(comment_id="11111", author="alpha", text="first", card_png=make_png(300, 80))],
        profile=make_png(500, 200),
    )
    with caplog.at_level(logging.WARNING, logger=cards.__name__):
        persist_cards(snapshot, "wf_cards_001", tmp_path)
    assert caplog.records == []


def test_persist_cards_without_a_snapshot_records_nothing(tmp_path) -> None:
    assert persist_cards(None, "wf_cards_001", tmp_path) == ([], None)
    assert list(tmp_path.iterdir()) == []


def test_persisted_comments_serialize_without_image_bytes(tmp_path) -> None:
    snapshot = _snapshot(
        [TikTokComment(comment_id="11111", author="alpha", text="first", card_png=make_png(300, 80))],
        profile=make_png(500, 200),
    )
    comments, profile = persist_cards(snapshot, "wf_cards_001", tmp_path)
    assert profile is not None
    dumped = json.dumps([comment.model_dump(mode="json") for comment in comments])
    dumped += profile.model_dump_json()
    assert "PNG" not in dumped
    assert "card_png" not in dumped
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_cards.py 2>&1 | tail -5`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.cards'`.

- [ ] **Step 3: Implement `cards.py`**

Create `python/src/thoth_control_plane/acquisition/cards.py`:

```python
"""Persist real TikTok card crops as checksummed report artifacts.

Cards are best effort. A crop that is not a usable PNG, or whose write fails, is dropped and
its comment keeps `card=None`; nothing here fails acquisition. Nothing from a comment (text,
handle, id, path) reaches the log: the single warning carries counts only.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import struct
from pathlib import Path, PurePosixPath

from thoth_control_plane.acquisition.models import (
    MAX_CARD_BYTES,
    BrowserSnapshot,
    CardArtifact,
    ReportComment,
)

logger = logging.getLogger(__name__)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Scout keeps a crop only when rect.w > 30 and rect.h > 12.
MIN_CARD_WIDTH = 31
MIN_CARD_HEIGHT = 13
MAX_CARD_SIDE = 4_096
# Scout's black-crop guard (scout/lib/crop_guard.ts): a real card runs ~0.09-0.15 bytes per
# pixel, a flat or blank crop ~0.005.
MIN_CARD_BPP = 0.02


class CardRejected(ValueError):
    """The crop is not a usable PNG card."""


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height from the PNG IHDR chunk."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise CardRejected("not a png")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def card_problem(width: int, height: int, size: int) -> str | None:
    if not 0 < size <= MAX_CARD_BYTES:
        return "size"
    if not (
        MIN_CARD_WIDTH <= width <= MAX_CARD_SIDE and MIN_CARD_HEIGHT <= height <= MAX_CARD_SIDE
    ):
        return "dimensions"
    if size / (width * height) < MIN_CARD_BPP:
        return "flat"
    return None


def write_card(data: bytes, artifact_root: Path, location: PurePosixPath) -> CardArtifact:
    """Validate, then write atomically; a retry overwrites the same deterministic name."""
    width, height = png_size(data)
    problem = card_problem(width, height, len(data))
    if problem is not None:
        raise CardRejected(problem)
    destination = artifact_root / location
    part_path = destination.with_name(destination.name + ".part")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(data)
        os.replace(part_path, destination)
    except BaseException:
        with contextlib.suppress(OSError):
            part_path.unlink(missing_ok=True)
        raise
    return CardArtifact(
        location=location,
        bytes=len(data),
        checksum=f"sha256:{hashlib.sha256(data).hexdigest()}",
        width=width,
        height=height,
    )


def persist_cards(
    snapshot: BrowserSnapshot | None, workflow_id: str, artifact_root: Path
) -> tuple[list[ReportComment], CardArtifact | None]:
    """Report comments and the profile card for a headless snapshot, with cards on disk."""
    if snapshot is None:
        return [], None
    card_dir = PurePosixPath("reports") / workflow_id / "cards"
    counts = {"written": 0, "rejected": 0, "failed": 0}

    def persist(data: bytes | None, name: str) -> CardArtifact | None:
        if data is None:
            return None
        try:
            artifact = write_card(data, artifact_root, card_dir / name)
        except CardRejected:
            counts["rejected"] += 1
            return None
        except OSError:
            counts["failed"] += 1
            return None
        counts["written"] += 1
        return artifact

    comments = [
        ReportComment(
            comment_id=comment.comment_id,
            author=comment.author,
            text=comment.text,
            likes=comment.likes,
            card=persist(comment.card_png, f"comment-{comment.comment_id}.png"),
        )
        for comment in snapshot.comments
    ]
    profile_card = persist(snapshot.profile_card_png, "profile.png")
    if counts["rejected"] or counts["failed"]:
        logger.warning(
            "tiktok card crops: written=%d rejected=%d failed=%d",
            counts["written"],
            counts["rejected"],
            counts["failed"],
        )
    return comments, profile_card
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_cards.py 2>&1 | tail -5`
Expected: 25 passed.

- [ ] **Step 5: Lint and commit**

Run the ruff command from Task 1 Step 5. Expected: clean.

```bash
git add python/src/thoth_control_plane/acquisition/cards.py python/tests/acquisition/test_cards.py
git commit -m "feat: persist real tiktok card crops as checksummed artifacts"
```

---

### Task 3: Wire comments and cards into the acquisition report

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/service.py`
  - `_build_report`, at about lines 119-137;
  - the two report returns, at about lines 231-235 and 284-287.
- Test: `python/tests/acquisition/test_service.py`

**Interfaces:**
- Consumes:
  - `persist_cards(snapshot, workflow_id, artifact_root)` from Task 2;
  - `ReportComment` and `CardArtifact` from Task 1;
  - `make_png` from `tests.acquisition.test_cards`.
- Produces: `TikTokAcquisitionService.inspect` returns reports whose `comments` and `profile_card` are filled from the headless snapshot.

- [ ] **Step 1: Write the failing tests**

In `python/tests/acquisition/test_service.py`, add `TikTokComment` to the existing
`from thoth_control_plane.acquisition.models import (...)` list. Then add:

```python
from tests.acquisition.test_cards import make_png
```

This goes after the `thoth_control_plane` imports, which is the repo's convention for cross-test
helpers. Append:

```python
def snapshot_with_comments() -> BrowserSnapshot:
    return complete_snapshot().model_copy(
        update={
            "comments": [
                TikTokComment(
                    comment_id="11111", author="alpha", text="first", card_png=make_png(300, 80)
                ),
                TikTokComment(comment_id="22222", author="beta", text="second"),
            ],
            "profile_card_png": make_png(500, 200),
        }
    )


@pytest.mark.asyncio
async def test_headless_success_records_comments_and_card_artifacts(tmp_path) -> None:
    result = await TikTokAcquisitionService(
        FakeBrowser(snapshot_with_comments()), FakeResolver(), FakeMaterializer()
    ).inspect(workflow_id="wf_cards_001", source_url=SOURCE_URL, artifact_root=tmp_path)

    assert result.report is not None
    report = result.report
    assert report.schema_version == 2
    assert [comment.comment_id for comment in report.comments] == ["11111", "22222"]
    first_card = report.comments[0].card
    assert first_card is not None
    assert first_card.location == PurePosixPath("reports/wf_cards_001/cards/comment-11111.png")
    assert (tmp_path / first_card.location).is_file()
    assert report.comments[1].card is None
    assert report.profile_card is not None
    assert report.profile_card.location == PurePosixPath("reports/wf_cards_001/cards/profile.png")


@pytest.mark.asyncio
async def test_comments_survive_a_tikwm_rescue(tmp_path) -> None:
    result = await TikTokAcquisitionService(
        FakeBrowser(snapshot_with_comments()),
        FakeResolver.from_payload(tikwm_fixture_payload()),
        FakeMaterializer(fail_for=frozenset({"scrapling_headless"})),
    ).inspect(workflow_id="wf_cards_002", source_url=SOURCE_URL, artifact_root=tmp_path)

    assert result.report is not None
    assert [attempt.strategy for attempt in result.report.outcome.attempts] == [
        "scrapling_headless",
        "tikwm_cdn",
    ]
    assert [comment.comment_id for comment in result.report.comments] == ["11111", "22222"]
    assert result.report.comments[0].card is not None
    assert result.report.profile_card is not None


@pytest.mark.asyncio
async def test_headless_exception_rescue_has_no_comments_or_cards(tmp_path) -> None:
    result = await TikTokAcquisitionService(
        FakeBrowser(HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)),
        FakeResolver.from_payload(tikwm_fixture_payload()),
        FakeMaterializer(),
    ).inspect(workflow_id="wf_cards_003", source_url=SOURCE_URL, artifact_root=tmp_path)

    assert result.report is not None
    assert result.report.comments == []
    assert result.report.profile_card is None
    assert not (tmp_path / "reports" / "wf_cards_003" / "cards").exists()


@pytest.mark.asyncio
async def test_a_rejected_card_never_fails_acquisition(tmp_path) -> None:
    snapshot = complete_snapshot().model_copy(
        update={
            "comments": [
                TikTokComment(
                    comment_id="11111", author="alpha", text="first", card_png=b"not a png"
                )
            ],
            "profile_card_png": make_png(400, 100, flat=True),
        }
    )
    result = await TikTokAcquisitionService(
        FakeBrowser(snapshot), FakeResolver(), FakeMaterializer()
    ).inspect(workflow_id="wf_cards_004", source_url=SOURCE_URL, artifact_root=tmp_path)

    assert result.failure is None
    assert result.report is not None
    assert [comment.comment_id for comment in result.report.comments] == ["11111"]
    assert result.report.comments[0].card is None
    assert result.report.profile_card is None


@pytest.mark.asyncio
async def test_failed_tikwm_after_headless_comments_writes_no_cards(tmp_path) -> None:
    result = await TikTokAcquisitionService(
        FakeBrowser(snapshot_with_comments()),
        FakeResolver(TikWmError("cdn_unavailable")),
        FakeMaterializer(fail_for=frozenset({"scrapling_headless"})),
    ).inspect(workflow_id="wf_cards_005", source_url=SOURCE_URL, artifact_root=tmp_path)

    assert result.failure is not None
    assert result.failure.code == "cdn_unavailable"
    assert list(tmp_path.rglob("*.png")) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_service.py -k "cards or comments" 2>&1 | tail -8`
Expected: 3 failed and 2 passed.
- The failures are `test_headless_success_records_comments_and_card_artifacts`,
  `test_comments_survive_a_tikwm_rescue` and `test_a_rejected_card_never_fails_acquisition`.
  They fail with `assert [] == ['11111', ...]` or with `assert ... == ['11111']`.
- The two absence tests already pass, which is correct: they pin behavior this task must not break.

- [ ] **Step 3: Wire `persist_cards` into the service**

In `service.py`, add the import:

```python
from thoth_control_plane.acquisition.cards import persist_cards
```

Add `CardArtifact` and `ReportComment` to the `models` import list.

Replace `_build_report` with:

```python
def _build_report(
    workflow_id: str,
    identity: TikTokPostIdentity | None,
    post: TikTokPost,
    materialized: MaterializedMedia,
    attempts: list[AcquisitionAttempt],
    comments: list[ReportComment],
    profile_card: CardArtifact | None,
) -> TikTokSourceReport:
    canonical_url = (
        identity.canonical_url if identity is not None else _fallback_canonical_url(post)
    )
    return TikTokSourceReport(
        workflow_id=workflow_id,
        source=TikTokSource(canonical_url=canonical_url),
        post=post,
        media=[materialized],
        outcome=AcquisitionOutcome(attempts=attempts),
        comments=comments,
        profile_card=profile_card,
    )
```

Replace the headless success return, currently:

```python
        if materialized is not None:
            post = _merge_post(identity, headless_post, None)
            return TikTokAcquisitionResult(
                report=_build_report(workflow_id, identity, post, materialized, attempts)
            )
```

with:

```python
        if materialized is not None:
            post = _merge_post(identity, headless_post, None)
            comments, profile_card = persist_cards(snapshot, workflow_id, artifact_root)
            return TikTokAcquisitionResult(
                report=_build_report(
                    workflow_id, identity, post, materialized, attempts, comments, profile_card
                )
            )
```

Replace the final TikWM return, currently:

```python
        post = _merge_post(merged_identity, headless_post, resolution.post)
        return TikTokAcquisitionResult(
            report=_build_report(workflow_id, merged_identity, post, materialized, attempts)
        )
```

with:

```python
        post = _merge_post(merged_identity, headless_post, resolution.post)
        # Comments come only from the headless visit; TikWM yields none.
        comments, profile_card = persist_cards(snapshot, workflow_id, artifact_root)
        return TikTokAcquisitionResult(
            report=_build_report(
                workflow_id, merged_identity, post, materialized, attempts, comments, profile_card
            )
        )
```

`snapshot` is `None` when the headless fetch raised, so that path records no comments.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Lint and commit**

Run the ruff command from Task 1 Step 5. Expected: clean.

```bash
git add python/src/thoth_control_plane/acquisition/service.py python/tests/acquisition/test_service.py
git commit -m "feat: record headless comments and card crops in the source report"
```

---

### Task 4: Remove card files when report persistence fails

**Files:**
- Modify: `python/src/thoth_control_plane/activities/source_investigation.py`, the `_cleanup_after_persistence_failure` function at lines 164-183
- Test: `python/tests/activities/test_source_investigation.py`

**Interfaces:**
- Consumes: `TikTokSourceReport.comments[].card`, `TikTokSourceReport.profile_card`, `CardArtifact`, `ReportComment` (Task 1).
- Produces: the same activity contract; cleanup now also covers card files.

- [ ] **Step 1: Write the failing test**

In `python/tests/activities/test_source_investigation.py`, add `CardArtifact` and `ReportComment` to the
existing `from thoth_control_plane.acquisition.models import (...)` list. Then append:

```python
async def test_report_persistence_failure_removes_recorded_card_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card_dir = PurePosixPath("reports/wf_contract_001/cards")

    def card(name: str) -> CardArtifact:
        return CardArtifact(
            location=card_dir / name,
            bytes=4_000,
            checksum="sha256:" + "b" * 64,
            width=300,
            height=80,
        )

    report = _load_fixture_report().model_copy(
        update={
            "schema_version": 2,
            "comments": [
                ReportComment(
                    comment_id="11111", author="alpha", text="first", card=card("comment-11111.png")
                )
            ],
            "profile_card": card("profile.png"),
        }
    )
    paths = [
        tmp_path / str(report.media[0].location),
        tmp_path / str(card_dir / "comment-11111.png"),
        tmp_path / str(card_dir / "profile.png"),
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0" * 10_100)

    async def runner(workflow_id: str, source_url: str, artifact_root: Path):
        del workflow_id, source_url, artifact_root
        return TikTokAcquisitionResult(report=report)

    from thoth_control_plane.activities import source_investigation as module

    def raising_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module.os, "replace", raising_replace)

    result = await build_source_investigation_activity(_settings(tmp_path), runner=runner)(INPUT)

    assert result.failure is not None
    assert result.failure.code == "artifact_persistence_failed"
    assert [path for path in paths if path.exists()] == []
    assert list(tmp_path.rglob("*.part")) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/activities/test_source_investigation.py -k recorded_card_files 2>&1 | tail -5`
Expected: 1 failed, with an `assert [PosixPath('.../comment-11111.png'), PosixPath('.../profile.png')] == []` style message.

- [ ] **Step 3: Extend the cleanup**

Replace `_cleanup_after_persistence_failure` with:

```python
def _cleanup_after_persistence_failure(
    part_path: Path, report: TikTokSourceReport, artifact_root: Path
) -> None:
    """Remove the partial report and every media and card file the report recorded.

    Artifact locations are validated as `PurePosixPath` (POSIX separators only),
    but a Windows-style backslash string can slip past that check as a single
    opaque segment and then, once joined with a real `Path`, resolve to an
    absolute path or a `..` escape outside `artifact_root`. Only unlink
    candidates that resolve inside the artifact root; skip anything else.
    """
    with contextlib.suppress(OSError):
        part_path.unlink(missing_ok=True)
    resolved_root = artifact_root.resolve()
    locations = [media.location for media in report.media]
    locations += [comment.card.location for comment in report.comments if comment.card]
    if report.profile_card is not None:
        locations.append(report.profile_card.location)
    for location in locations:
        candidate = (artifact_root / location).resolve()
        if not candidate.is_relative_to(resolved_root):
            continue
        with contextlib.suppress(OSError):
            candidate.unlink(missing_ok=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/activities 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Lint and commit**

Run the ruff command from Task 1 Step 5. Expected: clean.

```bash
git add python/src/thoth_control_plane/activities/source_investigation.py python/tests/activities/test_source_investigation.py
git commit -m "fix: remove recorded card files when report persistence fails"
```

---

### Task 5: Capture sanitizer

**Files:**
- Create: `python/src/thoth_control_plane/operations/tiktok_comment_fixture.py`
- Test: `python/tests/operations/test_tiktok_comment_fixture.py`

**Interfaces:**
- Consumes: `thoth_control_plane.acquisition.browser._reduce_comments`, which is used only by the tests' replay helper.
- Produces (in `thoth_control_plane.operations.tiktok_comment_fixture`):
  - `ENTRY_KEYS: tuple[str, ...] = ("cid", "unique_id", "text", "digg_count")`
  - `INVALID_ID = "invalid-id"`
  - `INVALID_HANDLE = "invalid handle"`
  - `ID_BASE = 7_000_000_000_000_000_000`
  - `sanitize_capture(raw: dict[str, Any]) -> dict[str, Any]`
  - `main(argv: list[str] | None = None) -> int`
- Produces (in `tests.operations.test_tiktok_comment_fixture`): `replay(capture: dict) -> list[dict]`. Task 6 uses it.
- Raw capture shape, which Task 6 writes:
  - `{"pages": [...], "card_texts": [str], "card_stats": [{"width", "height", "bytes"}], "profile_card_stats": {...} | null, "expected": [{"comment_id": str, "card": int | null}]}`
  - The sanitized shape is identical. Pages are reduced to `{"comments": [entry | null]}` or `null`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/operations/test_tiktok_comment_fixture.py`:

```python
"""Golden TikTok comment captures: sanitizer and reducer replay."""

import copy
import json
import re
from pathlib import Path

import pytest

from thoth_control_plane.acquisition.browser import _reduce_comments
from thoth_control_plane.operations.tiktok_comment_fixture import (
    ENTRY_KEYS,
    ID_BASE,
    INVALID_HANDLE,
    INVALID_ID,
    main,
    sanitize_capture,
)


def replay(capture: dict) -> list[dict]:
    """Run the reducer over a capture; each card is identified by its index."""
    pngs = [f"card-{index}".encode() for index in range(len(capture["card_texts"]))]
    comments = _reduce_comments(capture["pages"], list(zip(capture["card_texts"], pngs, strict=True)))
    return [
        {
            "comment_id": comment.comment_id,
            "card": None if comment.card_png is None else pngs.index(comment.card_png),
        }
        for comment in comments
    ]


def raw_capture() -> dict:
    capture = {
        "pages": [
            {
                "comments": [
                    {
                        "cid": "7300000000000000001",
                        "unique_id": "real.handle",
                        "text": "Mantap 123 😂",
                        "digg_count": 5,
                        "nickname": "Real Name",
                    },
                    {
                        "cid": "7300000000000000002",
                        "unique_id": "other_one",
                        "text": " [sticker] ",
                        "digg_count": 0,
                    },
                    {
                        "cid": "7300000000000000001",
                        "unique_id": "real.handle",
                        "text": "Mantap 123 😂",
                        "digg_count": 5,
                    },
                    {"cid": "bad", "unique_id": "has space", "text": None, "digg_count": "7"},
                    {
                        "cid": "7300000000000000003",
                        "unique_id": "real.handle",
                        "text": "ok",
                        "digg_count": 1,
                    },
                    {"cid": "7300000000000000004", "unique_id": "third", "text": "no"},
                    "not a dict",
                ],
                "has_more": 1,
                "cursor": 20,
                "extra": "secret",
            },
            "captcha body",
        ],
        "card_texts": ["Mantap 123 😂 ", "ok", "unmatched words"],
        "card_stats": [{"width": 300, "height": 80, "bytes": 6_000}] * 3,
        "profile_card_stats": {"width": 500, "height": 200, "bytes": 30_000},
    }
    capture["expected"] = replay(capture)
    return capture


def test_raw_capture_exercises_matching_and_duplicates() -> None:
    assert [item["card"] for item in raw_capture()["expected"]] == [0, None, 1, None]


def test_sanitized_capture_replays_like_the_raw_capture() -> None:
    raw = raw_capture()
    sanitized = sanitize_capture(raw)
    assert replay(sanitized) == sanitized["expected"]
    assert [item["card"] for item in sanitized["expected"]] == [0, None, 1, None]
    assert sanitized["card_stats"] == raw["card_stats"]
    assert sanitized["profile_card_stats"] == raw["profile_card_stats"]


def test_sanitized_capture_contains_no_original_identifiers() -> None:
    dumped = json.dumps(sanitize_capture(raw_capture()), ensure_ascii=False)
    for secret in (
        "730000000000000000",
        "real.handle",
        "other_one",
        "third",
        "Mantap",
        "123",
        "Real Name",
        "secret",
        "has space",
        "unmatched",
        "words",
    ):
        assert secret not in dumped


def test_sanitizer_preserves_what_the_reducer_reads() -> None:
    sanitized = sanitize_capture(raw_capture())
    page, captcha = sanitized["pages"]
    assert captcha is None
    assert set(page) == {"comments"}
    entries = page["comments"]
    assert entries[6] is None
    assert all(set(entry) == set(ENTRY_KEYS) for entry in entries[:6])
    first = entries[0]
    assert len(first["text"]) == len("Mantap 123 😂")
    assert first["text"].endswith(" 😂")
    assert first["unique_id"] == entries[4]["unique_id"] == "user_001"
    assert int(first["cid"]) >= ID_BASE
    assert entries[2] == first
    assert entries[1]["text"] == " [sticker] "
    assert entries[3] == {
        "cid": INVALID_ID,
        "unique_id": INVALID_HANDLE,
        "text": None,
        "digg_count": None,
    }
    assert entries[5]["digg_count"] is None
    assert sanitized["card_texts"][0] == first["text"] + " "


def test_sanitizer_is_deterministic() -> None:
    assert sanitize_capture(raw_capture()) == sanitize_capture(raw_capture())


def test_sanitizer_keeps_distinct_texts_distinct() -> None:
    capture = copy.deepcopy(raw_capture())
    singles = [chr(ord("a") + index) for index in range(26)] + [str(digit) for digit in range(10)]
    capture["card_texts"] = singles
    capture["card_stats"] = [{"width": 300, "height": 80, "bytes": 6_000}] * len(singles)
    sanitized = sanitize_capture(capture)
    assert len(set(sanitized["card_texts"])) == len(singles)


def test_sanitizer_refuses_texts_it_cannot_keep_distinct() -> None:
    capture = copy.deepcopy(raw_capture())
    capture["card_texts"] = [chr(ord("a") + index) for index in range(26)]
    capture["card_texts"] += [str(digit) for digit in range(10)] + ["é"]
    with pytest.raises(ValueError, match="distinct"):
        sanitize_capture(capture)


def test_cli_writes_lf_json(tmp_path: Path) -> None:
    source = tmp_path / "raw.json"
    target = tmp_path / "post-1.json"
    source.write_text(json.dumps(raw_capture()), encoding="utf-8")
    assert main([str(source), str(target)]) == 0
    data = target.read_bytes()
    assert b"\r\n" not in data
    assert json.loads(data) == sanitize_capture(raw_capture())
    assert re.search(rb"user_\d{3}", data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_tiktok_comment_fixture.py 2>&1 | tail -5`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'thoth_control_plane.operations.tiktok_comment_fixture'`.

- [ ] **Step 3: Implement the sanitizer**

Create `python/src/thoth_control_plane/operations/tiktok_comment_fixture.py`:

```python
"""Sanitize a one-time live TikTok comment capture into a public golden fixture.

The repository is public. A fixture keeps only what the comment reducer reads
(`comments[].cid`, `unique_id`, `text`, `digg_count`) and replaces every id, handle, and text
with a stable pseudonym. Pseudonyms preserve what the reducer depends on: id and handle
validity, duplicates, text length, emoji and punctuation, sticker markers, and text equality
after strip between API entries and card texts. Card images never enter a fixture; only
their width, height, and byte size do.

Usage: python -m thoth_control_plane.operations.tiktok_comment_fixture RAW.json FIXTURE.json
"""

from __future__ import annotations

import itertools
import json
import re
import string
import sys
from pathlib import Path
from typing import Any

ENTRY_KEYS = ("cid", "unique_id", "text", "digg_count")
INVALID_ID = "invalid-id"
INVALID_HANDLE = "invalid handle"
ID_BASE = 7_000_000_000_000_000_000
COMMENT_ID = re.compile(r"[0-9]{5,32}")
HANDLE = re.compile(r"[A-Za-z0-9._-]{1,64}")
STICKER = re.compile(r"\[\s*sti?c?ker\s*\]", re.IGNORECASE)
FILL_ALPHABET = string.ascii_lowercase + string.digits
FILL_WIDTH = 3


def _fill(index: int) -> itertools.cycle[str]:
    size = len(FILL_ALPHABET)
    return itertools.cycle(
        FILL_ALPHABET[(index // size**place) % size] for place in range(FILL_WIDTH)
    )


class _Pseudonyms:
    def __init__(self) -> None:
        self._ids: dict[str, str] = {}
        self._handles: dict[str, str] = {}
        self._texts: dict[str, str] = {}

    def comment_id(self, value: Any) -> str | None:
        if value is None:
            return None
        key = str(value)
        if not COMMENT_ID.fullmatch(key):
            return INVALID_ID
        return self._ids.setdefault(key, str(ID_BASE + len(self._ids)))

    def handle(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        if not HANDLE.fullmatch(value):
            return INVALID_HANDLE
        return self._handles.setdefault(value, f"user_{len(self._handles) + 1:03d}")

    def text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        core = value.strip()
        leading = value[: len(value) - len(value.lstrip())]
        trailing = value[len(value.rstrip()) :]
        return leading + self._core(core) + trailing

    def _core(self, core: str) -> str:
        if core in self._texts:
            return self._texts[core]
        if not core or STICKER.fullmatch(core):
            self._texts[core] = core
            return core
        used = set(self._texts.values())
        for index in range(len(self._texts), len(FILL_ALPHABET) ** FILL_WIDTH):
            fill = _fill(index)
            pseudonym = "".join(next(fill) if char.isalnum() else char for char in core)
            if pseudonym not in used:
                self._texts[core] = pseudonym
                return pseudonym
        raise ValueError("cannot keep comment texts distinct; capture another post")


def _entry(names: _Pseudonyms, entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    likes = entry.get("digg_count")
    return {
        "cid": names.comment_id(entry.get("cid")),
        "unique_id": names.handle(entry.get("unique_id")),
        "text": names.text(entry.get("text")),
        "digg_count": likes if isinstance(likes, int) else None,
    }


def sanitize_capture(raw: dict[str, Any]) -> dict[str, Any]:
    names = _Pseudonyms()
    pages: list[dict[str, Any] | None] = []
    for page in raw["pages"]:
        entries = page.get("comments") if isinstance(page, dict) else None
        if not isinstance(entries, list):
            pages.append(None)
            continue
        pages.append({"comments": [_entry(names, entry) for entry in entries]})
    return {
        "pages": pages,
        "card_texts": [names.text(text) for text in raw["card_texts"]],
        "card_stats": raw["card_stats"],
        "profile_card_stats": raw["profile_card_stats"],
        "expected": [
            {"comment_id": names.comment_id(item["comment_id"]), "card": item["card"]}
            for item in raw["expected"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    source, target = argv if argv is not None else sys.argv[1:]
    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    Path(target).write_text(
        json.dumps(sanitize_capture(raw), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_tiktok_comment_fixture.py 2>&1 | tail -5`
Expected: 8 passed.

- [ ] **Step 5: Lint and commit**

Run the ruff command from Task 1 Step 5. Expected: clean.

```bash
git add python/src/thoth_control_plane/operations/tiktok_comment_fixture.py python/tests/operations/test_tiktok_comment_fixture.py
git commit -m "feat: add deterministic sanitizer for tiktok comment captures"
```

---

### Task 6: One-time live capture and golden fixtures

This task makes live TikTok requests: one headless visit to each of 3 public posts. Scope:
- It is the one-time capture that spec section 5 authorizes.
- It runs outside pytest, in the deployed image, the same way as the earlier `probe6` checks.
- It must not be repeated, extended to more posts, or turned into a smoke test.

**Files:**
- Create (throwaway, never committed):
  - `D:/thoth-tmp/bu/capture_comments.py`
  - `D:/thoth-tmp/bu/capture_comments.sh`
  - `D:/thoth-tmp/bu/check_fixture_leak.py`
- Create: `python/tests/fixtures/tiktok/comments/post-1.json`, `post-2.json` and `post-3.json`
- Modify: `python/tests/operations/test_tiktok_comment_fixture.py` (append golden tests)

**Interfaces:**
- Consumes:
  - `png_size` and `card_problem` from `cards.py` (Task 2), plus `MIN_CARD_BPP`;
  - `sanitize_capture` and `main`, and `replay`, from Task 5;
  - `browser._reduce_comments`.
- Produces: three committed sanitized fixtures and the golden tests over them.

- [ ] **Step 1: Write the capture scripts**

Write the files with the Write tool, not a Bash heredoc: the Bash tool corrupts line continuations.

`D:/thoth-tmp/bu/capture_comments.py`:

```python
# One-time Stage 2 golden capture: raw comment pages, card texts, PNG statistics.
# Raw output stays under D:/thoth-tmp; only the sanitized fixture is committed.
import asyncio
import json
import os
import sys

sys.path.insert(0, "/src")
from thoth_control_plane.acquisition import browser as bm  # noqa: E402
from thoth_control_plane.acquisition.browser import ScraplingHeadlessBrowser  # noqa: E402
from thoth_control_plane.acquisition.cards import png_size  # noqa: E402

TAG = os.environ["TAG"]
captured: dict = {}
_reduce = bm._reduce_comments


def _stats(png: bytes) -> dict:
    width, height = png_size(png)
    return {"width": width, "height": height, "bytes": len(png)}


def _traced(pages, cards):
    comments = _reduce(pages, cards)
    index: dict[bytes, int] = {}
    for position, (_, png) in enumerate(cards):
        index.setdefault(png, position)
    captured.update(
        pages=pages,
        card_texts=[text for text, _ in cards],
        card_stats=[_stats(png) for _, png in cards],
        expected=[
            {
                "comment_id": c.comment_id,
                "card": None if c.card_png is None else index[c.card_png],
            }
            for c in comments
        ],
    )
    for position, (_, png) in enumerate(cards):
        with open(f"/out/capture-{TAG}-c{position}.png", "wb") as handle:
            handle.write(png)
    return comments


bm._reduce_comments = _traced


async def main() -> None:
    browser = ScraplingHeadlessBrowser()
    try:
        snapshot = await browser.fetch(os.environ["PROBE_URL"])
    finally:
        await browser.close()
    png = snapshot.profile_card_png
    captured["profile_card_stats"] = _stats(png) if png else None
    if png:
        with open(f"/out/capture-{TAG}-profile.png", "wb") as handle:
            handle.write(png)
    with open(f"/out/capture-{TAG}.json", "w", encoding="utf-8") as handle:
        json.dump(captured, handle, ensure_ascii=False)
    carded = sum(c.card_png is not None for c in snapshot.comments)
    print(
        f"tag={TAG} media={len(snapshot.media_candidates)} comments={len(snapshot.comments)}"
        f" cards={len(captured.get('card_texts', []))} carded={carded}"
        f" profile={'yes' if png else 'no'}"
    )


asyncio.run(main())
```

`D:/thoth-tmp/bu/capture_comments.sh`:

```bash
#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER
IMAGE=$(grep -E '^THOTH_IMAGE=' .env.stage1.local | cut -d= -f2- | tr -d '\r')
mkdir -p /mnt/d/thoth-tmp/bu/out
for TAG in 1 2 3; do
  export TAG
  PROBE_URL=$(head -"$TAG" /mnt/d/thoth-tmp/bu/links.txt | tail -1 | tr -d '\r')
  export PROBE_URL
  docker run --rm -i -e PROBE_URL -e TAG -v /mnt/d/thoth-tmp/bu/out:/out -v "$PWD/python/src":/src:ro --entrypoint /opt/thoth/python/.venv/bin/python "$IMAGE" - < /mnt/d/thoth-tmp/bu/capture_comments.py 2>&1 | grep -E "^tag=|Traceback|^[A-Za-z]+Error"
done
```

`D:/thoth-tmp/bu/check_fixture_leak.py` prints counts only and never a raw value:

```python
# Fail if any raw id, handle, or text (4+ chars) survives into a sanitized fixture.
import json
import pathlib
import sys

root = pathlib.Path("C:/Users/mfr/Documents/MyTools/CLIPPER/python/tests/fixtures/tiktok/comments")
leaks = 0
for tag in (1, 2, 3):
    raw = json.loads(pathlib.Path(f"D:/thoth-tmp/bu/out/capture-{tag}.json").read_text("utf-8"))
    fixture = (root / f"post-{tag}.json").read_text("utf-8")
    secrets = set()
    for page in raw["pages"]:
        for entry in (page.get("comments") or []) if isinstance(page, dict) else []:
            if isinstance(entry, dict):
                for key in ("cid", "unique_id", "text"):
                    value = entry.get(key)
                    if value is not None and len(str(value).strip()) >= 4:
                        secrets.add(str(value).strip())
    secrets.update(t.strip() for t in raw["card_texts"] if len(t.strip()) >= 4)
    hits = sum(secret in fixture for secret in secrets)
    leaks += hits
    print(f"post-{tag}: checked={len(secrets)} leaks={hits}")
sys.exit(1 if leaks else 0)
```

- [ ] **Step 2: Run the live capture (one run, 3 posts)**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/capture_comments.sh`
Expected: three lines like `tag=1 media=1 comments=50 cards=10 carded=10 profile=yes`, and no `Traceback`.
- Any post with `comments=0`, `cards=0`, or a traceback may be re-run once, alone, by changing the
  loop to that tag.
- If it still fails, stop and report to the operator. Do not substitute other posts.
- `profile=no` on one post is acceptable (earlier live checks showed 11 of 12). The fixture records
  `null`.

- [ ] **Step 3: Eyeball the crops locally**

Open `D:/thoth-tmp/bu/out/capture-1-c0.png`, `capture-2-c0.png`, `capture-3-c0.png`, and every
`capture-*-profile.png` with the Read tool.
- Expected: each is a real TikTok comment card or profile header. It is not blank, not a grey
  placeholder, and not synthetic.
- These PNGs are never committed or described in public artifacts.

- [ ] **Step 4: Sanitize into fixtures and check for leaks**

Run:
```bash
cd C:/Users/mfr/Documents/MyTools/CLIPPER/python && mkdir -p tests/fixtures/tiktok/comments && for n in 1 2 3; do PYTHONPATH=src python -m thoth_control_plane.operations.tiktok_comment_fixture D:/thoth-tmp/bu/out/capture-$n.json tests/fixtures/tiktok/comments/post-$n.json || exit 1; done && python D:/thoth-tmp/bu/check_fixture_leak.py
```
Expected: three `post-N: checked=<k> leaks=0` lines, and exit 0.
- If the sanitizer raises `cannot keep comment texts distinct`, stop and report.
- If any leak is reported, stop and report. Do not commit.

- [ ] **Step 5: Write the golden tests**

Append to `python/tests/operations/test_tiktok_comment_fixture.py`, and add
`from thoth_control_plane.acquisition.cards import MIN_CARD_BPP, card_problem` to its imports:

```python
GOLDEN = sorted(
    (
        Path(__file__).resolve().parent.parent / "fixtures" / "tiktok" / "comments"
    ).glob("post-*.json")
)


def _golden(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_three_golden_captures_exist() -> None:
    assert [path.name for path in GOLDEN] == ["post-1.json", "post-2.json", "post-3.json"]


@pytest.mark.parametrize("path", GOLDEN, ids=lambda path: path.stem)
def test_reducer_replays_the_golden_capture(path: Path) -> None:
    capture = _golden(path)
    assert capture["expected"]
    assert replay(capture) == capture["expected"]


@pytest.mark.parametrize("path", GOLDEN, ids=lambda path: path.stem)
def test_real_card_statistics_clear_the_card_guard_with_margin(path: Path) -> None:
    capture = _golden(path)
    stats = list(capture["card_stats"])
    if capture["profile_card_stats"] is not None:
        stats.append(capture["profile_card_stats"])
    assert stats
    for stat in stats:
        assert card_problem(stat["width"], stat["height"], stat["bytes"]) is None
        assert stat["bytes"] / (stat["width"] * stat["height"]) >= 2 * MIN_CARD_BPP


@pytest.mark.parametrize("path", GOLDEN, ids=lambda path: path.stem)
def test_golden_capture_carries_only_pseudonyms(path: Path) -> None:
    capture = _golden(path)
    assert set(capture) == {"pages", "card_texts", "card_stats", "profile_card_stats", "expected"}
    for page in capture["pages"]:
        for entry in (page or {}).get("comments", []):
            if entry is None:
                continue
            assert set(entry) == set(ENTRY_KEYS)
            handle = entry["unique_id"]
            assert handle in (None, INVALID_HANDLE) or re.fullmatch(r"user_\d{3}", handle)
            cid = entry["cid"]
            assert cid in (None, INVALID_ID) or int(cid) >= ID_BASE
```

- [ ] **Step 6: Run the golden tests**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_tiktok_comment_fixture.py 2>&1 | tail -5`
Expected: 18 passed (8 from Task 5, plus 1 + 3×3 golden).
- If `test_real_card_statistics_clear_the_card_guard_with_margin` fails, the real bytes-per-pixel is
  too close to the 0.02 floor. Stop and report the minimum observed bpp (a number only) to the
  operator.
- Do not change `MIN_CARD_BPP` without an operator decision.

- [ ] **Step 7: Lint and commit**

Run the ruff command from Task 1 Step 5. Expected: clean.
Then run `git status --short`. Expected: only the three fixtures and the test file are new or modified under `python/`, and no PNG appears.

```bash
git add python/tests/fixtures/tiktok/comments/post-1.json python/tests/fixtures/tiktok/comments/post-2.json python/tests/fixtures/tiktok/comments/post-3.json python/tests/operations/test_tiktok_comment_fixture.py
git commit -m "test: add sanitized golden tiktok comment captures"
```

---

### Task 7: Documentation, full verification, and checkpoint

**Files:**
- Modify: `docs/python-scout-migration-roadmap.md` (CRLF), the target diagram at lines 17-32
- Modify: `CHANGELOG.md` (CRLF), with a new entry above the newest `## 2026-09-27` entry
- Modify (gitignored): `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` (CRLF)

**Interfaces:**
- Consumes: evidence from Tasks 1-6: commit hashes, test counts, capture counts, and minimum bpp.
- Produces: the documentation record. No code.

- [ ] **Step 1: Run the full verification**

Run: `wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh 2>&1 | tail -6`
Expected: all passed except the known pre-existing `test_route_modules_do_not_depend_on_a_process_runner` failure (`'bun'` matches "bundle"). Any other failure blocks this task.

Run the ruff command from Task 1 Step 5. Expected: clean.

Run: `git diff --stat master...HEAD -- '*.rs'`
Expected: empty. No Rust changed, so `build_cuda.bat` is not required by spec section 7. Record that in the CHANGELOG entry.

- [ ] **Step 2: Correct the roadmap target diagram**

Write `D:/thoth-tmp/bu/edit_roadmap.py` with the Write tool:

```python
import pathlib

p = pathlib.Path("C:/Users/mfr/Documents/MyTools/CLIPPER/docs/python-scout-migration-roadmap.md")
data = p.read_bytes()
old = """Target

FastAPI -> Temporal
                |-- Python acquisition
                |-- Python source intelligence
                |-- Python content assembly
                |-- Python enrichment
                `-- Rust media engine
                          |
                          `-- validated content-set
```
""".replace("\n", "\r\n").encode("utf-8")
new = """Target

FastAPI -> Temporal
                |-- Python acquisition
                |-- Python source intelligence
                |-- Python enrichment
                `-- Python content assembly
                          |
                          `-- validated content-set -> Creator Studio (Remotion render)
```

The Content Set page still reads through the Rust `thoth-server` route
`/api/scout/content-set/data`; that route must move before Rust retires. Acquisition output
(the source report with comments and real card artifacts) reaches Studio only through the
content set, never directly.
""".replace("\n", "\r\n").encode("utf-8")
assert data.count(old) == 1, "diagram anchor not found exactly once"
p.write_bytes(data.replace(old, new, 1))
print("ok")
```

Run: `python D:/thoth-tmp/bu/edit_roadmap.py && git diff --stat docs/python-scout-migration-roadmap.md`
Expected: `ok`, then one file changed. `file docs/python-scout-migration-roadmap.md` still reports CRLF.

- [ ] **Step 3: Add the CHANGELOG entry and fix the stale push line**

Write `D:/thoth-tmp/bu/edit_changelog_stage2.py` with the Write tool. Fill every `<...>` from the
evidence already produced in this run:
- commit hashes come from `git log --oneline master..HEAD`;
- counts come from the Task 6 Step 2 lines and the Step 1 summary;
- the minimum bpp comes from a one-off computation over the three fixtures' `card_stats`.

```python
import pathlib

p = pathlib.Path("C:/Users/mfr/Documents/MyTools/CLIPPER/CHANGELOG.md")
data = p.read_bytes()
anchor = b"## 2026-09-27 - Headless TikTok comments and real card crops"
stale = b"- Not pushed: `0742c21` and `b1798b6` need the operator's push approval."
fixed = b"- Pushed on 2026-09-27 with the operator's approval."
assert data.count(anchor) == 1 and data.count(stale) == 1 and b"\r\n" in data
entry = """## 2026-09-27 - Stage 2: TikTok comments and real card artifacts (report v2)

- Spec `docs/superpowers/specs/2026-09-27-tiktok-stage2-comments-cards-design.md`, plan
  `docs/superpowers/plans/2026-09-27-tiktok-stage2-comments-cards.md`.
- `<t1>`: `TikTokSourceReport` schema v2 adds `comments[]` (`ReportComment`) and `profile_card`.
  Cards are path-only `CardArtifact` records. Version 1 reports, including the Stage 1 evidence,
  still validate.
- `<t2>`: `acquisition/cards.py` validates each real crop with the standard library and writes it
  atomically to `reports/<workflow_id>/cards/`. The checks are PNG IHDR, 2 MiB, 31..4096 x
  13..4096, and bytes-per-pixel of at least 0.02. A rejected or failed card is dropped and its
  comment is kept.
- `<t3>`: both success paths record comments and cards, including a TikWM rescue. Failure paths
  write no card files.
- `<t4>`: a report persistence failure also removes the recorded card files.
- `<t5>`, `<t6>`: a deterministic sanitizer and golden fixtures from one live capture of 3 public
  posts: <c1>/<c2>/<c3> comments, <k1>/<k2>/<k3> carded, profile cards <p>/3. The fixtures replay
  the reducer exactly. The lowest real card density is <bpp> B/px against the 0.02 floor.
  - This deviates from ADR 0001: the fixtures come from Python, not Scout. The operator approved
    this on 2026-09-27.
- The roadmap target diagram now ends in the content set and Creator Studio, not a Rust media
  engine. It also notes that the Rust content-set route must move before Rust retires.
- Verification:
  - WSL, Python 3.12: <passed> passed and 1 failed. The failure is the pre-existing
    `test_route_modules_do_not_depend_on_a_process_runner`.
  - ruff check and ruff format are clean.
  - No Rust changed, so no `build_cuda.bat` run was needed.
- Deferred for an operator decision: the sticker-only filter and the 10 vs 12 card cap.
- Not pushed.

""".replace("\n", "\r\n").encode("utf-8")
data = data.replace(stale, fixed, 1)
p.write_bytes(data.replace(anchor, entry + anchor, 1))
print("ok")
```

Run: `python D:/thoth-tmp/bu/edit_changelog_stage2.py && git diff --stat CHANGELOG.md`
Expected: `ok`, then one file changed. Then run `grep -nE '<(t[0-9]|c[0-9]|k[0-9]|p|bpp|passed)>' CHANGELOG.md`. Expected: no output (every placeholder was filled).

- [ ] **Step 4: Commit the docs**

```bash
git add docs/python-scout-migration-roadmap.md CHANGELOG.md
git commit -m "docs: record stage 2 tiktok comments and card artifacts"
```

- [ ] **Step 5: Update the program checkpoint**

Append a `## 2026-09-27 - Stage 2 single-post enrichment implemented` section to
`.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md`. Use a Python binary
CRLF append, in the same pattern as Step 3, and never stage the file. The section lists:
- the commits;
- the verification numbers;
- the capture counts and the minimum bpp;
- the Rulings from this plan;
- the next operator gates:
  - pushing the branch;
  - the deferred minors;
  - the next Stage 2 sub-stage (profile, keyword, and trending discovery).

Expected: `git status --short` shows a clean tree, because the checkpoint is gitignored.
