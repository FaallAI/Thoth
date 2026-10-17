# Render and Editor Media in Object Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No service shares the artifact volume any more. Editor uploads, render bundles, render outputs, and the renderer's inputs and outputs go through the media store or the control plane's internal HTTP API, and the volume's leftovers are archived in the bucket.

**Architecture:**
- **Store-backed adapter.** `LocalArtifactRoot` keeps its role as the one render/editor storage adapter, but every persistent object now goes through an injected `MediaStore`. Temporary files (uploads in flight, outputs being received) stay in the container's local root.
- **Renderer transport.** The renderer downloads assets and uploads its output through two new internal routes with the credential it already holds.
- **Downloads.** Download and preview stream from the store through one shared `Range` helper.

**Tech Stack:** Python 3.12, FastAPI, minio 7.2.x, Bun/TypeScript renderer, docker compose, pytest, bun test.

**Spec:** `docs/superpowers/specs/2026-10-17-render-object-storage-design.md`. Task 9 adds a Corrections section, which carries the planning rulings below.

## Global Constraints

**Locators and storage:**
- Locator first segments: `reports`, `uploads`, `renders`, `work`, `archive`. Segment rule `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, 1–512 characters, unchanged.
- Store calls are synchronous. Async code wraps them in `asyncio.to_thread`. A sync iterator handed to `StreamingResponse` is fine, because Starlette iterates it in a threadpool.
- Size caps:
  - asset cap `RENDER_ASSET_MAX_BYTES = 1024 * 1024 * 1024`, unchanged;
  - new output cap `RENDER_OUTPUT_MAX_BYTES = 2 * 1024 * 1024 * 1024`;
  - upload cap unchanged.

**Renderer:**
- Renderer failure codes stay within the existing taxonomy. No new code is added (planning ruling 2):
  - an asset download failure is `render_asset_unavailable`;
  - an output upload failure is `render_output_invalid`.
- The renderer keeps the env name `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` for its own container-local work root (planning ruling 1). Its value becomes `/tmp/thoth-renderer`, with no bind mount.

**Compose:**
- `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` on `api` and `worker` becomes `/tmp/thoth-artifacts`. That path is container-local and writable by uid 10001.

**Repository rules:**
- Tests are offline only.
- Commits use one `-m` subject, with no body, trailer, or AI attribution.
- Repository text is in English.
- `docs/superpowers/` is gitignored, so add plan and spec files with `git add -f`.
- Run tests from WSL:
  - `make test T=<path relative to python/>`;
  - `make test-minio`;
  - `make lint`;
  - `cd renderer && bun test`;
  - `make smoke-renderer IMAGE=<thoth image> RENDERER_IMAGE=<renderer image>` (CI runs it on the published digests).

**Rollout:** never print a secret, and never run a live gate without its operator authorization.

## Planning rulings (record them in the spec, Task 9)

1. **Renderer env name.** The renderer keeps the env name `THOTH_CONTROL_PLANE_ARTIFACT_ROOT`. The spec's `THOTH_RENDERER_WORK_DIR` would have touched the template-release CLI, its CI job, and its tests for a rename only. The value moves to a container-local path, which is what the spec asks for.
2. **Failure codes.** No new failure codes. `render_asset_unavailable` already exists for preparation failures. An upload failure happens in the `finalizing` stage, which already maps to `render_output_invalid`. A new code would ripple into the Python `Literal`, the OpenAPI schema, and the generated dashboard client for no new behaviour.
3. **The deploy reaches the old volume only through a one-off mount.** Once the service mounts are gone, the deploy's `import-reports`, `import-media`, and new `archive-media` steps run with `docker compose run -v <host artifacts>:/var/lib/thoth/artifacts`, and only when the host folder still holds files. `--remove-local` stays an operator command run the same way.

## Review Focus

1. **An asset id the job's bundle does not list.**
   - Expected: the internal assets route answers 404 and never streams another project's object.
   - Pinned in Task 3: `test_an_asset_outside_the_bundle_is_not_served`.
2. **A renderer that retries its output upload.**
   - Expected: the second `PUT` replaces the first, and publish verifies the last one.
   - Pinned in Task 3: `test_a_second_output_upload_replaces_the_first`.
3. **A `Range` header that is malformed or past the end.**
   - Expected: a malformed header is served as 200 with the whole object; an unsatisfiable range answers 416 with `Content-Range: bytes */<size>`.
   - Pinned in Task 2: `test_ranged_response_handles_malformed_and_unsatisfiable_ranges`.
4. **Cleanup of a job that never published.**
   - Expected: `work/<job>/` objects go, `renders/<job>/` keeps its metadata and diagnostics, and a second cleanup is a no-op.
   - Pinned in Task 3: `test_cleanup_deletes_the_output_and_work_objects_only`.
5. **The renderer loses the control plane mid-download.**
   - Expected: the render fails with `render_asset_unavailable` and no browser is launched.
   - Pinned in Task 6: `"an asset download failure is render_asset_unavailable"`.

---

## File map

**Modify (Python):**
- Store and adapters:
  - `python/src/thoth_control_plane/infrastructure/media_store.py`: prefixes, `open_range`, `copy`;
  - `python/src/thoth_control_plane/infrastructure/s3_media_store.py`: `open_range`, `copy`;
  - `python/src/thoth_control_plane/infrastructure/artifact_root.py`: store-backed;
  - `python/src/thoth_control_plane/infrastructure/editor_preview.py`: `resolve_preview_path` is removed.
- Application:
  - `python/src/thoth_control_plane/application/render_job_ports.py`: new and changed method signatures;
  - `python/src/thoth_control_plane/application/render_bundles.py`;
  - `python/src/thoth_control_plane/application/render_jobs.py`.
- API:
  - `python/src/thoth_control_plane/api/routes/internal_render_jobs.py`: two routes;
  - `python/src/thoth_control_plane/api/routes/render_jobs.py`: the download route;
  - `python/src/thoth_control_plane/api/routes/editor_assets.py`: the preview route;
  - `python/src/thoth_control_plane/api/app.py`: one media store, wired in.
- Operations: `python/src/thoth_control_plane/operations/media_import.py` and `cli.py` (`--archive`).

**Create (Python):**
- `python/src/thoth_control_plane/api/ranged.py`, the shared `Range` streaming helper.
- Tests: `python/tests/api/test_ranged.py` and `python/tests/api/test_internal_render_media.py`.

**Modify (renderer):**
- `renderer/src/control-plane-client.ts`: `fetchAsset`, `uploadOutput`;
- `renderer/src/artifact-root.ts`: `receiveAsset`, `removeAssets`;
- `renderer/src/server.ts`: the download, verify, render, verify, upload, complete flow;
- their tests.

**Modify (deployment):**
- `compose.stage1.local.yml` and `compose.stage1.renderer.yml`;
- `scripts/ops/deploy-stage1.sh`;
- `docker/test-renderer-offline.sh`;
- `.github/workflows/container-image.yml`, only if a contract test or the smoke needs it;
- the deployment tests.

**Docs:** the spec Corrections section and `CHANGELOG.md` (CRLF).

---

### Task 1: Store prefixes, `open_range`, and `copy`

**Files:**
- Modify:
  - `python/src/thoth_control_plane/infrastructure/media_store.py`;
  - `python/src/thoth_control_plane/infrastructure/s3_media_store.py`.
- Test: `python/tests/infrastructure/test_media_store.py`. The contract tests run on `local` always, and on `s3` under `make test-minio`.

**Interfaces:**
- Produces:
  - `MediaStore.open_range(location: str, start: int = 0, end: int | None = None) -> Iterator[bytes]`. `end` is inclusive; `None` means to the end of the object.
  - `MediaStore.copy(source: str, destination: str) -> None`.
  - `_PREFIXES = frozenset({"reports", "uploads", "renders", "work", "archive"})`.

- [ ] **Step 1: Failing tests** (append to `test_media_store.py`; `store` is the existing parametrized fixture)

```python
@pytest.mark.parametrize("prefix", ["uploads", "renders", "work", "archive"])
def test_the_new_prefixes_are_valid_locators(store, tmp_path: Path, prefix: str) -> None:
    location = f"{prefix}/job_1/output.mp4"
    store.put_file(location, _file(tmp_path, "o.mp4", b"out"))
    assert store.stat(location).size_bytes == 3


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [(0, None, b"0123456789"), (3, None, b"3456789"), (2, 5, b"2345"), (8, 99, b"89")],
)
def test_open_range_streams_the_requested_bytes(
    store, tmp_path: Path, start: int, end: int | None, expected: bytes
) -> None:
    store.put_file(LOCATION, _file(tmp_path, "d.mp4", b"0123456789"))
    assert b"".join(store.open_range(LOCATION, start, end)) == expected


def test_open_range_of_an_absent_object_is_unavailable(store) -> None:
    with pytest.raises(MediaUnavailable):
        b"".join(store.open_range(LOCATION))


def test_copy_keeps_the_bytes_and_the_digest(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "s.mp4", b"render-bytes")
    store.put_file("work/rj_1/output.mp4", source)
    store.copy("work/rj_1/output.mp4", "renders/rj_1/output.mp4")
    copied = store.stat("renders/rj_1/output.mp4")
    assert copied.size_bytes == len(b"render-bytes")
    assert copied.sha256 == sha256_file(source)
    assert store.stat("work/rj_1/output.mp4").size_bytes == len(b"render-bytes")  # source stays


def test_copy_of_an_absent_object_is_unavailable(store) -> None:
    with pytest.raises(MediaUnavailable):
        store.copy("work/rj_1/output.mp4", "renders/rj_1/output.mp4")
```

Also, in `test_an_unsafe_locator_is_refused_before_any_io`, replace the `"media/wf_a/x.mp4"` case with `"secrets/wf_a/x.mp4"`, because `media` was never a valid prefix and still is not. Keep every other case.

- [ ] **Step 2: Watch them fail**

Run `make test T=tests/infrastructure/test_media_store.py`. Expected: the new tests FAIL with `MediaLocatorInvalid` for the new prefixes and `AttributeError` for `open_range` and `copy`.

- [ ] **Step 3: Implement (`media_store.py`)**

Replace `_PREFIX = "reports"` with:

```python
#: Workflow media (`reports`), editor uploads, render inputs and outputs, and the volume archive.
_PREFIXES = frozenset({"reports", "uploads", "renders", "work", "archive"})
```

In `checked_locator`, change `segments[0] != _PREFIX` to `segments[0] not in _PREFIXES`.

Add to the `MediaStore` Protocol:

```python
    def open_range(
        self, location: str, start: int = 0, end: int | None = None
    ) -> Iterator[bytes]: ...

    def copy(self, source: str, destination: str) -> None: ...
```

Add `from collections.abc import Iterator`.

`LocalMediaStore`:

```python
    def open_range(
        self, location: str, start: int = 0, end: int | None = None
    ) -> Iterator[bytes]:
        path = self._path(location)
        if not path.is_file():
            raise MediaUnavailable("media_unavailable")
        return self._chunks(path, start, end)

    @staticmethod
    def _chunks(path: Path, start: int, end: int | None) -> Iterator[bytes]:
        remaining = None if end is None else max(0, end - start + 1)
        with path.open("rb") as reader:
            reader.seek(start)
            while remaining is None or remaining > 0:
                chunk = reader.read(_CHUNK if remaining is None else min(_CHUNK, remaining))
                if not chunk:
                    return
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk

    def copy(self, source: str, destination: str) -> None:
        origin = self._path(source)
        if not origin.is_file():
            raise MediaUnavailable("media_unavailable")
        _copy(origin, self._path(destination))
```

`open_range` checks the object before it returns the generator, so a missing object raises at the call and not only when someone iterates.

- [ ] **Step 4: Implement (`s3_media_store.py`)**

```python
    def open_range(
        self, location: str, start: int = 0, end: int | None = None
    ) -> Iterator[bytes]:
        key = checked_locator(location)
        length = None if end is None else max(0, end - start + 1)
        with _errors():
            response = self._client.get_object(self._bucket, key, offset=start, length=length or 0)
        return self._stream(response)

    @staticmethod
    def _stream(response) -> Iterator[bytes]:
        try:
            with _errors():
                yield from response.stream(1024 * 1024)
        finally:
            response.close()
            response.release_conn()

    def copy(self, source: str, destination: str) -> None:
        from minio.commonconfig import CopySource

        src, dst = checked_locator(source), checked_locator(destination)
        with _errors():
            self._client.copy_object(self._bucket, dst, CopySource(self._bucket, src))
```

minio 7.2's `get_object(length=0)` means "to the end". An inclusive `end` past the object's size is clamped by S3. `copy_object` keeps the user metadata by default (`metadata_directive=COPY`), so `x-amz-meta-sha256` carries over. The `test_copy_keeps_the_bytes_and_the_digest` `[s3]` case proves it.

- [ ] **Step 5: Run**

`make test T=tests/infrastructure/test_media_store.py` and `make test-minio`. Expected: everything passes, and the `[s3]` cases have 0 skips under `test-minio`.

- [ ] **Step 6: Lint and commit**

`make lint`, then:

```bash
git add python/src/thoth_control_plane/infrastructure python/tests/infrastructure/test_media_store.py
git commit -m "feat(media): add render prefixes, ranged reads, and copies to the store"
```

---

### Task 2: The shared `Range` streaming helper

**Files:**
- Create: `python/src/thoth_control_plane/api/ranged.py`
- Test: `python/tests/api/test_ranged.py`

**Interfaces:**
- Produces: `ranged_response(*, size: int, read: Callable[[int, int | None], Iterator[bytes]], media_type: str, range_header: str | None, headers: Mapping[str, str] | None = None) -> Response`.

- [ ] **Step 1: Failing tests**

```python
"""One Range implementation for every streamed object (spec 2026-10-17, render storage)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from thoth_control_plane.api.ranged import ranged_response

DATA = b"0123456789"


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/object")
    def serve(request: Request):
        def read(start: int, end: int | None):
            yield DATA[start : None if end is None else end + 1]

        return ranged_response(
            size=len(DATA),
            read=read,
            media_type="video/mp4",
            range_header=request.headers.get("range"),
            headers={"X-Extra": "1"},
        )

    return TestClient(app)


def test_a_request_without_range_gets_the_whole_object() -> None:
    response = _client().get("/object")
    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["content-length"] == "10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["x-extra"] == "1"


def test_a_closed_range_is_partial_content() -> None:
    response = _client().get("/object", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"


def test_an_open_and_a_suffix_range_are_partial_content() -> None:
    assert _client().get("/object", headers={"Range": "bytes=7-"}).content == b"789"
    suffix = _client().get("/object", headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206 and suffix.content == b"789"
    assert suffix.headers["content-range"] == "bytes 7-9/10"


def test_ranged_response_handles_malformed_and_unsatisfiable_ranges() -> None:
    malformed = _client().get("/object", headers={"Range": "pages=1-2"})
    assert malformed.status_code == 200 and malformed.content == DATA
    beyond = _client().get("/object", headers={"Range": "bytes=10-"})
    assert beyond.status_code == 416
    assert beyond.headers["content-range"] == "bytes */10"
    clamped = _client().get("/object", headers={"Range": "bytes=8-99"})
    assert clamped.status_code == 206 and clamped.content == b"89"
```

- [ ] **Step 2: Watch them fail**

Run `make test T=tests/api/test_ranged.py`. Expected: ERROR at collection, `No module named 'thoth_control_plane.api.ranged'`.

- [ ] **Step 3: Implement `api/ranged.py`**

```python
"""Serve one stored object whole or by a single byte range (RFC 9110 section 14).

Only one `bytes=` range is honoured: a browser seeking in a video sends exactly one. A
header that is not a single bytes range is ignored and the whole object is served, which
the RFC allows; a range that starts past the end is 416.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping

from fastapi import Response
from fastapi.responses import StreamingResponse

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _bounds(header: str | None, size: int) -> tuple[int, int] | None | str:
    """(start, end inclusive), None for the whole object, or "unsatisfiable"."""
    match = _RANGE.fullmatch((header or "").strip())
    if match is None or (not match.group(1) and not match.group(2)):
        return None
    first, last = match.group(1), match.group(2)
    if not first:  # a suffix: the last N bytes
        length = int(last)
        if length == 0:
            return "unsatisfiable"
        return max(0, size - length), size - 1
    start = int(first)
    end = size - 1 if not last else min(int(last), size - 1)
    if start >= size or end < start:
        return "unsatisfiable"
    return start, end


def ranged_response(
    *,
    size: int,
    read: Callable[[int, int | None], Iterator[bytes]],
    media_type: str,
    range_header: str | None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    common = {"Accept-Ranges": "bytes", **(headers or {})}
    bounds = _bounds(range_header, size)
    if bounds == "unsatisfiable":
        return Response(status_code=416, headers={**common, "Content-Range": f"bytes */{size}"})
    if bounds is None:
        return StreamingResponse(
            read(0, None),
            media_type=media_type,
            headers={**common, "Content-Length": str(size)},
        )
    start, end = bounds
    return StreamingResponse(
        read(start, end),
        status_code=206,
        media_type=media_type,
        headers={
            **common,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
        },
    )
```

- [ ] **Step 4: Run**

`make test T=tests/api/test_ranged.py`. Expected: 4 passed.

- [ ] **Step 5: Lint and commit**

```bash
git add python/src/thoth_control_plane/api/ranged.py python/tests/api/test_ranged.py
git commit -m "feat(api): add one Range streaming helper for stored objects"
```

---

### Task 3: The render adapter on the store, the bundle, the service, and the internal routes

**Files:**
- Modify:
  - `python/src/thoth_control_plane/infrastructure/artifact_root.py`;
  - `python/src/thoth_control_plane/application/render_job_ports.py`;
  - `python/src/thoth_control_plane/application/render_bundles.py`;
  - `python/src/thoth_control_plane/application/render_jobs.py`;
  - `python/src/thoth_control_plane/api/routes/internal_render_jobs.py`;
  - `python/src/thoth_control_plane/api/routes/render_jobs.py`, the download route;
  - `python/src/thoth_control_plane/api/app.py`.
- Test:
  - `python/tests/infrastructure/test_artifact_root.py`: rewrite the render half;
  - `python/tests/application/test_render_bundles.py` and `python/tests/application/test_render_jobs.py`: update their `Artifacts` fakes;
  - `python/tests/api/test_internal_render_media.py`: new;
  - the existing render route tests.

**Interfaces:**
- Consumes:
  - from Task 1: `MediaStore`, `open_range`, `copy`, `list`, `stat`, `put_file`, `delete`;
  - from Task 2: `ranged_response`.
- Produces:
  - **`LocalArtifactRoot(root: Path, media: MediaStore | None = None)`.** `media=None` means `LocalMediaStore(root)`, which keeps every existing locator at the same place on disk, so the editor upload tests stay valid.
  - **Protocol changes** (`ArtifactRoot` in `render_job_ports.py`):
    - `resolve_source` is removed.
    - `stage_asset(workspace, *, asset_id, location: str, expected_checksum, max_bytes) -> StagedAsset` takes a locator in place of `source: Path`, and verifies only: `stat` size, sha256, and cap.
    - `read_bundle(render_job_id) -> bytes`, unchanged signature, now read from the store.
    - `receive_output(render_job_id: str, chunks: AsyncIterator[bytes], *, max_bytes: int) -> ReceivedOutput` is new; `ReceivedOutput(size_bytes: int, checksum: str)` is a frozen dataclass in `render_job_ports.py`.
    - `verify_temporary_output(render_job_id, expected) -> str` returns the `work/<job>/output.mp4` locator.
    - `resolve_download(render_job_id, relative_path) -> str` returns the locator.
    - `object_size(location: str) -> int` and `read_object(location: str, start: int, end: int | None) -> Iterator[bytes]` are new.
    - `publish` and `cleanup` keep their signatures.
  - `DownloadableRender.path: Path` is replaced by `location: str`.
  - `RenderJobService.asset_location(render_job_id: str, asset_id: str) -> str`, `RenderJobService.receive_output(render_job_id: str, chunks) -> ReceivedOutput`, and `RenderJobService.read_object(location, start, end)` / `object_size(location)`, which delegate to the adapter for the routes.
  - `RenderPresetSettings.max_output_bytes: int = RENDER_OUTPUT_MAX_BYTES`.
  - Internal routes:
    - `GET /internal/render-jobs/{job}/assets/{asset_id}`: 200 with the stream, 404 `render_asset_unavailable`;
    - `PUT /internal/render-jobs/{job}/output`: 200 `{"size_bytes": int, "checksum": "sha256:…"}`, 413 `render_output_too_large`, 404 for an unknown or inactive job, 503 `media_store_unavailable`.

- [ ] **Step 1: Failing adapter tests** (`test_artifact_root.py`)

1. Delete the tests for removed behaviour, `stage_asset` copies and `resolve_source`: lines ~120–227 and ~431–488. Those are `test_stage_asset_copies_bytes_into_the_job_workspace` through `test_stage_asset_validates_the_asset_identity`, plus the four `test_resolve_source_*` tests.
2. Replace `test_verify_temporary_output_*`, `test_publish_*`, `test_resolve_download_*`, and `test_cleanup_*` with store-backed versions.
3. Keep the identity and link tests and the upload tests.
4. New and replacement tests (use `_root(tmp_path)`, which builds `LocalArtifactRoot(tmp_path)`, so its media store is `LocalMediaStore(tmp_path)` and every object is a file you can assert on):

```python
def _facts(path: Path) -> RenderOutputFacts:
    data = path.read_bytes()
    return RenderOutputFacts(
        media_type="video/mp4", size_bytes=len(data),
        checksum="sha256:" + hashlib.sha256(data).hexdigest(), codec="h264",
        width=1080, height=1920, fps=30.0, duration_seconds=4.0, has_audio=True,
    )


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


async def test_receive_output_stores_the_upload_under_work_and_reports_its_facts(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    received = await root.receive_output("rj_1", _chunks(b"ab", b"cd"), max_bytes=10)
    assert received.size_bytes == 4
    assert received.checksum == "sha256:" + hashlib.sha256(b"abcd").hexdigest()
    assert (tmp_path / "work/rj_1/output.mp4").read_bytes() == b"abcd"
    assert not list((tmp_path / "temp").rglob("*.part"))


async def test_receive_output_over_the_cap_stores_nothing(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    with pytest.raises(RenderOutputTooLarge):
        await root.receive_output("rj_1", _chunks(b"x" * 8, b"y" * 8), max_bytes=10)
    assert not (tmp_path / "work/rj_1/output.mp4").exists()
    assert not list((tmp_path / "temp").rglob("*.part"))


async def test_a_second_output_upload_replaces_the_first(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output("rj_1", _chunks(b"old"), max_bytes=10)
    received = await root.receive_output("rj_1", _chunks(b"newer"), max_bytes=10)
    assert received.size_bytes == 5
    assert (tmp_path / "work/rj_1/output.mp4").read_bytes() == b"newer"


async def test_publish_copies_the_verified_output_and_drops_the_work_objects(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output("rj_1", _chunks(b"render"), max_bytes=100)
    facts = _facts(tmp_path / "work/rj_1/output.mp4")
    root.write_bundle(root.prepare("rj_1"), b"{}")
    published = root.publish("rj_1", facts, b'{"m":1}', b'{"d":1}')
    assert published.relative_path == "renders/rj_1/output.mp4"
    assert (tmp_path / "renders/rj_1/output.mp4").read_bytes() == b"render"
    assert (tmp_path / "renders/rj_1/metadata.json").read_bytes() == b'{"m":1}'
    assert (tmp_path / "renders/rj_1/diagnostics.json").read_bytes() == b'{"d":1}'
    assert not (tmp_path / "work/rj_1/output.mp4").exists()
    assert not (tmp_path / "work/rj_1/bundle.json").exists()


async def test_publish_refuses_an_output_that_differs_from_its_facts(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output("rj_1", _chunks(b"render"), max_bytes=100)
    facts = _facts(tmp_path / "work/rj_1/output.mp4").model_copy(update={"size_bytes": 99})
    with pytest.raises(ArtifactUnavailable):
        root.publish("rj_1", facts, b"{}", b"{}")
    assert not (tmp_path / "renders/rj_1/output.mp4").exists()


def test_a_missing_output_is_unavailable(tmp_path):
    with pytest.raises(ArtifactUnavailable):
        LocalArtifactRoot(tmp_path).verify_temporary_output("rj_1", _facts_of_size(1))


async def test_cleanup_deletes_the_output_and_work_objects_only(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output("rj_1", _chunks(b"render"), max_bytes=100)
    facts = _facts(tmp_path / "work/rj_1/output.mp4")
    root.publish("rj_1", facts, b"{}", b"{}")
    await root.receive_output("rj_1", _chunks(b"stray"), max_bytes=100)  # a late retry
    root.cleanup("rj_1")
    root.cleanup("rj_1")
    assert not (tmp_path / "renders/rj_1/output.mp4").exists()
    assert (tmp_path / "renders/rj_1/metadata.json").exists()
    assert (tmp_path / "renders/rj_1/diagnostics.json").exists()
    assert not (tmp_path / "work/rj_1").exists() or not any((tmp_path / "work/rj_1").iterdir())


def test_read_bundle_returns_the_stored_bytes(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    root.write_bundle(root.prepare("rj_1"), b'{"bundle":1}')
    assert root.read_bundle("rj_1") == b'{"bundle":1}'


def test_stage_asset_verifies_a_stored_asset_without_copying_it(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    (tmp_path / "uploads/proj_1").mkdir(parents=True)
    (tmp_path / "uploads/proj_1/asset_1.mp4").write_bytes(b"clip")
    checksum = "sha256:" + hashlib.sha256(b"clip").hexdigest()
    staged = root.stage_asset(
        root.prepare("rj_1"), asset_id="asset_1", location="uploads/proj_1/asset_1.mp4",
        expected_checksum=checksum, max_bytes=100,
    )
    assert (staged.relative_name, staged.size_bytes, staged.checksum) == (
        "assets/asset_1.mp4", 4, checksum)
    assert not (tmp_path / "work/rj_1/assets").exists()
    with pytest.raises(ArtifactUnavailable):
        root.stage_asset(root.prepare("rj_1"), asset_id="asset_1",
                         location="uploads/proj_1/asset_1.mp4",
                         expected_checksum="sha256:" + "0" * 64, max_bytes=100)
    with pytest.raises(ArtifactUnavailable):
        root.stage_asset(root.prepare("rj_1"), asset_id="asset_1",
                         location="uploads/proj_1/asset_1.mp4",
                         expected_checksum=checksum, max_bytes=3)


def test_read_object_streams_a_range_of_a_published_render(tmp_path):
    root = LocalArtifactRoot(tmp_path)
    (tmp_path / "renders/rj_1").mkdir(parents=True)
    (tmp_path / "renders/rj_1/output.mp4").write_bytes(b"0123456789")
    assert root.object_size("renders/rj_1/output.mp4") == 10
    assert b"".join(root.read_object("renders/rj_1/output.mp4", 2, 4)) == b"234"
```

Clean up the `cleanup` test's last assertion to one form: `assert not (tmp_path / "work/rj_1").exists() or not any((tmp_path / "work/rj_1").iterdir())`. Add `_facts_of_size(n)`, which builds a `RenderOutputFacts` with `size_bytes=n` and any checksum. Import `RenderOutputTooLarge` from `render_job_ports`; it is a new exception defined in Step 3.

- [ ] **Step 2: Watch them fail**

Run `make test T=tests/infrastructure/test_artifact_root.py`. Expected: the new tests fail with `AttributeError` (`receive_output`, `object_size`, `read_object`) or `TypeError` (`stage_asset` `location=`).

- [ ] **Step 3: Implement the port and the adapter**

In `render_job_ports.py`:
- Add the frozen `ReceivedOutput(size_bytes: int, checksum: str)`.
- Add `class RenderOutputTooLarge(Exception)`, with the message "render output too large".
- Update the `ArtifactRoot` Protocol to the signatures in **Interfaces**, and remove `resolve_source`.
- Change the `stage_asset` docstring to "Verify one stored asset against its record and name it for the renderer."

In `artifact_root.py`:
- Update the module docstring layout:
  - `uploads/<project>/<asset>.<ext>` → store;
  - `work/<job>/{bundle.json,output.mp4}` → store;
  - `renders/<job>/{output.mp4,metadata.json,diagnostics.json}` → store;
  - `temp/<job>/` and `temp/uploads/` → local only.
- Constructor:

```python
    def __init__(self, root: Path, media: MediaStore | None = None) -> None:
        self._root = Path(root).resolve()
        self._media = media if media is not None else LocalMediaStore(self._root)
```

- Methods (keep `_valid_identifier`, `_contained`, `_is_link`, `_atomic_write`, and the upload methods as they are):

```python
    def prepare(self, render_job_id: str) -> JobWorkspace:
        job = _valid_identifier(render_job_id)
        self._contained("temp", job).mkdir(parents=True, exist_ok=True)
        return JobWorkspace(render_job_id=job)

    def stage_asset(
        self, workspace: JobWorkspace, *, asset_id: str, location: str,
        expected_checksum: str, max_bytes: int,
    ) -> StagedAsset:
        asset = _valid_identifier(asset_id)
        suffix = PurePosixPath(location).suffix
        suffix = suffix if _SUFFIX.match(suffix) else ""
        try:
            facts = self._media.stat(location)
        except (MediaUnavailable, MediaLocatorInvalid):
            raise ArtifactUnavailable() from None
        if facts.size_bytes > max_bytes or f"sha256:{facts.sha256}" != expected_checksum:
            raise ArtifactUnavailable()
        return StagedAsset(
            asset_id=asset, relative_name=f"{workspace.assets_name}/{asset}{suffix}",
            size_bytes=facts.size_bytes, checksum=expected_checksum,
        )

    def write_bundle(self, workspace: JobWorkspace, bundle_json: bytes) -> str:
        job = _valid_identifier(workspace.render_job_id)
        self._put_bytes(f"work/{job}/{workspace.bundle_name}", bundle_json, job)
        return workspace.bundle_name

    def read_bundle(self, render_job_id: str) -> bytes:
        job = _valid_identifier(render_job_id)
        location = f"work/{job}/{JobWorkspace(render_job_id=job).bundle_name}"
        try:
            if self._media.stat(location).size_bytes > _MAX_BUNDLE_BYTES:
                raise ArtifactUnavailable()
            return b"".join(self._media.open_range(location))
        except MediaUnavailable:
            raise ArtifactUnavailable() from None

    async def receive_output(
        self, render_job_id: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> ReceivedOutput:
        job = _valid_identifier(render_job_id)
        self._contained("temp", job).mkdir(parents=True, exist_ok=True)
        partial = self._contained("temp", job, f"{_OUTPUT_NAME}.part")
        digest, written = hashlib.sha256(), 0
        try:
            with partial.open("wb") as writer:
                async for chunk in chunks:
                    written += len(chunk)
                    if written > max_bytes:
                        raise RenderOutputTooLarge()
                    digest.update(chunk)
                    writer.write(chunk)
            await asyncio.to_thread(self._media.put_file, f"work/{job}/{_OUTPUT_NAME}", partial)
        finally:
            partial.unlink(missing_ok=True)
        return ReceivedOutput(size_bytes=written, checksum=f"sha256:{digest.hexdigest()}")

    def verify_temporary_output(self, render_job_id: str, expected: RenderOutputFacts) -> str:
        job = _valid_identifier(render_job_id)
        location = f"work/{job}/{_OUTPUT_NAME}"
        try:
            facts = self._media.stat(location)
        except MediaUnavailable:
            raise ArtifactUnavailable() from None
        if (facts.size_bytes, f"sha256:{facts.sha256}") != (expected.size_bytes, expected.checksum):
            raise ArtifactUnavailable()
        return location

    def publish(self, render_job_id, output, metadata_json, diagnostics_json) -> PublishedArtifact:
        job = _valid_identifier(render_job_id)
        source = self.verify_temporary_output(job, output)
        self._put_bytes(f"renders/{job}/metadata.json", metadata_json, job)
        self._put_bytes(f"renders/{job}/diagnostics.json", diagnostics_json, job)
        # Publication is the last step: one copy of the verified object.
        self._media.copy(source, f"renders/{job}/{_OUTPUT_NAME}")
        for location in self._media.list(f"work/{job}/"):
            self._media.delete(location)
        return PublishedArtifact(
            relative_path=f"renders/{job}/{_OUTPUT_NAME}",
            size_bytes=output.size_bytes, checksum=output.checksum,
        )

    def resolve_download(self, render_job_id: str, relative_path: str) -> str:
        job = _valid_identifier(render_job_id)
        if relative_path != f"renders/{job}/{_OUTPUT_NAME}":
            raise ArtifactPathInvalid()
        return relative_path

    def object_size(self, location: str) -> int:
        try:
            return self._media.stat(location).size_bytes
        except MediaUnavailable:
            raise ArtifactUnavailable() from None

    def read_object(self, location: str, start: int, end: int | None) -> Iterator[bytes]:
        try:
            return self._media.open_range(location, start, end)
        except MediaUnavailable:
            raise ArtifactUnavailable() from None

    def cleanup(self, render_job_id: str) -> None:
        job = _valid_identifier(render_job_id)
        self._media.delete(f"renders/{job}/{_OUTPUT_NAME}")
        for location in self._media.list(f"work/{job}/"):
            self._media.delete(location)
        temporary = self._contained("temp", job)
        if _is_link(temporary):
            raise ArtifactPathInvalid()
        if temporary.is_dir():
            shutil.rmtree(temporary, ignore_errors=True)

    def _put_bytes(self, location: str, data: bytes, job: str) -> None:
        self._contained("temp", job).mkdir(parents=True, exist_ok=True)
        staging = self._contained("temp", job, f"{PurePosixPath(location).name}.part")
        try:
            staging.write_bytes(data)
            self._media.put_file(location, staging)
        finally:
            staging.unlink(missing_ok=True)
```

**Error mapping.** `MediaStoreUnavailable` propagates unchanged from every method. The routes map it to 503, and `_publish` already turns any exception into `render_output_invalid`. Imports:
- `asyncio`, `PurePosixPath`, and `AsyncIterator` / `Iterator`;
- from `media_store`: `LocalMediaStore`, `MediaStore`, `MediaUnavailable`, `MediaLocatorInvalid`;
- from `render_job_ports`: `ReceivedOutput` and `RenderOutputTooLarge`.

`_digest` and the old local publish code become unused. Delete them.

- [ ] **Step 4: Bundle and service**

`render_bundles.py`, in the asset loop:

```python
        copied = artifacts.stage_asset(
            workspace,
            asset_id=asset_id,
            location=record.artifact_location,
            expected_checksum=record.asset.checksum,
            max_bytes=settings.max_asset_bytes,
        )
```

`render_jobs.py`:
- `DownloadableRender.path: Path` becomes `location: str`, and `output_path(...)` sets `location=self._artifacts.resolve_download(...)`.
- In `RenderPresetSettings`, wherever it is defined (find it with `grep -rn "class RenderPresetSettings"`), add the field `max_output_bytes: int = 2 * 1024 * 1024 * 1024`.
- New service methods:

```python
    async def asset_location(self, render_job_id: str, asset_id: str) -> str:
        """The stored asset a running job's bundle lists; anything else is not this job's."""
        jobs = self._require_enabled()
        job = await jobs.get_internal(render_job_id=render_job_id)
        if job is None:
            raise RenderJobNotFound()
        if job.status not in ACTIVE_RENDER_STATUSES or self._artifacts is None:
            raise ArtifactUnavailable()
        bundle = json.loads(await asyncio.to_thread(self._artifacts.read_bundle, render_job_id))
        if asset_id not in {entry["asset_id"] for entry in bundle.get("assets", [])}:
            raise ArtifactUnavailable()
        records = await self._assets.get_ready_records(
            project_id=job.project_id, asset_ids=(asset_id,)
        )
        if len(records) != 1:
            raise ArtifactUnavailable()
        return records[0].artifact_location

    async def receive_output(self, render_job_id: str, chunks) -> ReceivedOutput:
        jobs = self._require_enabled()
        job = await jobs.get_internal(render_job_id=render_job_id)
        if job is None:
            raise RenderJobNotFound()
        if job.status not in ACTIVE_RENDER_STATUSES or self._artifacts is None:
            raise RenderJobNotActive()
        return await self._artifacts.receive_output(
            render_job_id, chunks, max_bytes=self._settings.max_output_bytes
        )

    def object_size(self, location: str) -> int:
        if self._artifacts is None:
            raise ArtifactUnavailable()
        return self._artifacts.object_size(location)

    def read_object(self, location: str, start: int, end: int | None):
        if self._artifacts is None:
            raise ArtifactUnavailable()
        return self._artifacts.read_object(location, start, end)
```

Use the attribute names `__init__` actually stores for the asset repository and the settings (read `__init__` around line 130). If they differ from `self._assets` and `self._settings`, use the real names, and ledger the deviation as a ruling.

- [ ] **Step 5: Routes**

`internal_render_jobs.py`, after `read_render_bundle`:

```python
@router.get("/{render_job_id}/assets/{asset_id}", include_in_schema=False)
async def read_render_asset(
    render_job_id: OpaqueId, asset_id: OpaqueId, service: ServiceDependency
) -> Response:
    """Stream one asset the job's bundle lists, and nothing else."""
    with safe_render_errors(unavailable=(status.HTTP_404_NOT_FOUND, "render_asset_unavailable")):
        location = await service.asset_location(render_job_id, asset_id)
        size = await asyncio.to_thread(service.object_size, location)
    return StreamingResponse(
        service.read_object(location, 0, None),
        media_type="application/octet-stream",
        headers={"Content-Length": str(size)},
    )


class RenderOutputReceipt(StrictModel):
    size_bytes: NonNegativeInt
    checksum: str


@router.put("/{render_job_id}/output", include_in_schema=False)
async def receive_render_output(
    render_job_id: OpaqueId, request: Request, service: ServiceDependency
) -> RenderOutputReceipt:
    """Take the renderer's finished file into the store; publish verifies it later."""
    try:
        with safe_render_errors(unavailable=(status.HTTP_404_NOT_FOUND, "render_job_not_active")):
            received = await service.receive_output(render_job_id, request.stream())
    except RenderOutputTooLarge:
        raise HTTPException(status_code=413, detail={"code": "render_output_too_large"}) from None
    return RenderOutputReceipt(size_bytes=received.size_bytes, checksum=received.checksum)
```

**`safe_render_errors`.** Read it in `render_jobs.py` around line 92. It must map `MediaStoreUnavailable` to 503 `media_store_unavailable`. If it does not already, add `except MediaStoreUnavailable: raise HTTPException(503, detail={"code": "media_store_unavailable"}) from None` before its generic branch. Also make sure `RenderJobNotActive` and `RenderJobNotFound` map the way the bundle route already relies on.

**Download route** (`render_jobs.py`):

```python
async def download_render_output(project_id, render_job_id, request: Request, actor, service):
    with safe_render_errors(unavailable=(status.HTTP_404_NOT_FOUND, "render_output_unavailable")):
        download = await service.output_path(project_id, render_job_id)
        size = await asyncio.to_thread(service.object_size, download.location)
    return ranged_response(
        size=size,
        read=lambda start, end: service.read_object(download.location, start, end),
        media_type=download.media_type,
        range_header=request.headers.get("range"),
        headers={
            **DOWNLOAD_HEADERS,
            "Content-Disposition": f'attachment; filename="{download.filename}"',
            "X-Thoth-Render-Checksum": download.checksum,
        },
    )
```

Change `response_class=FileResponse` to `response_class=Response` and keep its `responses=` entry.

- [ ] **Step 6: Wiring (`app.py`)**

Build one store, `media = build_media_store(settings)`, once in `create_app`, and set `app.state.media_store = media`. Pass `LocalArtifactRoot(settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT, media)` in both places, line ~145 (render service) and line ~292 (upload service). The render service builder is a separate function; give it a `media` parameter and pass the same instance.

`build_media_store` does no I/O, so the API still starts with MinIO down (spec: the API does not wait for MinIO).

- [ ] **Step 7: Route tests** (`tests/api/test_internal_render_media.py`)

Use the existing render route test app factory. Find it with `grep -rn "internal/render-jobs" python/tests/api`, and reuse its helpers for an app with a render service, an internal credential, and a seeded job, plus its fixture for a job with a bundle. Write:
- `test_an_asset_in_the_bundle_streams_with_its_length`;
- `test_an_asset_outside_the_bundle_is_not_served` (404, code `render_asset_unavailable`);
- `test_the_asset_route_needs_the_internal_credential` (401);
- `test_output_upload_answers_its_size_and_checksum`;
- `test_an_oversized_output_is_413` (set `max_output_bytes=4` through the service settings the factory accepts);
- `test_output_upload_for_an_unknown_job_is_404`;
- `test_a_store_outage_on_upload_is_503` (an artifacts adapter whose `receive_output` raises `MediaStoreUnavailable`);
- `test_the_render_download_honours_range` (206 with `Content-Range`, and 200 without).

Each test is three to eight lines on top of the existing fixtures. Write the RED run before touching the routes, then run `make test T=tests/api/test_internal_render_media.py`; expected: all pass.

- [ ] **Step 8: Update the fakes and run the render suites**

- In `tests/application/test_render_bundles.py` and `test_render_jobs.py`, the `Artifacts` fakes:
  - drop `resolve_source`;
  - `stage_asset` takes `location=` and records it in place of `source`;
  - `verify_temporary_output` and `resolve_download` return locator strings;
  - add `receive_output`, `object_size`, and `read_object` stubs only where a test calls them.
- Fix the assertions that compared `Path("/srv/artifacts") / …` to compare locator strings.

Run `make test T="tests/infrastructure/test_artifact_root.py tests/application tests/api"`. Expected: all pass.

- [ ] **Step 9: Lint and commit**

```bash
git add python/src python/tests
git commit -m "feat(render): keep render inputs and outputs in the media store"
```

---

### Task 4: Editor uploads and preview on the store

**Files:**
- Modify:
  - `python/src/thoth_control_plane/infrastructure/artifact_root.py`: `publish_upload`, `discard`;
  - `python/src/thoth_control_plane/api/routes/editor_assets.py`: preview;
  - `python/src/thoth_control_plane/infrastructure/editor_preview.py`: remove `resolve_preview_path` and its exception if nothing else uses them.
- Test:
  - `python/tests/infrastructure/test_artifact_root.py`: the upload half;
  - `python/tests/api/test_editor_asset_uploads.py` or the preview route tests (find them with `grep -rln "preview" python/tests/api`);
  - `python/tests/infrastructure/test_editor_preview.py`: remove the `resolve_preview_path` tests.

**Interfaces:**
- Consumes:
  - from Task 3: `LocalArtifactRoot(root, media)` and `read_object` / `object_size`;
  - from Task 2: `ranged_response`.
- Produces: the preview streams from `app.state.media_store`.

- [ ] **Step 1: Failing tests**

```python
async def test_publish_upload_puts_the_file_in_the_store_and_drops_the_local_copy(tmp_path):
    store_root = tmp_path / "store"
    store_root.mkdir()
    root = LocalArtifactRoot(tmp_path / "local", LocalMediaStore(store_root))
    (tmp_path / "local").mkdir()
    received = await root.receive_upload(asset_id="asset_1", chunks=_chunks(b"clip"), max_bytes=10)
    location = root.publish_upload(received, project_id="proj_1", suffix=".mp4")
    assert location == "uploads/proj_1/asset_1.mp4"
    assert (store_root / location).read_bytes() == b"clip"
    assert not received.path.exists()
    root.discard(location)
    assert not (store_root / location).exists()
```

Plus a preview route test: an upload stored only in the store (not under the artifact root) is served with 200, and `Range: bytes=0-1` gets 206.

- [ ] **Step 2: Watch them fail**

Run `make test T=tests/infrastructure/test_artifact_root.py`. Expected: FAIL, because the file sits at `local/uploads/…`, not in the store.

- [ ] **Step 3: Implement**

```python
    def publish_upload(self, received: ReceivedUpload, *, project_id: str, suffix: str) -> str:
        """Store one received upload at its project-scoped locator, then drop the local copy."""
        if not _LOCATOR_SEGMENT.match(project_id) or not _SUFFIX.match(suffix):
            raise ArtifactPathInvalid()
        source = self._contained(*received.location.split("/"))
        if _is_link(source) or not source.is_file():
            raise ArtifactUnavailable()
        name = f"{source.name.removesuffix('.part')}{suffix}"
        location = f"uploads/{project_id}/{name}"
        self._media.put_file(location, source)
        source.unlink(missing_ok=True)
        return location

    def discard(self, relative_location: str) -> None:
        """Remove one upload: a local temporary file, or a stored object."""
        segments = relative_location.split("/")
        if any(not _LOCATOR_SEGMENT.match(segment) for segment in segments):
            raise ArtifactPathInvalid()
        if segments[0] == "temp":
            target = self._contained(*segments)
            if _is_link(target):
                raise ArtifactPathInvalid()
            target.unlink(missing_ok=True)
            return
        self._media.delete(relative_location)
```

Preview route (`editor_assets.py`), replacing the `resolve_preview_path` block:

```python
    media = request.app.state.media_store
    location = record.artifact_location
    try:
        size = await asyncio.to_thread(lambda: media.stat(location).size_bytes)
    except (MediaUnavailable, MediaLocatorInvalid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"code": "asset_not_ready"}
        ) from None
    except MediaStoreUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "media_store_unavailable"},
        ) from None
    return ranged_response(
        size=size,
        read=lambda start, end: media.open_range(location, start, end),
        media_type=record.asset.media_type,
        range_header=request.headers.get("range"),
        headers=PREVIEW_HEADERS,
    )
```

Test apps that build the API without S3 settings get `LocalMediaStore(artifact_root)`. Existing preview tests that wrote files under `tmp_path/uploads/...` therefore keep passing; adjust the ones that wrote outside `uploads/`.

- [ ] **Step 4: Run, lint, commit**

Run `make test T="tests/infrastructure tests/api tests/application"`; expected: all pass. Then `make lint` and:

```bash
git add python/src python/tests
git commit -m "feat(editor): store uploads and stream previews from the media store"
```

---

### Task 5: `media import --archive`

**Files:**
- Modify:
  - `python/src/thoth_control_plane/operations/media_import.py`;
  - `python/src/thoth_control_plane/cli.py`.
- Test: `python/tests/operations/test_media_import.py`

**Interfaces:**
- Produces: `import_media(root, store, *, archive: bool = False)` and `remove_local_media(root, store, *, archive: bool = False)`. With `archive=True` they walk `reports/` and `legacy-scout/`, include `.json`, and use the key `archive/<relative path>`. The CLI gains `--archive`.

- [ ] **Step 1: Failing tests**

```python
def test_archive_copies_report_json_and_legacy_scout_under_archive(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, REPORT, b"{}")
    _write(volume, "legacy-scout/wf_a/source-report.json", b'{"l":1}')
    assert import_media(volume, store, archive=True) == MediaImportCounts(2, 0, 0, 0)
    assert store.list("archive/reports/") == ["archive/reports/wf_a/source-report.json"]
    assert store.list("archive/legacy-scout/") == ["archive/legacy-scout/wf_a/source-report.json"]
    assert import_media(volume, store, archive=True) == MediaImportCounts(0, 2, 0, 0)


def test_archive_remove_local_keeps_nothing_it_verified(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, REPORT, b"{}")
    _write(volume, "legacy-scout/wf_a/source-report.json", b'{"l":1}')
    import_media(volume, store, archive=True)
    assert remove_local_media(volume, store, archive=True) == MediaRemovalCounts(2, 0)
    assert not (volume / "reports").exists() or not any((volume / "reports").rglob("*"))


def test_cli_archive_prints_counts(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, REPORT, b"{}")
    result = _cli(monkeypatch, _CliStore(store.root), "--artifact-root", str(volume), "--archive")
    assert result.exit_code == 0
    assert result.output.strip() == "imported=1 present=0 invalid=0 mismatch=0"
```

- [ ] **Step 2: Watch them fail**

Run `make test T=tests/operations/test_media_import.py`. Expected: `TypeError: unexpected keyword argument 'archive'`.

- [ ] **Step 3: Implement**

`_candidates(root, *, archive=False)`:
- iterates `("reports", "legacy-scout") if archive else ("reports",)`;
- skips `.json` only when not archiving;
- yields `(path, key)` where `key = checked_locator("archive/" + relative)` when archiving, else `checked_locator(relative)`.

`import_media` and `remove_local_media` take `*, archive: bool = False` and pass it through.

The CLI gets `archive: Annotated[bool, typer.Option("--archive")] = False` and passes `archive=archive` to both calls. `remove_local_media`'s empty-folder sweep runs over each walked top folder.

- [ ] **Step 4: Run, lint, commit**

Run `make test T=tests/operations/test_media_import.py`; expected: all pass. Then:

```bash
git add python/src python/tests
git commit -m "feat(media): archive the volume's leftover reports in the bucket"
```

---

### Task 6: The renderer downloads assets and uploads its output

**Files:**
- Modify:
  - `renderer/src/control-plane-client.ts`;
  - `renderer/src/artifact-root.ts`;
  - `renderer/src/server.ts`.
- Test:
  - `renderer/src/control-plane-client.test.ts`;
  - `renderer/src/artifact-root.test.ts`;
  - `renderer/src/server.test.ts`.

**Interfaces:**
- Consumes (from Task 3): `GET /internal/render-jobs/{job}/assets/{asset_id}` and `PUT /internal/render-jobs/{job}/output`.
- Produces:
  - `ControlPlaneClient.fetchAsset(renderJobId: string, assetId: string): Promise<ReadableStream<Uint8Array>>`;
  - `ControlPlaneClient.uploadOutput(renderJobId: string, path: string): Promise<void>`;
  - `RendererArtifactRoot.receiveAsset(renderJobId: string, asset: RenderBundleAsset, body: ReadableStream<Uint8Array>): Promise<void>`;
  - `RendererArtifactRoot.removeAssets(renderJobId: string): Promise<void>`;
  - `ControlPlanePort` and `ArtifactPort` (`server.ts`) gain the matching members.

- [ ] **Step 1: Failing tests**

`control-plane-client.test.ts`, following the file's existing `fetchImpl` stub pattern:
- `fetchAsset` sends `GET <base>/internal/render-jobs/rj_1/assets/asset_1` with the bearer credential and `redirect: "error"`, and resolves to the response body;
- a non-2xx response rejects with `ControlPlaneUnavailable`;
- `uploadOutput` sends `PUT …/rj_1/output` with `Content-Type: video/mp4` and the file's bytes as the body (stub: read `await request.arrayBuffer()`, compare to the written temp file);
- a non-2xx upload rejects with `ControlPlaneUnavailable`.

`artifact-root.test.ts`:
- `receiveAsset` writes the stream to `assetsDirectory(job)/<name>`, and `verifyStagedAssets` then passes;
- a body with the wrong bytes makes `verifyStagedAssets` throw `ArtifactUnavailable`;
- `receiveAsset` refuses a `relative_name` outside `assets/` by throwing `ArtifactPathInvalid` (the contract already restricts it; this is the second check);
- `removeAssets` deletes only that job's assets directory.

`server.test.ts`, extending the fake `client` with `fetchAsset` and `uploadOutput`, and `artifacts` with `receiveAsset` and `removeAssets`:
- `"assets are downloaded before they are verified"`: the order of calls is fetchAsset, receiveAsset, verifyStagedAssets;
- `"an asset download failure is render_asset_unavailable"`: `fetchAsset` rejects; the closing event is `failed` / `render_asset_unavailable`, and `engine.render` is never called;
- `"the output is uploaded before completed"`: `uploadOutput` is called with `temporaryOutput(job)` before the `completed` event is published;
- `"an upload failure is render_output_invalid and never completed"`: `uploadOutput` rejects; the closing event is `failed` / `render_output_invalid`, and no `completed` event is sent;
- `"the local output and assets are removed after a completed render"`.

- [ ] **Step 2: Watch them fail**

Run `cd renderer && bun test`. Expected: the new tests fail (`fetchAsset is not a function`, or the call order is wrong). The existing tests pass.

- [ ] **Step 3: Implement the client**

```ts
const TRANSFER_TIMEOUT_MS = 15 * 60_000;

  /** Stream one asset the job's bundle lists. */
  async fetchAsset(renderJobId: string, assetId: string): Promise<ReadableStream<Uint8Array>> {
    if (!IDENTIFIER.test(assetId)) {
      throw new ControlPlaneUnavailable();
    }
    const response = await this.#send(this.#url(renderJobId, `assets/${assetId}`), {
      method: "GET",
      timeoutMs: TRANSFER_TIMEOUT_MS,
    });
    if (response.body === null) {
      throw new ControlPlaneUnavailable();
    }
    return response.body;
  }

  /** Hand the finished render to the control plane, which stores and later verifies it. */
  async uploadOutput(renderJobId: string, path: string): Promise<void> {
    const response = await this.#send(this.#url(renderJobId, "output"), {
      method: "PUT",
      body: Bun.file(path),
      contentType: "video/mp4",
      timeoutMs: TRANSFER_TIMEOUT_MS,
    });
    await this.#bounded(response);
  }
```

Generalize `#send(url, init: { method: string; body?: BodyInit; contentType?: string; timeoutMs?: number })`. Its defaults are `"application/json"` and `REQUEST_TIMEOUT_MS`.

- [ ] **Step 4: Implement the artifact root**

```ts
  /** Write one downloaded asset where the bundle names it; the checksum is verified after. */
  async receiveAsset(
    renderJobId: string,
    asset: RenderBundleAsset,
    body: ReadableStream<Uint8Array>,
  ): Promise<void> {
    if (!asset.relative_name.startsWith("assets/")) {
      throw new ArtifactPathInvalid();
    }
    const directory = this.assetsDirectory(renderJobId);
    const name = asset.relative_name.slice("assets/".length);
    const path = this.#contained("work", this.#identifier(renderJobId), "assets", name);
    await this.#assertLinkFree(path);
    try {
      await mkdir(directory, { recursive: true });
      await Bun.write(path, new Response(body));
    } catch {
      throw new ArtifactUnavailable();
    }
  }

  /** Remove this job's downloaded assets, and only them. */
  async removeAssets(renderJobId: string): Promise<void> {
    const directory = this.assetsDirectory(renderJobId);
    await this.#assertLinkFree(directory);
    await rm(directory, { recursive: true, force: true });
  }
```

Use the class's real containment helper names; read lines 360–445 for `#contained`, `#identifier`, and `#assertLinkFree`.

- [ ] **Step 5: Implement the flow (`server.ts`)**

1. After `await deps.artifacts.prepare(renderJobId);` and before `verifyStagedAssets`:

```ts
      for (const asset of bundle.assets) {
        try {
          const body = await deps.client.fetchAsset(renderJobId, asset.asset_id);
          await deps.artifacts.receiveAsset(renderJobId, asset, body);
        } catch {
          // A missing input is the asset's failure, never the bundle's.
          throw new ArtifactUnavailable();
        }
      }
```

2. After `const output = await deps.artifacts.verifyTemporaryOutput(renderJobId, expected);`, add `await deps.client.uploadOutput(renderJobId, deps.artifacts.temporaryOutput(renderJobId));`. A rejection stays in the `finalizing` stage, so `closingEvent` already returns `render_output_invalid`.

3. After the `completed` event is published, add:

```ts
      await safely(deps, "render_temporary_output_cleanup_failed", () =>
        deps.artifacts.removeTemporaryOutput(renderJobId),
      );
```

4. In the `finally` that ends every run (or right after both the success and the failure branch), add:

```ts
      await safely(deps, "render_temporary_output_cleanup_failed", () =>
        deps.artifacts.removeAssets(renderJobId),
      );
```

5. Extend `ControlPlanePort` and `ArtifactPort` with the new members. Import `ArtifactUnavailable` if `server.ts` does not already.

- [ ] **Step 6: Run and commit**

Run `cd renderer && bun test`; expected: all pass. Also run `bunx tsc --noEmit -p renderer` if the renderer has a `tsconfig`; expected: no errors. Then:

```bash
git add renderer/src
git commit -m "feat(renderer): fetch assets and upload the output through the control plane"
```

---

### Task 7: Compose, the deploy script, and the offline render smoke

**Files:**
- Modify:
  - `compose.stage1.local.yml`, `compose.stage1.renderer.yml`;
  - `scripts/ops/deploy-stage1.sh`;
  - `docker/test-renderer-offline.sh`;
  - `python/tests/deployment/test_local_stage1_compose_contract.py` and any other deployment test that asserts the removed mounts (`grep -rn "target: /var/lib/thoth/artifacts" python/tests`).

**Interfaces:**
- Consumes (Tasks 3–6): the routes and the renderer flow, and `media import --archive`.

- [ ] **Step 1: Failing contract tests**

In `test_local_stage1_compose_contract.py`:
- Replace every assertion that `api` or `worker` mounts `target: /var/lib/thoth/artifacts` with the opposite: it must not appear in either block.
- The renderer overlay must not contain `source: ${THOTH_STAGE1_DATA_ROOT:?set THOTH_STAGE1_DATA_ROOT}/artifacts`.
- Add:

```python
def test_no_service_shares_the_artifact_volume() -> None:
    for name in ("compose.stage1.local.yml", "compose.stage1.renderer.yml"):
        assert "/artifacts\n" not in _repo_text(name).replace("\r\n", "\n")
    compose = _repo_text("compose.stage1.local.yml")
    for service in ("api", "worker"):
        assert "THOTH_CONTROL_PLANE_ARTIFACT_ROOT: /tmp/thoth-artifacts" in _service_block(
            compose, service
        )
    assert "THOTH_CONTROL_PLANE_ARTIFACT_ROOT: /tmp/thoth-renderer" in _repo_text(
        "compose.stage1.renderer.yml"
    )


def test_the_deploy_reaches_the_old_volume_only_through_a_one_off_mount() -> None:
    deploy = _repo_text("scripts/ops/deploy-stage1.sh")
    assert "media import --archive" in deploy
    assert '-v "$data_root/artifacts:/var/lib/thoth/artifacts"' in deploy
    assert "--remove-local" not in deploy
```

Run `make test T=tests/deployment`. Expected: FAIL.

- [ ] **Step 2: Compose**

- `compose.stage1.local.yml`:
  - remove the `artifacts` bind entries from `api` and `worker`, leaving the account-profiles bind;
  - set `THOTH_CONTROL_PLANE_ARTIFACT_ROOT: /tmp/thoth-artifacts` on both.
- `compose.stage1.renderer.yml`:
  - remove the renderer's `volumes:` block;
  - set `THOTH_CONTROL_PLANE_ARTIFACT_ROOT: /tmp/thoth-renderer`.

- [ ] **Step 3: Deploy script**

Replace the `import-reports` and `import-media` steps with one guarded block:

```bash
# The artifact volume is no longer mounted (spec 2026-10-17, render storage): its leftovers are
# reached through a one-off mount, only while the host folder still holds files.
on_volume=(run --rm --no-deps -v "$data_root/artifacts:/var/lib/thoth/artifacts" api)
leftovers=$(find "$data_root/artifacts" -type f 2>/dev/null | head -1 || true)
if [ -n "$leftovers" ]; then
    step import-reports
    import_rc=0
    import_line=$("${compose[@]}" "${on_volume[@]}" thoth-control reports import \
        --artifact-root /var/lib/thoth/artifacts 2>&1 | tail -1) || import_rc=$?
    echo "$import_line"
    if [ "$import_rc" -ne 0 ]; then
        echo "report import failed (exit $import_rc); the old worker stays stopped — decide, then re-run" >&2
        exit 1
    fi
    case "$import_line" in *" invalid=0") ;; *)
        echo "report import not clean; the old worker stays stopped — decide, then re-run" >&2
        exit 1 ;;
    esac
fi
step media-store
mkdir -p "$data_root/minio"
"${compose[@]}" up -d --wait minio 2>&1 | tail -3
if [ -n "$leftovers" ]; then
    for mode in "" "--archive"; do
        step "import-media${mode:+ $mode}"
        media_rc=0
        media_line=$("${compose[@]}" "${on_volume[@]}" thoth-control media import $mode \
            --artifact-root /var/lib/thoth/artifacts 2>&1 | tail -1) || media_rc=$?
        echo "$media_line"
        if [ "$media_rc" -ne 0 ]; then
            echo "media import failed (exit $media_rc); the old worker stays stopped — decide, then re-run" >&2
            exit 1
        fi
        case "$media_line" in *" invalid=0 mismatch=0") ;; *)
            echo "media import not clean; the old worker stays stopped — decide, then re-run" >&2
            exit 1 ;;
        esac
    done
fi
```

Keep the existing order: `migrate`, `stop-worker`, this block, `up`, `status`.

**Line endings.** Write the file with the Write or Edit tool, never through a Bash heredoc, which collapses `\`-newline. Keep LF, and check with `bash -n scripts/ops/deploy-stage1.sh` and `file scripts/ops/deploy-stage1.sh`.

- [ ] **Step 4: The offline render smoke**

Edit `docker/test-renderer-offline.sh`.

**Stack:**
1. Add a `minio` service to the generated `stack.yml`:
   - image `pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372`;
   - `command: ["server", "/data"]`;
   - `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` from two new harness env values made with `openssl rand -hex 12` and `-hex 24`;
   - a healthcheck on `curl -fsS http://127.0.0.1:9000/minio/health/live`;
   - no volume.
2. `api`:
   - gains `THOTH_MEDIA_S3_ENDPOINT: minio:9000`, `THOTH_MEDIA_S3_BUCKET: thoth-media`, and the two keys;
   - `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` becomes `/tmp/thoth-artifacts`;
   - loses its `volumes:`.
3. `remotion-renderer`:
   - `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` becomes `/tmp/thoth-renderer`;
   - loses its `volumes:`.
4. Drop `SMOKE_ARTIFACT_ROOT`, the `mkdir`/`chmod` of `$work_root/artifacts`, and the teardown's `find /var/lib/thoth/artifacts -delete` line.
5. Bring `minio` up with the other base services. Then, before `api`, create the bucket with `compose run --rm --no-deps -T api python -c` and this body: `from thoth_control_plane.config import Settings; from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore; S3MediaStore.from_settings(Settings()).ensure_bucket()`.

**Driver (`driver.py`):**
- `ROOT` is gone. Add `from thoth_control_plane.config import Settings` and `from thoth_control_plane.infrastructure.media_store import build_media_store`, plus `STORE = build_media_store(Settings())`.
- **`seed`:**
  - it receives the asset's local path from a new command `put <path>`, which runs `STORE.put_file(f"uploads/{PROJECT_ID}/{ASSET_ID}.mp4", Path(path))`;
  - it inserts `artifact_location = f"uploads/{PROJECT_ID}/{ASSET_ID}.mp4"`;
  - the checksum is computed from that same local file.
- **`verify`:**
  - download the published render through the public route `GET /projects/{PROJECT_ID}/render-jobs/{id}/output` into `/tmp/smoke-output.mp4` inside the api container;
  - compare its size and sha256 with `job["output"]`;
  - the shell then runs `ffprobe` on `/tmp/smoke-output.mp4` inside the **api** container, which ships ffprobe, in place of the renderer container and the host path.
- **`absent`:** `STORE.list(f"renders/{id}/")` holds no `output.mp4`, and `STORE.list(f"work/{id}/")` is empty.

**Shell:**
- Generate the test clip with `ffmpeg` inside the **api** container at `/tmp/smoke-asset.mp4`, using the same lavfi arguments, then run `driver put /tmp/smoke-asset.mp4`.
- The renderer mount verdict becomes `[ -z "$mounts" ] || fail renderer_holds_no_control_plane_capability`.
- Replace the `render_output_inside_artifact_root` phase with `render_output_in_the_store`: the driver checks `STORE.stat(f"renders/{job}/output.mp4").size_bytes == job["output"]["size_bytes"]`.
- `render_output_sha256` is printed from the downloaded file.

The verdict names (`*_=true` lines) change only where the phase changed. If a contract test pins the old names (`grep -rn "render_output_inside_artifact_root" python/tests`), update it to the new name.

- [ ] **Step 5: Run the smoke locally against images built from this branch**

```bash
docker build -t thoth:render-s3 -f Dockerfile .
docker build -t thoth-renderer:render-s3 -f Dockerfile.renderer .
make smoke-renderer IMAGE=thoth:render-s3 RENDERER_IMAGE=thoth-renderer:render-s3
```

Expected:
- every verdict line ends `=true`;
- `deadline_failure_code=render_deadline_exceeded`;
- `teardown_leaves_nothing=true`.

If local image builds are too heavy for the machine (memory), run the smoke in CI instead and record a ledger ruling. CI's "Non-live stack smoke" job runs it on the published digests.

- [ ] **Step 6: Run the deployment tests and commit**

Run `make test T=tests/deployment`; expected: all pass. Then:

```bash
git add compose.stage1.local.yml compose.stage1.renderer.yml scripts/ops/deploy-stage1.sh docker/test-renderer-offline.sh python/tests/deployment
git commit -m "feat(deploy): drop the shared artifact volume from every service"
```

---

### Task 8: Full verification

- [ ] **Step 1: Run every gate**

```bash
make lint
make test > /tmp/full.txt 2>&1; tail -1 /tmp/full.txt
make test-minio
cd renderer && bun test
```

Expected: lint is clean, `make test` has 0 failed, `make test-minio` has 0 skipped, and `bun test` has 0 failed. Record the totals in the ledger.

---

### Task 9: Spec corrections and the CHANGELOG

- [ ] **Step 1: Append to the spec**

Add a `## Corrections (planning, 2026-10-17)` section listing the three planning rulings at the top of this plan, worded as in "Planning rulings".

- [ ] **Step 2: CHANGELOG** (CRLF, above the first `## `)

```markdown
## 2026-10-17 - Render and editor media in object storage (sub-project 2)

Branch `feat/render-object-storage`. Spec `docs/superpowers/specs/2026-10-17-render-object-storage-design.md`, plan `docs/superpowers/plans/2026-10-17-render-object-storage.md`.

**What changed:**
- The store accepts the `uploads`, `renders`, `work`, and `archive` prefixes, and gains `open_range` and `copy`.
- `api/ranged.py` serves one byte range for render downloads and editor previews.
- `LocalArtifactRoot` keeps every persistent render and editor object in the media store:
  - bundles and received outputs under `work/<job>/`;
  - published renders and their records under `renders/<job>/`;
  - uploads under `uploads/<project>/`.
- New internal routes: `GET …/assets/{asset_id}` streams only an asset the job's bundle lists; `PUT …/output` takes the finished render, capped at 2 GiB, answering 413 above that.
- The renderer downloads its assets and uploads its output through those routes before it reports `completed`. It keeps a container-local work root and holds no S3 credential.
- `media import --archive` copies the volume's leftover report JSON and `legacy-scout/` into `archive/`, verified.
- No service mounts the artifact volume. The deploy reaches it through a one-off mount while it still holds files.

**Verification:** <the totals from Task 8 and the smoke verdicts>.

**Next steps**
1. PR, CI (its stack smoke runs the new offline render smoke), merge. Operator gate.
2. Pin the new thoth and renderer digests, then `make deploy`. Operator gate.
3. One footage smoke. Operator gate.
4. `media import --archive --remove-local` through the one-off mount. Operator gate.
- Follow-ups: Studio reads the footage artifact; attribution for reposts with no credit; Stage 5c; label the newly admitted calibration clips.
```

Fill the Verification line from the real runs before committing.

- [ ] **Step 3: Commit**

```bash
git add -f docs/superpowers/specs/2026-10-17-render-object-storage-design.md docs/superpowers/plans/2026-10-17-render-object-storage.md
git add CHANGELOG.md
git commit -m "docs: record render and editor media in object storage"
```

---

## Rollout (operator-gated; for the final report)

1. PR, CI green on every check, merge.
2. Pin `THOTH_IMAGE` and `THOTH_RENDERER_IMAGE` from the master Publish job (`IMAGE_DIGEST`, `RENDERER_IMAGE_DIGEST`), back up `.env.stage1.local`, and `docker pull` both.
3. Run `make deploy`. Expected:
   - `import-media` `imported=0 present=0 invalid=0 mismatch=0`, since the workflow media already moved;
   - `import-media --archive` `imported=<≈277> present=0 invalid=0 mismatch=0`;
   - every service healthy.
4. One footage smoke, with zero `event loop stalled`.
5. `docker compose … run --rm --no-deps -v <data_root>/artifacts:/var/lib/thoth/artifacts api thoth-control media import --archive --remove-local --artifact-root /var/lib/thoth/artifacts`. Expected: `kept=0`.
