# Render and Editor Media in Object Storage — Design

Status: approved in conversation by the operator, 2026-10-17. Sub-project 2 of 2 of the
"media to S3" follow-up. Sub-project 1 (workflow media) is
`2026-10-17-media-object-storage-design.md`, deployed on 2026-10-17.

## Goal

No service shares the artifact volume any more. Editor uploads, render bundles, render outputs,
and the renderer's inputs and outputs all go through object storage or the control plane's HTTP
API. The `artifacts` bind mount leaves `api`, `worker`, and `remotion-renderer`. The volume's
leftover files are archived in the bucket. After this, the stack can run on several hosts.

## Decisions (operator, 2026-10-17)

1. **The renderer reaches media through the control plane's internal API, not S3.**
   - It uses the internal credential it already holds, the same pattern as `fetchBundle`.
   - The renderer gets no S3 credentials and no new dependency.
   - Rejected: presigned URLs (the renderer must reach MinIO, and URL hosts must agree across
     networks) and S3 credentials in the renderer (credentials spread to another service).
2. **The volume's leftovers are archived, never deleted outright.** The leftovers are the 275
   report JSON files under `reports/` and `legacy-scout/`. They are copied to `archive/<original
   path>` and verified. Local copies go only with `--remove-local`, as an operator-gated step.
3. **No render or upload data exists on the live volume today**, so render jobs and editor
   uploads need no migration.

## Store changes

`infrastructure/media_store.py`:

- **Locator rule.** The first segment may be `reports`, `uploads`, `renders`, `work`, or
  `archive`. The segment rule and the 512-character limit are unchanged.
- **New method:** `open_range(location: str, start: int, end: int | None) -> Iterator[bytes]`.
  - It streams the bytes `start..end` inclusive, or `start..` to the end of the object.
  - `LocalMediaStore` reads the file in 1 MiB chunks.
  - `S3MediaStore` uses `get_object(offset=, length=)` and releases the connection when done.
  - Both raise `MediaUnavailable` and `MediaStoreUnavailable` exactly as the other methods do.
- **New method:** `copy(source: str, destination: str) -> None`.
  - It makes a server-side copy; publication uses it.
  - `LocalMediaStore` copies through `.part` and `os.replace`.
  - `S3MediaStore` uses `copy_object`, keeping the recorded sha256 metadata.

## Editor uploads

- `LocalArtifactRoot.receive_upload` still streams the upload into a local temp file below the
  API's own temp directory. Hashing, the size cap, and the magic-byte head check are unchanged.
- **Publishing an upload:**
  1. `put_file` stores it at `uploads/<project_id>/<asset_id>.<ext>`, the same locator string as
     today;
  2. the local temp file is removed.
- **`discard`** deletes the object.
- **Preview** (`GET /projects/{p}/editor-assets/{a}/preview`) streams from the store with
  `stat` and `open_range`:
  - `Range: bytes=a-b` gets 206 with `Content-Range`;
  - a request with no range gets 200;
  - `MediaUnavailable` is 404 and `MediaStoreUnavailable` is 503;
  - authorization by the asset-scoped cookie is unchanged.

## Render jobs (control plane)

- **Preparation.** A render job's bundle JSON goes to the store at `work/<job>/bundle.json`. The
  bundle's checksum facts are unchanged. Assets are no longer copied into a workspace; the
  bundle names each asset's id, checksum, and size as today.
- **`GET /internal/render-jobs/{job}/bundle`** reads the bundle object.
- **New: `GET /internal/render-jobs/{job}/assets/{asset_id}`** (internal credential).
  - It streams the asset's stored object.
  - It answers only for an asset the job's bundle lists; anything else is 404.
  - It returns the object's bytes with its content length. The renderer verifies the checksum.
- **New: `PUT /internal/render-jobs/{job}/output`** (internal credential).
  - It streams the request body into a local temp file and hashes it as it lands.
  - It is capped at the render output maximum; above that it answers 413.
  - On success it stores the file at `work/<job>/output.mp4` and answers with
    `{size_bytes, checksum}`.
  - A second upload for the same job replaces the first, so a retry is idempotent.
- **Publish** (on the renderer's `completed` event):
  1. `stat` the `work/<job>/output.mp4` object;
  2. compare its size and sha256 with the event's output facts; a mismatch fails the job, as a
     bad temporary output does today;
  3. `copy` the object to `renders/<job>/output.mp4`;
  4. write `metadata.json` and `diagnostics.json` beside it with `put_file`;
  5. delete the `work/<job>/` objects.
- **Download** (`GET …/render-jobs/{job}/artifact`) streams `renders/<job>/output.mp4` from the
  store, with `Range`.
- **Cleanup** deletes every object under `renders/<job>/` and `work/<job>/` through `list`.
- **The application port.** `LocalArtifactRoot`'s render methods become a store-backed render
  artifact adapter behind the existing `ArtifactRoot` protocol in `render_job_ports.py`. The
  protocol's methods that return a `Path` change to locators or streams, and the plan names
  the exact signatures.

## Renderer (TypeScript)

- **Its own local working directory.** It is a container-local path, `THOTH_RENDERER_WORK_DIR`
  (default `/tmp/thoth-renderer`), with no bind mount. Its layout is unchanged:
  `temp/<job>/bundle/`, `claims/`, `output.mp4`, `template-release/`, and `work/<job>/assets/`.
  `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` leaves the renderer.
- **Assets.**
  - After `fetchBundle`, the renderer downloads each listed asset through the new assets
    endpoint into `work/<job>/assets/`.
  - It then runs the existing `verifyStagedAssets` checksum check.
  - A failed download or a checksum mismatch fails the render with `render_asset_unavailable`.
- **Output.**
  - After `verifyTemporaryOutput`, the renderer uploads `output.mp4` through
    `PUT …/output`.
  - It sends the `completed` event only after the upload succeeds.
  - A failed upload sends `failed` with `render_output_upload_failed`.
  - The local temporary output is removed in both cases.
- **Unchanged:** the Remotion engine, dispatch claims, cancellation, and progress events.

## Compose and configuration

- **The `artifacts` bind mount leaves `api`, `worker`, and `remotion-renderer`.**
- **`THOTH_CONTROL_PLANE_ARTIFACT_ROOT` stays on `api` and `worker`, pointing at a
  container-local path.** It is used only for:
  - scratch;
  - the `LocalMediaStore` fallback (tests and offline runs);
  - the legacy Scout temp file.
- **The API needs the media store now.** Uploads, preview, and render download read and write it.
  - `api` keeps its `THOTH_MEDIA_S3_*` variables.
  - `api` does not wait for MinIO to be healthy. A store outage answers 503 on those routes
    only, and the rest of the API, the dashboard included, stays up.
- **The renderer overlay** (`compose.stage1.renderer.yml`) loses the bind mount and the artifact
  root variable, and gains `THOTH_RENDERER_WORK_DIR`.
- **The deploy script** keeps `import-media` for workflow media, which is idempotent and a no-op
  once the volume is empty.

## Moving the leftovers

`thoth-control media import --archive --artifact-root <root>`:

- It walks every regular file under `<root>/reports/` and `<root>/legacy-scout/`, without
  following links.
- Each file is copied to `archive/<relative path>`, for example
  `archive/reports/wf_x/source-report.json`.
- It uses the same rules and counts as the media import: `imported`, `present`, `invalid`,
  `mismatch`, with verification by fetching a copy.
- `--archive --remove-local` deletes only verified files, then removes folders left empty. It
  never touches anything outside those two folders.

## Errors

- **Internal endpoints:**
  - a wrong or missing credential: 401, as today;
  - an asset not in the job's bundle, or an unknown job: 404;
  - a store outage: 503;
  - an output above the cap: 413.
- **Renderer:** `render_asset_unavailable` and `render_output_upload_failed` are new
  closing-event reason codes. They join the existing fixed taxonomy and carry no URL or body.
- **Control plane:** a publish whose output object is missing or differs fails the job with the
  existing artifact failure.
- **Upload, preview, download:** a store outage is 503 and a missing object is 404.
- **Secrets** stay out of every log and response, as in sub-project 1.

## Testing

All tests are offline.

- **Store contract** (`make test` local, `make test-minio` S3):
  - the new prefixes;
  - `open_range` edges: start only, start and end, past the end;
  - `copy` keeps the content and the sha256.
- **Control plane:**
  - the assets endpoint: authorization, the bundle-membership check, 404, 503;
  - the output endpoint: credential, size cap with 413, sha and size in the answer, replace on
    retry;
  - publish: verify, copy, the records, the `work/` cleanup, mismatch fails the job;
  - download with and without `Range`; cleanup;
  - editor upload, preview `Range`, and discard against the store.
- **`media import --archive`:** counts, idempotency, and `--remove-local`.
- **Renderer (`bun test`):**
  - assets downloaded through the client and checksum-verified;
  - a bad checksum fails the render;
  - the output is uploaded before `completed`, and a failed upload sends `failed`.
- **Offline smoke.** `make smoke-renderer` (`docker/test-renderer-offline.sh`) runs the API, the
  renderer, and MinIO with no shared volume, and proves one render end to end: upload an asset,
  render, download the output.
- **Compose contract:** no `artifacts` bind on `api`, `worker`, or the renderer overlay.

## Rollout

Each step is an operator gate:

1. PR, CI, merge.
2. Pin the new thoth and renderer digests.
3. `make deploy`.
4. One footage smoke.
5. `media import --archive`, then `--archive --remove-local`.

## Out of scope

- Studio reading the footage artifact, which is its own follow-up.
- The source-account profiles volume (`account-profiles`), which is sealed browser state and
  not media.
- The 14 review minors of sub-project 1, already fixed in PR #20.
