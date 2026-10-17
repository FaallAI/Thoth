# Workflow Media in Object Storage — Design

Status: approved in conversation by the operator, 2026-10-17. Sub-project 1 of 2 of the
"media to S3" follow-up from the workflow-reports-postgres spec.

## Goal

The control plane runs on several hosts with no shared volume. As the first step, every
workflow media file is stored in S3-compatible object storage. Workflow media means the source
videos, the card PNGs, and the footage clips under `reports/<id>/`. The worker and the API stop
reading and writing workflow media on the artifact volume.

## Decisions (operator, 2026-10-17)

1. **Purpose: multi-host / cloud readiness.** Every writer and reader of workflow media goes
   through object storage. Disk space, backup, and publication are not goals.
2. **MinIO in compose for Stage 1.** The code speaks the plain S3 API, so moving to AWS S3 or R2
   later only changes the endpoint and credentials.
3. **Approach A: a `MediaStore` port with local staging, split into two sub-projects.**
   - **Sub-project 1 (this spec):** MinIO, the port, every Python writer and reader of workflow
     media, and moving the existing media.
   - **Sub-project 2 (its own spec):** the renderer, `LocalArtifactRoot` (`renders/`, `work/`,
     `temp/`, `uploads/`), and dropping the artifact volume from compose.
   - **Rejected:** FUSE mounts (privileged containers, and no rename in mountpoint-s3) and a
     sync sidecar (not multi-host).
4. **Existing media is moved, never deleted outright.**
   - It is copied to MinIO and verified by size and sha256.
   - After that, a separate, operator-gated step removes only the local copies whose objects
     verified identical.

## Scope

The key is the existing locator, unchanged. Reports in PostgreSQL, Temporal history, and
editor-asset records keep pointing at the right object with no data migration.

| Locator | Writer | Readers |
|---|---|---|
| `reports/<workflow_id>/media/<name>` (source video or image) | acquisition services (`acquisition/service.py`, `youtube_service.py`, `threads_service.py`, `instagram_service.py`, `x_service.py`) | `activities/source_attribution.py` (`_video`), `footage/service.py`, `assembly/service.py`, API artifact download, editor preview, render-bundle staging |
| `reports/<candidate_id>/media/<name>` (a candidate original, fetched during attribution) | acquisition, called from attribution | attribution, footage, assembly |
| `reports/<id>/cards/<name>.png` | `acquisition/cards.py` (`write_card`), `card_browser.py`, `threads_service.py` | assembly, API, editor preview |
| `reports/<workflow_id>/footage/<name>.mp4` | `footage/service.py` | assembly, API, editor preview, render-bundle staging |

Also in scope:
- **Failure cleanup:** the unlink paths become store deletes. These are
  `_cleanup_after_persistence_failure` in `source_investigation.py`, the rejected-clip unlinks
  and `_clean_parts` in `footage/service.py`, and the Threads rollback.

Out of scope:
- **Renderer and render jobs.** `LocalArtifactRoot` and its layout, and the renderer (sub-project
  2). Render-bundle staging still copies into `work/<job>/assets` on the volume. Only its source
  read for a `reports/` locator goes through the store.
- **Report JSON files.** The 277 files are already in PostgreSQL, and the files leave with the
  volume in sub-project 2.
- **`legacy-scout/`.** Compatibility data, not workflow media.
- **Operations tooling** (parity, captures, fixtures). These are operator tools, not pipeline
  storage.

## The port

`python/src/thoth_control_plane/infrastructure/media_store.py`:

```python
class MediaUnavailable(LookupError): ...        # no such object
class MediaStoreUnavailable(RuntimeError): ...  # the store cannot be reached
class MediaLocatorInvalid(ValueError): ...      # the locator is unsafe

@dataclass(frozen=True)
class MediaStat:
    size_bytes: int
    content_type: str

class MediaStore(Protocol):
    def put_file(self, location: str, path: Path, content_type: str) -> None: ...
    def put_bytes(self, location: str, data: bytes, content_type: str) -> None: ...
    def fetch(self, location: str, destination: Path) -> None: ...
    def stat(self, location: str) -> MediaStat: ...
    def open_range(self, location: str, start: int, end: int | None) -> Iterator[bytes]: ...
    def delete(self, location: str) -> None: ...   # an absent object is fine
    def exists(self, location: str) -> bool: ...
    def check(self) -> None: ...   # raises MediaStoreUnavailable
```

**Locator validation.** One shared validator runs before any key or path is built:
- the locator is 1–512 characters, made of `/`-separated segments;
- each segment matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, the same rule as `LocalArtifactRoot`;
- the first segment is `reports`.

Anything else raises `MediaLocatorInvalid`.

**Calls are synchronous**, like `Reports`. Async callers use `asyncio.to_thread`, so no storage
I/O runs on the event loop.

**Two implementations, chosen by settings:**

- **`S3MediaStore`** uses the `minio` Python SDK.
  - It is selected when `THOTH_MEDIA_S3_ENDPOINT` is set, together with `THOTH_MEDIA_S3_BUCKET`,
    `THOTH_MEDIA_S3_ACCESS_KEY` (secret), `THOTH_MEDIA_S3_SECRET_KEY` (secret), and
    `THOTH_MEDIA_S3_SECURE` (bool, default false for Stage 1).
  - `fetch` writes to `<destination>.part`, then renames it.
  - Any connection or 5xx error maps to `MediaStoreUnavailable`; `NoSuchKey` maps to
    `MediaUnavailable`.
- **`LocalMediaStore`** stores files below `THOTH_CONTROL_PLANE_ARTIFACT_ROOT`.
  - It is selected when the endpoint is unset.
  - Writes use `.part` plus `os.replace`, exactly as today.
  - The offline tests and offline smokes use it, and a deployment without S3 config behaves as it
    does now.

**Startup.** `build_media_store(settings)` returns the store.

- **`check()`:**
  - `S3MediaStore` calls `bucket_exists`, and fails for a missing bucket or an unreachable
    store.
  - `LocalMediaStore` fails when the root is not a directory.
- **Worker:** calls `check()` after the media-tool check and before polling, and fails startup
  loudly, like `check_media_tools`.
- **API:** does not check at startup. Like reports (ruling R1 of the reports spec), the API still
  starts, and each media request answers 503 when the store is unavailable.
- **Event loop:** `import minio` joins `preload_heavy_modules()`, so the import never lands on the
  event loop.

## Data flow

**Writers:**
- Each activity that produces media gets one scratch directory from
  `tempfile.TemporaryDirectory(dir=settings.THOTH_MEDIA_SCRATCH_DIR)`. The directory defaults to
  the system temp, and in the container `THOTH_MEDIA_SCRATCH_DIR` is an ext4 path.
- Downloaders (yt-dlp, the TikWM CDN, Scrapling) write into it as they write into the artifact
  root today.
- Each finished file is uploaded with `put_file` at its locator. Card PNGs held in memory go
  through `put_bytes`.
- The scratch directory is removed in `finally`.
- The checksum and size the report records are still computed from the local file before upload.

**Readers:**
- Code that needs a file path — ffmpeg, ORB, ONNX, and OCR in attribution, footage, and
  assembly — calls `fetch` into the activity's scratch directory first. Everything after that is
  unchanged.
- A missing object raises `MediaUnavailable`. Each reader handles it where it handles a missing
  file today; for example, attribution's `_video` returns `None`.

**Render-bundle staging:**
- For a `reports/` locator, `resolve_source` fetches the object into `temp/<job>/` and stages that
  copy. The checksum check is unchanged.
- Upload locators (`uploads/…`) stay local until sub-project 2.

**API:**
- Workflow artifact download, for non-report kinds, and the editor preview stream from the
  store:
  - `stat` provides the length and type;
  - `Range: bytes=a-b` is answered with 206 and `Content-Range` through `open_range`;
  - a request without `Range` gets 200 with the whole object.
- Authorization is unchanged: the workflow owner boundary, and the asset-scoped preview cookie.
- `MediaUnavailable` returns 404; `MediaStoreUnavailable` returns 503.
- The browser never talks to MinIO.

## Moving the existing media

**`thoth-control media import --artifact-root <root>`** is a new CLI command that sits next to
`reports import`.

- It walks every regular file under `<root>/reports/` whose name does not end in `.json`.
- A file is **invalid** in two cases:
  - it is a symlink, or its path breaks the locator rule;
  - it is a `.part` leftover.
- Otherwise, the importer compares the file with the object at the same key:
  - **imported:** there is no object, so the file is uploaded, then read back with `stat` and
    hashed through `open_range`.
  - **present:** an object exists with the same size and sha256.
  - **mismatch:** an object exists with a different size or sha256. It is never overwritten.
- It prints one line: `imported=N present=N invalid=N mismatch=N`.
- It exits 1 when `invalid > 0`, when `mismatch > 0`, or when the store is unavailable.
- It is idempotent, so every deploy can run it.

**`--remove-local`** deletes the local file only after it re-verifies that the object is
present with the same size and sha256. It then removes directories left empty under
`reports/`. It never touches `.json` files, `legacy-scout/`, or anything outside `reports/`.
It prints `removed=N kept=N`.

## Compose and deploy

**`compose.stage1.local.yml`:**
- A `minio` service is added:
  - image `minio/minio` pinned by digest;
  - its own bind volume `${THOTH_STAGE1_DATA_ROOT}/minio`;
  - a healthcheck on `/minio/health/live`;
  - no published port.
- A one-shot `minio-init` creates the private bucket `thoth-media`.
- `api` and `worker` gain the `THOTH_MEDIA_S3_*` variables and depend on `minio` healthy and
  `minio-init` completed.
- **Credentials:**
  - `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` come from `.env.stage1.local`;
  - the stack uses the root credentials for Stage 1;
  - a scoped access key is a cloud-deploy concern.
- **Preflight:** `stage1-local-preflight` checks that the new variables are present without
  printing them.

**`scripts/ops/deploy-stage1.sh`:**
- New order: `migrate` → `stop-worker` → `import-reports` → `up minio minio-init` →
  `import-media` → `up`.
- `import-media` gets the same guarded handling as `import-reports`:
  - a non-zero exit, or a line that does not end in `invalid=0 mismatch=0`, stops the deploy;
  - the old worker stays stopped.

## Errors and safety

- **Unsafe locator:** `MediaLocatorInvalid` is raised before any I/O, at the activity boundary
  and in the API. The API answers 404.
- **Store down during an activity:** the activity fails with `MediaStoreUnavailable` and
  Temporal retries it. During an API request, the API answers 503.
- **Missing object:** handled as a missing file is today, as described above.
- **Interrupted upload:** S3 never exposes a partial object. The local `.part` and the scratch
  directory are removed in `finally`.
- **Secrets:** the S3 keys are `SecretStr`, never logged, and never included in errors.
- **Bucket access:** the bucket is private.

## Testing

All tests are offline. The conftest guard still blocks non-loopback hosts.

- **Store contract tests** run against `LocalMediaStore` in `make test`:
  - put/fetch round trip;
  - `stat`;
  - `open_range` edges: start only, start and end, past the end;
  - `delete` of an absent object;
  - locator rejection: `..`, an absolute path, a backslash, a colon, an empty segment, and a
    prefix other than `reports`.
- **`make test-minio`** runs the same contract against a throwaway MinIO container on loopback,
  like `make test-postgres`. CI runs it in the quality job, so the S3 path is really tested.
- **Activity tests:**
  - writers upload to the store, readers fetch from it;
  - a missing object takes the existing missing-file path;
  - an unavailable store raises.
- **API tests:**
  - 200 for a full read, 206 for a `Range` request, 404 for a missing object, 503 for an
    unavailable store;
  - an unauthorized actor gets nothing from the store.
- **`media import` tests:**
  - each count: imported, present, invalid (symlink, `.part`, bad name), and mismatch, which is
    never overwritten;
  - idempotency;
  - exit codes;
  - `--remove-local` removes only verified files and never `.json`.
- **Worker startup test:** an unreachable store fails startup, and `minio` is in the preload set.

## Rollout

The operator authorized every step on 2026-10-17:

1. PR, CI, merge.
2. Pin the new thoth digest in `.env.stage1.local`, together with the new MinIO variables.
3. `make deploy`. MinIO starts and `import-media` reports `invalid=0 mismatch=0`.
4. One footage smoke. Its media objects are in MinIO, its `reports/<wf>/` folder on the volume
   holds no media, and the worker log has zero `event loop stalled`.
5. `media import --remove-local`. Only verified local copies are removed.

## Next

Sub-project 2 gets its own spec:
- the renderer reads inputs and writes outputs through presigned URLs;
- `LocalArtifactRoot` moves to the store;
- the artifact volume and the report JSON files leave the stack.
