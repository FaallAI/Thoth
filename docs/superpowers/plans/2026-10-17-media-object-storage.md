# Workflow Media in Object Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The worker stores and reads every workflow media file (`reports/<id>/{media,cards,footage}/…`) through an S3-compatible object store. Stage 1 runs MinIO in compose, and the media already on the artifact volume is moved there.

**Architecture:**
- **The port.** A small synchronous `MediaStore` port has two implementations:
  - `LocalMediaStore`, below the artifact root, used when no S3 endpoint is configured;
  - `S3MediaStore`, on the `minio` SDK.
- **Activities.** Each media-touching activity works in a private `MediaScratch` directory laid out like the store. It pulls what it reads before the existing code runs, and pushes what it made afterwards. The acquisition, attribution, footage, and assembly internals keep working on file paths, unchanged.
- **Deploy.** A `media import` CLI copies the old files into the store. Each file is verified there, and a separate `--remove-local` pass deletes the local copies.

**Tech Stack:** Python 3.12, `minio` 7.2.x (PyPI latest is 7.2.20), `pgsty/minio` server image, Temporal activities, Typer CLI, docker compose, pytest.

**Spec:** `docs/superpowers/specs/2026-10-17-media-object-storage-design.md`. Read its "Corrections (planning, 2026-10-17)" section first; Task 11 adds it.

## Global Constraints

**Media and storage behaviour:**
- Locator = key. It has 1–512 characters in `/`-separated segments. Each segment matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, and the first segment is `reports`.
- Media store calls are synchronous. Async code calls them through `asyncio.to_thread`, so no storage I/O runs on the event loop.
- `import minio` happens in `preload_heavy_modules()` (worker), never lazily inside an activity.
- Existing media is moved, never deleted outright. A local file is removed only after its object verified identical, by size plus sha256 of a fetched copy, and only with `--remove-local`.
- `--remove-local` never touches `.json` files, `legacy-scout/`, or anything outside `<root>/reports/`.
- Secrets (`THOTH_MEDIA_S3_ACCESS_KEY`, `THOTH_MEDIA_S3_SECRET_KEY`) are `SecretStr`. They are never logged, printed, or put in an error message.

**Deployment and images:**
- S3 server image: `pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372`. This is MinIO RELEASE.2026-08-04. The official `minio/minio` image is no longer pullable; the operator chose `pgsty/minio` on 2026-10-17.
- Python client pin: `minio>=7.2.20,<8`. Version 8 renames keyword arguments (`metadata` becomes `user_metadata`).
- Bucket name: `thoth-media`, private, with no published port.

**Repository rules:**
- Tests are offline only. The conftest guard blocks non-loopback hosts, and MinIO tests use `127.0.0.1`.
- Commits use exactly one `git commit -m "<subject>"`: no body, no trailer, no AI attribution.
- Repository artifacts are in English.
- Never stage `.superpowers/`, `design/`, `graphify-out/`, `.serena/`, or the `.codegraph` DB. `docs/superpowers/` is gitignored: add plan and spec files with `git add -f`.
- Run tests from WSL:
  - `make test T=<path relative to python/>`, for example `make test T=tests/infrastructure/test_media_store.py`;
  - `make lint`;
  - `make test-minio`, the new target.

## Review Focus

1. **MinIO goes down between acquisition and the report write.**
   - Expected: the activity returns `artifact_persistence_failed` (retryable). No report row is written that points at media the store does not hold.
   - Pinned in Task 4: `test_a_store_outage_while_pushing_media_fails_before_the_report_is_stored`.
2. **A report carries an unsafe media locator** (absolute, backslash, `..`).
   - Expected: nothing outside the scratch directory or the `reports/` key space is read, written, or deleted.
   - Pinned in Task 3 (`test_pull_skips_and_push_refuses_an_unsafe_locator`) and by the existing canary test in Task 4.
3. **An activity is cancelled mid-run.**
   - Expected: its scratch directory is still removed, with no multi-GB leak in `/tmp`.
   - Pinned in Task 3: `test_the_scratch_directory_is_removed_when_the_body_raises`.
4. **The store lost an object after import, then `--remove-local` runs.**
   - Expected: the local file is kept.
   - Pinned in Task 9: `test_remove_local_keeps_a_file_whose_object_is_missing_or_different`.
5. **`media import` targets the very directory it reads from** (local store at the same root).
   - Expected: `--remove-local` refuses instead of verifying a file against itself and deleting it.
   - Pinned in Task 9: `test_remove_local_refuses_a_local_store_on_the_same_root`.

---

## File map

**Create:**
- `python/src/thoth_control_plane/infrastructure/media_store.py`: the port, errors, the locator check, `LocalMediaStore`, `build_media_store`, and `sha256_file`.
- `python/src/thoth_control_plane/infrastructure/s3_media_store.py`: `S3MediaStore`.
- `python/src/thoth_control_plane/activities/media_scratch.py`: `MediaScratch`, `media_locations`, and `report_media_locations`.
- `python/src/thoth_control_plane/operations/media_import.py`: `import_media` and `remove_local_media`.
- `scripts/dev/pytest-minio.sh`.
- Tests:
  - `python/tests/infrastructure/test_media_store.py`;
  - `python/tests/activities/test_media_scratch.py`;
  - `python/tests/operations/test_media_import.py`.

**Modify:**
- Settings, CLI, and worker:
  - `python/src/thoth_control_plane/config.py`: settings;
  - `python/src/thoth_control_plane/cli.py`: the `media import` command;
  - `python/src/thoth_control_plane/worker.py`: preload, store check, wiring.
- Activities:
  - `python/src/thoth_control_plane/activities/source_investigation.py`;
  - `python/src/thoth_control_plane/activities/source_attribution.py`;
  - `python/src/thoth_control_plane/activities/footage.py`;
  - `python/src/thoth_control_plane/activities/content_assembly.py`.
- Python project: `python/pyproject.toml` and `python/uv.lock` (the `minio` dependency).
- Operations:
  - `python/src/thoth_control_plane/operations/stage1_local_preflight.py`: required secrets;
  - `scripts/dev/pytest-wsl.sh`: `--with minio`;
  - `scripts/ops/deploy-stage1.sh`;
  - `Makefile`.
- Deployment config:
  - `compose.stage1.local.yml`;
  - `.env.stage1.local.example`;
  - `.github/workflows/container-image.yml`.
- Deployment tests:
  - `python/tests/deployment/test_local_stage1_compose_contract.py`;
  - `python/tests/deployment/test_container_contract.py`, only where it asserts the changed lines.
- Activity and worker tests:
  - `python/tests/activities/test_source_investigation.py`;
  - `python/tests/activities/test_source_attribution.py`;
  - `python/tests/activities/test_footage.py`;
  - `python/tests/activities/test_content_assembly.py`;
  - `python/tests/test_worker.py`.
- Docs:
  - `docs/superpowers/specs/2026-10-17-media-object-storage-design.md`: Corrections section;
  - `CHANGELOG.md` (CRLF).

---

### Task 1: The `MediaStore` port and `LocalMediaStore`

**Files:**
- Create: `python/src/thoth_control_plane/infrastructure/media_store.py`
- Modify: `python/src/thoth_control_plane/config.py`. Add the setting after `THOTH_FOOTAGE_QUERY_MODEL`, near line 101.
- Test: `python/tests/infrastructure/test_media_store.py`

**Interfaces:**
- Produces:
  - `MediaUnavailable(LookupError)`, `MediaStoreUnavailable(RuntimeError)`, and `MediaLocatorInvalid(ValueError)`;
  - `MediaStat(size_bytes: int, sha256: str | None)`;
  - the `MediaStore` Protocol, with `put_file(location: str, path: Path) -> None`, `fetch(location: str, destination: Path) -> None`, `stat(location: str) -> MediaStat`, `delete(location: str) -> None`, `list(prefix: str) -> list[str]`, and `check() -> None`;
  - `checked_locator(location: str) -> str`;
  - `sha256_file(path: Path) -> str` (hex);
  - `LocalMediaStore(root: Path)`, with a `.root` property;
  - `build_media_store(settings: Settings) -> MediaStore`.
- Settings: `THOTH_MEDIA_SCRATCH_DIR: Path | None = None`.

- [ ] **Step 1: Write the failing tests**

```python
"""The media store contract (spec 2026-10-17); every store implementation passes the same tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaLocatorInvalid,
    MediaStoreUnavailable,
    MediaUnavailable,
    build_media_store,
    sha256_file,
)

LOCATION = "reports/wf_a/media/tiktok-1.mp4"
STORES = ["local"]


@pytest.fixture(params=STORES)
def store(request: pytest.FixtureRequest, tmp_path: Path):
    root = tmp_path / "store"
    root.mkdir()
    return LocalMediaStore(root)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_a_put_file_is_fetched_back_byte_for_byte(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "in.mp4", b"video-bytes" * 100)
    store.put_file(LOCATION, source)
    target = tmp_path / "out" / "copy.mp4"
    store.fetch(LOCATION, target)
    assert target.read_bytes() == source.read_bytes()


def test_stat_reports_size_and_sha256(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "in.png", b"png" * 7)
    store.put_file("reports/wf_a/cards/profile.png", source)
    stat = store.stat("reports/wf_a/cards/profile.png")
    assert stat.size_bytes == 21
    assert stat.sha256 == sha256_file(source)


def test_a_second_put_replaces_the_object(store, tmp_path: Path) -> None:
    store.put_file(LOCATION, _file(tmp_path, "a.mp4", b"first"))
    store.put_file(LOCATION, _file(tmp_path, "b.mp4", b"second!"))
    assert store.stat(LOCATION).size_bytes == 7


def test_an_absent_object_is_unavailable(store, tmp_path: Path) -> None:
    with pytest.raises(MediaUnavailable):
        store.fetch(LOCATION, tmp_path / "x.mp4")
    with pytest.raises(MediaUnavailable):
        store.stat(LOCATION)
    assert not (tmp_path / "x.mp4").exists()


def test_deleting_twice_is_fine(store, tmp_path: Path) -> None:
    store.put_file(LOCATION, _file(tmp_path, "a.mp4", b"x"))
    store.delete(LOCATION)
    store.delete(LOCATION)
    with pytest.raises(MediaUnavailable):
        store.stat(LOCATION)


def test_list_returns_the_locators_below_a_prefix(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "a.mp4", b"x")
    for location in (
        "reports/wf_a/footage/b.mp4",
        "reports/wf_a/footage/a.mp4",
        "reports/wf_a/media/m.mp4",
        "reports/wf_b/footage/c.mp4",
    ):
        store.put_file(location, source)
    assert store.list("reports/wf_a/footage/") == [
        "reports/wf_a/footage/a.mp4",
        "reports/wf_a/footage/b.mp4",
    ]
    assert store.list("reports/wf_none/footage/") == []


@pytest.mark.parametrize(
    "location",
    [
        "",
        "/reports/wf_a/x.mp4",
        "reports/../x.mp4",
        "reports/wf_a/..",
        "reports\\wf_a\\x.mp4",
        "reports/wf_a/c:x.mp4",
        "reports//x.mp4",
        "reports/.hidden/x.mp4",
        "media/wf_a/x.mp4",
        "reports",
        "reports/" + "a" * 600,
    ],
)
def test_an_unsafe_locator_is_refused_before_any_io(store, tmp_path: Path, location: str) -> None:
    source = _file(tmp_path, "a.mp4", b"x")
    for call in (
        lambda: store.put_file(location, source),
        lambda: store.fetch(location, tmp_path / "y.mp4"),
        lambda: store.stat(location),
        lambda: store.delete(location),
    ):
        with pytest.raises(MediaLocatorInvalid):
            call()


def test_the_local_store_refuses_a_link_out_of_its_root(tmp_path: Path) -> None:
    root = tmp_path / "store"
    (root / "reports").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"secret")
    try:
        (root / "reports" / "wf_a").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available here")
    store = LocalMediaStore(root)
    with pytest.raises(MediaLocatorInvalid):
        store.fetch("reports/wf_a/secret.mp4", tmp_path / "copy.mp4")


def test_the_local_store_check_needs_its_root(tmp_path: Path) -> None:
    LocalMediaStore(tmp_path).check()
    with pytest.raises(MediaStoreUnavailable):
        LocalMediaStore(tmp_path / "absent").check()


def test_without_an_endpoint_the_store_is_local_on_the_artifact_root(tmp_path: Path) -> None:
    store = build_media_store(
        Settings(THOTH_CONTROL_PLANE_API_KEY="k", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path)
    )
    assert isinstance(store, LocalMediaStore)
    assert store.root == tmp_path.resolve()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test T=tests/infrastructure/test_media_store.py`
Expected: an ERROR at collection: `ModuleNotFoundError: No module named 'thoth_control_plane.infrastructure.media_store'`.

- [ ] **Step 3: Add the scratch setting**

In `config.py`, inside `class Settings`, after `THOTH_FOOTAGE_QUERY_MODEL: …`:

```python
    # Where activities stage media for ffmpeg and the models; None is the system temp directory.
    THOTH_MEDIA_SCRATCH_DIR: Path | None = None
```

- [ ] **Step 4: Write `media_store.py`**

```python
"""Workflow media storage (spec 2026-10-17): the port, its errors, and the local store.

A locator is the key: `reports/<id>/<kind>/<name>`, the same string reports, Temporal history,
and footage rows already hold. Calls are synchronous like `Reports`; async callers wrap them in
`asyncio.to_thread`.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from thoth_control_plane.config import Settings

#: The same segment rule as `LocalArtifactRoot`: no dot-segment, separator, or colon.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PREFIX = "reports"
_CHUNK = 1024 * 1024


class MediaUnavailable(LookupError):
    """No object is stored at this locator."""


class MediaStoreUnavailable(RuntimeError):
    """The store could not be reached or refused the request."""


class MediaLocatorInvalid(ValueError):
    """The locator is not a safe media key."""


@dataclass(frozen=True)
class MediaStat:
    size_bytes: int
    sha256: str | None  # hex; None when the object carries no recorded digest


class MediaStore(Protocol):
    def put_file(self, location: str, path: Path) -> None: ...

    def fetch(self, location: str, destination: Path) -> None: ...

    def stat(self, location: str) -> MediaStat: ...

    def delete(self, location: str) -> None: ...

    def list(self, prefix: str) -> list[str]: ...

    def check(self) -> None: ...


def checked_locator(location: str) -> str:
    """The locator itself, or `MediaLocatorInvalid`; runs before any key or path is built."""
    if not isinstance(location, str) or not 0 < len(location) <= 512:
        raise MediaLocatorInvalid("media_locator_invalid")
    segments = location.split("/")
    if (
        len(segments) < 2
        or segments[0] != _PREFIX
        or not all(_SEGMENT.fullmatch(segment) for segment in segments)
    ):
        raise MediaLocatorInvalid("media_locator_invalid")
    return location


def checked_prefix(prefix: str) -> str:
    """A listing prefix: a valid locator followed by one `/`."""
    if not prefix.endswith("/"):
        raise MediaLocatorInvalid("media_locator_invalid")
    checked_locator(prefix[:-1])
    return prefix


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.part")
    try:
        shutil.copyfile(source, partial)
        os.replace(partial, destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


class LocalMediaStore:
    """Media below one directory: the artifact root when no S3 endpoint is configured."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def put_file(self, location: str, path: Path) -> None:
        _copy(path, self._path(location))

    def fetch(self, location: str, destination: Path) -> None:
        source = self._path(location)
        if not source.is_file():
            raise MediaUnavailable("media_unavailable")
        _copy(source, destination)

    def stat(self, location: str) -> MediaStat:
        path = self._path(location)
        if not path.is_file():
            raise MediaUnavailable("media_unavailable")
        return MediaStat(size_bytes=path.stat().st_size, sha256=sha256_file(path))

    def delete(self, location: str) -> None:
        self._path(location).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        base = self._path(checked_prefix(prefix)[:-1])
        if not base.is_dir():
            return []
        return sorted(
            path.relative_to(self._root).as_posix()
            for path in base.rglob("*")
            if path.is_file() and not path.is_symlink() and not path.name.endswith(".part")
        )

    def check(self) -> None:
        if not self._root.is_dir():
            raise MediaStoreUnavailable("media_root_missing")

    def _path(self, location: str) -> Path:
        """Join a checked locator below the root, refusing any link along the way."""
        candidate = self._root.joinpath(*checked_locator(location).split("/"))
        current = self._root
        for segment in location.split("/"):
            current = current / segment
            if current.is_symlink():
                raise MediaLocatorInvalid("media_locator_invalid")
        if not candidate.resolve().is_relative_to(self._root):
            raise MediaLocatorInvalid("media_locator_invalid")
        return candidate


def build_media_store(settings: Settings) -> MediaStore:
    """The local store on the artifact root; Task 2 adds the S3 store for a configured endpoint."""
    return LocalMediaStore(settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT)
```

- [ ] **Step 5: Run the tests**

Run: `make test T=tests/infrastructure/test_media_store.py`
Expected: every test passes. On WSL the symlink test runs, not skips.

- [ ] **Step 6: Lint and commit**

Run `make lint`; expected: clean. Then:

```bash
git add python/src/thoth_control_plane/infrastructure/media_store.py python/src/thoth_control_plane/config.py python/tests/infrastructure/test_media_store.py
git commit -m "feat(media): add the media store port and its local store"
```

---

### Task 2: `S3MediaStore`, the `minio` dependency, `make test-minio`, and CI

**Files:**
- Create:
  - `python/src/thoth_control_plane/infrastructure/s3_media_store.py`
  - `scripts/dev/pytest-minio.sh`
- Modify:
  - `python/src/thoth_control_plane/config.py`: S3 settings;
  - `python/src/thoth_control_plane/infrastructure/media_store.py`: `build_media_store`;
  - `python/pyproject.toml` and `python/uv.lock`;
  - `scripts/dev/pytest-wsl.sh`;
  - `Makefile`;
  - `.github/workflows/container-image.yml`: the quality job.
- Test: `python/tests/infrastructure/test_media_store.py`

**Interfaces:**
- Consumes (from Task 1): `MediaStat`, the three error classes, `checked_locator`, `checked_prefix`, `sha256_file`, and `build_media_store`.
- Produces:
  - `S3MediaStore(client: minio.Minio, bucket: str)`, with all `MediaStore` methods;
  - `S3MediaStore.from_settings(settings) -> S3MediaStore`;
  - `S3MediaStore.ensure_bucket() -> None`, which creates the private bucket when absent;
  - settings `THOTH_MEDIA_S3_ENDPOINT: str | None = None`, `THOTH_MEDIA_S3_BUCKET: str = "thoth-media"`, `THOTH_MEDIA_S3_ACCESS_KEY: SecretStr | None = None`, `THOTH_MEDIA_S3_SECRET_KEY: SecretStr | None = None`, and `THOTH_MEDIA_S3_SECURE: bool = False`.

- [ ] **Step 1: Add the dependency (WSL)**

Run:

```bash
cd python && ~/.local/bin/uv add 'minio>=7.2.20,<8'
```

Expected: `pyproject.toml` gains `"minio>=7.2.20,<8",` in `[project] dependencies`, and `uv.lock` updates. Also add `--with 'minio>=7.2.20,<8'` to the `uv run` line in `scripts/dev/pytest-wsl.sh`, right after `--with alembic`.

- [ ] **Step 2: Extend the contract tests to S3**

In `test_media_store.py`, replace `STORES = ["local"]` and the `store` fixture with:

```python
S3_ENDPOINT = os.environ.get("THOTH_TEST_MEDIA_S3_ENDPOINT", "")
REQUIRED = os.environ.get("THOTH_REQUIRE_MINIO_TESTS") == "1"
if REQUIRED and not S3_ENDPOINT:
    raise RuntimeError("THOTH_REQUIRE_MINIO_TESTS=1 but THOTH_TEST_MEDIA_S3_ENDPOINT is unset")

STORES = [
    "local",
    pytest.param(
        "s3", marks=pytest.mark.skipif(not S3_ENDPOINT, reason="needs a throwaway MinIO")
    ),
]


def _s3_client():
    from minio import Minio

    return Minio(
        S3_ENDPOINT,
        access_key=os.environ["THOTH_TEST_MEDIA_S3_ACCESS_KEY"],
        secret_key=os.environ["THOTH_TEST_MEDIA_S3_SECRET_KEY"],
        secure=False,
    )


@pytest.fixture(params=STORES)
def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "local":
        root = tmp_path / "store"
        root.mkdir()
        yield LocalMediaStore(root)
        return
    import uuid

    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    client = _s3_client()
    bucket = f"thoth-test-{uuid.uuid4().hex[:12]}"
    client.make_bucket(bucket)
    try:
        yield S3MediaStore(client, bucket)
    finally:
        for item in client.list_objects(bucket, recursive=True):
            client.remove_object(bucket, item.object_name)
        client.remove_bucket(bucket)
```

Append these tests:

```python
@pytest.mark.skipif(not S3_ENDPOINT, reason="needs a throwaway MinIO")
def test_the_s3_store_check_refuses_a_missing_bucket() -> None:
    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    store = S3MediaStore(_s3_client(), "thoth-test-absent-bucket")
    with pytest.raises(MediaStoreUnavailable):
        store.check()
    store.ensure_bucket()
    try:
        store.check()
    finally:
        _s3_client().remove_bucket("thoth-test-absent-bucket")


def test_an_unreachable_s3_store_is_unavailable_not_missing(tmp_path: Path) -> None:
    from minio import Minio

    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    import urllib3

    # Port 9 on loopback: nothing listens; no retries, so the request fails at once, offline.
    client = Minio(
        "127.0.0.1:9",
        access_key="a",
        secret_key="b",
        secure=False,
        http_client=urllib3.PoolManager(retries=urllib3.Retry(total=0)),
    )
    store = S3MediaStore(client, "thoth-media")
    with pytest.raises(MediaStoreUnavailable):
        store.stat(LOCATION)
    with pytest.raises(MediaStoreUnavailable):
        store.check()


def test_an_endpoint_without_both_keys_is_refused(tmp_path: Path) -> None:
    from thoth_control_plane.config import SettingsValidationError

    with pytest.raises(SettingsValidationError, match="media_s3_credentials_missing"):
        build_media_store(
            Settings(THOTH_CONTROL_PLANE_API_KEY="k", THOTH_MEDIA_S3_ENDPOINT="127.0.0.1:9")
        )


def test_an_endpoint_selects_the_s3_store(tmp_path: Path) -> None:
    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    store = build_media_store(
        Settings(
            THOTH_CONTROL_PLANE_API_KEY="k",
            THOTH_MEDIA_S3_ENDPOINT="127.0.0.1:9",
            THOTH_MEDIA_S3_ACCESS_KEY="a",
            THOTH_MEDIA_S3_SECRET_KEY="b",
        )
    )
    assert isinstance(store, S3MediaStore)
```

The unreachable-store test builds its client with `Retry(total=0)`. The SDK's default client retries with backoff and would take several seconds per call.

- [ ] **Step 3: Run and watch the new tests fail**

Run: `make test T=tests/infrastructure/test_media_store.py`
Expected: FAIL. The three non-skipped new tests fail with `ModuleNotFoundError: …s3_media_store` or a missing setting. The `s3`-parametrized cases are SKIPPED, because no MinIO is running.

- [ ] **Step 4: Add the S3 settings**

In `config.py`, after `THOTH_MEDIA_SCRATCH_DIR`:

```python
    # Workflow media in S3-compatible storage (spec 2026-10-17); unset keeps it on the volume.
    THOTH_MEDIA_S3_ENDPOINT: str | None = None
    THOTH_MEDIA_S3_BUCKET: str = "thoth-media"
    THOTH_MEDIA_S3_ACCESS_KEY: SecretStr | None = None
    THOTH_MEDIA_S3_SECRET_KEY: SecretStr | None = None
    THOTH_MEDIA_S3_SECURE: bool = False
```

- [ ] **Step 5: Write `s3_media_store.py`**

```python
"""Workflow media in an S3-compatible bucket (MinIO in Stage 1) through the `minio` SDK.

Every object records its sha256 as user metadata, so `stat` can compare without a download.
A `NoSuchKey` is `MediaUnavailable`; anything else that fails is `MediaStoreUnavailable`, whose
message is a fixed code: an SDK error can carry the endpoint and request details.
"""

from __future__ import annotations

import contextlib
import mimetypes
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import urllib3
from minio import Minio
from minio.error import MinioException, S3Error

from thoth_control_plane.infrastructure.media_store import (
    MediaStat,
    MediaStoreUnavailable,
    MediaUnavailable,
    checked_locator,
    checked_prefix,
    sha256_file,
)

if TYPE_CHECKING:
    from thoth_control_plane.config import Settings

_MISSING = frozenset({"NoSuchKey", "NoSuchObject", "NotFound", "ResourceNotFound"})
_SHA_KEY = "x-amz-meta-sha256"


@contextlib.contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except S3Error as error:
        if error.code in _MISSING:
            raise MediaUnavailable("media_unavailable") from None
        raise MediaStoreUnavailable("media_store_unavailable") from None
    except (MinioException, urllib3.exceptions.HTTPError):
        raise MediaStoreUnavailable("media_store_unavailable") from None


class S3MediaStore:
    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> S3MediaStore:
        from thoth_control_plane.config import SettingsValidationError

        access, secret = settings.THOTH_MEDIA_S3_ACCESS_KEY, settings.THOTH_MEDIA_S3_SECRET_KEY
        if not settings.THOTH_MEDIA_S3_ENDPOINT or access is None or secret is None:
            raise SettingsValidationError("media_s3_credentials_missing")
        http = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5.0, read=120.0),
            retries=urllib3.Retry(
                total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504)
            ),
        )
        client = Minio(
            settings.THOTH_MEDIA_S3_ENDPOINT,
            access_key=access.get_secret_value(),
            secret_key=secret.get_secret_value(),
            secure=settings.THOTH_MEDIA_S3_SECURE,
            http_client=http,
        )
        return cls(client, settings.THOTH_MEDIA_S3_BUCKET)

    def put_file(self, location: str, path: Path) -> None:
        key = checked_locator(location)
        digest = sha256_file(path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with _errors():
            self._client.fput_object(
                self._bucket,
                key,
                str(path),
                content_type=content_type,
                metadata={"sha256": digest},
            )

    def fetch(self, location: str, destination: Path) -> None:
        key = checked_locator(location)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # fget_object downloads to its own temporary name and renames it on success.
        with _errors():
            self._client.fget_object(self._bucket, key, str(destination))

    def stat(self, location: str) -> MediaStat:
        key = checked_locator(location)
        with _errors():
            found = self._client.stat_object(self._bucket, key)
        metadata = found.metadata or {}
        return MediaStat(size_bytes=int(found.size or 0), sha256=metadata.get(_SHA_KEY))

    def delete(self, location: str) -> None:
        key = checked_locator(location)
        with _errors():
            self._client.remove_object(self._bucket, key)

    def list(self, prefix: str) -> list[str]:
        checked_prefix(prefix)
        with _errors():
            return sorted(
                item.object_name
                for item in self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
                if item.object_name and not item.is_dir
            )

    def check(self) -> None:
        with _errors():
            present = self._client.bucket_exists(self._bucket)
        if not present:
            raise MediaStoreUnavailable("media_bucket_missing")

    def ensure_bucket(self) -> None:
        """Create the private bucket when absent (the deploy's media import does this once)."""
        with _errors():
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
```

Check after writing: `stat_object(...).metadata` is an `HTTPHeaderDict`, whose `.get` is case-insensitive in minio 7.2.x. If the s3 contract run shows `sha256=None`, read it with `metadata.get("X-Amz-Meta-Sha256")` and record a ledger Ruling.

- [ ] **Step 6: Make `build_media_store` choose S3**

Replace the function body in `media_store.py`:

```python
def build_media_store(settings: Settings) -> MediaStore:
    """S3 when an endpoint is configured; otherwise the artifact root, as before."""
    if not settings.THOTH_MEDIA_S3_ENDPOINT:
        return LocalMediaStore(settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT)
    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    return S3MediaStore.from_settings(settings)
```

- [ ] **Step 7: Write `scripts/dev/pytest-minio.sh`** (LF line endings; `chmod +x`)

```bash
#!/usr/bin/env bash
# Run the media store contract against a throwaway MinIO (the stack's own image), removed
# afterwards. A skipped MinIO test fails here (THOTH_REQUIRE_MINIO_TESTS=1).
#
#     bash scripts/dev/pytest-minio.sh [pytest args...]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image=pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372
name="thoth-test-minio-$$"
port=59000

docker run -d --rm --name "$name" -e MINIO_ROOT_USER=thoth-test \
    -e MINIO_ROOT_PASSWORD=thoth-test-secret -p "127.0.0.1:$port:9000" "$image" server /data >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$port/minio/health/live" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS "http://127.0.0.1:$port/minio/health/live" >/dev/null

[ "$#" -gt 0 ] || set -- tests/infrastructure/test_media_store.py
THOTH_TEST_MEDIA_S3_ENDPOINT="127.0.0.1:$port" \
THOTH_TEST_MEDIA_S3_ACCESS_KEY=thoth-test \
THOTH_TEST_MEDIA_S3_SECRET_KEY=thoth-test-secret \
THOTH_REQUIRE_MINIO_TESTS=1 \
    bash "$root/scripts/dev/pytest-wsl.sh" "$@"
```

- [ ] **Step 8: Add the Makefile target**

Add `test-minio` to `.PHONY`, then add the rule below `test-postgres`:

```make
test-minio: ## Media store tests on a throwaway MinIO (a skip is a failure)
	bash scripts/dev/pytest-minio.sh
```

- [ ] **Step 9: Run both stores**

Run: `make test T=tests/infrastructure/test_media_store.py`
Expected: the local cases and the three offline S3 tests pass; the `s3` cases skip.

Run: `make test-minio`
Expected: every test passes with 0 skipped, including the `[s3]` cases and the missing-bucket test.

- [ ] **Step 10: CI quality job runs the S3 contract**

In `.github/workflows/container-image.yml`, quality job:

1. Before the pytest step (the one with `THOTH_REQUIRE_POSTGRES_TESTS: "1"`), add a step. GitHub service containers cannot take a `command`, so this is a plain step:

```yaml
      - name: Start a throwaway MinIO for the media store contract
        run: |
          set -euo pipefail
          docker run -d --name thoth-ci-minio -p 127.0.0.1:9000:9000 \
            -e MINIO_ROOT_USER=thoth-test -e MINIO_ROOT_PASSWORD=thoth-test-secret \
            pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372 server /data
          for _ in $(seq 1 60); do
            curl -fsS http://127.0.0.1:9000/minio/health/live >/dev/null 2>&1 && break
            sleep 1
          done
          curl -fsS http://127.0.0.1:9000/minio/health/live >/dev/null
```

2. In the pytest step's `env:`, under `THOTH_REQUIRE_POSTGRES_TESTS: "1"`, add:

```yaml
          THOTH_TEST_MEDIA_S3_ENDPOINT: 127.0.0.1:9000
          THOTH_TEST_MEDIA_S3_ACCESS_KEY: thoth-test
          THOTH_TEST_MEDIA_S3_SECRET_KEY: thoth-test-secret
          THOTH_REQUIRE_MINIO_TESTS: "1"
```

Then run `make test T=tests/deployment`. If a contract test asserts the exact quality-job block (`test_container_contract.py` around line 150), extend its expected text with these lines, and nothing else. Also run `actionlint .github/workflows/container-image.yml` if it is installed (memory: workflow preflight); expected: no errors.

- [ ] **Step 11: Lint and commit**

Run `make lint` and `make test T=tests/infrastructure tests/deployment`; expected: green. Then:

```bash
git add python/pyproject.toml python/uv.lock python/src/thoth_control_plane/config.py python/src/thoth_control_plane/infrastructure/media_store.py python/src/thoth_control_plane/infrastructure/s3_media_store.py python/tests/infrastructure/test_media_store.py scripts/dev/pytest-minio.sh scripts/dev/pytest-wsl.sh Makefile .github/workflows/container-image.yml python/tests/deployment
git commit -m "feat(media): add the S3 media store and its MinIO contract tests"
```

---

### Task 3: `MediaScratch`

**Files:**
- Create: `python/src/thoth_control_plane/activities/media_scratch.py`
- Test: `python/tests/activities/test_media_scratch.py`

**Interfaces:**
- Consumes (from Task 1): `MediaStore`, `LocalMediaStore`, `MediaUnavailable`, `MediaLocatorInvalid`, and `checked_locator`.
- Produces:
  - `MediaScratch(store: MediaStore, parent: Path | None = None)`, an async context manager. Its `.root: Path` is set on enter. Methods:
    - `async pull(locations: Iterable[str]) -> list[str]` returns the fetched locators. Absent objects and unsafe locators are skipped.
    - `async push(locations: Iterable[str]) -> list[str]` returns the pushed locators. Locators with no local file are skipped; an unsafe locator raises `MediaLocatorInvalid`.
  - `media_locations(report: SourceReport | None) -> list[str]`, the media only;
  - `report_media_locations(report: SourceReport) -> list[str]`: media, comment cards, the profile card, and the post card.

- [ ] **Step 1: Write the failing tests**

```python
"""The per-activity media scratch directory (spec 2026-10-17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from thoth_control_plane.activities.media_scratch import (
    MediaScratch,
    media_locations,
    report_media_locations,
)
from thoth_control_plane.infrastructure.media_store import LocalMediaStore, MediaLocatorInvalid
from tests.activities.test_source_investigation import _load_fixture_report

LOCATION = "reports/wf_a/media/tiktok-1.mp4"


def _store(tmp_path: Path) -> LocalMediaStore:
    root = tmp_path / "store"
    root.mkdir()
    return LocalMediaStore(root)


async def test_pull_lays_files_out_like_the_store_and_skips_absent_ones(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "v.mp4"
    source.write_bytes(b"video")
    store.put_file(LOCATION, source)
    async with MediaScratch(store, tmp_path / "scratch") as scratch:
        fetched = await scratch.pull([LOCATION, "reports/wf_a/media/absent.mp4", LOCATION])
        assert fetched == [LOCATION]
        assert (scratch.root / LOCATION).read_bytes() == b"video"
        assert scratch.root.parent == tmp_path / "scratch"


async def test_push_uploads_what_exists_and_the_directory_is_removed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    async with MediaScratch(store) as scratch:
        made = scratch.root / "reports/wf_a/cards/profile.png"
        made.parent.mkdir(parents=True)
        made.write_bytes(b"png")
        pushed = await scratch.push(["reports/wf_a/cards/profile.png", "reports/wf_a/cards/no.png"])
        root = scratch.root
    assert pushed == ["reports/wf_a/cards/profile.png"]
    assert store.stat("reports/wf_a/cards/profile.png").size_bytes == 3
    assert not root.exists()


async def test_the_scratch_directory_is_removed_when_the_body_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        async with MediaScratch(_store(tmp_path), tmp_path / "scratch") as scratch:
            (scratch.root / "big.mp4").write_bytes(b"x" * 1024)
            raise RuntimeError("cancelled mid-run")
    assert list((tmp_path / "scratch").iterdir()) == []


async def test_pull_skips_and_push_refuses_an_unsafe_locator(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"canary")
    async with MediaScratch(_store(tmp_path)) as scratch:
        assert await scratch.pull([str(outside), "reports/../outside.mp4"]) == []
        with pytest.raises(MediaLocatorInvalid):
            await scratch.push(["reports/..\\..\\outside.mp4"])
    assert outside.read_bytes() == b"canary"


def test_report_locations_cover_media_and_every_card() -> None:
    report = _load_fixture_report()
    every = report_media_locations(report)
    assert media_locations(report) == [str(media.location) for media in report.media]
    assert set(media_locations(report)) <= set(every)
    cards = [str(c.card.location) for c in report.comments if c.card]
    assert set(cards) <= set(every)
    assert media_locations(None) == []
```

- [ ] **Step 2: Run and watch them fail**

Run: `make test T=tests/activities/test_media_scratch.py`
Expected: an ERROR at collection: `No module named 'thoth_control_plane.activities.media_scratch'`.

- [ ] **Step 3: Write `media_scratch.py`**

```python
"""Per-activity local copies of workflow media (spec 2026-10-17).

Code that needs a file path (ffmpeg, ORB, ONNX, OCR, yt-dlp) works in a private directory laid
out like the store, `<root>/<locator>`. The activity pulls what it reads, pushes what it made,
and the directory is removed when the activity leaves it, whatever the outcome.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.infrastructure.media_store import (
    MediaLocatorInvalid,
    MediaStore,
    MediaUnavailable,
    checked_locator,
)


def media_locations(report: SourceReport | None) -> list[str]:
    """The report's media files: what a reader of the post's video or images needs."""
    return [str(media.location) for media in report.media] if report is not None else []


def report_media_locations(report: SourceReport) -> list[str]:
    """Every file the report records: its media and every card."""
    locations = media_locations(report)
    locations += [str(comment.card.location) for comment in report.comments if comment.card]
    for card in (report.profile_card, report.post_card):
        if card is not None:
            locations.append(str(card.location))
    return locations


class MediaScratch:
    def __init__(self, store: MediaStore, parent: Path | None = None) -> None:
        self._store = store
        self._parent = parent
        self.root = Path()

    async def __aenter__(self) -> MediaScratch:
        if self._parent is not None:
            await asyncio.to_thread(self._parent.mkdir, parents=True, exist_ok=True)
        made = await asyncio.to_thread(tempfile.mkdtemp, prefix="thoth-media-", dir=self._parent)
        self.root = Path(made)
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await asyncio.to_thread(shutil.rmtree, self.root, True)

    async def pull(self, locations: Iterable[str]) -> list[str]:
        """Fetch each object to its place; an absent object or unsafe locator is left out, as a
        missing file was before. A store outage propagates."""
        fetched: list[str] = []
        for location in dict.fromkeys(locations):
            try:
                await asyncio.to_thread(self._store.fetch, location, self._path(location))
            except (MediaUnavailable, MediaLocatorInvalid):
                continue
            fetched.append(location)
        return fetched

    async def push(self, locations: Iterable[str]) -> list[str]:
        """Upload each file this activity made; a locator with no file here is left out."""
        pushed: list[str] = []
        for location in dict.fromkeys(locations):
            path = self._path(location)
            if not path.is_file():
                continue
            await asyncio.to_thread(self._store.put_file, location, path)
            pushed.append(location)
        return pushed

    def _path(self, location: str) -> Path:
        return self.root.joinpath(*checked_locator(location).split("/"))
```

- [ ] **Step 4: Run the tests**

Run: `make test T=tests/activities/test_media_scratch.py`
Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

```bash
git add python/src/thoth_control_plane/activities/media_scratch.py python/tests/activities/test_media_scratch.py
git commit -m "feat(media): add the per-activity media scratch directory"
```

---

### Task 4: Source investigation pushes its media through the store

**Files:**
- Modify: `python/src/thoth_control_plane/activities/source_investigation.py`. Touch `_cleanup_after_persistence_failure` (lines ~219-241), `_run` (lines ~244-345), and `build_source_investigation_activity` (lines ~358-389).
- Test: `python/tests/activities/test_source_investigation.py`

**Interfaces:**
- Consumes:
  - from Task 1: `MediaStore`, `LocalMediaStore`, the errors, and `build_media_store`;
  - from Task 3: `MediaScratch` and `report_media_locations`.
- Produces:
  - `_run(input_, artifact_root, runner, capability, reports, *, media: MediaStore | None = None, scratch_dir: Path | None = None)`. `media=None` means `LocalMediaStore(artifact_root)`.
  - `build_source_investigation_activity(settings, *, runner=None, capability=None, reports=None, media: MediaStore | None = None)`.

**Behavior:**
- The runner now gets the scratch root instead of the artifact root.
- After a report:
  1. push every recorded file;
  2. then store the report row;
  3. if either step fails, delete the pushed objects.
- Cleanup evidence (`_terminal_events`) inspects the scratch root before it is removed.

- [ ] **Step 1: Write the failing tests** (append to `test_source_investigation.py`)

```python
class _RecordingStore:
    """A media store that records calls and can fail like an unreachable MinIO."""

    def __init__(self, root: Path, *, down: bool = False) -> None:
        from thoth_control_plane.infrastructure.media_store import LocalMediaStore

        self.inner = LocalMediaStore(root)
        self.down = down
        self.deleted: list[str] = []

    def put_file(self, location: str, path: Path) -> None:
        from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable

        if self.down:
            raise MediaStoreUnavailable("media_store_unavailable")
        self.inner.put_file(location, path)

    def fetch(self, location: str, destination: Path) -> None:
        self.inner.fetch(location, destination)

    def stat(self, location: str):
        return self.inner.stat(location)

    def delete(self, location: str) -> None:
        self.deleted.append(location)
        self.inner.delete(location)

    def list(self, prefix: str) -> list[str]:
        return self.inner.list(prefix)

    def check(self) -> None:
        self.inner.check()


def _writing_runner(seen: list[Path]):
    async def runner(workflow_id: str, source_url: str, artifact_root: Path):
        del source_url
        seen.append(artifact_root)
        media_path = artifact_root / f"reports/{workflow_id}/media/tiktok-1234567890.mp4"
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(b"0" * 10_100)
        return AcquisitionResult(report=_load_fixture_report())

    return runner


@pytest.mark.asyncio
async def test_acquired_media_lands_in_the_store_not_the_artifact_root(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = _RecordingStore(store_root)
    seen: list[Path] = []
    configured = build_source_investigation_activity(
        _settings(tmp_path), runner=_writing_runner(seen), media=store
    )
    result = await configured(INPUT)

    assert result.failure is None
    location = f"reports/{INPUT.workflow_id}/media/tiktok-1234567890.mp4"
    assert store.stat(location).size_bytes == 10_100
    assert seen[0] != tmp_path and not seen[0].exists()  # a scratch root, removed afterwards
    assert not (tmp_path / location).exists()


@pytest.mark.asyncio
async def test_a_store_outage_while_pushing_media_fails_before_the_report_is_stored(
    tmp_path: Path, report_store
) -> None:
    store_root = tmp_path / "store"
    store_root.mkdir()
    configured = build_source_investigation_activity(
        _settings(tmp_path),
        runner=_writing_runner([]),
        reports=report_store,
        media=_RecordingStore(store_root, down=True),
    )
    result = await configured(INPUT)

    assert result.failure is not None
    assert result.failure.code == "artifact_persistence_failed"
    assert result.failure.retryable is True
    assert report_store.get(f"reports/{INPUT.workflow_id}/source-report.json") is None


@pytest.mark.asyncio
async def test_a_report_store_outage_deletes_the_pushed_media(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = _RecordingStore(store_root)
    configured = build_source_investigation_activity(
        _settings(tmp_path), runner=_writing_runner([]), reports=DownReports(), media=store
    )
    result = await configured(INPUT)

    location = f"reports/{INPUT.workflow_id}/media/tiktok-1234567890.mp4"
    assert result.failure is not None
    assert location in store.deleted
    assert not (store_root / location).exists()
```

Imports: `DownReports` and `report_store` come from `tests/conftest.py`, the same way other tests in this file use them. Add `from tests.conftest import DownReports` only if the file does not import it already. If `INPUT`'s workflow id differs from the fixture report's media locator id, use the fixture's media location string from `_load_fixture_report().media[0].location` instead of the f-string.

- [ ] **Step 2: Run and watch them fail**

Run: `make test T=tests/activities/test_source_investigation.py`
Expected: the three new tests FAIL with `TypeError: build_source_investigation_activity() got an unexpected keyword argument 'media'`. Every existing test passes.

- [ ] **Step 3: Implement**

Imports (top of `source_investigation.py`):

```python
from thoth_control_plane.activities.media_scratch import MediaScratch, report_media_locations
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaLocatorInvalid,
    MediaStore,
    MediaStoreUnavailable,
    MediaUnavailable,
    build_media_store,
)
```

Replace `_cleanup_after_persistence_failure` with:

```python
def _forget_media(media: MediaStore, locations: list[str]) -> None:
    """Delete every pushed file of a report that was not stored. An unsafe locator was never
    pushed, and a store that is down keeps what it has: the next attempt overwrites it."""
    for location in locations:
        with contextlib.suppress(MediaLocatorInvalid, MediaStoreUnavailable):
            media.delete(location)
```

Change `_run`'s signature to:

```python
async def _run(
    input_: SourceInvestigationActivityInput,
    artifact_root: Path,
    runner: AcquisitionRunner,
    capability: ScraplingCapability,
    reports: Reports,
    *,
    media: MediaStore | None = None,
    scratch_dir: Path | None = None,
) -> SourceInvestigationActivityResult:
```

Leave the platform and capability branches as they are; they still pass `artifact_root` to `_terminal_events`.

Replace everything from `try: acquisition_result = await runner(` to the final `return SourceInvestigationActivityResult(report=artifact, events=events)` with the block below. The `failure` and `report is None` branches keep their bodies, with `root` in place of `artifact_root`.

```python
    store = media or LocalMediaStore(artifact_root)
    async with MediaScratch(store, scratch_dir) as scratch:
        root = scratch.root
        try:
            acquisition_result = await runner(
                input_.workflow_id, str(input_.canonical_source_url), root
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return SourceInvestigationActivityResult(
                failure=SafeActivityError(code="acquisition_runner_failed", retryable=False),
                events=_terminal_events([], root, input_.workflow_id, platform),
            )

        if acquisition_result.failure is not None:
            return SourceInvestigationActivityResult(
                failure=SafeActivityError(
                    code=acquisition_result.failure.code,
                    retryable=acquisition_result.failure.retryable,
                ),
                events=_terminal_events(
                    acquisition_result.failure.attempts,
                    root,
                    input_.workflow_id,
                    platform,
                    acquisition_result.account,
                ),
            )

        report = acquisition_result.report
        assert report is not None  # AcquisitionResult guarantees exactly one outcome

        location = PurePosixPath("reports") / input_.workflow_id / "source-report.json"
        content = report.model_dump_json(indent=2, exclude_none=False).encode("utf-8")
        recorded = report_media_locations(report)

        try:
            # Media first: a stored report must never point at media the store lacks.
            await scratch.push(recorded)
            await asyncio.to_thread(reports.put, location.as_posix(), "source_report", content)
        except asyncio.CancelledError:
            # Not awaited: a cancelled activity must not block its loop on the store.
            threading.Thread(target=_forget_media, args=(store, recorded), daemon=True).start()
            raise
        except (
            MediaStoreUnavailable,
            MediaUnavailable,
            MediaLocatorInvalid,
            ReportStoreUnavailable,
            ReportInvalid,
        ):
            await asyncio.to_thread(_forget_media, store, recorded)
            return SourceInvestigationActivityResult(
                failure=SafeActivityError(code="artifact_persistence_failed", retryable=True),
                events=_terminal_events(
                    report.outcome.attempts,
                    root,
                    input_.workflow_id,
                    platform,
                    acquisition_result.account,
                ),
            )

        digest = sha256(content).hexdigest()
        artifact = ArtifactRef(
            artifact_id=f"art_source_{digest[:20]}",
            kind="source_report",
            label="Source investigation report",
            media_type="application/json",
            location=location.as_posix(),
            checksum=f"sha256:{digest}",
            size_bytes=len(content),
        )
        events = _terminal_events(
            report.outcome.attempts,
            root,
            input_.workflow_id,
            platform,
            acquisition_result.account,
        )
        return SourceInvestigationActivityResult(report=artifact, events=events)
```

Keep the existing comments that explained each branch, moving them inside the block. Add `import threading` at the top.

In `build_source_investigation_activity`, add `media: MediaStore | None = None` to its keyword parameters. Then:

```python
    selected_media = media or build_media_store(settings)
    scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR
```

The inner call becomes:

```python
        return await _run(
            input_,
            artifact_root,
            selected_runner,
            selected_capability,
            selected_reports,
            media=selected_media,
            scratch_dir=scratch_dir,
        )
```

- [ ] **Step 4: Run the file**

Run: `make test T=tests/activities/test_source_investigation.py`
Expected: all tests pass. This includes the existing canary test (`test_cleanup_after_persistence_failure_never_touches_outside_artifact_root`), which now fails safe through `MediaLocatorInvalid` in `push`, and `test_cleanup_event_fails_when_part_file_remains`, which now writes its `.part` into the scratch root.

If a pre-existing test asserts a media file under `tmp_path` after success, it still passes: the default store is `LocalMediaStore(artifact_root)`.

- [ ] **Step 5: Lint and commit**

```bash
git add python/src/thoth_control_plane/activities/source_investigation.py python/tests/activities/test_source_investigation.py
git commit -m "feat(media): push acquired media through the store before the report"
```

---

### Task 5: Attribution reads the repost video and stores the original's media through the store

**Files:**
- Modify: `python/src/thoth_control_plane/activities/source_attribution.py`. Touch `RunnerAcquirer` (~lines 97-117), `_run` (~lines 179-244), and `build_source_attribution_activity` (~lines 280-293).
- Test: `python/tests/activities/test_source_attribution.py`

**Interfaces:**
- Consumes:
  - from Task 1: `MediaStore`, `LocalMediaStore`, and `build_media_store`;
  - from Task 3: `MediaScratch`, `media_locations`, and `report_media_locations`.
- Produces:
  - `ACQUISITION_ROOT: contextvars.ContextVar[Path]`, the scratch root of the running attribution;
  - `RunnerAcquirer(runner, artifact_root: Path | None = None)`, which acquires below `ACQUISITION_ROOT` when set and falls back to `artifact_root` otherwise;
  - `_run(input_, artifact_root, attributor, reports, *, media=None, scratch_dir=None)`;
  - `build_source_attribution_activity(settings, *, attributor=None, reports=None, media=None)`.

**Why a ContextVar:** `RunnerAcquirer` is built once, inside `_OnFirstUse`, but each attribution needs its own scratch root. A ContextVar carries the root into the attributor's tasks without changing the `SourceAttributor` port.

- [ ] **Step 1: Write the failing tests** (append to `test_source_attribution.py`)

Reuse what the file already has: `_report`/fixture helpers, `ORIGINAL`, and the fake attributor and fake `AttributionOutcome` builders used by the existing `_run` tests (lines ~80-180). Copy the existing setup that writes a repost report into the `report_store` fixture.

```python
@pytest.mark.asyncio
async def test_attribution_reads_the_repost_video_from_the_store(tmp_path: Path, report_store) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    store = LocalMediaStore(store_root)
    report = _stored_repost_report(report_store)  # the helper the existing _run tests use
    video = next(m for m in report.media if m.kind == "video")
    source = tmp_path / "repost.mp4"
    source.write_bytes(b"repost-video")
    store.put_file(str(video.location), source)

    seen: list[Path | None] = []

    class Seeing:
        async def identify(self, workflow_id, report, video):
            seen.append(video)
            assert video is not None and video.read_bytes() == b"repost-video"
            return _outcome_without_original()  # the helper the existing tests use

    await _run(
        SourceAttributionActivityInput(workflow_id=WORKFLOW_ID),
        tmp_path / "unused-root",
        Seeing(),
        report_store,
        media=store,
    )
    assert seen and seen[0] is not None and not seen[0].exists()  # scratch removed afterwards


@pytest.mark.asyncio
async def test_the_original_media_is_pushed_and_candidate_acquisition_uses_the_scratch(
    tmp_path: Path, report_store
) -> None:
    from thoth_control_plane.activities.source_attribution import ACQUISITION_ROOT
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    store = LocalMediaStore(store_root)
    _stored_repost_report(report_store)
    candidate = f"{WORKFLOW_ID}-c1"

    class Finding:
        async def identify(self, workflow_id, report, video):
            root = ACQUISITION_ROOT.get()
            original = _original_report(candidate)  # media under reports/<candidate>/media/
            for media in original.media:
                path = root / str(media.location)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"original-video")
            return _outcome_with_original(candidate, original)

    await _run(
        SourceAttributionActivityInput(workflow_id=WORKFLOW_ID),
        tmp_path / "unused-root",
        Finding(),
        report_store,
        media=store,
    )
    original = _original_report(candidate)
    for media in original.media:
        assert store.stat(str(media.location)).size_bytes == len(b"original-video")


@pytest.mark.asyncio
async def test_the_runner_acquirer_follows_the_running_scratch_root(tmp_path: Path) -> None:
    from thoth_control_plane.activities.source_attribution import ACQUISITION_ROOT

    roots: list[Path] = []

    async def runner(workflow_id: str, source_url: str, artifact_root: Path):
        roots.append(artifact_root)
        return AcquisitionResult(report=None, failure=_safe_failure())  # existing helper

    acquirer = RunnerAcquirer(runner, tmp_path / "fallback")
    token = ACQUISITION_ROOT.set(tmp_path / "scratch")
    try:
        await acquirer.acquire("wf_a-c1", ORIGINAL)
    finally:
        ACQUISITION_ROOT.reset(token)
    await acquirer.acquire("wf_a-c2", ORIGINAL)
    assert roots == [tmp_path / "scratch", tmp_path / "fallback"]
```

**Helper note.** The names `_stored_repost_report`, `_outcome_without_original`, `_outcome_with_original`, `_original_report`, `_safe_failure`, and `WORKFLOW_ID` stand for whatever the existing `_run` tests in this file already use to:
- seed the repost report;
- build an `AttributionOutcome` with and without `original`;
- build an acquisition failure.

Read lines 1-185 first and reuse those helpers. Where one does not exist, add it as a small module-level function in the test file, built the same way the existing tests build the value inline. Ledger a Ruling naming the helpers you added.

- [ ] **Step 2: Run and watch them fail**

Run: `make test T=tests/activities/test_source_attribution.py`
Expected: FAIL with `ImportError: cannot import name 'ACQUISITION_ROOT'` or `TypeError: _run() got an unexpected keyword argument 'media'`.

- [ ] **Step 3: Implement**

Imports:

```python
import contextvars

from thoth_control_plane.activities.media_scratch import MediaScratch, report_media_locations
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaStore,
    build_media_store,
)
```

Module level, after `Verdict`:

```python
#: The running attribution's scratch root: candidates are acquired below it (spec 2026-10-17).
ACQUISITION_ROOT: contextvars.ContextVar[Path] = contextvars.ContextVar("attribution_root")
```

`RunnerAcquirer`:

```python
class RunnerAcquirer:
    """Acquire candidates through the production runner, each under its own report key, below
    the running attribution's scratch root (or the given root outside an attribution)."""

    def __init__(self, runner: AcquisitionRunner, artifact_root: Path | None = None) -> None:
        self._runner = runner
        self._fallback = artifact_root

    @property
    def _root(self) -> Path:
        root = ACQUISITION_ROOT.get(self._fallback)
        if root is None:
            raise RuntimeError("no acquisition root")
        return root

    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None:
        root = self._root
        result = await self._runner(candidate_id, url, root)
        if result.report is None:
            return None
        return AcquiredCandidate(candidate_id, result.report, _video(result.report, root))

    async def discard(self, candidate_id: str) -> None:
        if not re.fullmatch(OPAQUE_ID_PATTERN, candidate_id):
            return
        reports = (self._root / "reports").resolve()
        target = (reports / candidate_id).resolve()
        if target.parent == reports:
            await asyncio.to_thread(shutil.rmtree, target, True)
```

`_run`: change the signature to add `*, media: MediaStore | None = None, scratch_dir: Path | None = None`. After the `report is None` early return, wrap the rest of the body:

```python
    store = media or LocalMediaStore(artifact_root)
    async with MediaScratch(store, scratch_dir) as scratch:
        # The repost's first video: what `_video` hands the attributor.
        await scratch.pull([str(m.location) for m in report.media if m.kind == "video"][:1])
        token = ACQUISITION_ROOT.set(scratch.root)
        heartbeat = asyncio.create_task(_heartbeat())
        try:
            outcome = await attributor.identify(
                input_.workflow_id, report, _video(report, scratch.root)
            )
        except asyncio.CancelledError:
            raise
        except AttributionError as error:
            ...  # unchanged body
        except Exception:
            ...  # unchanged body
        finally:
            ACQUISITION_ROOT.reset(token)
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

        content = outcome.attribution.model_dump_json(indent=2).encode("utf-8")
        location = folder / ATTRIBUTION_FILE
        await asyncio.to_thread(reports.put, location.as_posix(), "source_attribution", content)
        attribution = _artifact("source_attribution", "Source attribution", location, content)
        original = None
        if outcome.original is not None:
            # The original's media goes up before its report row, as acquisition does.
            await scratch.push(report_media_locations(outcome.original.report))
            original_location = (
                PurePosixPath("reports") / outcome.original.candidate_id / REPORT_FILE
            )
            ...  # unchanged: put the original report, build `original`

        verdict = outcome.attribution.verdict
        elapsed = int((time.monotonic() - started) * 1000)
        return SourceAttributionActivityResult(...)  # unchanged
```

The `...` lines mean: keep the existing statements exactly as they are, only indented one level. A `MediaStoreUnavailable` from `pull` or `push` propagates and fails the activity, so Temporal retries it (spec "Errors and safety").

`build_source_attribution_activity`: add `media: MediaStore | None = None`, then:

```python
    selected_media = media or build_media_store(settings)
    scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR
    ...
        return await _run(
            input_, artifact_root, selected, selected_reports,
            media=selected_media, scratch_dir=scratch_dir,
        )
```

`_OnFirstUse` and `build_production_ports` keep passing `artifact_root`, now only as the acquirer's fallback.

- [ ] **Step 4: Run the attribution tests**

Run: `make test T=tests/activities/test_source_attribution.py`
Expected: all pass, the existing `RunnerAcquirer(runner, tmp_path)` tests included.

- [ ] **Step 5: Lint and commit**

```bash
git add python/src/thoth_control_plane/activities/source_attribution.py python/tests/activities/test_source_attribution.py
git commit -m "feat(media): run attribution on scratch media and store the original's files"
```

---

### Task 6: Footage pulls its inputs and pushes its clips

**Files:**
- Modify: `python/src/thoth_control_plane/activities/footage.py`. Touch `_run` (~lines 82-117) and `build_footage_activity` (~lines 182-197).
- Test: `python/tests/activities/test_footage.py`

**Interfaces:**
- Consumes:
  - from Task 1: `MediaStore`, `LocalMediaStore`, and `build_media_store`;
  - from Task 3: `MediaScratch` and `media_locations`.
- Produces:
  - `_run(input_, artifact_root, builder, reports, *, media=None, scratch_dir=None)`;
  - `build_footage_activity(settings, *, builder=None, reports=None, media=None)`.

**Behavior:**
- Before the build, pull:
  - the post's media;
  - the original's media;
  - every stored clip under `reports/<wf>/footage/`, so `_verify_admitted` finds clips admitted on an earlier attempt.
- The builder gets `artifact_root=scratch.root`.
- After a successful build, push every `reports/<wf>/footage/*.mp4` in the scratch.
- A failed build pushes nothing. Its retry reopens admitted clips whose files are missing, which is the footage service's existing contract (`footage/service.py` `_verify_admitted`).

- [ ] **Step 1: Write the failing test** (append to `test_footage.py`)

Reuse the file's existing `_run` test setup: the stored report helper and a fake builder that returns a `FootageResult`. Read the first 80 lines and copy how an existing test seeds `reports` and builds `FootageActivityInput`.

```python
@pytest.mark.asyncio
async def test_footage_works_on_pulled_media_and_pushes_its_clips(tmp_path: Path, report_store) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    store = LocalMediaStore(store_root)
    report = _seed_report(report_store)  # the existing helper that stores reports/wf_a/source-report.json
    main = report.media[0]
    source = tmp_path / "main.mp4"
    source.write_bytes(b"main-video")
    store.put_file(str(main.location), source)
    earlier = tmp_path / "earlier.mp4"
    earlier.write_bytes(b"admitted-before")
    store.put_file("reports/wf_a/footage/earlier.mp4", earlier)

    class Building:
        async def build(self, inputs):
            root = inputs.artifact_root
            assert (root / str(main.location)).read_bytes() == b"main-video"
            assert (root / "reports/wf_a/footage/earlier.mp4").read_bytes() == b"admitted-before"
            clip = root / "reports/wf_a/footage/new.mp4"
            clip.write_bytes(b"new-clip")
            (root / "reports/wf_a/footage/half.mp4.part").write_bytes(b"x")
            return FootageResult(status="ok", admitted=2)

    await _run(_input("wf_a"), tmp_path / "unused-root", Building(), report_store, media=store)

    assert store.stat("reports/wf_a/footage/new.mp4").size_bytes == len(b"new-clip")
    assert store.list("reports/wf_a/footage/") == [
        "reports/wf_a/footage/earlier.mp4",
        "reports/wf_a/footage/new.mp4",
    ]
```

`_seed_report` and `_input` stand for the existing setup in `test_footage.py`; reuse it, or add the minimal helper and ledger a Ruling. `FootageResult` is imported from `thoth_control_plane.footage.service` (or wherever the file already imports it from).

- [ ] **Step 2: Run and watch it fail**

Run: `make test T=tests/activities/test_footage.py`
Expected: FAIL with `TypeError: _run() got an unexpected keyword argument 'media'`.

- [ ] **Step 3: Implement**

Imports:

```python
from thoth_control_plane.activities.media_scratch import MediaScratch, media_locations
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaStore,
    build_media_store,
)
```

`_run`: change the signature to add `*, media: MediaStore | None = None, scratch_dir: Path | None = None`. Replace the block from `inputs = FootageInputs(` to the end of the `finally:` with:

```python
    attribution = await _attribution(reports, input_.attribution)
    original = await _original(reports, input_.original_report)
    store = media or LocalMediaStore(artifact_root)
    clips = f"reports/{input_.workflow_id}/footage/"
    async with MediaScratch(store, scratch_dir) as scratch:
        stored_clips = await asyncio.to_thread(store.list, clips)
        await scratch.pull([*media_locations(report), *media_locations(original), *stored_clips])
        inputs = FootageInputs(
            workflow_id=input_.workflow_id,
            report=report,
            attribution=attribution,
            original=original,
            artifact_root=scratch.root,
        )
        heartbeat = asyncio.create_task(_heartbeat())
        try:
            result = await builder.build(inputs)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            if not isinstance(code, str) or not _CODE.fullmatch(code):
                code = "footage_failed"
            logger.warning("footage failed: %s", code)
            raise ApplicationError(code, type="FootageFailed") from None
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        # Only after success: a failed attempt's retry reopens admitted clips it cannot find.
        folder = scratch.root / clips
        made = sorted(path.name for path in folder.glob("*.mp4") if path.is_file())
        await scratch.push(f"{clips}{name}" for name in made)
    return _done(result.status, result.admitted, started)
```

Keep the existing comments: "Read before the try…" goes above the two `await _attribution/_original` lines, and "Only a code reaches Temporal history…" stays above `code = …`.

`build_footage_activity`: add `media: MediaStore | None = None`, then:

```python
    selected_media = media or build_media_store(settings)
    scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR
    ...
        return await _run(
            input_, artifact_root, selected, selected_reports,
            media=selected_media, scratch_dir=scratch_dir,
        )
```

- [ ] **Step 4: Run**

Run: `make test T=tests/activities/test_footage.py`
Expected: all pass.

Also run: `make test T=tests/footage/test_service.py`
Expected: unchanged and green; the service is untouched.

- [ ] **Step 5: Lint and commit**

```bash
git add python/src/thoth_control_plane/activities/footage.py python/tests/activities/test_footage.py
git commit -m "feat(media): build footage on pulled media and push the admitted clips"
```

---

### Task 7: Content assembly reads the main video from the store

**Files:**
- Modify: `python/src/thoth_control_plane/activities/content_assembly.py`. Touch `_run` (~lines 109-160) and `build_content_assembly_activity` (~lines 208-222).
- Test: `python/tests/activities/test_content_assembly.py`

**Interfaces:**
- Consumes:
  - from Task 1: `MediaStore`, `LocalMediaStore`, and `build_media_store`;
  - from Task 3: `MediaScratch` and `media_locations`.
- Produces:
  - `_run(input_, artifact_root, assembler, reports, *, media=None, scratch_dir=None)`;
  - `build_content_assembly_activity(settings, *, assembler=None, reports=None, media=None)`.

- [ ] **Step 1: Write the failing test** (append to `test_content_assembly.py`, reusing its `_run` call helper at line ~75 and its report seeding)

```python
@pytest.mark.asyncio
async def test_assembly_reads_the_main_video_from_the_store(tmp_path: Path, report_store) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    store = LocalMediaStore(store_root)
    report = _seed_report(report_store)  # the file's existing helper for reports/wf_a/source-report.json
    video = next(m for m in report.media if m.kind == "video")
    source = tmp_path / "main.mp4"
    source.write_bytes(b"main-video")
    store.put_file(str(video.location), source)
    roots: list[Path] = []

    class Reading:
        async def build(self, inputs):
            roots.append(inputs.artifact_root)
            assert (inputs.artifact_root / str(video.location)).read_bytes() == b"main-video"
            return _content_set()  # the file's existing ContentSet fixture builder

    result = await _run(
        ContentAssemblyActivityInput(workflow_id="wf_a"),
        tmp_path / "unused-root",
        Reading(),
        report_store,
        media=store,
    )
    assert result.content_set is not None
    assert roots and not roots[0].exists()
```

- [ ] **Step 2: Run and watch it fail**

Run: `make test T=tests/activities/test_content_assembly.py`
Expected: FAIL with `TypeError: _run() got an unexpected keyword argument 'media'`.

- [ ] **Step 3: Implement**

Imports as in Task 6, without `build_media_store` if it is unused there; it is used in the builder. In `_run`, change the signature to add the two keyword parameters. Replace the block from `inputs = AssemblyInputs(` through the `finally:` with:

```python
    attribution = await _attribution(reports, input_.attribution)
    original = await _original(reports, input_.original_report)
    store = media or LocalMediaStore(artifact_root)
    async with MediaScratch(store, scratch_dir) as scratch:
        await scratch.pull([*media_locations(report), *media_locations(original)])
        inputs = AssemblyInputs(
            workflow_id=input_.workflow_id,
            report=report,
            attribution=attribution,
            original=original,
            artifact_root=scratch.root,
        )
        heartbeat = asyncio.create_task(_heartbeat())
        try:
            content_set = await assembler.build(inputs)
        except AssemblyError as error:
            logger.warning("content assembly failed: %s", error.code)
            return _failed(error.code, started)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
```

The rest of `_run` (writing the content set, building the result) stays after the `async with`, unchanged.

`build_content_assembly_activity`: add `media`, `selected_media = media or build_media_store(settings)`, and `scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR`, and pass both to `_run` as keywords.

- [ ] **Step 4: Run**

Run: `make test T=tests/activities/test_content_assembly.py`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
git add python/src/thoth_control_plane/activities/content_assembly.py python/tests/activities/test_content_assembly.py
git commit -m "feat(media): assemble content from the main video in the store"
```

---

### Task 8: The worker checks the store and wires it into every activity

**Files:**
- Modify: `python/src/thoth_control_plane/worker.py`
- Test: `python/tests/test_worker.py`

**Interfaces:**
- Consumes (from Tasks 1, 4-7): `build_media_store`, `MediaStore`, and the `media=` keyword of the four activity builders.
- Produces:
  - `check_media_store(settings: Settings) -> MediaStore`, which builds the store, calls `check()`, and returns it;
  - `build_source_investigation_worker(client, settings, *, runner=None, capability=None, reports=None, media: MediaStore | None = None)`;
  - `HEAVY_MODULES` gains `"minio"`.

- [ ] **Step 1: Write and update the failing tests**

In `test_worker.py`:

1. In `test_worker_configures_provider_logging_before_capability_check`, add:
   ```python
   monkeypatch.setattr(worker, "check_media_store", lambda settings: calls.append("media"))
   ```
   Change the expected list to `["json", "preload", "warm", "media", "logging", "capability"]`.
2. In `test_the_yt_dlp_check_runs_in_the_background_and_stops_with_the_worker` and `test_the_worker_sweeps_profiles_a_killed_worker_left_before_any_lease`, add:
   ```python
   monkeypatch.setattr(worker, "check_media_store", lambda settings: None)
   ```
3. Append:

```python
def test_minio_is_preloaded() -> None:
    assert "minio" in worker.HEAVY_MODULES


def test_the_worker_refuses_to_start_without_its_media_store(tmp_path: Path) -> None:
    from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable

    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key",
        THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path / "absent",
    )
    with pytest.raises(MediaStoreUnavailable):
        worker.check_media_store(settings)


def test_the_media_store_check_returns_the_checked_store(tmp_path: Path) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store = worker.check_media_store(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path)
    )
    assert isinstance(store, LocalMediaStore)
```

- [ ] **Step 2: Run and watch them fail**

Run: `make test T=tests/test_worker.py`
Expected: FAIL with `AttributeError: … has no attribute 'check_media_store'`, and the ordering assertion fails.

- [ ] **Step 3: Implement**

In `worker.py`:

```python
from thoth_control_plane.infrastructure.media_store import MediaStore, build_media_store
```

1. Append `"minio",` to `HEAVY_MODULES`, right after `"sherpa_onnx",`.

2. Add after `warm_up`:

```python
def check_media_store(settings: Settings) -> MediaStore:
    """Every activity reads or writes workflow media: an unreachable store stops the worker at
    startup, like a missing tool (spec 2026-10-17)."""
    store = build_media_store(settings)
    store.check()
    return store
```

3. `build_source_investigation_worker`: add `media: MediaStore | None = None` to its keyword parameters, set `media = media or build_media_store(settings)`, and pass `media=media` to all four builders:

```python
            build_source_investigation_activity(
                settings, runner=runner, capability=capability, reports=reports, media=media
            ),
            build_source_attribution_activity(settings, reports=reports, media=media),
            build_content_assembly_activity(settings, reports=reports, media=media),
            build_footage_activity(settings, reports=reports, media=media),
```

4. `run_worker`: right after `warm_up(runtime_settings)`, add `media = check_media_store(runtime_settings)`. Then pass it on:

```python
            build_source_investigation_worker(
                client, runtime_settings, capability=capability, reports=reports, media=media
            ),
```

- [ ] **Step 4: Run**

Run: `make test T=tests/test_worker.py`
Expected: all pass.

- [ ] **Step 5: Full suite, lint, commit**

Run `make lint` and `make test`. Expected: lint clean; the suite has no failures, with the previous total plus this plan's new tests passing (the baseline is 3849 passed, 29 skipped).

```bash
git add python/src/thoth_control_plane/worker.py python/tests/test_worker.py
git commit -m "feat(media): check the media store at worker startup and wire it in"
```

---

### Task 9: `thoth-control media import` and `--remove-local`

**Files:**
- Create: `python/src/thoth_control_plane/operations/media_import.py`
- Modify: `python/src/thoth_control_plane/cli.py`. Add the command after the `reports import` command, near line 92.
- Test: `python/tests/operations/test_media_import.py`

**Interfaces:**
- Consumes:
  - from Task 1: `MediaStore`, `LocalMediaStore`, `MediaUnavailable`, `MediaLocatorInvalid`, `checked_locator`, and `sha256_file`;
  - from Task 2: `S3MediaStore.from_settings` and `ensure_bucket`.
- Produces:
  - `MediaImportCounts(imported, present, invalid, mismatch)`;
  - `MediaRemovalCounts(removed, kept)`;
  - `import_media(root: Path, store: MediaStore) -> MediaImportCounts`;
  - `remove_local_media(root: Path, store: MediaStore) -> MediaRemovalCounts`;
  - CLI `thoth-control media import --artifact-root <root> [--remove-local]`.

**Rules:**
- **Scan scope:** the importer walks `<root>/reports/` and never follows a link.
- **Counted invalid:** a link (file or directory), a `.part`, a path that breaks the locator rule, or a file it cannot read.
- **Skipped, not counted:** `.json` files, because reports live in PostgreSQL.
- **Present:** the object exists with the same size, and the same recorded sha256. When no sha256 is recorded, a fetched copy must match.
- **Mismatch:** an existing object that differs. It is never overwritten. A fresh upload that fails its read-back is deleted again and also counted as a mismatch.

- [ ] **Step 1: Write the failing tests**

```python
"""Moving the media already on the volume into the store (spec 2026-10-17)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from thoth_control_plane import cli
from thoth_control_plane.cli import app
from thoth_control_plane.infrastructure.media_store import LocalMediaStore
from thoth_control_plane.operations.media_import import (
    MediaImportCounts,
    MediaRemovalCounts,
    import_media,
    remove_local_media,
)

VIDEO = "reports/wf_a/media/tiktok-1.mp4"
CARD = "reports/wf_a/cards/profile.png"
REPORT = "reports/wf_a/source-report.json"


def _write(root: Path, relative: str, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _volume_and_store(tmp_path: Path) -> tuple[Path, LocalMediaStore]:
    volume = tmp_path / "artifacts"
    volume.mkdir()
    store_root = tmp_path / "store"
    store_root.mkdir()
    return volume, LocalMediaStore(store_root)


def test_media_is_imported_and_report_json_is_left_alone(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, CARD, b"png")
    _write(volume, REPORT, b"{}")
    assert import_media(volume, store) == MediaImportCounts(2, 0, 0, 0)
    assert store.stat(VIDEO).size_bytes == 5
    assert store.list("reports/wf_a/") == [CARD, VIDEO]


def test_a_rerun_finds_everything_present(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    import_media(volume, store)
    assert import_media(volume, store) == MediaImportCounts(0, 1, 0, 0)


def test_a_different_object_is_a_mismatch_and_never_overwritten(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"local")
    store.put_file(VIDEO, _write(tmp_path, "other.mp4", b"stored-other"))
    assert import_media(volume, store) == MediaImportCounts(0, 0, 0, 1)
    assert store.stat(VIDEO).size_bytes == len(b"stored-other")


def test_links_partials_and_bad_names_are_invalid(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, "reports/wf_a/footage/half.mp4.part", b"x")
    _write(volume, "reports/wf_a/media/bad name.mp4", b"x")
    outside = _write(tmp_path, "outside/secret.mp4", b"secret")
    try:
        (volume / "reports/wf_a/media/link.mp4").symlink_to(outside)
        (volume / "reports/wf_b").symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available here")
    assert import_media(volume, store) == MediaImportCounts(1, 0, 4, 0)
    assert store.list("reports/wf_b/") == []


def test_an_unreadable_file_is_invalid(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, CARD, b"png")
    from thoth_control_plane.operations import media_import

    real = media_import.sha256_file

    def unreadable(path: Path) -> str:
        if path.name == "profile.png":
            raise PermissionError("denied")
        return real(path)

    monkeypatch.setattr(media_import, "sha256_file", unreadable)
    assert import_media(volume, store) == MediaImportCounts(1, 0, 1, 0)


def test_an_upload_that_fails_its_read_back_is_removed_and_counted(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")

    class Corrupting(LocalMediaStore):
        def fetch(self, location: str, destination: Path) -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"corrupt")

    corrupting = Corrupting(store.root)
    assert import_media(volume, corrupting) == MediaImportCounts(0, 0, 0, 1)
    assert store.list("reports/wf_a/") == []


def test_remove_local_deletes_only_verified_media(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, REPORT, b"{}")
    import_media(volume, store)
    assert remove_local_media(volume, store) == MediaRemovalCounts(removed=1, kept=0)
    assert not (volume / VIDEO).exists()
    assert not (volume / "reports/wf_a/media").exists()  # emptied folders go too
    assert (volume / REPORT).read_bytes() == b"{}"


def test_remove_local_keeps_a_file_whose_object_is_missing_or_different(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, CARD, b"png")
    store.put_file(CARD, _write(tmp_path, "other.png", b"different"))
    assert remove_local_media(volume, store) == MediaRemovalCounts(removed=0, kept=2)
    assert (volume / VIDEO).exists() and (volume / CARD).exists()


def test_remove_local_refuses_a_local_store_on_the_same_root(tmp_path: Path) -> None:
    volume = tmp_path / "artifacts"
    _write(volume, VIDEO, b"video")
    with pytest.raises(ValueError, match="media_store_is_the_volume"):
        remove_local_media(volume, LocalMediaStore(volume))
    assert (volume / VIDEO).exists()


class _CliStore(LocalMediaStore):
    def ensure_bucket(self) -> None:
        return None


def _cli(monkeypatch, store: LocalMediaStore, *args: str):
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_MEDIA_S3_ENDPOINT", "127.0.0.1:9")
    monkeypatch.setattr(
        cli.S3MediaStore, "from_settings", classmethod(lambda cls, settings: store)
    )
    return CliRunner().invoke(app, ["media", "import", *args])


def test_cli_prints_counts_only(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    result = _cli(monkeypatch, _CliStore(store.root), "--artifact-root", str(volume))
    assert result.exit_code == 0
    assert result.output.strip() == "imported=1 present=0 invalid=0 mismatch=0"


def test_cli_exits_one_on_a_mismatch(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"local")
    store.put_file(VIDEO, _write(tmp_path, "o.mp4", b"other"))
    result = _cli(monkeypatch, _CliStore(store.root), "--artifact-root", str(volume))
    assert result.exit_code == 1
    assert result.output.strip().endswith("mismatch=1")


def test_cli_remove_local_prints_its_counts(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    import_media(volume, store)
    result = _cli(
        monkeypatch, _CliStore(store.root), "--artifact-root", str(volume), "--remove-local"
    )
    assert result.exit_code == 0
    assert result.output.strip() == "removed=1 kept=0"


def test_cli_refuses_without_an_s3_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.delenv("THOTH_MEDIA_S3_ENDPOINT", raising=False)
    result = CliRunner().invoke(app, ["media", "import", "--artifact-root", str(tmp_path)])
    assert result.exit_code == 1
    assert result.output.strip() == "media store is not configured"
```

- [ ] **Step 2: Run and watch them fail**

Run: `make test T=tests/operations/test_media_import.py`
Expected: an ERROR at collection: `No module named 'thoth_control_plane.operations.media_import'`.

- [ ] **Step 3: Write `media_import.py`**

```python
"""Moving the media already on the artifact volume into the store (spec 2026-10-17).

The import copies and verifies, never overwrites and never deletes. `remove_local_media` is the
separate, operator-gated step that deletes a local file once its object verified identical.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaLocatorInvalid,
    MediaStore,
    MediaUnavailable,
    checked_locator,
    sha256_file,
)


@dataclass(frozen=True)
class MediaImportCounts:
    imported: int
    present: int
    invalid: int
    mismatch: int


@dataclass(frozen=True)
class MediaRemovalCounts:
    removed: int
    kept: int


def _candidates(root: Path) -> Iterator[tuple[Path, str | None]]:
    """Each media file below `<root>/reports/` with its locator, or None when it is invalid.
    Links are never followed; report JSON is skipped (it lives in PostgreSQL)."""
    reports = root / "reports"
    if not reports.is_dir() or reports.is_symlink():
        return
    for directory, folders, files in os.walk(reports, followlinks=False):
        here = Path(directory)
        for name in sorted(folders):
            if (here / name).is_symlink():
                yield here / name, None
        folders[:] = sorted(name for name in folders if not (here / name).is_symlink())
        for name in sorted(files):
            path = here / name
            if name.endswith(".json") and not path.is_symlink():
                continue
            if path.is_symlink() or not path.is_file() or name.endswith(".part"):
                yield path, None
                continue
            try:
                yield path, checked_locator(path.relative_to(root).as_posix())
            except MediaLocatorInvalid:
                yield path, None


def _matches(store: MediaStore, location: str, size: int, digest: str) -> bool:
    """True when a fetched copy of the object has this size and sha256."""
    with tempfile.TemporaryDirectory(prefix="thoth-media-verify-") as scratch:
        copy = Path(scratch) / "object"
        store.fetch(location, copy)
        return copy.stat().st_size == size and sha256_file(copy) == digest


def import_media(root: Path, store: MediaStore) -> MediaImportCounts:
    """Copy each media file that is not stored yet. `MediaStoreUnavailable` propagates."""
    imported = present = invalid = mismatch = 0
    for path, location in _candidates(root):
        if location is None:
            invalid += 1
            continue
        try:
            size, digest = path.stat().st_size, sha256_file(path)
        except OSError:
            invalid += 1
            continue
        try:
            existing = store.stat(location)
        except MediaUnavailable:
            existing = None
        if existing is not None:
            same = existing.size_bytes == size and (
                existing.sha256 == digest
                if existing.sha256 is not None
                else _matches(store, location, size, digest)
            )
            if same:
                present += 1
            else:
                mismatch += 1
            continue
        store.put_file(location, path)
        if _matches(store, location, size, digest):
            imported += 1
        else:
            store.delete(location)
            mismatch += 1
    return MediaImportCounts(imported, present, invalid, mismatch)


def remove_local_media(root: Path, store: MediaStore) -> MediaRemovalCounts:
    """Delete each local media file whose object verifies identical; keep every other file."""
    if isinstance(store, LocalMediaStore) and store.root == root.resolve():
        raise ValueError("media_store_is_the_volume")
    removed = kept = 0
    for path, location in _candidates(root):
        if location is None:
            kept += 1
            continue
        try:
            size, digest = path.stat().st_size, sha256_file(path)
            verified = _matches(store, location, size, digest)
        except (OSError, MediaUnavailable):
            verified = False
        if not verified:
            kept += 1
            continue
        path.unlink()
        removed += 1
    reports = root / "reports"
    for directory, _, _ in sorted(os.walk(reports, followlinks=False), reverse=True):
        if Path(directory) != reports:
            with contextlib.suppress(OSError):
                Path(directory).rmdir()  # only an empty folder goes
    return MediaRemovalCounts(removed, kept)
```

- [ ] **Step 4: Add the CLI command** (`cli.py`, after `reports_import`)

Imports:

```python
from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable
from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore
from thoth_control_plane.operations.media_import import import_media, remove_local_media
```

```python
media_app = typer.Typer(no_args_is_help=True)
app.add_typer(media_app, name="media")


@media_app.command("import")
def media_import(
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    remove_local: Annotated[bool, typer.Option("--remove-local")] = False,
) -> None:
    """Copy the volume's media into the S3 store and verify it; counts only."""
    settings = Settings()
    if not settings.THOTH_MEDIA_S3_ENDPOINT:
        typer.echo("media store is not configured")
        raise typer.Exit(1)
    if not artifact_root.is_dir():
        typer.echo("artifact root not found")
        raise typer.Exit(1)
    store = S3MediaStore.from_settings(settings)
    try:
        store.ensure_bucket()
        if remove_local:
            removal = remove_local_media(artifact_root, store)
            typer.echo(f"removed={removal.removed} kept={removal.kept}")
            if removal.kept:
                raise typer.Exit(1)
            return
        counts = import_media(artifact_root, store)
    except MediaStoreUnavailable:
        typer.echo("media store unavailable")
        raise typer.Exit(1) from None
    typer.echo(
        f"imported={counts.imported} present={counts.present} "
        f"invalid={counts.invalid} mismatch={counts.mismatch}"
    )
    if counts.invalid or counts.mismatch:
        raise typer.Exit(1)
```

`cli.py` imports `S3MediaStore` at module level, which pulls in `minio` for every CLI command. That is acceptable: the CLI is not on the worker's event loop.

- [ ] **Step 5: Run**

Run: `make test T=tests/operations/test_media_import.py`
Expected: all pass. The symlink test runs on WSL.

- [ ] **Step 6: Lint and commit**

```bash
git add python/src/thoth_control_plane/operations/media_import.py python/src/thoth_control_plane/cli.py python/tests/operations/test_media_import.py
git commit -m "feat(media): add the media import command and its verified local removal"
```

---

### Task 10: MinIO in compose, the preflight, CI, and the deploy step

**Files:**
- Modify:
  - `compose.stage1.local.yml`;
  - `.env.stage1.local.example`;
  - `python/src/thoth_control_plane/operations/stage1_local_preflight.py`;
  - `.github/workflows/container-image.yml`: the stack-smoke env and data dirs;
  - `scripts/ops/deploy-stage1.sh`.
- Test:
  - `python/tests/deployment/test_local_stage1_compose_contract.py`;
  - `python/tests/deployment/test_container_contract.py`, only where it asserts changed text;
  - the preflight tests, under `tests/operations/` (find them with `grep -rln REQUIRED_SECRET_VARIABLES python/tests`).

**Interfaces:**
- Consumes (from Task 9): `thoth-control media import --artifact-root /var/lib/thoth/artifacts`, which prints `imported=N present=N invalid=N mismatch=N`.
- Produces:
  - the compose service `minio`;
  - the env variables `THOTH_MEDIA_S3_ACCESS_KEY` and `THOTH_MEDIA_S3_SECRET_KEY`;
  - the deploy steps `media-store` and `import-media`.

- [ ] **Step 1: Write the failing contract tests** (append to `test_local_stage1_compose_contract.py`; it already has `_repo_text`, `_service_block`, `_service_env`, and `_env_file`)

```python
MINIO_IMAGE = (
    "pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372"
)


def test_minio_is_pinned_private_and_on_the_data_root() -> None:
    compose = _repo_text("compose.stage1.local.yml")
    minio = _service_block(compose, "minio")
    assert f"image: {MINIO_IMAGE}" in minio
    assert "ports:" not in minio
    assert "source: ${THOTH_STAGE1_DATA_ROOT:?set THOTH_STAGE1_DATA_ROOT}/minio" in minio
    assert "MINIO_ROOT_USER: ${THOTH_MEDIA_S3_ACCESS_KEY:?set THOTH_MEDIA_S3_ACCESS_KEY}" in minio
    assert (
        "MINIO_ROOT_PASSWORD: ${THOTH_MEDIA_S3_SECRET_KEY:?set THOTH_MEDIA_S3_SECRET_KEY}" in minio
    )
    assert "/minio/health/live" in minio
    assert "networks: [stage1-private]" in minio


def test_api_and_worker_reach_the_media_store() -> None:
    compose = _repo_text("compose.stage1.local.yml")
    for service in ("api", "worker"):
        block = _service_block(compose, service)
        assert "THOTH_MEDIA_S3_ENDPOINT: minio:9000" in block
        assert "THOTH_MEDIA_S3_BUCKET: thoth-media" in block
        assert "THOTH_MEDIA_S3_SECRET_KEY: ${THOTH_MEDIA_S3_SECRET_KEY:?" in block
        assert "minio:\n        condition: service_healthy" in block
    env_example = _env_file()
    assert "THOTH_MEDIA_S3_ACCESS_KEY=replace-with-local-secret" in env_example
    assert "THOTH_MEDIA_S3_SECRET_KEY=replace-with-local-secret" in env_example


def test_the_deploy_imports_media_before_the_new_worker_starts() -> None:
    deploy = _repo_text("scripts/ops/deploy-stage1.sh")
    order = [
        deploy.index("step import-reports"),
        deploy.index("step media-store"),
        deploy.index("step import-media"),
        deploy.index("step up"),
    ]
    assert order == sorted(order)
    assert "thoth-control media import" in deploy
    assert '*" invalid=0 mismatch=0"' in deploy
    assert "--remove-local" not in deploy  # removal is its own operator gate
```

In `test_editor_preview_adds_no_service_port_or_mount`, insert `"  minio:",` into the expected service list, between `"  legacy-cdp:",` and `"  api:",`.

In `test_editor_preview_signing_key_is_local_to_api` (around line 333), add `"minio"` to the tuple of services that must not see the preview signing key.

In the preflight tests, add one test: a placeholder `THOTH_MEDIA_S3_SECRET_KEY` is refused, mirroring the existing placeholder-secret test.

- [ ] **Step 2: Run and watch them fail**

Run: `make test T=tests/deployment tests/operations`
Expected: the new tests FAIL. `_service_block` finds no `minio` service, the deploy steps are missing, and the preflight accepts the placeholder.

- [ ] **Step 3: Compose**

In `compose.stage1.local.yml`, insert after the `legacy-cdp` service and before `api:`:

```yaml
  minio:
    # The official minio/minio image is no longer published; pgsty/minio rebuilds the same
    # server (operator, 2026-10-17). Workflow media lives here (spec 2026-10-17).
    image: pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372
    command: ["server", "/data"]
    environment:
      MINIO_ROOT_USER: ${THOTH_MEDIA_S3_ACCESS_KEY:?set THOTH_MEDIA_S3_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${THOTH_MEDIA_S3_SECRET_KEY:?set THOTH_MEDIA_S3_SECRET_KEY}
      MINIO_BROWSER: "off"
    volumes:
      - type: bind
        source: ${THOTH_STAGE1_DATA_ROOT:?set THOTH_STAGE1_DATA_ROOT}/minio
        target: /data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 10s
    restart: unless-stopped
    networks: [stage1-private]
```

In both `api` and `worker`:

1. Add to `depends_on`:
   ```yaml
      minio:
        condition: service_healthy
   ```
2. Add to `environment`, after `THOTH_CONTROL_PLANE_ARTIFACT_ROOT`:
   ```yaml
      THOTH_MEDIA_S3_ENDPOINT: minio:9000
      THOTH_MEDIA_S3_BUCKET: thoth-media
      THOTH_MEDIA_S3_ACCESS_KEY: ${THOTH_MEDIA_S3_ACCESS_KEY:?set THOTH_MEDIA_S3_ACCESS_KEY}
      THOTH_MEDIA_S3_SECRET_KEY: ${THOTH_MEDIA_S3_SECRET_KEY:?set THOTH_MEDIA_S3_SECRET_KEY}
   ```

- [ ] **Step 4: Env example and preflight**

`.env.stage1.local.example`, after `THOTH_EDITOR_PREVIEW_SIGNING_KEY=…`:

```
# Workflow media object storage (MinIO in compose). The secret key needs 8+ characters.
THOTH_MEDIA_S3_ACCESS_KEY=replace-with-local-secret
THOTH_MEDIA_S3_SECRET_KEY=replace-with-local-secret
```

In `stage1_local_preflight.py`, add `"THOTH_MEDIA_S3_ACCESS_KEY",` and `"THOTH_MEDIA_S3_SECRET_KEY",` to `REQUIRED_SECRET_VARIABLES`.

- [ ] **Step 5: CI stack smoke**

In `.github/workflows/container-image.yml`, stack-smoke job:

1. Add `"${root}"/minio` to the `mkdir -p "${root}"/postgres …` line.
2. Add to the `stage1.ci.env` block:
   ```
            echo "THOTH_MEDIA_S3_ACCESS_KEY=thoth-ci-$(openssl rand -hex 6)"
            echo "THOTH_MEDIA_S3_SECRET_KEY=$(openssl rand -hex 24)"
   ```

The `up -d --wait postgresql editor-postgresql temporal temporal-ui api` line stays as it is: `api` now depends on `minio`, so compose starts it.

- [ ] **Step 6: Deploy script**

In `scripts/ops/deploy-stage1.sh`, insert between the import-reports `esac` and `step up`:

```bash
step media-store
mkdir -p "$data_root/minio"
"${compose[@]}" up -d --wait minio 2>&1 | tail -3
step import-media
# Same guard as the report import: a failed or unclean import leaves the old worker stopped.
media_rc=0
media_line=$("${compose[@]}" run --rm --no-deps api thoth-control media import \
    --artifact-root /var/lib/thoth/artifacts 2>&1 | tail -1) || media_rc=$?
echo "$media_line"
if [ "$media_rc" -ne 0 ]; then
    echo "media import failed (exit $media_rc); the old worker stays stopped — decide, then re-run" >&2
    exit 1
fi
case "$media_line" in
    *" invalid=0 mismatch=0") ;;
    *) echo "media import not clean; the old worker stays stopped — decide, then re-run" >&2
       exit 1 ;;
esac
```

Keep the file's LF line endings; check with `file scripts/ops/deploy-stage1.sh` (memory: python edit scripts write CRLF).

- [ ] **Step 7: Validate compose and run the tests**

Run in WSL:

```bash
docker compose --env-file .env.stage1.local.example -f compose.stage1.local.yml config --quiet && echo ok
docker compose --env-file .env.stage1.local.example -f compose.stage1.local.yml -f compose.stage1.renderer.yml config --quiet && echo ok
make test T=tests/deployment tests/operations
```

Expected: `ok` twice, and every test passes.

- [ ] **Step 8: Commit**

```bash
git add compose.stage1.local.yml .env.stage1.local.example python/src/thoth_control_plane/operations/stage1_local_preflight.py .github/workflows/container-image.yml scripts/ops/deploy-stage1.sh python/tests/deployment python/tests/operations
git commit -m "feat(media): run MinIO in the stage1 stack and import media on deploy"
```

---

### Task 11: Spec corrections and the CHANGELOG

**Files:**
- Modify: `docs/superpowers/specs/2026-10-17-media-object-storage-design.md`. Add the section; use `git add -f`.
- Modify: `CHANGELOG.md`. It uses CRLF: insert the entry above the first `## ` heading and keep CRLF.

- [ ] **Step 1: Add the spec corrections** (append to the spec)

```markdown
## Corrections (planning, 2026-10-17)

Found while writing the plan; the operator was told before execution.

1. **No API route serves workflow media today.**
   - The workflow artifact download serves only report kinds: every `ArtifactRef` the workflow
     records is a report.
   - Editor assets come only from uploads (`uploads/<project>/…`), so neither the editor preview
     nor render-bundle staging reads a `reports/` locator.
   - The API streaming, `Range`, and 503 parts of "Data flow" and "Testing" are therefore
     dropped. Serving workflow media to the browser belongs to the follow-up "Studio reads the
     footage artifact". `open_range` leaves the port, and so does `exists`, since `stat` covers
     it; `list` joins the port for the footage clips.
2. **`put_bytes` is not needed.** Cards are written to files in the scratch directory and go up
   with `put_file`.
3. **`content_type` is guessed inside `put_file`** from the file name, not passed in.
4. **`minio-init` is dropped.** `thoth-control media import` creates the private bucket when it
   is absent, and the deploy runs it before `up`, so the worker's startup `check()` finds it.
5. **Image `pgsty/minio`** replaces `minio/minio`, which is no longer pullable (operator,
   2026-10-17).
6. **Cleanup paths in footage stay local deletes.**
   - Rejected or timed-out clips were never pushed, because the footage activity pushes only
     after a successful build, so they need no store delete.
   - A failed build pushes nothing; its retry reopens admitted clips it cannot find, which is the
     existing `_verify_admitted` contract.
7. **Verification.**
   - Each object records its sha256 as metadata, so the import compares size and sha256 without
     downloading.
   - A fresh upload, and every `--remove-local` candidate, is verified by fetching a copy and
     hashing it.
```

- [ ] **Step 2: Add the CHANGELOG entry** (above the first `## `, CRLF)

```markdown
## 2026-10-17 - Workflow media in object storage (sub-project 1)

Branch `feat/media-object-storage`. Spec `docs/superpowers/specs/2026-10-17-media-object-storage-design.md`, plan `docs/superpowers/plans/2026-10-17-media-object-storage.md`.

**What changed:**
- `infrastructure/media_store.py` holds the `MediaStore` port with `LocalMediaStore` and `build_media_store`; `infrastructure/s3_media_store.py` holds `S3MediaStore` on `minio` 7.2.x, which records each object's sha256 as metadata.
- `activities/media_scratch.py`: each media activity works in a private directory laid out like the store. Acquisition, attribution (through `ACQUISITION_ROOT`), footage, and assembly pull what they read and push what they made.
- Acquisition pushes its media before it stores the report; a failure deletes what it pushed.
- The worker checks the store at startup, and `minio` is preloaded.
- `thoth-control media import` copies the volume's media into the bucket and verifies it (`imported/present/invalid/mismatch`). `--remove-local` deletes only verified local copies.
- `compose.stage1.local.yml` runs `minio` (`pgsty/minio`, pinned), and the deploy imports media before the new worker starts.
- `make test-minio` and the CI quality job run the store contract against a throwaway MinIO.

**Verification:** <fill in from the real runs: `make lint`, `make test` totals, `make test-minio` totals, and both compose config checks>.

**Next steps**
1. PR, CI, merge (operator authorized the whole rollout, 2026-10-17).
2. Add `THOTH_MEDIA_S3_ACCESS_KEY` and `THOTH_MEDIA_S3_SECRET_KEY` to `.env.stage1.local`, and pin the new digest.
3. Run `make deploy`. Expect `invalid=0 mismatch=0`.
4. One footage smoke: media in MinIO, none under `reports/<wf>/` on the volume, and zero `event loop stalled`.
5. `media import --remove-local`.
- Follow-ups: sub-project 2 (the renderer, `LocalArtifactRoot`, dropping the volume); Studio reads the footage artifact; attribution for reposts with no credit; Stage 5c; label the newly admitted calibration clips.
```

Replace the `<fill in …>` line with the actual numbers before committing. It is the one value only the run can supply.

- [ ] **Step 3: Commit**

```bash
git add -f docs/superpowers/specs/2026-10-17-media-object-storage-design.md docs/superpowers/plans/2026-10-17-media-object-storage.md
git add CHANGELOG.md
git commit -m "docs: record the media object storage work and its spec corrections"
```

---

## Rollout (after the branch; operator authorized every step on 2026-10-17)

These are not plan tasks. They are the executor's report checklist.

1. **Publish:** push, open the PR, wait until every check has finished and is green, then merge.
2. **Digest:** read the master "Container image" Publish job log for `IMAGE_DIGEST`.
3. **Back up the env**, then add the two secrets without printing them:
   ```
   echo "THOTH_MEDIA_S3_ACCESS_KEY=thoth-$(openssl rand -hex 6)" >> .env.stage1.local
   echo "THOTH_MEDIA_S3_SECRET_KEY=$(openssl rand -hex 24)" >> .env.stage1.local
   ```
4. **Pin** `THOTH_IMAGE`, then `docker pull`.
5. **Deploy:** `make deploy`, with one attached `wsl` command for the whole run. Expected: `imported=<≈487> present=0 invalid=0 mismatch=0`, against 352 mp4 and 135 png counted on 2026-10-17.
6. **Smoke:** one footage smoke inside one attached `wsl` command.
   - The new workflow's media objects are in MinIO, checked with `docker exec … mc ls` or a `media import` rerun showing `present` grow.
   - No media file is under `reports/<new wf>/` on the volume.
   - Zero `event loop stalled` and zero TMPRL1101 in the worker log.
7. **Remove the local copies:** `docker compose … run --rm --no-deps api thoth-control media import --artifact-root /var/lib/thoth/artifacts --remove-local`. Expected: `removed=<same count> kept=0`.
