# Workflow to Studio with media (roadmap priority 2)

## Why

A finished workflow leaves a Content Set and its media behind, but the dashboard stops there: to
edit the result, a person has to export JSON, paste it into the Studio import gate, and upload
every video and image again by hand. The Studio import gate (spec 2026-09 "Studio import") already
turns a source projection into a draft and lets a person attach assets to its items. What is
missing is the bridge: one action on a workflow that projects its Content Set on the server, copies
its media into the project, and opens the draft with the media already attached.

## Outcome

- A completed workflow that produced a Content Set shows **Open in Studio**.
- One click creates a Studio draft in the active project with the main video (or still), the
  footage clips and the comments as scenes, and the media attached where the server could.
- Opening the same workflow again offers **Resume draft** or **Create new draft**; media already
  in the project are reused, never copied twice.
- Anything Studio cannot represent yet is listed before the import, and any item whose media
  failed stays unresolved in the existing gate, to be fixed by upload or by choosing an asset.

## Decisions (operator, 2026-10-19 and 2026-10-20)

- An unassigned run's Open in Studio moves the run into the active project first.
- Re-open offers Resume or Create new, as the import gate already does.
- Approach A: one synchronous server endpoint does the projection, draft creation, media copy,
  probe, registration and attachment. No new workflow, no background job.
- Failed items stay unresolved; the import as a whole still succeeds.
- The import consumes no billing allowance; only renders do.
- Copied media count as `media_stored` for the workspace.

## 1. Projecting a Content Set (server side)

The Content Set is a row in Postgres `workflow_reports` (`kind = 'content_set'`, location
`reports/<workflow_id>/content-set.json`, exact JSON in `content`, digest in `sha256`), read with
`Reports.get(location)` and validated as `assembly.models.ContentSet` (schema 1). It is not a
file in the object store; only its media are.

A new pure function `project_content_set(content_set) -> WorkflowProjection` returns the existing
`StudioSourceProjection` plus, for each media item, the `MediaRef` it came from. It lives in the
domain layer next to `domain/studio_imports.py` and does no I/O.

| Content Set field | Projection |
|---|---|
| `main` with `kind = "video"` | `main` item, `media_kind = "video"`, `trim_start_seconds = main.ocr.trim_start` when the OCR ran and the trim is above zero |
| `main` with `kind = "images"` | `main` item, `media_kind = "image"` from `images[0]`; `images[1:]` reported unsupported (`main.images`, "carousel slides wait for Stage 5c") |
| `main` with `kind = "card"` | `main` item, `media_kind = "image"` from `card` |
| `main.title` / `main.description` | the main item's `title` / `text` |
| `footage[i]` | `footage` item `i`, `media_kind = "video"`, `trim_start_seconds = footage[i].ocr.trim_start` when above zero (file-relative; `clip_start` is only the offset in the source post) |
| `comments[i]` | `comment` item `i`, `media_kind = "none"`, `text = comment.text`, `title = @author` |
| `main.profile_card`, `comments[i].card` | unsupported ("cards wait for Stage 5c") |
| `main.ocr.mute_audio`, `main.ocr.subtitle_blur`, `footage[i].ocr.subtitle_blur` | unsupported ("Studio has no mute or blur yet") |
| `figures` | unsupported ("figures are context, not scenes") |

Each unsupported entry carries a `value_digest` of the dropped value, as the import gate requires.
Items past `MAX_SOURCE_ITEMS` and scenes past `SCENE_LIMIT` are dropped in source order and reported
unsupported (`overflow`), so the projection always validates.

### 1.1 The source key

The import gate's `source_key(projection)` hashes the projection alone, so two workflows with an
identical projection would share drafts. A workflow import instead uses
`sha256("workflow:" + workflow_id + ":" + report.sha256)` (64 hex). It is stable for one Content
Set, distinct per workflow, and changes when the Content Set is re-assembled. Drafts are listed and
created under this key; the existing gate's own key rule is untouched.

## 2. Importing the media

For each projected item that has a `MediaRef`, in item order:

1. **Reuse.** If the project already has a ready editor asset whose `checksum` equals
   `MediaRef.checksum`, use it: no fetch, copy, probe or registration. A new repository read
   `find_ready_by_checksum(project_id, checksum)` backs this.
2. **Check the source.** `media.stat(MediaRef.location)`. A missing object makes the item
   unresolved with reason `media_missing`; a size different from `MediaRef.bytes` makes it
   unresolved with `media_mismatch`.
3. **Probe, reading MinIO directly.** A new store method `probe_url(location) -> str` returns a
   short-lived (5 minute) presigned GET URL from the MinIO client (`presigned_get_object`, signed
   locally against the internal endpoint the API already uses, with an explicit `region` from a new
   setting `THOTH_MEDIA_S3_REGION`, default `us-east-1`, so signing never makes a network call).
   ffprobe reads that URL with HTTP
   range requests, so only the container header and index are transferred, never the whole file.
   `probe_media` accepts the URL as its input argument and restricts ffprobe with
   `-protocol_whitelist http,https,tcp,tls`; the URL is passed only as an argument vector entry and
   never logged or returned. The local filesystem store (development and tests) returns the
   object's file path instead. `described_asset(...)` turns the report into the asset exactly as
   an upload does. An invalid report or a probe timeout (the existing 30 seconds per probe) makes
   the item unresolved with `media_invalid`; nothing has been copied yet. Probes run one at a time:
   at most seven media items (one main, `MAX_FOOTAGE = 6`) bound the worst case near three and a
   half minutes against a very slow store; concurrent probes are added only if imports prove
   slow.
4. **Copy.** `media.copy(MediaRef.location, "uploads/<project_id>/<new name>")`, a server-side
   copy in MinIO, using the same name rule as `publish_upload`.
5. **Register.** `register_ready(EditorAssetRecord(asset, location, provenance="workflow_import"))`
   with `checksum = MediaRef.checksum`. If registration fails, the copy is deleted and the item is
   unresolved with `asset_unavailable`.
6. **Attach.** The existing `resolve` with `AttachImportAsset(asset_id)` against the current
   revision, so the existing trim and kind checks apply. A refused attach (for example
   `trim_exceeds_asset`) leaves the item unresolved with that code; the asset stays registered and
   can be chosen later.

One item's failure never stops the others. Every outcome is reported per item:
`reused`, `copied` or `unresolved` with its reason.

Two imports running at the same moment in one project (two tabs pressing Create) can both miss
the checksum lookup and copy the same media twice. The result is a duplicate asset and wasted
bytes, never corrupt data, so it is accepted. A unique index is not an option: manual uploads may
already hold duplicates. `ponytail:` if duplicates show up in practice, hold a Postgres advisory
lock per project around lookup, copy and registration.

### 2.1 Metering, billing and isolation

- `MeteredMediaStore.copy` records `media_stored` with the source object's size, under the
  request's meter scope only (`in_scope_only=True`), like `put_file`. The renderer's output copy in
  `artifact_root` runs outside any scope and stays unrecorded.
- The import consumes no allowance.
- The project guard on `/projects/{project_id}/…` applies. The workflow must belong to the
  caller's workspace (`run.owned_by(actor)`); otherwise the answer is 404, never 403, so another
  workspace's run cannot be probed for.

## 3. Endpoints and dashboard

### 3.1 Endpoints

Both sit in a new route module beside `api/routes/studio_imports.py` and use the same service
dependency style.

- `GET /api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import` returns a
  `WorkflowStudioInspection`: `source_key`, the inventory items (as `StudioSourceInspection`
  does), the unsupported list, and the newest drafts made from this key with `more_drafts`. It is
  read-only: it neither assigns the run nor copies anything. An unassigned run is accepted.
- `POST /api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import`, with a required
  `Idempotency-Key` header and no body:
  1. an unassigned run is assigned to `project_id` through `WorkflowRuns.assign`;
  2. the draft is created through the existing import service under the workflow source key;
  3. the media are imported (section 2);
  4. the answer is `201` with `WorkflowStudioImport`: the `StudioDraft` plus the per-item
     outcomes.

  Replaying the key returns the same draft and **continues** the import: every item that has
  media and is still unresolved goes through section 2 again, so a request cut off after the draft
  was created (a dropped connection, a restarted API) finishes on the next try. Media already
  copied are found by checksum and never copied again; items already attached are left alone.
  Items a person excluded in the gate are not retried.

### 3.2 Dashboard

- `WorkflowDetailPage` shows **Open in Studio** when the run is completed and carries a
  `content_set` artifact. Without an active project the button is disabled with the hint
  "Choose a project first".
- Clicking it calls GET. The unsupported list is shown as a note. If drafts exist, the page offers
  **Resume draft** (opens that draft in Studio; the gate's resolve-only mode shows its inventory)
  or **Create new draft**; otherwise it goes straight to POST.
- During POST the button reads "Importing media…" and is disabled; a new idempotency key is made
  per click of Create.
- On success the page navigates to Studio on the new document. Unresolved items appear in the
  existing gate.
- Errors use fixed copy per code (section 4); the server's own text never reaches the page.

## 4. Errors and testing

### 4.1 Errors

| Condition | Answer |
|---|---|
| No `content_set` row, or the run is not completed | `409 content_set_unavailable` |
| The row does not validate as ContentSet schema 1 | `409 content_set_invalid` |
| The run belongs to another project | `409 workflow_in_other_project` |
| The run is unknown or owned by another workspace; the project is not the caller's | `404` |
| Postgres or the media store unreachable before the draft exists | `503`; nothing is created |
| One item's media missing, mismatched, invalid, or refused | that item `unresolved` with its code; the import still answers `201` |
| Replayed `Idempotency-Key` | the same draft; unresolved media items are retried, copied media are reused |

### 4.2 Testing

All offline.

- **Projection unit tests:** each row of the table in section 1, the trim rules (OCR absent, zero,
  positive), overflow past `SCENE_LIMIT` and `MAX_SOURCE_ITEMS`, the source key formula, and that
  every projection validates as `StudioSourceProjection`.
- **Import unit tests** with an in-memory media store and a fake probe: reuse by checksum (no
  fetch, no copy), missing and mismatched objects, invalid probe (nothing copied), registration
  failure (copy deleted), refused attach (asset kept), presigning with an explicit region, the probe given a presigned URL (never a downloaded file) on the S3 store, and
  `media_stored` recorded only inside a meter scope.
- **Route tests:** GET is read-only and accepts an unassigned run; POST assigns, creates and
  imports; a replayed key returns the same draft and finishes items a cut-off first request left unresolved, without a second copy; every 409, 404 and 503 code; the structural
  route test and the workflow path-pair contract list include the new routes.
- **Postgres test:** one import that reads a real `workflow_reports` row and registers an asset
  with `provenance = 'workflow_import'`.
- **Dashboard tests:** the button's visibility and disabled state, the Resume/Create choice, the
  busy state, the message per error code, and navigation to Studio.
- **Smoke:** `docker/test-renderer-offline.sh` gains one step: from a fixture run with a Content
  Set, call the POST and assert the draft exists with its main item attached.

## Out of scope

- Serialising concurrent imports in one project (see section 2).

- Carousel slides past the first, profile cards, comment cards, mute and subtitle blur (Stage 5c).
- A background or resumable import for very large Content Sets.
- Moving a run between two projects.
