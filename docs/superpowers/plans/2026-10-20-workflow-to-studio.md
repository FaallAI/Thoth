# Workflow to Studio with Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One click on a finished workflow creates a Studio draft in the active project with the
run's main video (or still) and footage copied in and attached, and a replay finishes whatever a
cut-off first attempt left.

**Architecture:** The Content Set row (Postgres `workflow_reports`) is projected in Python into the
existing `StudioSourceProjection`, keyed by a workflow source key. A new application service
creates the draft through the existing `StudioImportService`, then for each media item reuses a
ready project asset by checksum or probes the object in place (presigned MinIO URL), copies it
server side into `uploads/<project>/`, registers it, and attaches it through the existing resolve
path. Two routes expose it; the dashboard adds "Open in Studio" to the workflow detail page.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, psycopg, SQLAlchemy, minio 7.2.20, ffprobe;
React 19 + Bun + Testing Library in `dashboard/`.

**Spec:** `docs/superpowers/specs/2026-10-20-workflow-to-studio-design.md`

## Global Constraints

- Repository artifacts are English; chat reports to the operator are Indonesian.
- Commits: exactly one `git commit -m "<subject>"`, subject ≤ 72 characters, no body, no trailer,
  no `Co-Authored-By`, no AI attribution.
- Never stage `.superpowers/`, `graphify-out/`, `.serena/`, `design/`. Files under
  `docs/superpowers/` need `git add -f`.
- No live tests: every test is offline (the conftest guard blocks non-loopback hosts).
- Required tools fail loud: a missing `ffprobe` is an explicit error, never a silent skip.
- The Content Set is read only through `Reports.get("reports/<workflow_id>/content-set.json")`.
- Workflow source key: `sha256("workflow:" + workflow_id + ":" + sha256(content bytes))`, 64 hex.
- Presigned probe URL lives 5 minutes; ffprobe is limited to
  `-protocol_whitelist file,http,https,tcp,tls`; the URL is never logged or returned.
- New setting `THOTH_MEDIA_S3_REGION`, default `us-east-1`, passed to the MinIO client.
- Probes run one at a time, each within the existing 30-second `PROBE_TIMEOUT_SECONDS`.
- Copies land at `uploads/<project_id>/<asset_id><suffix>`, provenance `workflow_import`.
- `MeteredMediaStore.copy` records `media_stored` (destination size, `in_scope_only=True`).
- The import consumes no billing allowance.
- Refusals: `409 content_set_unavailable`, `409 content_set_invalid`,
  `409 workflow_in_other_project`, `404` (unknown or foreign run), `503` (store unreachable),
  `422 invalid_idempotency_key`; a failed item answers inside a `201`.
- Replay with the same `Idempotency-Key` returns the same draft and retries every media item that
  is still unresolved; items attached or excluded are reported `decided` and left alone.
- Python tests run from WSL: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=<path relative to python/>'`.
- Dashboard checks run from `dashboard/`: `bun test <paths>`, `bunx tsc --noEmit -p tsconfig.app.json`, `bun run build`.

## Review Focus

1. A Content Set checksum in upper-case hex (`Checksum` allows `A-F`) must still match and register:
   `editor_assets.checksum` only accepts lower case, so the importer lower-cases it (Task 5 test
   `test_an_upper_case_checksum_is_stored_lower_case`).
2. A carousel main (`kind = "images"`) imports its first slide as a still image with a `.jpg`
   suffix and no trim (Task 5 test `test_an_images_main_imports_its_first_slide_as_a_still`).
3. A run whose stored status still says `running` while its Content Set exists opens anyway: the
   stored status lags Temporal, so only the Content Set row gates the import (Task 5 test
   `test_a_lagging_run_status_does_not_block_the_import`).
4. A person deciding an item in the import gate while the import runs: their decision stands, the
   import reports `draft_changed` for it and carries on (Task 5 test
   `test_a_decision_made_meanwhile_in_the_gate_stands`).
5. Project and workflow ids that need URL encoding reach the right route from the dashboard
   client (Task 8 test `workflow import routes encode both ids`).

---

## File Structure

| File | Responsibility |
|---|---|
| `python/src/thoth_control_plane/infrastructure/media_store.py` | `probe_source` on the port, the local store and the metered store; metered `copy` |
| `python/src/thoth_control_plane/infrastructure/s3_media_store.py` | presigned `probe_source`; client region |
| `python/src/thoth_control_plane/infrastructure/media_probe.py` | ffprobe accepts a path or URL, with a protocol whitelist |
| `python/src/thoth_control_plane/config.py` | `THOTH_MEDIA_S3_REGION` |
| `python/src/thoth_control_plane/application/editor_asset_uploads.py` | `MediaProbe` takes `Path | str` |
| `python/src/thoth_control_plane/assembly/studio.py` (new) | pure ContentSet → `StudioSourceProjection` + media map; workflow source key |
| `python/src/thoth_control_plane/domain/studio_imports.py` | `WorkflowImportItem`, `WorkflowStudioImport` response models |
| `python/src/thoth_control_plane/application/editor_asset_ports.py` | `find_ready_by_checksum` on the port |
| `python/src/thoth_control_plane/infrastructure/editor_asset_repository.py` | its Postgres query |
| `python/src/thoth_control_plane/application/studio_imports.py` | `inspect_keyed`, `create_keyed` |
| `python/src/thoth_control_plane/application/workflow_studio_imports.py` (new) | the import service |
| `python/src/thoth_control_plane/api/routes/workflow_studio_imports.py` (new) | GET/POST routes |
| `python/src/thoth_control_plane/api/app.py` | wiring |
| `dashboard/src/api/control-plane.ts` | two client methods, one type |
| `dashboard/src/features/workflows/OpenInStudio.tsx` (new) | the button, choice panel and errors |
| `dashboard/src/features/workflows/WorkflowDetailPage.tsx` | holds the snapshot, renders the button |
| `dashboard/src/App.tsx` | passes the active project, navigates, `?resolve=1` opens the gate |
| `docker/test-renderer-offline.sh` | smoke step `workflow_opens_in_studio` |

---

### Task 1: Media store probes in place and meters copies

**Files:**
- Modify: `python/src/thoth_control_plane/infrastructure/media_store.py` (`MediaStore` protocol, `LocalMediaStore`, `MeteredMediaStore`)
- Modify: `python/src/thoth_control_plane/infrastructure/s3_media_store.py` (`from_settings`, new `probe_source`)
- Modify: `python/src/thoth_control_plane/infrastructure/media_probe.py`
- Modify: `python/src/thoth_control_plane/config.py:130` (after `THOTH_MEDIA_S3_SECURE`)
- Modify: `python/src/thoth_control_plane/application/editor_asset_uploads.py` (`MediaProbe` alias)
- Test: `python/tests/infrastructure/test_media_store.py`, `python/tests/infrastructure/test_media_probe.py`

**Interfaces:**
- Produces: `MediaStore.probe_source(location: str) -> str` (local: absolute file path; S3: presigned GET URL, 300 s); `MeteredMediaStore.probe_source`; `MeteredMediaStore.copy` records `media_stored`; `probe_media(ffprobe: str, source: Path | str) -> dict[str, Any]`; `MediaProbe = Callable[[Path | str], Awaitable[dict[str, Any]]]`; `Settings.THOTH_MEDIA_S3_REGION: str = "us-east-1"`.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/infrastructure/test_media_store.py`:

```python
def test_probe_source_reads_the_object_in_place(store, tmp_path: Path) -> None:
    store.put_file(LOCATION, _file(tmp_path, "s.mp4", b"probe-bytes"))
    source = store.probe_source(LOCATION)
    if source.startswith("http"):
        import urllib.request

        with urllib.request.urlopen(source, timeout=10) as response:
            assert response.read() == b"probe-bytes"
    else:
        assert Path(source).read_bytes() == b"probe-bytes"


def test_the_local_probe_source_of_an_absent_object_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(MediaUnavailable):
        LocalMediaStore(tmp_path).probe_source("reports/wf_a/media/absent.mp4")


def test_signing_a_probe_url_makes_no_network_call(tmp_path: Path) -> None:
    # Port 9 is closed: without an explicit region minio would ask the bucket for its location.
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path,
        THOTH_MEDIA_S3_ENDPOINT="127.0.0.1:9",
        THOTH_MEDIA_S3_ACCESS_KEY="access",
        THOTH_MEDIA_S3_SECRET_KEY="secret-key",
    )
    url = build_media_store(settings).probe_source(LOCATION)
    assert url.startswith(f"http://127.0.0.1:9/thoth-media/{LOCATION}?")
    assert "X-Amz-Expires=300" in url


def test_the_metered_store_records_scoped_copies_only(tmp_path) -> None:
    from tests.test_metering import Sink
    from thoth_control_plane import metering
    from thoth_control_plane.infrastructure.media_store import MeteredMediaStore
    from thoth_control_plane.metering import MeterScope

    sink = Sink()
    metering.install(sink)
    store = MeteredMediaStore(LocalMediaStore(tmp_path / "root"))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x" * 120)
    store.put_file("reports/wf_1/clip.mp4", source)
    store.copy("reports/wf_1/clip.mp4", "renders/rj_1/output.mp4")  # unscoped: a render publish
    with metering.scoped(MeterScope("ws_a", project_id="p1")):
        store.copy("reports/wf_1/clip.mp4", "uploads/p1/asset_1.mp4")
    assert [(e.workspace_id, e.key, e.quantity) for e in sink.events] == [
        ("ws_a", "uploads", 120.0)
    ]
    assert store.probe_source("uploads/p1/asset_1.mp4").endswith("asset_1.mp4")
```

Before writing the region test, read `test_an_endpoint_selects_the_s3_store` (around line 226)
and copy any extra `Settings` field it passes; keep the assertion lines above unchanged.

Append to `python/tests/infrastructure/test_media_probe.py`:

```python
@pytest.mark.asyncio
async def test_probe_may_open_only_files_and_http(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = spawned(monkeypatch, Process(0, b"{}"))

    await media_probe.probe_media(
        "ffprobe", "http://minio:9000/thoth-media/reports/a.mp4?X-Amz-Signature=s"
    )

    [argv] = calls
    whitelist = argv.index("-protocol_whitelist")
    assert argv[whitelist + 1] == "file,http,https,tcp,tls"
    assert argv[-1] == "http://minio:9000/thoth-media/reports/a.mp4?X-Amz-Signature=s"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T="tests/infrastructure/test_media_store.py tests/infrastructure/test_media_probe.py"'`
Expected: FAIL — `AttributeError: 'LocalMediaStore' object has no attribute 'probe_source'`, the
region test fails the same way, the metered test records no `uploads` event, and the probe test
fails on `argv.index("-protocol_whitelist")` (`ValueError`).

- [ ] **Step 3: Implement**

`config.py`, after `THOTH_MEDIA_S3_SECURE: bool = False`:

```python
    #: Signing a probe URL locally needs the region; MinIO's own default is us-east-1.
    THOTH_MEDIA_S3_REGION: str = "us-east-1"
```

`media_store.py` — add to the `MediaStore` protocol, after `copy`:

```python
    def probe_source(self, location: str) -> str:
        """An input ffprobe reads in place: a local path, or a short-lived signed URL."""
        ...
```

`LocalMediaStore`, after `copy`:

```python
    def probe_source(self, location: str) -> str:
        path = self._path(location)
        if not path.is_file():
            raise MediaUnavailable("media_unavailable")
        return str(path)
```

`MeteredMediaStore` — replace `copy` and add `probe_source`:

```python
    def copy(self, source: str, destination: str) -> None:
        self._inner.copy(source, destination)
        from thoth_control_plane import metering

        try:
            size = self._inner.size(destination)
        except (MediaUnavailable, MediaStoreUnavailable):
            return  # the copy succeeded; only its size is unknown
        metering.record_sync(
            "media_stored", destination.split("/", 1)[0], size, "byte", in_scope_only=True
        )

    def probe_source(self, location: str) -> str:
        return self._inner.probe_source(location)
```

Update the class docstring's second paragraph to say copies are recorded like writes.

`s3_media_store.py` — add `from datetime import timedelta`; in `from_settings` pass
`region=settings.THOTH_MEDIA_S3_REGION,` to `Minio(...)` (after `secure=`); add after `copy`:

```python
    def probe_source(self, location: str) -> str:
        """A five-minute signed GET URL; the client's region keeps signing off the network."""
        key = checked_locator(location)
        with _errors():
            # minio 7.2.20 takes these positionally (the 8.x keyword form does not exist here).
            return self._client.presigned_get_object(self._bucket, key, timedelta(minutes=5))
```

`media_probe.py`:

```python
#: ffprobe may open a local file or the store's signed HTTP(S) URL, and nothing else.
PROTOCOLS = "file,http,https,tcp,tls"


async def probe_media(ffprobe: str, source: Path | str) -> dict[str, Any]:
    """Raise ``OSError`` when ffprobe itself is missing, invalid media when it refuses."""
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-protocol_whitelist",
        PROTOCOLS,
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(source),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
```

(the rest of the function is unchanged). Update the module docstring: "the only
caller-controlled value is a path or signed URL this process composed".

`editor_asset_uploads.py`: `MediaProbe = Callable[[Path | str], Awaitable[dict[str, Any]]]`.

Confirm no deployment sets a non-default MinIO region:
Run: `cd /d/thoth-tmp/wt-studio && rg -n "MINIO_REGION|MINIO_SITE_REGION" compose*.yml docker deploy`
Expected: no output.

- [ ] **Step 4: Run them to verify they pass**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T="tests/infrastructure/test_media_store.py tests/infrastructure/test_media_probe.py tests/application/test_editor_asset_uploads.py tests/api/test_editor_asset_uploads.py"'`
Expected: PASS (the `s3` parameter skips without a MinIO).

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && bash scripts/dev/pytest-minio.sh tests/infrastructure/test_media_store.py'`
Expected: PASS, no skip — the presigned URL is fetched from a real MinIO.

- [ ] **Step 5: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add python/src/thoth_control_plane/infrastructure/media_store.py python/src/thoth_control_plane/infrastructure/s3_media_store.py python/src/thoth_control_plane/infrastructure/media_probe.py python/src/thoth_control_plane/config.py python/src/thoth_control_plane/application/editor_asset_uploads.py python/tests/infrastructure/test_media_store.py python/tests/infrastructure/test_media_probe.py
git commit -m "feat(media): probe objects in place and meter scoped copies"
```

---

### Task 2: Project a Content Set for Studio

**Files:**
- Create: `python/src/thoth_control_plane/assembly/studio.py`
- Modify: `python/src/thoth_control_plane/domain/studio_imports.py` (append response models)
- Test: `python/tests/assembly/test_studio_projection.py`

**Interfaces:**
- Consumes: `ContentSet`, `MainOcr`, `MediaRef` (`assembly/models.py`); `StudioSourceItem`, `StudioSourceProjection`, `StudioUnsupportedField`, `SourceRole`, `inventory` (`domain/studio_imports.py`).
- Produces:
  - `WorkflowProjection(projection: StudioSourceProjection, media: dict[str, MediaRef])` — keys are inventory item ids `f"{role}_{order:03d}"`.
  - `project_content_set(content_set: ContentSet) -> WorkflowProjection`
  - `workflow_source_key(workflow_id: str, content_sha256: str) -> str`
  - `ImportOutcome = Literal["reused", "copied", "unresolved", "decided"]`
  - `WorkflowImportItem(item_id: str, outcome: ImportOutcome, reason: str | None = None)`
  - `WorkflowStudioImport(draft: StudioDraft, items: list[WorkflowImportItem])`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/assembly/test_studio_projection.py`:

```python
"""A Content Set projected for Studio: items, trims, stills, and what Studio leaves out."""

from __future__ import annotations

import hashlib
from typing import Any

from tests.assembly.test_models import OCR, VIDEO, content_set
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.studio import project_content_set, workflow_source_key
from thoth_control_plane.domain.studio_imports import inventory

IMAGE = {
    "location": "reports/wf_a/media/slide-1.jpg",
    "media_type": "image/jpeg",
    "checksum": "sha256:" + "b" * 64,
    "bytes": 900,
    "width": 1080,
    "height": 1350,
}
REGION = {"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.1, "start": 0.0, "end": 4.0}


def footage(index: int, **changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": "search",
        "url": f"https://www.tiktok.com/@kreator/video/740000000000000000{index}",
        "platform": "tiktok",
        "owner_handle": "kreator",
        "query": "banjir jakarta",
        "description": f"Footage {index}",
        "video": {
            "location": f"reports/wf_a/footage/clip-{index}.mp4",
            "media_type": "video/mp4",
            "checksum": "sha256:" + "cd"[index] * 64,
            "bytes": 2048,
            "duration_seconds": 20.0,
        },
        "clip_start": 3.0,
        "ocr": OCR,
        "story_score": 0.61,
        "shows_object": "yes",
    }
    item.update(changes)
    return item


def parse(data: dict[str, Any]) -> ContentSet:
    return ContentSet.model_validate(data)


def test_a_video_main_becomes_the_main_item_with_its_trim() -> None:
    data = content_set(
        ocr=OCR | {"outcome": "cover", "trim_start": 2.5},
        url="https://www.tiktok.com/@creator/video/1234567890?lang=id#top",
    )
    projected = project_content_set(parse(data))
    [main] = projected.projection.items
    assert (main.role, main.order, main.media_kind) == ("main", 0, "video")
    assert main.trim_start_seconds == 2.5
    assert main.source_url == "https://www.tiktok.com/@creator/video/1234567890"
    assert (main.title, main.text, main.platform) == ("judul", "judul panjang", "tiktok")
    assert projected.media["main_000"].location.as_posix() == VIDEO["location"]
    assert projected.projection.unsupported == []


def test_a_clean_main_has_no_trim() -> None:
    [main] = project_content_set(parse(content_set())).projection.items
    assert main.trim_start_seconds is None


def test_an_images_main_keeps_its_first_slide_and_reports_the_rest() -> None:
    second = IMAGE | {"location": "reports/wf_a/media/slide-2.jpg"}
    data = content_set(kind="images", video=None, ocr=None, images=[IMAGE, second])
    projected = project_content_set(parse(data))
    [main] = projected.projection.items
    assert (main.media_kind, main.trim_start_seconds) == ("image", None)
    assert projected.media["main_000"].location.as_posix() == IMAGE["location"]
    [slides] = projected.projection.unsupported
    assert (slides.field, slides.role, slides.order) == ("main.images", "main", 0)
    assert slides.value_digest is not None


def test_a_card_main_is_a_still() -> None:
    data = content_set(kind="card", video=None, ocr=None, card=IMAGE)
    projected = project_content_set(parse(data))
    assert projected.projection.items[0].media_kind == "image"
    assert projected.media["main_000"].media_type == "image/jpeg"


def test_footage_and_comments_follow_the_main_in_order() -> None:
    data = content_set() | {
        "footage": [footage(0, ocr=OCR | {"outcome": "cover", "trim_start": 1.0}), footage(1)],
        "footage_status": "ok",
        "comments": [{"text": "wow", "author": "viewer", "source": "input"}],
    }
    projected = project_content_set(parse(data))
    items = projected.projection.items
    assert [(i.role, i.order, i.media_kind) for i in items] == [
        ("main", 0, "video"),
        ("footage", 0, "video"),
        ("footage", 1, "video"),
        ("comment", 0, "none"),
    ]
    assert [i.trim_start_seconds for i in items[1:3]] == [1.0, None]
    assert (items[1].title, items[1].text) == ("@kreator", "Footage 0")
    assert (items[3].title, items[3].text, items[3].source_url) == ("@viewer", "wow", None)
    media_items = {i.item_id for i in inventory(projected.projection) if i.media_kind != "none"}
    assert media_items == set(projected.media) == {"main_000", "footage_000", "footage_001"}


def test_what_studio_cannot_show_is_reported_once_each_with_a_digest() -> None:
    subtitled = OCR | {"outcome": "subtitle", "mute_audio": True, "subtitle_blur": [REGION]}
    data = content_set(profile_card=IMAGE, ocr=subtitled) | {
        "comments": [{"text": "wow", "author": "viewer", "source": "input", "card": IMAGE}],
        "figures": [{"name": "Prabowo", "type": "person"}],
        "figures_status": "ok",
    }
    unsupported = project_content_set(parse(data)).projection.unsupported
    assert [(u.field, u.role, u.order) for u in unsupported] == [
        ("main.profile_card", "main", 0),
        ("main.ocr.mute_audio", "main", 0),
        ("main.ocr.subtitle_blur", "main", 0),
        ("comments.card", "comment", 0),
        ("figures", None, None),
    ]
    assert all(u.value_digest and len(u.value_digest) == 64 for u in unsupported)


def test_a_description_past_the_text_limit_is_reported_not_cut() -> None:
    data = content_set(description="x" * 2_001)
    projected = project_content_set(parse(data))
    assert projected.projection.items[0].text is None
    assert [u.field for u in projected.projection.unsupported] == ["main.description"]


def test_the_workflow_source_key_is_per_workflow_and_per_content() -> None:
    digest = hashlib.sha256(b"content").hexdigest()
    key = workflow_source_key("wf_a", digest)
    assert key == hashlib.sha256(f"workflow:wf_a:{digest}".encode()).hexdigest()
    assert key != workflow_source_key("wf_b", digest)
    assert key != workflow_source_key("wf_a", hashlib.sha256(b"other").hexdigest())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=tests/assembly/test_studio_projection.py'`
Expected: FAIL — `ModuleNotFoundError: No module named 'thoth_control_plane.assembly.studio'`.

- [ ] **Step 3: Implement**

Append to `python/src/thoth_control_plane/domain/studio_imports.py`:

```python
ImportOutcome: TypeAlias = Literal["reused", "copied", "unresolved", "decided"]
ImportCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class WorkflowImportItem(StrictModel):
    """What one media item's import did: reused or copied an asset, left it unresolved with a
    fixed reason, or found it already decided (attached or excluded) by an earlier attempt."""

    item_id: ImportCode
    outcome: ImportOutcome
    reason: ImportCode | None = None


class WorkflowStudioImport(StrictModel):
    """The draft a workflow opened into, at its latest revision, and each media item's outcome."""

    draft: StudioDraft
    items: list[WorkflowImportItem]
```

Create `python/src/thoth_control_plane/assembly/studio.py`:

```python
"""A Content Set projected for Studio (spec 2026-10-20 workflow to Studio, section 1).

Pure: no I/O. Each media item keeps the `MediaRef` it came from, keyed by the inventory item id
the import gate gives it (`<role>_<order:03d>`), so the importer copies exactly that object.
Schema 1 bounds a Content Set at one main, six footage and twelve comments, far inside the
gate's item and scene limits, so nothing here truncates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from thoth_control_plane.assembly.models import ContentSet, MainOcr, MediaRef
from thoth_control_plane.domain.studio_imports import (
    SourceRole,
    StudioSourceItem,
    StudioSourceProjection,
    StudioUnsupportedField,
)

TITLE_LIMIT = 300
TEXT_LIMIT = 2_000
CARDS = "Cards wait for Stage 5c"
SLIDES = "Carousel slides wait for Stage 5c"
MUTE = "Per-clip mute is not supported"
BLUR = "Subtitle blur is not supported"
FIGURES = "Figures are context, not scenes"


@dataclass(frozen=True)
class WorkflowProjection:
    projection: StudioSourceProjection
    media: dict[str, MediaRef]


def workflow_source_key(workflow_id: str, content_sha256: str) -> str:
    """Distinct per workflow, stable for one Content Set, new when it is re-assembled."""
    return hashlib.sha256(f"workflow:{workflow_id}:{content_sha256}".encode()).hexdigest()


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(url: object) -> str | None:
    """The gate takes no query, fragment or credentials: keep the scheme, host and path."""
    parts = urlsplit(str(url))
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    value = urlunsplit((parts.scheme, host, parts.path or "/", "", ""))
    return value if len(value) <= 2_048 and "\\" not in value else None


def _trim(ocr: MainOcr | None) -> float | None:
    return ocr.trim_start if ocr is not None and ocr.trim_start > 0 else None


class _Builder:
    def __init__(self) -> None:
        self.items: list[StudioSourceItem] = []
        self.unsupported: list[StudioUnsupportedField] = []
        self.media: dict[str, MediaRef] = {}

    def report(
        self, field: str, role: SourceRole | None, order: int | None, reason: str, value: Any
    ) -> None:
        self.unsupported.append(
            StudioUnsupportedField(
                field=field, role=role, order=order, reason=reason, value_digest=_digest(value)
            )
        )

    def bounded(
        self, field: str, role: SourceRole, order: int, value: str, limit: int
    ) -> str | None:
        if not value:
            return None
        if len(value) > limit:
            self.report(field, role, order, f"Longer than {limit} characters", value)
            return None
        return value

    def add(
        self,
        role: SourceRole,
        order: int,
        *,
        title: str | None,
        text: str | None,
        platform: str | None,
        url: object | None,
        media: MediaRef | None,
        trim: float | None,
    ) -> None:
        if media is None:
            kind = "none"
        else:
            kind = "video" if media.media_type.startswith("video/") else "image"
            self.media[f"{role}_{order:03d}"] = media
        self.items.append(
            StudioSourceItem(
                role=role,
                order=order,
                title=title,
                text=text,
                platform=platform,
                source_url=None if url is None else _canonical(url),
                media_kind=kind,
                trim_start_seconds=trim if kind == "video" else None,
            )
        )

    def ocr(self, prefix: str, role: SourceRole, order: int, ocr: MainOcr | None) -> None:
        if ocr is None:
            return
        if ocr.mute_audio:
            self.report(f"{prefix}.mute_audio", role, order, MUTE, True)
        if ocr.subtitle_blur:
            regions = [region.model_dump(mode="json") for region in ocr.subtitle_blur]
            self.report(f"{prefix}.subtitle_blur", role, order, BLUR, regions)


def project_content_set(content_set: ContentSet) -> WorkflowProjection:
    built = _Builder()
    main = content_set.main
    if main.kind == "video":
        media = main.video
    elif main.kind == "images":
        media = main.images[0]
    else:
        media = main.card
    built.add(
        "main",
        0,
        title=built.bounded("main.title", "main", 0, main.title, TITLE_LIMIT),
        text=built.bounded("main.description", "main", 0, main.description, TEXT_LIMIT),
        platform=str(main.platform),
        url=main.url,
        media=media,
        trim=_trim(main.ocr),
    )
    if len(main.images) > 1:
        slides = [image.location.as_posix() for image in main.images[1:]]
        built.report("main.images", "main", 0, SLIDES, slides)
    if main.profile_card is not None:
        built.report("main.profile_card", "main", 0, CARDS, main.profile_card.location.as_posix())
    built.ocr("main.ocr", "main", 0, main.ocr)
    for order, clip in enumerate(content_set.footage):
        built.add(
            "footage",
            order,
            title=f"@{clip.owner_handle}",
            text=clip.description or None,
            platform=clip.platform,
            url=clip.url,
            media=clip.video,
            trim=_trim(clip.ocr),
        )
        built.ocr("footage.ocr", "footage", order, clip.ocr)
    for order, comment in enumerate(content_set.comments):
        built.add(
            "comment",
            order,
            title=f"@{comment.author}",
            text=comment.text,
            platform=None,
            url=None,
            media=None,
            trim=None,
        )
        if comment.card is not None:
            built.report("comments.card", "comment", order, CARDS, comment.card.location.as_posix())
    if content_set.figures:
        figures = [figure.model_dump(mode="json") for figure in content_set.figures]
        built.report("figures", None, None, FIGURES, figures)
    projection = StudioSourceProjection(items=built.items, unsupported=built.unsupported)
    return WorkflowProjection(projection=projection, media=built.media)
```

The order of `report` calls inside one main fixes the order the test asserts: profile card,
then mute, then blur (from `built.ocr`), then comment cards, then figures — keep it.

- [ ] **Step 4: Run them to verify they pass**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T="tests/assembly/test_studio_projection.py tests/domain/test_studio_imports.py"'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add python/src/thoth_control_plane/assembly/studio.py python/src/thoth_control_plane/domain/studio_imports.py python/tests/assembly/test_studio_projection.py
git commit -m "feat(studio): project a Content Set into a Studio source"
```

---

### Task 3: Find a ready asset by checksum

**Files:**
- Modify: `python/src/thoth_control_plane/application/editor_asset_ports.py` (`EditorAssetRepository`)
- Modify: `python/src/thoth_control_plane/infrastructure/editor_asset_repository.py`
- Test: `python/tests/infrastructure/test_editor_asset_repository.py`

**Interfaces:**
- Produces: `EditorAssetRepository.find_ready_by_checksum(*, project_id: str, checksum: str) -> EditorAssetRecord | None` — the oldest ready asset of that project with that checksum.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/infrastructure/test_editor_asset_repository.py`:

```python
@pytest.mark.asyncio
async def test_find_ready_by_checksum_is_project_scoped_and_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = Cursor(row=record_row(provenance="workflow_import"))

    record = await patched(monkeypatch, cursor).find_ready_by_checksum(
        project_id="project_001", checksum="sha256:" + "a" * 64
    )

    assert record is not None and record.provenance == "workflow_import"
    query, params = cursor.calls[0]
    assert "WHERE project_id = %s AND checksum = %s" in query
    assert "validation_state = 'ready'" in query
    assert "ORDER BY created_at, asset_id" in query and "LIMIT 1" in query
    assert params == ("project_001", "sha256:" + "a" * 64)


@pytest.mark.asyncio
async def test_find_ready_by_checksum_without_a_match_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = patched(monkeypatch, Cursor(row=None))
    assert (
        await repository.find_ready_by_checksum(project_id="project_001", checksum="sha256:" + "f" * 64)
        is None
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=tests/infrastructure/test_editor_asset_repository.py'`
Expected: FAIL — `AttributeError: 'PostgresEditorAssetRepository' object has no attribute 'find_ready_by_checksum'`.

- [ ] **Step 3: Implement**

Port (`editor_asset_ports.py`), after `get_ready_records`:

```python
    async def find_ready_by_checksum(
        self, *, project_id: str, checksum: str
    ) -> EditorAssetRecord | None:
        """The project's oldest ready asset with these exact bytes, so a copy is never repeated."""
        ...
```

Postgres (`editor_asset_repository.py`), after `get_ready_record`:

```python
    async def find_ready_by_checksum(
        self, *, project_id: str, checksum: str
    ) -> EditorAssetRecord | None:
        try:
            connection = await AsyncConnection.connect(self._database_url)
            async with connection:
                database_cursor = connection.cursor()
                await database_cursor.execute(
                    f"""
                    SELECT {PUBLIC_COLUMNS}, artifact_location, provenance
                    FROM editor_assets
                    WHERE project_id = %s AND checksum = %s AND validation_state = 'ready'
                    ORDER BY created_at, asset_id
                    LIMIT 1
                    """,
                    (project_id, checksum),
                )
                row = await database_cursor.fetchone()
                if row is None:
                    return None
                return EditorAssetRecord(
                    asset=_asset(row), artifact_location=row[-2], provenance=row[-1]
                )
        except Exception as error:
            raise EditorAssetPersistenceError() from error
```

- [ ] **Step 4: Run them to verify they pass**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=tests/infrastructure/test_editor_asset_repository.py'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add python/src/thoth_control_plane/application/editor_asset_ports.py python/src/thoth_control_plane/infrastructure/editor_asset_repository.py python/tests/infrastructure/test_editor_asset_repository.py
git commit -m "feat(assets): find a project's ready asset by checksum"
```

---

### Task 4: Drafts under a caller-derived source key

**Files:**
- Modify: `python/src/thoth_control_plane/application/studio_imports.py` (`inspect`, `create`, new `inspect_keyed`, `create_keyed`)
- Test: `python/tests/application/test_studio_imports.py`

**Interfaces:**
- Produces:
  - `StudioImportService.inspect_keyed(project_id: ProjectId, key: str, projection: StudioSourceProjection) -> StudioSourceInspection`
  - `StudioImportService.create_keyed(project_id: ProjectId, key: str, projection: StudioSourceProjection, idempotency_key: str) -> StudioDraft`
  - `inspect` and `create` keep their behaviour and now delegate to these.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/application/test_studio_imports.py`:

```python
async def test_a_keyed_draft_lives_under_the_given_key_not_the_projection_hash() -> None:
    repository = MemoryStudioImports()
    service = StudioImportService(repository)
    projection = create_request().source
    key = "f" * 64

    draft = await service.create_keyed(PROJECT, key, projection, "wf-open-1")
    again = await service.create_keyed(PROJECT, key, projection, "wf-open-1")

    assert (draft.source_key, again.document_id) == (key, draft.document_id)
    inspection = await service.inspect_keyed(PROJECT, key, projection)
    assert inspection.source_key == key
    assert [found.document_id for found in inspection.drafts] == [draft.document_id]
    assert (await service.inspect(PROJECT, projection)).drafts == []


async def test_a_keyed_draft_refuses_an_unsafe_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        await StudioImportService(MemoryStudioImports()).create_keyed(
            PROJECT, "f" * 64, create_request().source, "C:\\Users\\key"
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=tests/application/test_studio_imports.py'`
Expected: FAIL — `AttributeError: 'StudioImportService' object has no attribute 'create_keyed'`.

- [ ] **Step 3: Implement**

Replace `inspect` and `create` in `StudioImportService` with:

```python
    async def inspect(
        self, project_id: ProjectId, projection: StudioSourceProjection
    ) -> StudioSourceInspection:
        """Read-only: what would be imported, and which drafts already exist."""
        return await self.inspect_keyed(project_id, source_key(projection), projection)

    async def inspect_keyed(
        self, project_id: ProjectId, key: str, projection: StudioSourceProjection
    ) -> StudioSourceInspection:
        """`inspect` under a key the caller derived (a workflow import), not the projection's."""
        inspection = inspect_source(project_id, projection).model_copy(update={"source_key": key})
        listing = await self.list_drafts(project_id, key)
        return inspection.model_copy(
            update={"drafts": listing.drafts, "more_drafts": listing.more_drafts}
        )

    async def create(
        self, project_id: ProjectId, request: CreateStudioImport, idempotency_key: str
    ) -> StudioDraft:
        IDEMPOTENCY_KEY_ADAPTER.validate_python(idempotency_key)
        self._store()
        if source_key(request.source) != request.source_key:
            raise StudioImportSourceMismatch()
        return await self.create_keyed(
            project_id, request.source_key, request.source, idempotency_key
        )

    async def create_keyed(
        self,
        project_id: ProjectId,
        key: str,
        projection: StudioSourceProjection,
        idempotency_key: str,
    ) -> StudioDraft:
        """Create one draft per idempotency key under `key`; a replay returns the same draft."""
        IDEMPOTENCY_KEY_ADAPTER.validate_python(idempotency_key)
        repository = self._store()
        try:
            return await repository.create_draft(
                project_id=project_id,
                source_key=key,
                idempotency_key=idempotency_key,
                document=build_studio_draft(project_id, f"edoc_{uuid4().hex}", projection),
                inventory=inventory(projection),
            )
        except PASSTHROUGH:
            raise
        except Exception as error:
            raise EditorUnavailable() from error
```

- [ ] **Step 4: Run them to verify they pass**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T="tests/application/test_studio_imports.py tests/api/test_studio_imports.py"'`
Expected: PASS (the existing tests prove `inspect`/`create` are unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add python/src/thoth_control_plane/application/studio_imports.py python/tests/application/test_studio_imports.py
git commit -m "feat(studio): create and inspect drafts under a given source key"
```

---

### Task 5: The workflow-to-Studio import service

**Files:**
- Create: `python/src/thoth_control_plane/application/workflow_studio_imports.py`
- Test: `python/tests/application/test_workflow_studio_imports.py`

**Interfaces:**
- Consumes: Task 1 `probe_source`, metered `copy`, `MediaProbe`; Task 2 `project_content_set`, `workflow_source_key`, `WorkflowImportItem`, `WorkflowStudioImport`; Task 3 `find_ready_by_checksum`; Task 4 `inspect_keyed`, `create_keyed`; existing `StudioImportService.get_inventory`, `StudioImportService.resolve`, `described_asset`, `UPLOAD_TYPES`, `StoredRun.owned_by`, store `get`/`assign`.
- Produces:
  - `WorkflowStudioImportService(*, runs, reports, media, assets, imports: StudioImportService, probe: MediaProbe)`
  - `async inspect(project_id: str, workflow_id: str, actor: Actor) -> StudioSourceInspection`
  - `async open(project_id: str, workflow_id: str, actor: Actor, idempotency_key: str) -> WorkflowStudioImport`
  - exceptions `WorkflowStudioUnavailable`, `ContentSetUnavailable`, `ContentSetInvalid`, `WorkflowInOtherProject`; unknown or foreign runs raise the existing `WorkflowNotFound`.
  - test helpers reused by Tasks 6–7: `WF`, `ACTOR`, `PROJECT`, `stored_run`, `content_set_data`, `content_set_bytes`, `seed_media`, `MemoryRuns`, `MemoryReports`, `MemoryAssets`, `AttachingImports`, `Probe`.
- Spec deviation, decided here: section 2 step 2 says `media.stat`; the service calls
  `media.size`, which answers the same presence and size without hashing the object on the local
  store. A store outage during one item leaves that item `media_store_unavailable` (a replay
  retries it) rather than failing the whole request after the draft exists.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/application/test_workflow_studio_imports.py`:

```python
"""Opening a workflow in Studio: reuse, probe in place, copy, attach, and resumable replay."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.application.test_studio_imports import MemoryStudioImports
from tests.assembly.test_models import OCR, content_set
from tests.test_metering import Sink
from thoth_control_plane import metering
from thoth_control_plane.application.editor_asset_ports import (
    EditorAssetMediaInvalid,
    EditorAssetPersistenceError,
)
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    StudioImportDecisionRejected,
    StudioImportItemResolved,
)
from thoth_control_plane.application.studio_imports import StudioImportService
from thoth_control_plane.application.workflow_studio_imports import (
    ContentSetInvalid,
    ContentSetUnavailable,
    WorkflowInOtherProject,
    WorkflowStudioImportService,
    WorkflowStudioUnavailable,
)
from thoth_control_plane.application.workflows import WorkflowNotFound
from thoth_control_plane.assembly.studio import workflow_source_key
from thoth_control_plane.domain.editor_assets import EditorAssetRecord
from thoth_control_plane.domain.models import Actor
from thoth_control_plane.domain.studio_imports import (
    AttachImportAsset,
    ExcludeImportItem,
    ResolveStudioImportItem,
)
from thoth_control_plane.domain.workflow_runs import StoredRun
from thoth_control_plane.infrastructure.media_store import LocalMediaStore, MeteredMediaStore
from thoth_control_plane.metering import MeterScope

PROJECT = "project_001"
WF = "wf_a"
ACTOR = Actor(actor_id="owner", actor_type="user")
COVER = OCR | {"outcome": "cover", "trim_start": 1.0}
VIDEO_REPORT = {
    "streams": [
        {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
        {"codec_type": "audio"},
    ],
    "format": {"duration": "30.0"},
}
IMAGE_REPORT = {"streams": [{"codec_type": "video", "width": 1080, "height": 1350}], "format": {}}
ALL_COPIED = [("main_000", "copied"), ("footage_000", "copied"), ("footage_001", "copied")]


def footage(index: int, **changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": "search",
        "url": f"https://www.tiktok.com/@kreator/video/740000000000000000{index}",
        "platform": "tiktok",
        "owner_handle": "kreator",
        "query": "banjir jakarta",
        "description": f"Footage {index}",
        "video": {
            "location": f"reports/{WF}/footage/clip-{index}.mp4",
            "media_type": "video/mp4",
            "checksum": "sha256:" + "cd"[index] * 64,
            "bytes": 2048,
            "duration_seconds": 20.0,
        },
        "clip_start": 0.0,
        "ocr": OCR,
        "story_score": 0.61,
        "shows_object": "yes",
    }
    item.update(changes)
    return item


def content_set_data(**main: Any) -> dict[str, Any]:
    return content_set(**main) | {
        "footage": [footage(0, ocr=COVER), footage(1)],
        "footage_status": "ok",
    }


def content_set_bytes(data: dict[str, Any] | None = None) -> bytes:
    return json.dumps(data or content_set_data()).encode()


def seed_media(media: Any, tmp_path: Path, data: dict[str, Any] | None = None) -> None:
    """Store one object per MediaRef, exactly as many bytes as it declares."""
    data = data or content_set_data()
    main = data["main"]
    refs = [ref for ref in (main.get("video"), main.get("card")) if ref]
    refs += [*main.get("images", []), *(item["video"] for item in data.get("footage", []))]
    for index, ref in enumerate(refs):
        source = tmp_path / f"seed-{index}.bin"
        source.write_bytes(b"m" * ref["bytes"])
        media.put_file(ref["location"], source)


def stored_run(
    project_id: str | None = None, actor_id: str = "owner", status: str = "succeeded"
) -> StoredRun:
    now = datetime(2026, 10, 20, tzinfo=UTC)
    return StoredRun(
        workflow_id=WF,
        project_id=project_id,
        actor_type="user",
        actor_id=actor_id,
        display_url="https://x.test/v",
        platform="tiktok",
        status=status,
        history_expired=False,
        summary=None,
        created_at=now,
        updated_at=now,
    )


class MemoryRuns:
    def __init__(self, *runs: StoredRun) -> None:
        self.runs = {run.workflow_id: run for run in runs}

    def get(self, workflow_id: str) -> StoredRun | None:
        return self.runs.get(workflow_id)

    def assign(self, workflow_id: str, project_id: str) -> StoredRun | None:
        run = self.runs.get(workflow_id)
        if run is None:
            return None
        self.runs[workflow_id] = dataclasses.replace(run, project_id=project_id)
        return self.runs[workflow_id]


class MemoryReports:
    def __init__(self, content: bytes | None) -> None:
        self.rows = {} if content is None else {f"reports/{WF}/content-set.json": content}

    def get(self, location: str) -> bytes | None:
        return self.rows.get(location)


class MemoryAssets:
    def __init__(self, *, fail_register: bool = False) -> None:
        self.records: list[EditorAssetRecord] = []
        self.fail_register = fail_register

    async def find_ready_by_checksum(
        self, *, project_id: str, checksum: str
    ) -> EditorAssetRecord | None:
        return next(
            (
                record
                for record in self.records
                if (record.asset.project_id, record.asset.checksum) == (project_id, checksum)
            ),
            None,
        )

    async def register_ready(self, record: EditorAssetRecord) -> None:
        if self.fail_register:
            raise EditorAssetPersistenceError()
        self.records.append(record)


class AttachingImports(MemoryStudioImports):
    """MemoryStudioImports plus the decision path, with the refusals Postgres gives."""

    def __init__(
        self, refuse: dict[str, str] | None = None, conflict: set[str] | None = None
    ) -> None:
        super().__init__()
        self.refuse = refuse or {}
        self.conflict = conflict or set()

    async def resolve_item(
        self,
        *,
        project_id: str,
        document_id: str,
        item_id: str,
        base_revision: int,
        decision: Any,
    ) -> Any:
        row = next(
            row
            for row in self.rows
            if (row["project_id"], row["draft"].document_id) == (project_id, document_id)
        )
        if item_id in self.conflict or base_revision != row["draft"].revision:
            raise EditDocumentRevisionConflict(row["document"])
        entry = next(item for item in row["inventory"] if item.item_id == item_id)
        if entry.disposition != "unresolved":
            raise StudioImportItemResolved()
        if item_id in self.refuse:
            raise StudioImportDecisionRejected(self.refuse[item_id])
        attached = isinstance(decision, AttachImportAsset)
        row["inventory"] = [
            item.model_copy(
                update={
                    "disposition": "attached" if attached else "excluded",
                    "asset_id": decision.asset_id if attached else None,
                }
            )
            if item.item_id == item_id
            else item
            for item in row["inventory"]
        ]
        row["draft"] = row["draft"].model_copy(update={"revision": row["draft"].revision + 1})
        return await self.get_inventory(project_id=project_id, document_id=document_id)


class Probe:
    def __init__(self, invalid: set[str] | None = None) -> None:
        self.sources: list[str] = []
        self.invalid = invalid or set()

    async def __call__(self, source: Path | str) -> dict[str, Any]:
        self.sources.append(str(source))
        if any(name in str(source) for name in self.invalid):
            raise EditorAssetMediaInvalid("invalid_media")
        return IMAGE_REPORT if str(source).endswith(".jpg") else VIDEO_REPORT


@dataclasses.dataclass
class World:
    service: WorkflowStudioImportService
    runs: MemoryRuns
    media: LocalMediaStore
    assets: MemoryAssets
    imports: AttachingImports
    probe: Probe


def world(
    tmp_path: Path,
    *,
    data: dict[str, Any] | None = None,
    reports: Any = None,
    run: StoredRun | None = None,
    assets: MemoryAssets | None = None,
    imports: AttachingImports | None = None,
    probe: Probe | None = None,
) -> World:
    media = LocalMediaStore(tmp_path / "store")
    seed_media(media, tmp_path, data)
    runs = MemoryRuns(run or stored_run())
    assets, imports, probe = assets or MemoryAssets(), imports or AttachingImports(), probe or Probe()
    service = WorkflowStudioImportService(
        runs=runs,
        reports=reports or MemoryReports(content_set_bytes(data)),
        media=MeteredMediaStore(media),
        assets=assets,
        imports=StudioImportService(imports),
        probe=probe,
    )
    return World(service, runs, media, assets, imports, probe)


def outcomes(opened: Any) -> list[tuple[str, str]]:
    return [(item.item_id, item.outcome) for item in opened.items]


async def test_inspect_is_read_only_and_keyed_by_the_workflow(tmp_path: Path) -> None:
    w = world(tmp_path)
    found = await w.service.inspect(PROJECT, WF, ACTOR)
    digest = hashlib.sha256(content_set_bytes()).hexdigest()
    assert found.source_key == workflow_source_key(WF, digest)
    media = {item.item_id for item in found.items if item.media_kind != "none"}
    assert media == {"main_000", "footage_000", "footage_001"}
    assert found.drafts == []
    assert (w.runs.get(WF).project_id, w.assets.records, w.imports.rows) == (None, [], [])


async def test_open_probes_in_place_copies_registers_and_attaches(tmp_path: Path) -> None:
    w = world(tmp_path)
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    assert outcomes(opened) == ALL_COPIED
    assert w.runs.get(WF).project_id == PROJECT
    assert len(w.probe.sources) == 3
    assert all(source.startswith(str(w.media.root)) for source in w.probe.sources)
    for record in w.assets.records:
        assert record.provenance == "workflow_import"
        assert record.artifact_location == f"uploads/{PROJECT}/{record.asset.asset_id}.mp4"
    assert sorted(w.media.size(r.artifact_location) for r in w.assets.records) == [2048, 2048, 20000]
    inventory = await StudioImportService(w.imports).get_inventory(PROJECT, opened.draft.document_id)
    attached = {i.item_id: i.disposition for i in inventory.items if i.media_kind != "none"}
    assert set(attached.values()) == {"attached"}
    assert opened.draft.revision == inventory.revision == 4


async def test_a_project_asset_with_the_same_bytes_is_reused(tmp_path: Path) -> None:
    w = world(tmp_path)
    await w.service.open(PROJECT, WF, ACTOR, "open-1")
    copies = w.media.list(f"uploads/{PROJECT}/")

    second = await w.service.open(PROJECT, WF, ACTOR, "open-2")

    assert {outcome for _, outcome in outcomes(second)} == {"reused"}
    assert w.media.list(f"uploads/{PROJECT}/") == copies
    assert len(w.probe.sources) == 3


async def test_replaying_the_key_finishes_what_a_cut_off_attempt_left(tmp_path: Path) -> None:
    w = world(tmp_path, assets=MemoryAssets(fail_register=True))
    first = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert {(item.outcome, item.reason) for item in first.items} == {
        ("unresolved", "asset_unavailable")
    }
    assert w.media.list(f"uploads/{PROJECT}/") == []  # every orphan copy was removed

    w.assets.fail_register = False
    again = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    third = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    assert again.draft.document_id == first.draft.document_id
    assert outcomes(again) == ALL_COPIED
    assert {outcome for _, outcome in outcomes(third)} == {"decided"}
    assert len(w.imports.rows) == 1


async def test_an_excluded_item_is_not_retried(tmp_path: Path) -> None:
    w = world(tmp_path, probe=Probe(invalid={"clip-1"}))
    first = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert ("footage_001", "unresolved") in outcomes(first)
    imports = StudioImportService(w.imports)
    inventory = await imports.get_inventory(PROJECT, first.draft.document_id)
    exclude = ResolveStudioImportItem(
        base_revision=inventory.revision, decision=ExcludeImportItem(kind="exclude")
    )
    await imports.resolve(PROJECT, first.draft.document_id, "footage_001", exclude)

    again = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    assert {outcome for _, outcome in outcomes(again)} == {"decided"}
    assert sum("clip-1" in source for source in w.probe.sources) == 1


@pytest.mark.parametrize(("damage", "reason"), [("delete", "media_missing"), ("grow", "media_mismatch")])
async def test_a_missing_or_changed_object_leaves_only_its_item(
    tmp_path: Path, damage: str, reason: str
) -> None:
    w = world(tmp_path)
    location = f"reports/{WF}/footage/clip-0.mp4"
    if damage == "delete":
        w.media.delete(location)
    else:
        bigger = tmp_path / "bigger.bin"
        bigger.write_bytes(b"m" * 4096)
        w.media.put_file(location, bigger)

    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", reason)
    assert found["main_000"] == ("copied", None)


async def test_invalid_media_is_never_copied(tmp_path: Path) -> None:
    w = world(tmp_path, probe=Probe(invalid={"clip-0"}))
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", "media_invalid")
    assert len(w.media.list(f"uploads/{PROJECT}/")) == 2


async def test_a_refused_attach_keeps_the_registered_asset(tmp_path: Path) -> None:
    w = world(tmp_path, imports=AttachingImports(refuse={"footage_000": "trim_exceeds_asset"}))
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", "trim_exceeds_asset")
    assert len(w.assets.records) == 3


async def test_a_decision_made_meanwhile_in_the_gate_stands(tmp_path: Path) -> None:
    w = world(tmp_path, imports=AttachingImports(conflict={"footage_000"}))
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", "draft_changed")
    assert found["footage_001"] == ("copied", None)


async def test_an_upper_case_checksum_is_stored_lower_case(tmp_path: Path) -> None:
    data = content_set_data()
    # A copy: `content_set()` shares the module-level VIDEO dict with every other test.
    data["main"]["video"] = data["main"]["video"] | {"checksum": "sha256:" + "A" * 64}
    w = world(tmp_path, data=data)
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert outcomes(opened) == ALL_COPIED
    assert "sha256:" + "a" * 64 in {record.asset.checksum for record in w.assets.records}


async def test_an_images_main_imports_its_first_slide_as_a_still(tmp_path: Path) -> None:
    slide = {
        "location": f"reports/{WF}/media/slide-1.jpg",
        "media_type": "image/jpeg",
        "checksum": "sha256:" + "b" * 64,
        "bytes": 900,
        "width": 1080,
        "height": 1350,
    }
    data = content_set_data(kind="images", video=None, ocr=None, images=[slide])
    w = world(tmp_path, data=data)
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert outcomes(opened)[0] == ("main_000", "copied")
    [still] = [r for r in w.assets.records if r.asset.kind == "image"]
    assert still.artifact_location.endswith(".jpg")


async def test_a_lagging_run_status_does_not_block_the_import(tmp_path: Path) -> None:
    w = world(tmp_path, run=stored_run(status="running"))
    assert outcomes(await w.service.open(PROJECT, WF, ACTOR, "open-1")) == ALL_COPIED


async def test_copies_count_as_stored_media_for_the_workspace(tmp_path: Path) -> None:
    sink = Sink()
    metering.install(sink)
    w = world(tmp_path)
    with metering.scoped(MeterScope("ws_a", project_id=PROJECT)):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    stored = sorted(event.quantity for event in sink.events if event.key == "uploads")
    assert stored == [2048.0, 2048.0, 20000.0]


async def test_an_unknown_or_foreign_run_is_not_found(tmp_path: Path) -> None:
    w = world(tmp_path, run=stored_run(actor_id="ws_other"))
    with pytest.raises(WorkflowNotFound):
        await w.service.inspect(PROJECT, WF, ACTOR)
    with pytest.raises(WorkflowNotFound):
        await w.service.open(PROJECT, "wf_unknown", ACTOR, "open-1")


async def test_a_run_of_another_project_is_refused_before_any_write(tmp_path: Path) -> None:
    w = world(tmp_path, run=stored_run(project_id="project_002"))
    with pytest.raises(WorkflowInOtherProject):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert w.imports.rows == []


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (None, ContentSetUnavailable),
        (b"{}", ContentSetInvalid),
        (content_set_bytes(content_set_data() | {"workflow_id": "wf_b"}), ContentSetInvalid),
    ],
)
async def test_a_missing_or_invalid_content_set_creates_nothing(
    tmp_path: Path, content: bytes | None, error: type[Exception]
) -> None:
    w = world(tmp_path, reports=MemoryReports(content))
    with pytest.raises(error):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert (w.imports.rows, w.runs.get(WF).project_id) == ([], None)


async def test_an_unreachable_report_store_is_unavailable(tmp_path: Path) -> None:
    class Down:
        def get(self, location: str) -> bytes | None:
            raise RuntimeError("database down")

    w = world(tmp_path, reports=Down())
    with pytest.raises(WorkflowStudioUnavailable):
        await w.service.inspect(PROJECT, WF, ACTOR)


async def test_a_missing_ffprobe_fails_loud(tmp_path: Path) -> None:
    class NoFfprobe(Probe):
        async def __call__(self, source: Path | str) -> dict[str, Any]:
            raise FileNotFoundError("ffprobe")

    w = world(tmp_path, probe=NoFfprobe())
    with pytest.raises(WorkflowStudioUnavailable):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=tests/application/test_workflow_studio_imports.py'`
Expected: FAIL — `ModuleNotFoundError: No module named 'thoth_control_plane.application.workflow_studio_imports'`.

- [ ] **Step 3: Implement**

Create `python/src/thoth_control_plane/application/workflow_studio_imports.py`:

```python
"""Open a finished workflow in Studio (spec 2026-10-20 workflow to Studio).

The Content Set row is read from the report store, projected on the server, and turned into a
draft under the workflow's own source key. Each media item is then reused by checksum, or probed
in place, copied server side into the project's uploads, registered, and attached. One item's
failure leaves only that item unresolved; replaying the same key finishes what is left.

Store failures are caught as plain exceptions, like the upload service does, so this layer never
imports an infrastructure module.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from typing import Any, Literal, Protocol
from uuid import uuid4

from thoth_control_plane.application.editor_asset_ports import EditorAssetMediaInvalid
from thoth_control_plane.application.editor_asset_uploads import (
    UPLOAD_TYPES,
    MediaProbe,
    described_asset,
)
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    StudioImportDecisionRejected,
    StudioImportItemResolved,
)
from thoth_control_plane.application.studio_imports import StudioImportService
from thoth_control_plane.application.workflows import WorkflowNotFound
from thoth_control_plane.assembly.models import ContentSet, MediaRef
from thoth_control_plane.assembly.studio import (
    WorkflowProjection,
    project_content_set,
    workflow_source_key,
)
from thoth_control_plane.domain.editor_assets import EditorAssetRecord
from thoth_control_plane.domain.models import Actor
from thoth_control_plane.domain.studio_imports import (
    AttachImportAsset,
    ResolveStudioImportItem,
    StudioImportInventory,
    StudioSourceInspection,
    WorkflowImportItem,
    WorkflowStudioImport,
)

logger = logging.getLogger(__name__)
PROVENANCE = "workflow_import"


class WorkflowStudioUnavailable(RuntimeError):
    """A store or tool the import needs could not be used."""


class ContentSetUnavailable(LookupError):
    """The workflow has no stored Content Set."""


class ContentSetInvalid(ValueError):
    """The stored Content Set is not schema 1, or belongs to another workflow."""


class WorkflowInOtherProject(Exception):
    """The run already belongs to another project; moving it is out of scope."""


class _ItemFailed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkflowMedia(Protocol):
    def size(self, location: str) -> int: ...

    def probe_source(self, location: str) -> str: ...

    def copy(self, source: str, destination: str) -> None: ...

    def delete(self, location: str) -> None: ...


class WorkflowAssets(Protocol):
    async def find_ready_by_checksum(
        self, *, project_id: str, checksum: str
    ) -> EditorAssetRecord | None: ...

    async def register_ready(self, record: EditorAssetRecord) -> None: ...


def content_set_location(workflow_id: str) -> str:
    return f"reports/{workflow_id}/content-set.json"


class WorkflowStudioImportService:
    def __init__(
        self,
        *,
        runs: Any,
        reports: Any,
        media: WorkflowMedia,
        assets: WorkflowAssets | None,
        imports: StudioImportService,
        probe: MediaProbe,
    ) -> None:
        self._runs = runs
        self._reports = reports
        self._media = media
        self._assets = assets
        self._imports = imports
        self._probe = probe

    async def inspect(
        self, project_id: str, workflow_id: str, actor: Actor
    ) -> StudioSourceInspection:
        """Read-only: neither assigns the run nor copies anything."""
        await self._run(project_id, workflow_id, actor)
        key, source = await self._source(workflow_id)
        return await self._imports.inspect_keyed(project_id, key, source.projection)

    async def open(
        self, project_id: str, workflow_id: str, actor: Actor, idempotency_key: str
    ) -> WorkflowStudioImport:
        run = await self._run(project_id, workflow_id, actor)
        key, source = await self._source(workflow_id)
        if self._assets is None:
            raise WorkflowStudioUnavailable()
        draft = await self._imports.create_keyed(
            project_id, key, source.projection, idempotency_key
        )
        # Assigned after the draft exists: a refusal above leaves the run where it was.
        if run.project_id is None:
            if await asyncio.to_thread(self._runs.assign, workflow_id, project_id) is None:
                raise WorkflowNotFound
        inventory = await self._imports.get_inventory(project_id, draft.document_id)
        items: list[WorkflowImportItem] = []
        for entry in list(inventory.items):
            ref = source.media.get(entry.item_id)
            if ref is None:
                continue
            if entry.disposition != "unresolved":
                items.append(WorkflowImportItem(item_id=entry.item_id, outcome="decided"))
                continue
            item, inventory = await self._import_item(project_id, inventory, entry.item_id, ref)
            items.append(item)
        return WorkflowStudioImport(
            draft=draft.model_copy(update={"revision": inventory.revision}), items=items
        )

    async def _run(self, project_id: str, workflow_id: str, actor: Actor) -> Any:
        if self._runs is None:
            raise WorkflowStudioUnavailable()
        run = await asyncio.to_thread(self._runs.get, workflow_id)
        if run is None or not run.owned_by(actor):
            raise WorkflowNotFound
        if run.project_id not in (None, project_id):
            raise WorkflowInOtherProject()
        return run

    async def _source(self, workflow_id: str) -> tuple[str, WorkflowProjection]:
        """The Content Set row is the only gate: the stored run status lags Temporal."""
        if self._reports is None:
            raise WorkflowStudioUnavailable()
        try:
            content = await asyncio.to_thread(
                self._reports.get, content_set_location(workflow_id)
            )
        except Exception as error:
            raise WorkflowStudioUnavailable() from error
        if content is None:
            raise ContentSetUnavailable()
        try:
            content_set = ContentSet.model_validate_json(content)
            if content_set.workflow_id != workflow_id:
                raise ValueError("the Content Set names another workflow")
            projected = project_content_set(content_set)
        except ValueError as error:  # a pydantic ValidationError is a ValueError
            raise ContentSetInvalid() from error
        return workflow_source_key(workflow_id, hashlib.sha256(content).hexdigest()), projected

    async def _import_item(
        self,
        project_id: str,
        inventory: StudioImportInventory,
        item_id: str,
        ref: MediaRef,
    ) -> tuple[WorkflowImportItem, StudioImportInventory]:
        try:
            record, outcome = await self._asset_for(project_id, ref)
        except _ItemFailed as failed:
            return self._left(item_id, failed.code), inventory
        request = ResolveStudioImportItem(
            base_revision=inventory.revision,
            decision=AttachImportAsset(kind="attach_asset", asset_id=record.asset.asset_id),
        )
        try:
            inventory = await self._imports.resolve(
                project_id, inventory.document_id, item_id, request
            )
        except StudioImportDecisionRejected as refused:
            return self._left(item_id, refused.code), inventory
        except (EditDocumentRevisionConflict, StudioImportItemResolved):
            # Someone decided in the gate meanwhile: their decision stands.
            latest = await self._imports.get_inventory(project_id, inventory.document_id)
            return self._left(item_id, "draft_changed"), latest
        return WorkflowImportItem(item_id=item_id, outcome=outcome), inventory

    @staticmethod
    def _left(item_id: str, reason: str) -> WorkflowImportItem:
        return WorkflowImportItem(item_id=item_id, outcome="unresolved", reason=reason)

    async def _asset_for(
        self, project_id: str, ref: MediaRef
    ) -> tuple[EditorAssetRecord, Literal["reused", "copied"]]:
        assert self._assets is not None  # checked by open()
        checksum = ref.checksum.lower()  # editor assets keep lower-case hex
        try:
            found = await self._assets.find_ready_by_checksum(
                project_id=project_id, checksum=checksum
            )
        except Exception:
            raise _ItemFailed("asset_unavailable") from None
        if found is not None:
            return found, "reused"
        location = ref.location.as_posix()
        size = await self._store(self._media.size, location)
        if size != ref.bytes:
            raise _ItemFailed("media_mismatch")
        upload = UPLOAD_TYPES[ref.media_type]
        asset_id = f"asset_{uuid4().hex}"
        source = await self._store(self._media.probe_source, location)
        try:
            report = await self._probe(source)
        except EditorAssetMediaInvalid:
            raise _ItemFailed("media_invalid") from None
        except OSError as error:  # ffprobe itself is missing: an installation fault, fail loud
            logger.error("ffprobe could not run")
            raise WorkflowStudioUnavailable("ffprobe_unavailable") from error
        try:
            asset = described_asset(
                asset_id=asset_id,
                project_id=project_id,
                media_type=ref.media_type,
                kind=upload.kind,
                checksum=checksum,
                report=report,
            )
        except EditorAssetMediaInvalid:
            raise _ItemFailed("media_invalid") from None
        destination = f"uploads/{project_id}/{asset_id}{upload.suffix}"
        await self._store(self._media.copy, location, destination)
        record = EditorAssetRecord(
            asset=asset, artifact_location=destination, provenance=PROVENANCE
        )
        try:
            await self._assets.register_ready(record)
        except Exception:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._media.delete, destination)
            raise _ItemFailed("asset_unavailable") from None
        return record, "copied"

    @staticmethod
    async def _store(call: Any, *args: str) -> Any:
        """One media store call: a missing object or a store outage fails only this item."""
        try:
            return await asyncio.to_thread(call, *args)
        except LookupError:  # MediaUnavailable
            raise _ItemFailed("media_missing") from None
        except Exception:
            raise _ItemFailed("media_store_unavailable") from None
```

- [ ] **Step 4: Run them to verify they pass**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=tests/application/test_workflow_studio_imports.py'`
Expected: PASS, every test listed in Step 1.

- [ ] **Step 5: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add python/src/thoth_control_plane/application/workflow_studio_imports.py python/tests/application/test_workflow_studio_imports.py
git commit -m "feat(studio): open a workflow in Studio with its media"
```

---

### Task 6: Routes, wiring and the public contract

**Files:**
- Create: `python/src/thoth_control_plane/api/routes/workflow_studio_imports.py`
- Modify: `python/src/thoth_control_plane/api/app.py` (service after `app.state.workflow_run_store = workflow_run_store`; router after `studio_import_router`)
- Modify: `python/tests/api/test_workflows.py` (path-pair list, after the `/workflows` pairs near line 577)
- Modify: `python/openapi.json` (regenerated)
- Test: `python/tests/api/test_workflow_studio_imports.py`

**Interfaces:**
- Consumes: Task 5 service and exceptions; `IDEMPOTENCY_KEY_ADAPTER`; `current_actor`.
- Produces: `GET /api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import` → `StudioSourceInspection`; `POST` same path, header `Idempotency-Key`, no body → `201 WorkflowStudioImport`; `app.state.workflow_studio_service`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/api/test_workflow_studio_imports.py`:

```python
"""The workflow-to-Studio routes: read-only inspection, the import, replay, and each refusal."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.api.open_projects import OPEN_PROJECTS
from tests.api.test_edit_documents import MemoryEditDocumentRepository
from tests.application.test_workflow_studio_imports import (
    WF,
    AttachingImports,
    MemoryAssets,
    MemoryReports,
    MemoryRuns,
    Probe,
    content_set_bytes,
    seed_media,
    stored_run,
)
from thoth_control_plane.api import create_app
from thoth_control_plane.assembly.studio import workflow_source_key
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.media_store import build_media_store

AUTH = {"Authorization": "Bearer test-key"}
PATH = f"/api/v1/projects/project_001/workflows/{WF}/studio-import"
DEFAULT = object()


def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runs: MemoryRuns | None = None,
    reports: Any = DEFAULT,
) -> httpx.AsyncClient:
    probe = Probe()

    async def probe_media(_ffprobe: str, source: Any) -> dict[str, Any]:
        return await probe(source)

    monkeypatch.setattr("thoth_control_plane.api.app.probe_media", probe_media)
    (tmp_path / "root").mkdir(exist_ok=True)
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path / "root"
    )
    seed_media(build_media_store(settings), tmp_path)
    app = create_app(
        settings,
        None,
        MemoryEditDocumentRepository(),
        editor_asset_repository=MemoryAssets(),
        studio_import_repository=AttachingImports(),
        project_store=OPEN_PROJECTS,
        workflow_run_store=runs or MemoryRuns(stored_run()),
        report_store=MemoryReports(content_set_bytes()) if reports is DEFAULT else reports,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def code_of(response: httpx.Response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


async def test_inspection_is_read_only_and_then_lists_the_draft(tmp_path, monkeypatch) -> None:
    runs = MemoryRuns(stored_run())
    async with client(tmp_path, monkeypatch, runs=runs) as api:
        found = await api.get(PATH, headers=AUTH)
        assert found.status_code == 200
        digest = hashlib.sha256(content_set_bytes()).hexdigest()
        assert found.json()["source_key"] == workflow_source_key(WF, digest)
        assert found.json()["drafts"] == []
        assert runs.get(WF).project_id is None

        opened = await api.post(PATH, headers={**AUTH, "Idempotency-Key": "open-1"})
        listed = await api.get(PATH, headers=AUTH)

    assert [draft["document_id"] for draft in listed.json()["drafts"]] == [
        opened.json()["draft"]["document_id"]
    ]


async def test_open_assigns_the_run_imports_and_replays(tmp_path, monkeypatch) -> None:
    runs = MemoryRuns(stored_run())
    async with client(tmp_path, monkeypatch, runs=runs) as api:
        headers = {**AUTH, "Idempotency-Key": "open-1"}
        opened = await api.post(PATH, headers=headers)
        replay = await api.post(PATH, headers=headers)

    assert opened.status_code == 201
    assert [(i["item_id"], i["outcome"]) for i in opened.json()["items"]] == [
        ("main_000", "copied"),
        ("footage_000", "copied"),
        ("footage_001", "copied"),
    ]
    assert runs.get(WF).project_id == "project_001"
    assert replay.status_code == 201
    assert replay.json()["draft"]["document_id"] == opened.json()["draft"]["document_id"]
    assert {i["outcome"] for i in replay.json()["items"]} == {"decided"}
    assert "reports/" not in opened.text and "uploads/" not in opened.text


CASES: list[tuple[Callable[[], Any], Callable[[], Any], int, str | None]] = [
    (lambda: MemoryRuns(), lambda: MemoryReports(content_set_bytes()), 404, None),
    (lambda: MemoryRuns(stored_run(actor_id="ws_other")), lambda: DEFAULT, 404, None),
    (
        lambda: MemoryRuns(stored_run(project_id="project_002")),
        lambda: DEFAULT,
        409,
        "workflow_in_other_project",
    ),
    (lambda: None, lambda: MemoryReports(None), 409, "content_set_unavailable"),
    (lambda: None, lambda: MemoryReports(b"{}"), 409, "content_set_invalid"),
    (lambda: None, lambda: None, 503, None),
]


@pytest.mark.parametrize(("runs", "reports", "status", "code"), CASES)
async def test_every_refusal_has_its_status_and_code(
    tmp_path, monkeypatch, runs, reports, status, code
) -> None:
    async with client(tmp_path, monkeypatch, runs=runs(), reports=reports()) as api:
        answers = [
            await api.get(PATH, headers=AUTH),
            await api.post(PATH, headers={**AUTH, "Idempotency-Key": "k-1"}),
        ]
    for answer in answers:
        assert (answer.status_code, code_of(answer)) == (status, code)


async def test_the_idempotency_key_is_required_and_checked(tmp_path, monkeypatch) -> None:
    async with client(tmp_path, monkeypatch) as api:
        missing = await api.post(PATH, headers=AUTH)
        unsafe = await api.post(PATH, headers={**AUTH, "Idempotency-Key": "not a key"})
    assert missing.status_code == 422
    assert (unsafe.status_code, code_of(unsafe)) == (422, "invalid_idempotency_key")
    assert "not a key" not in unsafe.text


async def test_the_routes_need_a_caller(tmp_path, monkeypatch) -> None:
    async with client(tmp_path, monkeypatch) as api:
        assert (await api.get(PATH)).status_code == 403
        assert (await api.post(PATH, headers={"Idempotency-Key": "k-1"})).status_code == 403
```

In `python/tests/api/test_workflows.py`, add after `("/api/v1/projects/{project_id}/workflows", "post"),`:

```python
        ("/api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import", "get"),
        ("/api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import", "post"),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T="tests/api/test_workflow_studio_imports.py tests/api/test_workflows.py"'`
Expected: FAIL — the new routes answer 404 (`Not Found`) and the path-pair test reports the two
missing pairs.

- [ ] **Step 3: Implement**

Create `python/src/thoth_control_plane/api/routes/workflow_studio_imports.py`:

```python
"""Open a finished workflow in Studio (spec 2026-10-20 workflow to Studio, section 3.1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application.edit_documents import (
    IDEMPOTENCY_KEY_ADAPTER,
    EditorUnavailable,
)
from thoth_control_plane.application.ports import StudioImportConflict
from thoth_control_plane.application.workflow_studio_imports import (
    ContentSetInvalid,
    ContentSetUnavailable,
    WorkflowInOtherProject,
    WorkflowStudioImportService,
    WorkflowStudioUnavailable,
)
from thoth_control_plane.application.workflows import WorkflowNotFound
from thoth_control_plane.domain.models import Actor
from thoth_control_plane.domain.studio_imports import StudioSourceInspection, WorkflowStudioImport

router = APIRouter()
PATH = "/projects/{project_id}/workflows/{workflow_id}/studio-import"
#: Each refusal and its fixed code, in the `{detail: {code}}` shape the Studio import routes use.
REFUSALS: tuple[tuple[type[Exception], int, str | None], ...] = (
    (WorkflowNotFound, status.HTTP_404_NOT_FOUND, None),
    (WorkflowInOtherProject, status.HTTP_409_CONFLICT, "workflow_in_other_project"),
    (ContentSetUnavailable, status.HTTP_409_CONFLICT, "content_set_unavailable"),
    (ContentSetInvalid, status.HTTP_409_CONFLICT, "content_set_invalid"),
    (StudioImportConflict, status.HTTP_409_CONFLICT, "studio_import_conflict"),
    (WorkflowStudioUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE, None),
    (EditorUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE, None),
)


def get_workflow_studio_service(request: Request) -> WorkflowStudioImportService:
    return request.app.state.workflow_studio_service


def _refused(error: Exception) -> HTTPException | None:
    for kind, code_status, code in REFUSALS:
        if isinstance(error, kind):
            return HTTPException(status_code=code_status, detail={"code": code} if code else None)
    return None


@router.get(PATH, response_model=StudioSourceInspection)
async def inspect_workflow_studio_import(
    project_id: str,
    workflow_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowStudioImportService, Depends(get_workflow_studio_service)],
) -> StudioSourceInspection:
    """Read-only: what opening this run would import, and the drafts already made from it."""
    try:
        return await service.inspect(project_id, workflow_id, actor)
    except Exception as error:
        refusal = _refused(error)
        if refusal is None:
            raise
        raise refusal from error


@router.post(PATH, response_model=WorkflowStudioImport, status_code=status.HTTP_201_CREATED)
async def open_workflow_in_studio(
    project_id: str,
    workflow_id: str,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowStudioImportService, Depends(get_workflow_studio_service)],
) -> WorkflowStudioImport:
    """Create (or replay) one draft from the run and bring its media in; a replay finishes the
    items an earlier attempt left unresolved."""
    try:
        IDEMPOTENCY_KEY_ADAPTER.validate_python(idempotency_key)
    except ValidationError as error:
        # The key itself is never echoed back: it may carry caller-controlled text.
        raise HTTPException(status_code=422, detail={"code": "invalid_idempotency_key"}) from error
    try:
        return await service.open(project_id, workflow_id, actor, idempotency_key)
    except Exception as error:
        refusal = _refused(error)
        if refusal is None:
            raise
        raise refusal from error
```

In `api/app.py`:
- import `from thoth_control_plane.api.routes.workflow_studio_imports import router as workflow_studio_router`
  next to the other route imports, and
  `from thoth_control_plane.application.workflow_studio_imports import WorkflowStudioImportService`
  next to `StudioImportService`;
- right after `app.state.workflow_run_store = workflow_run_store`:

```python
    app.state.workflow_studio_service = WorkflowStudioImportService(
        runs=workflow_run_store,
        reports=report_store,
        media=media,
        assets=editor_asset_repository,
        imports=app.state.studio_import_service,
        probe=functools.partial(probe_media, settings.THOTH_FFPROBE),
    )
```

- after `app.include_router(studio_import_router, prefix="/api/v1")`:
  `app.include_router(workflow_studio_router, prefix="/api/v1")`.

- [ ] **Step 4: Run them to verify they pass, then regenerate the contract**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T="tests/api/test_workflow_studio_imports.py tests/api/test_workflows.py tests/api/test_route_isolation.py tests/api/test_openapi_contract.py tests/api/test_studio_imports.py"'`
Expected: PASS (route isolation proves the project guard covers both routes).

Regenerate `python/openapi.json` with LF endings:

```bash
cd /d/thoth-tmp/wt-studio/python && uv run python -c "import json; from pathlib import Path; from thoth_control_plane.api import create_app; from thoth_control_plane.config import Settings; d = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY='openapi-export')).openapi(); Path('openapi.json').write_bytes((json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode())"
git diff --stat -- openapi.json
```
Expected: `openapi.json` changes, adding the two operations and the `WorkflowImportItem` and
`WorkflowStudioImport` schemas; `git diff -- openapi.json | rg -c '^\+.*\r'` prints `0`.

- [ ] **Step 5: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add python/src/thoth_control_plane/api/routes/workflow_studio_imports.py python/src/thoth_control_plane/api/app.py python/tests/api/test_workflow_studio_imports.py python/tests/api/test_workflows.py python/openapi.json
git commit -m "feat(api): open a workflow in Studio over two routes"
```

---

### Task 7: The import on a real PostgreSQL

**Files:**
- Test: `python/tests/infrastructure/test_workflow_studio_postgres.py`

**Interfaces:**
- Consumes: Task 5 service and test helpers; `PostgresStudioImportRepository`, `PostgresEditorAssetRepository`, `ReportStore`, `WorkflowRunStore`, `ProjectStore`, `apply_editor_migrations`.

- [ ] **Step 1: Write the test**

Create `python/tests/infrastructure/test_workflow_studio_postgres.py`:

```python
"""Opening a workflow in Studio on a disposable PostgreSQL: the real report row, draft,
attach and asset tables, with a local media store and a fake probe."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from tests.application.test_workflow_studio_imports import (
    ACTOR,
    WF,
    Probe,
    content_set_bytes,
    seed_media,
    stored_run,
)
from thoth_control_plane.application.studio_imports import StudioImportService
from thoth_control_plane.application.workflow_studio_imports import (
    WorkflowStudioImportService,
    content_set_location,
)
from thoth_control_plane.infrastructure.editor_asset_repository import (
    PostgresEditorAssetRepository,
)
from thoth_control_plane.infrastructure.media_store import LocalMediaStore
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.studio_import_repository import (
    PostgresStudioImportRepository,
)
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


@pytest.fixture
def database() -> str:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    return DATABASE_URL


async def test_a_workflow_opens_in_studio_on_the_real_tables(database: str, tmp_path: Path) -> None:
    project = ProjectStore.connect(database).create("Studio", "ws_bootstrap").project_id
    reports = ReportStore.connect(database)
    reports.put(content_set_location(WF), "content_set", content_set_bytes())
    runs = WorkflowRunStore.connect(database)
    runs.insert_missing(stored_run())
    media = LocalMediaStore(tmp_path / "store")
    seed_media(media, tmp_path)
    assets = PostgresEditorAssetRepository(database)
    imports = StudioImportService(PostgresStudioImportRepository(database))
    service = WorkflowStudioImportService(
        runs=runs, reports=reports, media=media, assets=assets, imports=imports, probe=Probe()
    )

    opened = await service.open(project, WF, ACTOR, "open-1")

    assert {(item.item_id, item.outcome) for item in opened.items} == {
        ("main_000", "copied"),
        ("footage_000", "copied"),
        ("footage_001", "copied"),
    }
    inventory = await imports.get_inventory(project, opened.draft.document_id)
    attached = {i.item_id: i.asset_id for i in inventory.items if i.disposition == "attached"}
    assert set(attached) == {"main_000", "footage_000", "footage_001"}
    record = await assets.get_ready_record(project_id=project, asset_id=attached["main_000"])
    assert record is not None and record.provenance == "workflow_import"
    assert record.artifact_location == f"uploads/{project}/{attached['main_000']}.mp4"
    assert runs.get(WF).project_id == project

    second = await service.open(project, WF, ACTOR, "open-2")

    assert {item.outcome for item in second.items} == {"reused"}
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM editor_assets").fetchone() == (3,)
```

- [ ] **Step 2: Run it**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && bash scripts/dev/pytest-postgres.sh tests/infrastructure/test_workflow_studio_postgres.py'`
Expected: PASS, 1 passed, no skip. This test exercises code already built in Tasks 1–6, so it is
not expected to go red first; if it fails, the failure is a real defect in those tasks (for
example a column or CHECK constraint the memory fakes do not model) — fix it there with its own
failing unit test, and ledger a ruling.

If `ProjectStore.create` refuses because `ws_bootstrap` is absent, insert it first exactly as
`tests/infrastructure/test_billing_store_postgres.py` inserts workspaces, and ledger it.

- [ ] **Step 3: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add python/tests/infrastructure/test_workflow_studio_postgres.py
git commit -m "test(studio): open a workflow in Studio on a real PostgreSQL"
```

---

### Task 8: Dashboard — Open in Studio

**Files:**
- Modify: `dashboard/src/api/generated/control-plane.ts` (regenerated)
- Modify: `dashboard/src/api/control-plane.ts` (type, `ControlPlaneClient` members, implementation)
- Create: `dashboard/src/features/workflows/OpenInStudio.tsx`
- Modify: `dashboard/src/features/workflows/WorkflowDetailPage.tsx`
- Modify: `dashboard/src/App.tsx` (`WorkflowDetailRoute`, its `<Route>`, `StudioDocumentRoute`)
- Test: `dashboard/src/api/control-plane.test.ts`, `dashboard/src/features/workflows/OpenInStudio.test.tsx`

**Interfaces:**
- Consumes: Task 6 routes and `openapi.json`.
- Produces: `WorkflowStudioImport` type; `inspectWorkflowStudioImport(projectId, workflowId): Promise<StudioSourceInspection>`; `openWorkflowInStudio(projectId, workflowId, idempotencyKey): Promise<WorkflowStudioImport>`; `OpenInStudio` component; `WorkflowDetailPage` props `projectId?: string | null`, `onOpenStudio?: (projectId, documentId, resolve) => void`.

- [ ] **Step 1: Regenerate the types**

Run: `cd /d/thoth-tmp/wt-studio/dashboard && bun run generate:control-plane-types && git diff --stat src/api/generated/control-plane.ts`
Expected: the file gains `WorkflowStudioImport`, `WorkflowImportItem` and the two operations.

- [ ] **Step 2: Write the failing tests**

Append to `dashboard/src/api/control-plane.test.ts`:

```ts
test("workflow import routes encode both ids", async () => {
  const calls: RecordedCall[] = [];
  const client = importClient(calls, ok({}));

  await client.inspectWorkflowStudioImport("project / 1", "wf / 1");
  await client.openWorkflowInStudio("project / 1", "wf / 1", "open_001");

  const path = "/api/v1/projects/project%20%2F%201/workflows/wf%20%2F%201/studio-import";
  expect(calls.map((call) => [call.url, call.init?.method ?? "GET"])).toEqual([
    [path, "GET"],
    [path, "POST"],
  ]);
  expect(new Headers(calls[1].init?.headers).get("Idempotency-Key")).toBe("open_001");
});
```

Create `dashboard/src/features/workflows/OpenInStudio.test.tsx`:

```tsx
/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  StudioImportRequestError,
  type StudioSourceInspection,
  type WorkflowStudioImport,
  type WorkflowSummary,
} from "@/api/control-plane";

import { OpenInStudio } from "./OpenInStudio";

afterEach(cleanup);

const KEY = "a".repeat(64);
const done = (artifacts = [{ artifact_id: "content_set", kind: "content_set" }], status = "succeeded") =>
  ({ workflow_id: "wf_1", status, artifacts }) as unknown as WorkflowSummary;
const inspection = (extra: Partial<StudioSourceInspection> = {}): StudioSourceInspection => ({
  project_id: "p1",
  source_key: KEY,
  items: [],
  drafts: [],
  more_drafts: false,
  ...extra,
});
const opened = (outcome: "copied" | "unresolved" = "copied"): WorkflowStudioImport => ({
  draft: { document_id: "edoc_1", source_key: KEY, revision: 2, created_at: "2026-10-20T00:00:00Z" },
  items: [{ item_id: "main_000", outcome, reason: outcome === "unresolved" ? "media_missing" : null }],
});

function client(found = inspection(), result = opened()) {
  return {
    inspectWorkflowStudioImport: mock(async () => found),
    openWorkflowInStudio: mock(async () => result),
  };
}

const open = () => userEvent.setup().click(screen.getByRole("button", { name: "Open in Studio" }));

test("the button shows only for a finished run with a Content Set", () => {
  const props = { client: client(), projectId: "p1", workflowId: "wf_1", onOpen: () => {} };
  const { rerender } = render(<OpenInStudio {...props} summary={null} />);
  expect(screen.queryByRole("button", { name: "Open in Studio" })).toBeNull();
  rerender(<OpenInStudio {...props} summary={done([])} />);
  expect(screen.queryByRole("button", { name: "Open in Studio" })).toBeNull();
  rerender(<OpenInStudio {...props} summary={done(undefined, "running")} />);
  expect(screen.queryByRole("button", { name: "Open in Studio" })).toBeNull();
  rerender(<OpenInStudio {...props} summary={done()} />);
  expect(screen.getByRole("button", { name: "Open in Studio" })).toBeDefined();
});

test("without an active project the button waits for one", () => {
  render(<OpenInStudio client={client()} projectId={null} workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  expect((screen.getByRole("button", { name: "Open in Studio" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("Choose a project first.")).toBeDefined();
});

test("a first open imports straight away and opens the draft", async () => {
  const c = client();
  const onOpen = mock(() => {});
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", false));
  expect(c.openWorkflowInStudio).toHaveBeenCalledTimes(1);
});

test("an item left unresolved opens the draft with the gate", async () => {
  const onOpen = mock(() => {});
  render(<OpenInStudio client={client(inspection(), opened("unresolved"))} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", true));
});

test("an earlier draft can be resumed instead of imported again", async () => {
  const drafts = [{ document_id: "edoc_old", source_key: KEY, revision: 2, created_at: "2026-10-19T00:00:00Z" }];
  const c = client(inspection({ drafts }));
  const onOpen = mock(() => {});
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await userEvent.setup().click(await screen.findByRole("button", { name: /Resume draft/ }));
  expect(onOpen).toHaveBeenCalledWith("p1", "edoc_old", false);
  expect(c.openWorkflowInStudio).not.toHaveBeenCalled();
  await userEvent.setup().click(screen.getByRole("button", { name: "Create new draft" }));
  await waitFor(() => expect(c.openWorkflowInStudio).toHaveBeenCalledTimes(1));
});

test("what Studio leaves out is listed before the import", async () => {
  const items = [
    {
      item_id: "unsupported_000",
      role: "main",
      order: 0,
      label: "main.profile_card",
      platform: null,
      media_kind: "none",
      scene_id: null,
      reason: "Cards wait for Stage 5c",
      disposition: "unresolved",
    },
  ] as StudioSourceInspection["items"];
  const c = client(inspection({ items }));
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  await open();
  expect(await screen.findByText("main.profile_card: Cards wait for Stage 5c")).toBeDefined();
  expect(c.openWorkflowInStudio).not.toHaveBeenCalled();
});

test("each refusal has its own words", async () => {
  const cases: [number | null, string | null, string][] = [
    [409, "workflow_in_other_project", "This run belongs to another project. Switch to that project to open it."],
    [409, "content_set_unavailable", "This run has no Content Set to open yet."],
    [409, "content_set_invalid", "Studio cannot read this run's Content Set."],
    [404, null, "This run was not found in this workspace."],
    [503, null, "Studio is not available right now. Try again later."],
    [null, null, "Offline — reconnect and try again."],
  ];
  for (const [status, code, text] of cases) {
    const c = {
      inspectWorkflowStudioImport: mock(async () => {
        throw new StudioImportRequestError(status, code);
      }),
      openWorkflowInStudio: mock(async () => opened()),
    };
    render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
    await open();
    expect(await screen.findByText(text)).toBeDefined();
    cleanup();
  }
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd /d/thoth-tmp/wt-studio/dashboard && bun test src/features/workflows/OpenInStudio.test.tsx src/api/control-plane.test.ts`
Expected: FAIL — `Cannot find module './OpenInStudio'` and
`client.inspectWorkflowStudioImport is not a function`.

- [ ] **Step 4: Implement**

`dashboard/src/api/control-plane.ts`:
- after `export type StudioImportInventory = …`:
  `export type WorkflowStudioImport = components["schemas"]["WorkflowStudioImport"];`
- in `ControlPlaneClient`, after `listStudioImportDrafts`:

```ts
  inspectWorkflowStudioImport: (projectId: string, workflowId: string) => Promise<StudioSourceInspection>;
  openWorkflowInStudio: (projectId: string, workflowId: string, idempotencyKey: string) => Promise<WorkflowStudioImport>;
```

- after `const importPost = …`:

```ts
  const workflowImportPath = (projectId: string, workflowId: string) =>
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflowId)}/studio-import`;
```

- in the returned object, after `listStudioImportDrafts`:

```ts
    inspectWorkflowStudioImport: (projectId, workflowId) => importCall(workflowImportPath(projectId, workflowId)),
    openWorkflowInStudio: (projectId, workflowId, idempotencyKey) =>
      importCall(workflowImportPath(projectId, workflowId), {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
      }),
```

Create `dashboard/src/features/workflows/OpenInStudio.tsx`:

```tsx
import { useState } from "react";

import {
  StudioImportRequestError,
  type ControlPlaneClient,
  type StudioSourceInspection,
  type WorkflowSummary,
} from "@/api/control-plane";
import { Button } from "@/components/ui/button";

export type OpenInStudioClient = Pick<ControlPlaneClient, "inspectWorkflowStudioImport" | "openWorkflowInStudio">;

type Props = {
  client: OpenInStudioClient;
  projectId: string | null;
  workflowId: string;
  summary: WorkflowSummary | null;
  /** `resolve` is true when an item still waits for a decision in the import gate. */
  onOpen: (projectId: string, documentId: string, resolve: boolean) => void;
};

// Fixed words per known refusal; the server's own text never reaches the page.
const MESSAGES: Record<string, string> = {
  content_set_unavailable: "This run has no Content Set to open yet.",
  content_set_invalid: "Studio cannot read this run's Content Set.",
  workflow_in_other_project: "This run belongs to another project. Switch to that project to open it.",
};
const FALLBACK = "Studio could not open this run. Try again.";

function failure(error: unknown): string {
  if (!(error instanceof StudioImportRequestError)) return FALLBACK;
  if (error.status === null) return "Offline — reconnect and try again.";
  if (error.status === 404) return "This run was not found in this workspace.";
  if (error.status === 503) return "Studio is not available right now. Try again later.";
  return (error.code && MESSAGES[error.code]) || FALLBACK;
}

// Inventory entries with no media and a reason are the fields Studio leaves out.
const leftOut = (found: StudioSourceInspection) => found.items.filter((item) => item.media_kind === "none" && item.reason);

/** "Open in Studio" for a finished run: import its Content Set, or resume a draft made from it. */
export function OpenInStudio({ client, projectId, workflowId, summary, onOpen }: Props) {
  const [inspection, setInspection] = useState<StudioSourceInspection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (summary?.status !== "succeeded" || !summary.artifacts?.some((artifact) => artifact.kind === "content_set")) {
    return null;
  }

  const attempt = async (step: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await step();
    } catch (caught) {
      setError(failure(caught));
    } finally {
      setBusy(false);
    }
  };
  // A fresh key per Create: a deliberate second draft must not replay the first.
  const create = async (project: string) => {
    const result = await client.openWorkflowInStudio(project, workflowId, crypto.randomUUID());
    onOpen(project, result.draft.document_id, result.items.some((item) => item.outcome === "unresolved"));
  };
  const start = (project: string) =>
    attempt(async () => {
      const found = await client.inspectWorkflowStudioImport(project, workflowId);
      if (found.drafts.length || leftOut(found).length) setInspection(found);
      else await create(project);
    });

  return (
    <section className="open-in-studio" aria-label="Open in Studio">
      <Button disabled={!projectId || busy} onClick={() => projectId && void start(projectId)}>
        {busy ? "Importing media…" : "Open in Studio"}
      </Button>
      {!projectId && <p className="text-sm text-muted-foreground">Choose a project first.</p>}
      {inspection && projectId && (
        <div className="open-in-studio-choice">
          {leftOut(inspection).length > 0 && (
            <>
              <p className="text-sm">Studio will not include:</p>
              <ul className="text-sm">
                {leftOut(inspection).map((item) => (
                  <li key={item.item_id}>{`${item.label}: ${item.reason}`}</li>
                ))}
              </ul>
            </>
          )}
          {inspection.drafts.map((draft) => (
            <Button key={draft.document_id} variant="outline" disabled={busy} onClick={() => onOpen(projectId, draft.document_id, false)}>
              {`Resume draft from ${new Date(draft.created_at).toLocaleString()}`}
            </Button>
          ))}
          <Button disabled={busy} onClick={() => void attempt(() => create(projectId))}>Create new draft</Button>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
```

Replace `dashboard/src/features/workflows/WorkflowDetailPage.tsx`:

```tsx
import { useCallback, useState } from "react";

import type { ControlPlaneClient, WorkflowSummary } from "@/api/control-plane";
import { WorkflowMonitor } from "@/components/WorkflowMonitor";

import { OpenInStudio, type OpenInStudioClient } from "./OpenInStudio";

type DetailClient = Pick<
  ControlPlaneClient,
  "streamWorkflow" | "cancelWorkflow" | "retryWorkflow" | "approveWorkflow" | "downloadWorkflowArtifact"
> &
  OpenInStudioClient;

/** One workflow by URL: its monitor, decisions, downloadable results, and the way into Studio. */
export function WorkflowDetailPage({
  client,
  workflowId,
  projectId = null,
  onOpenStudio = () => {},
}: {
  client: DetailClient;
  workflowId: string;
  projectId?: string | null;
  onOpenStudio?: (projectId: string, documentId: string, resolve: boolean) => void;
}) {
  const [summary, setSummary] = useState<WorkflowSummary | null>(null);
  // Stable, so the monitor's stream is not reopened on every snapshot.
  const onSnapshot = useCallback((value: WorkflowSummary) => setSummary(value), []);
  return (
    <div className="dashboard-workflows">
      <OpenInStudio client={client} projectId={projectId} workflowId={workflowId} summary={summary} onOpen={onOpenStudio} />
      <WorkflowMonitor workflowId={workflowId} client={client} onSnapshot={onSnapshot} />
    </div>
  );
}
```

`dashboard/src/App.tsx`:
- add `useSearchParams` to the `react-router` import;
- route: `<Route path="/workflows/:workflowId" element={<WorkflowDetailRoute projectId={projectId} />} />`;
- replace `WorkflowDetailRoute`:

```tsx
function WorkflowDetailRoute({ projectId }: { projectId: string | null }) {
  const { workflowId = "" } = useParams();
  const navigate = useNavigate();
  return (
    <WorkflowDetailPage
      client={controlPlaneClient}
      workflowId={workflowId}
      projectId={projectId}
      onOpenStudio={(project, document, resolve) =>
        navigate(`/studio/${encodeURIComponent(project)}/${encodeURIComponent(document)}${resolve ? "?resolve=1" : ""}`)
      }
    />
  );
}
```

- in `StudioDocumentRoute`, replace `const [resolving, setResolving] = useState(false);` with:

```tsx
  const [searchParams] = useSearchParams();
  // `?resolve=1`: a workflow import left an item unresolved, so the gate opens with the draft.
  const [resolving, setResolving] = useState(() => searchParams.get("resolve") === "1");
```

If `useActiveProject()` returns a type other than `string | null`, match `WorkflowDetailRoute`'s
prop type to it and ledger the change.

- [ ] **Step 5: Run them to verify they pass**

Run: `cd /d/thoth-tmp/wt-studio/dashboard && bun test src/features/workflows src/api/control-plane.test.ts && bunx tsc --noEmit -p tsconfig.app.json && bun run build`
Expected: tests PASS, `tsc` prints nothing, the build succeeds.

Run the whole dashboard suite: `cd /d/thoth-tmp/wt-studio/dashboard && bun test 2>&1 | tail -5`
Expected: 0 fail.

- [ ] **Step 6: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add dashboard/src/api/generated/control-plane.ts dashboard/src/api/control-plane.ts dashboard/src/api/control-plane.test.ts dashboard/src/features/workflows/OpenInStudio.tsx dashboard/src/features/workflows/OpenInStudio.test.tsx dashboard/src/features/workflows/WorkflowDetailPage.tsx dashboard/src/App.tsx
git commit -m "feat(dashboard): open a finished workflow in Studio"
```

---

### Task 9: Smoke — a workflow opens in Studio on the real stack

**Files:**
- Modify: `docker/test-renderer-offline.sh` (driver function, `COMMANDS`, one verdict block)
- Modify: `python/tests/deployment/test_container_contract.py` (`required` set in `test_renderer_smoke_proves_the_properties_a_render_stack_must_hold`)

**Interfaces:**
- Consumes: Task 6 POST route; the driver's `call`, `ensure_project`, `checksum_of`, `STORE`, `ASSET_FILE`, `DATABASE_URL`, `PROJECT_ID`.

- [ ] **Step 1: Write the failing contract test**

Add `"workflow_opens_in_studio=true",` to the `required` set in
`test_renderer_smoke_proves_the_properties_a_render_stack_must_hold`.

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test T=tests/deployment/test_container_contract.py'`
Expected: FAIL on that test (the verdict is not in the script).

- [ ] **Step 2: Add the driver command**

In the embedded Python driver, before `COMMANDS = {`:

```python
def studio_import():
    """Open a finished workflow in Studio (spec 2026-10-20 workflow to Studio): the API probes
    the run's main video straight from MinIO, copies it into the project, attaches it, and a
    replay of the same key copies nothing again."""
    from thoth_control_plane.assembly.models import ContentSet
    from thoth_control_plane.infrastructure.report_store import ReportStore

    ensure_project()
    workflow_id = "wf_smoke_studio"
    media = f"reports/{workflow_id}/media/main.mp4"
    STORE.put_file(media, ASSET_FILE)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "INSERT INTO workflow_runs (workflow_id, project_id, actor_type, actor_id,"
            " display_url, platform, status, created_at, updated_at)"
            " VALUES (%s, NULL, 'user', 'owner', 'https://example.test/v/1', 'tiktok',"
            " 'succeeded', now(), now()) ON CONFLICT DO NOTHING",
            (workflow_id,),
        )
    content_set = ContentSet.model_validate(
        {
            "workflow_id": workflow_id,
            "attribution_verdict": "none",
            "main": {
                "source": "input",
                "url": "https://example.test/v/1",
                "platform": "tiktok",
                "owner_handle": "smoke",
                "kind": "video",
                "video": {
                    "location": media,
                    "media_type": "video/mp4",
                    "checksum": checksum_of(ASSET_FILE),
                    "bytes": ASSET_FILE.stat().st_size,
                    "duration_seconds": 4.0,
                },
                "ocr": {
                    "analyzed_at": "2026-10-20T00:00:00Z",
                    "requested_frames": 12,
                    "valid_frames": 12,
                    "outcome": "clean",
                    "trim_start": 0.0,
                    "mute_audio": False,
                },
            },
            "figures_status": "none",
        }
    )
    ReportStore.connect(DATABASE_URL).put(
        f"reports/{workflow_id}/content-set.json",
        "content_set",
        content_set.model_dump_json(indent=2).encode("utf-8"),
    )
    path = f"/projects/{PROJECT_ID}/workflows/{workflow_id}/studio-import"
    status, opened = call("POST", path, idempotency_key="smoke-studio-1")
    if status != 201 or [(i["item_id"], i["outcome"]) for i in opened["items"]] != [
        ("main_000", "copied")
    ]:
        raise SystemExit(f"open returned {status}")
    document_id = opened["draft"]["document_id"]
    status, inventory = call("GET", f"/projects/{PROJECT_ID}/studio-imports/documents/{document_id}")
    main = next(item for item in inventory["items"] if item["item_id"] == "main_000")
    if status != 200 or main["disposition"] != "attached":
        raise SystemExit("the main video is not attached")
    if STORE.size(f"uploads/{PROJECT_ID}/{main['asset_id']}.mp4") != ASSET_FILE.stat().st_size:
        raise SystemExit("the copy is not in the project's uploads")
    status, again = call("POST", path, idempotency_key="smoke-studio-1")
    if (
        status != 201
        or again["draft"]["document_id"] != document_id
        or [i["outcome"] for i in again["items"]] != ["decided"]
    ):
        raise SystemExit("a replay did not return the same draft")
    print("ok")
```

Add `"studio_import": studio_import,` to `COMMANDS`.

Read `call` first: if it raises on a non-2xx status instead of returning it, or does not accept
a POST without a body, adapt only the three call sites above and ledger it.

- [ ] **Step 3: Add the verdict**

Right after `echo edit_documents_listed=true`:

```bash
# --- a finished workflow opens in Studio with its media (spec 2026-10-20) ----------
driver studio_import >/dev/null || fail workflow_opens_in_studio
echo workflow_opens_in_studio=true
```

- [ ] **Step 4: Verify**

Run: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && bash -n docker/test-renderer-offline.sh && make test T=tests/deployment/test_container_contract.py'`
Expected: no syntax error; PASS.

Run: `cd /d/thoth-tmp/wt-studio && rg -c "tiktok.com" docker/test-renderer-offline.sh; file docker/test-renderer-offline.sh`
Expected: no `tiktok.com` match; the script still has LF line endings (no "CRLF" in `file`).

The full smoke runs in CI ("Non-live stack smoke") after the operator authorizes the push; it
is the evidence that ffprobe reads a presigned MinIO URL inside the API image.

- [ ] **Step 5: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add docker/test-renderer-offline.sh python/tests/deployment/test_container_contract.py
git commit -m "test(smoke): a finished workflow opens in Studio"
```

---

### Task 10: Documentation and the whole-branch checks

**Files:**
- Modify: `docs/python-control-plane.md` (v1 HTTP contract table; media configuration line)
- Modify: `docs/ROADMAP.md` (row 2)
- Modify: `CHANGELOG.md` (new top entry)

- [ ] **Step 1: Run every check**

```bash
wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make lint && make test 2>&1 | tail -5'
wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && make test-postgres 2>&1 | tail -3 && bash scripts/dev/pytest-postgres.sh tests/infrastructure/test_workflow_studio_postgres.py 2>&1 | tail -3'
wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-studio && bash scripts/dev/pytest-minio.sh 2>&1 | tail -3'
cd /d/thoth-tmp/wt-studio/dashboard && bun test 2>&1 | tail -3 && bunx tsc --noEmit -p tsconfig.app.json && bun run build 2>&1 | tail -2
```
Expected: ruff clean; Python 0 failed; Postgres and MinIO 0 failed, 0 skipped; dashboard 0 fail,
`tsc` silent, build succeeds. Keep the exact pass counts for the changelog. No Rust file changes,
so `build_cuda.bat` is not part of this branch's verification; say so in the changelog.

- [ ] **Step 2: Write the docs**

`docs/python-control-plane.md`, in the "v1 HTTP contract" table, after the artifacts row:

```markdown
| `GET /api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import` | Read-only: what opening the run in Studio would import, what Studio leaves out, and the drafts already made from it. |
| `POST /api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import` | With `Idempotency-Key`: create (or replay) a Studio draft from the run's Content Set, assigning an unassigned run to the project. Each media item is reused by checksum or probed in place and copied server side into `uploads/<project>/`; an item that fails stays unresolved, and a replay of the key retries it. Refusals: `409 content_set_unavailable`, `409 content_set_invalid`, `409 workflow_in_other_project`, `404`, `503`. |
```

Find the media store settings (`rg -n "THOTH_MEDIA_S3_SECURE" docs/`) and add beside them:
"`THOTH_MEDIA_S3_REGION` (default `us-east-1`): the region the API signs probe URLs with; it
must match MinIO's region."

`docs/ROADMAP.md`, row 2's item cell becomes:
`~~Workflow to Studio with media (UI phase 2)~~ Built 2026-10-21 on \`feat/workflow-to-studio\`; push, merge and deploy pending`.

`CHANGELOG.md`, a new entry directly under the intro paragraph:

```markdown
## 2026-10-21 - Workflow to Studio with media (roadmap priority 2), built on `feat/workflow-to-studio`

A finished workflow now opens in Studio from its detail page. The API projects the run's Content
Set (the `workflow_reports` row) into a Studio draft under a per-workflow source key, reuses any
project asset with the same checksum, probes the rest straight from MinIO through a five-minute
signed URL, copies them server side into `uploads/<project>/`, registers them
(`provenance = workflow_import`) and attaches them. A failed item stays unresolved in the import
gate; replaying the same `Idempotency-Key` finishes it. Copies count as `media_stored`; the import
consumes no billing allowance. New setting `THOTH_MEDIA_S3_REGION` (default `us-east-1`).

**Verification:** <the exact counts from Step 1: Python passed/skipped, Postgres, MinIO, dashboard>.
No Rust change, so `build_cuda.bat` was not run.

**Next steps:**
- Operator gates, each needing its own authorization: push and PR, CI (including the stack smoke
  verdict `workflow_opens_in_studio=true`), merge, deploy.
- Roadmap item 4 (Stage 5c: post cards, carousel photos, creator profile) is unblocked by this.
- Deferred until every feature is finished: meter unit prices, the quota/reserve check, billing
  go-live, the second-account test.
```

Replace the angle-bracket placeholder with the real counts before committing.

- [ ] **Step 3: Commit**

```bash
cd /d/thoth-tmp/wt-studio
git add docs/python-control-plane.md docs/ROADMAP.md CHANGELOG.md
git commit -m "docs(studio): record workflow to Studio in the changelog"
```

- [ ] **Step 4: Update the checkpoint**

Append the completion record and the same next steps to
`.superpowers/sdd/2026-10-19-workflow-to-studio/progress.md` (gitignored; never staged).
