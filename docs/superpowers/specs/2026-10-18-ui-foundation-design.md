# UI Foundation (UI phases 0 and 1) and Voice Adapter Design

**Status:** approved by the operator 2026-10-18. The operator asked that the voice adapter from
the auto-video research be added (section 9).
**Roadmap:** priority 1 in `docs/ROADMAP.md`.
**Origin:** the 2026-10-18 UI audit (operator copy at `D:/thoth-tmp/ui-audit/LAPORAN-AUDIT-UI.md`).

## 1. Goal

Give the dashboard a durable spine that every later UI phase builds on:

- projects that live in the control plane;
- workflows that are stored, listed per project, and reachable by URL;
- Studio drafts that are listed per project and reachable by URL;
- a UI that only shows what the server supports.

Success, seen by the operator:

- a reload or the browser's back button keeps the page;
- every workflow, including the 264 older ones, appears in a list;
- a workflow's artifacts download, media included;
- every Studio draft of a project can be opened without going through the Content Set page.

## 2. Scope

In scope:

1. A `projects` table and API in the control plane, with a one-off import of the Rust projects
   that keeps their IDs.
2. A `workflow_runs` table, written at start and settled on read, with per-project and
   unassigned listings and a move between projects.
3. A backfill that creates run rows for the workflows that already have reports.
4. A per-project listing of Studio documents.
5. **Fix:** workflow media artifacts download from the media store. Today the route reads the
   local artifact root, which no service mounts since PR #19/#21, so media downloads answer 404.
6. Dashboard: React Router v7 in declarative mode, the active project in the control plane,
   the Workflows list and detail pages, the Studio list and deep links, and a resolve-only mode
   for the import gate.
7. UI phase 0 clean-up: remove the placeholders and the misleading copy, and point the Vite
   `/api` proxy at port 8787.
8. The voice adapter (section 9): a port with two providers and a CLI. It has no workflow,
   API, or UI consumer yet; auto-draft slice 2 is its first consumer.

Out of scope, each in its own later item of `docs/ROADMAP.md`:

- "Open in Studio" from a workflow with media (UI phase 2);
- serving the dashboard and Google/GitHub sign-in (UI phase 3);
- Rust Profiles;
- retiring the legacy pages.

The Profiles page and the Legacy Console keep calling the Rust server. They only work for a
project that also exists there; today that is the one imported project.

## 3. Backend

### 3.1 Migration 0012 (editor database)

Shipped as `python/migrations/editor/0012_projects_and_workflow_runs.sql` and applied by
`0012_projects_and_workflow_runs.py` through `execute_sql_file`, like 0011.

```sql
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY CHECK (char_length(project_id) BETWEEN 1 AND 128),
    name TEXT NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workflow_runs (
    workflow_id TEXT PRIMARY KEY CHECK (workflow_id ~ '^wf_[0-9a-f]{24}$'),
    project_id TEXT REFERENCES projects (project_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    display_url TEXT NOT NULL CHECK (char_length(display_url) BETWEEN 1 AND 2048),
    platform TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'running', 'awaiting_approval', 'succeeded', 'failed', 'cancelled', 'unknown')),
    history_expired BOOLEAN NOT NULL DEFAULT false,
    summary JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX workflow_runs_project ON workflow_runs (project_id, created_at DESC, workflow_id DESC);
CREATE INDEX workflow_runs_unsettled ON workflow_runs (status)
    WHERE status IN ('queued', 'running', 'awaiting_approval', 'unknown');
```

Editor tables that already carry a `project_id` gain no foreign key. Their existing rows predate
the `projects` table.

### 3.2 Projects

- **Repository:** `infrastructure/project_store.py`, SQLAlchemy ORM like
  `report_store.py`, with `list()`, `get(project_id)`, `create(name)`, and
  `insert_missing(project)`.
- **Domain model `Project`:** `project_id: ProjectId`, `name` (1–120 characters after trimming),
  `created_at`, `updated_at`.
- **Routes:**
  - `GET /api/v1/projects` → `{"items": [Project]}`, newest `updated_at` first.
  - `POST /api/v1/projects` `{"name"}` → 201 `Project`. The ID is a server-minted UUID4, which
    `PROJECT_ID_PATTERN` accepts.
  - `GET /api/v1/projects/{project_id}` → `Project`, or 404 `project_not_found`.
- **CLI `thoth-control projects import <file|->`:** reads the JSON list that the Rust
  `GET /api/projects` returns (`id`, `name`, `created_at`, `updated_at`; other fields are
  ignored). It inserts the missing projects with their IDs and prints
  `imported=N present=M invalid=K`. It never overwrites a project.

### 3.3 Workflow runs

**Repository:** `infrastructure/workflow_run_store.py` (ORM), with:

- `record_start(summary, project_id, actor)`, an upsert keyed by `workflow_id` that never
  changes an existing row's project;
- `page(project_id | None, cursor, limit)`;
- `get(workflow_id)`;
- `settle(workflow_id, status, summary, history_expired)`;
- `assign(workflow_id, project_id)`;
- `insert_missing(row)`.

**Response model `WorkflowRun`:** `workflow_id`, `project_id | null`, `source: WorkflowSource`,
`status: WorkflowRunStatus` (the six `WorkflowStatus` values plus `unknown`),
`history_expired`, `artifact_count`, `created_at`, `updated_at`.

**Pages:** `{"items": [WorkflowRun], "next_cursor": str | null}`, newest first. `limit` is
1–50 (default 20). The cursor is opaque, in the same style as `listEditorAssets`.

**Routes:**

| Route | Behaviour |
|---|---|
| `POST /api/v1/projects/{project_id}/workflows` | Same body and `Idempotency-Key` as `POST /workflows`. 404 `project_not_found` before any start. Starts through `WorkflowService.start`, then `record_start` with the project. → 202 `WorkflowSummary` |
| `POST /api/v1/workflows` | Unchanged contract (tests and smokes use it); also calls `record_start` with no project |
| `GET /api/v1/projects/{project_id}/workflows` | Page of that project's runs, settled first (3.4) |
| `GET /api/v1/workflows?unassigned=true` | Page of runs with no project. `unassigned` must be `true` (422 otherwise) |
| `PATCH /api/v1/workflows/{workflow_id}` `{"project_id"}` | Moves a run. 404 `workflow_not_found` or `project_not_found` → `WorkflowRun` |

**Order on start:** Temporal first, then the row. If the row write fails, the route answers
503 `workflow_runs_unavailable`. The client's retry reuses the same `Idempotency-Key`. Temporal
then returns the same workflow (`USE_EXISTING`) and the row lands. No started workflow is ever
left without a row once the client's retry succeeds.

### 3.4 Settling on read

Runs are settled when they are read; the workflow code does not change. Writing from inside the
workflow would touch fifteen `return` points of a deterministic workflow and need version
patching.

`TemporalWorkflowGateway.settle(workflow_id, actor)` returns one of three outcomes:

- `Live(summary)`: the execution is running. The summary comes from the existing `summary` query.
- `Closed(summary, status)`: the execution has closed.
  - `COMPLETED` → `summary = await handle.result()`. The workflow returns its `WorkflowSummary`,
    and its status is the summary's own. No worker replay is needed.
  - `FAILED`, `TERMINATED` and `TIMED_OUT` → status `failed`, keeping the last stored summary.
  - `CANCELED` → status `cancelled`.
- `Expired`: Temporal no longer holds the execution (`NOT_FOUND`, past the 30-day retention).

The listing settles at most 20 unsettled rows of the page it returns (`queued`, `running`,
`awaiting_approval`, `unknown` without `history_expired`), concurrently, each bounded by the
gateway's existing timeout.

Degradation, each case logged with `logger.warning`:

- a Temporal error leaves the row as stored and still returns the page;
- an `Expired` row gets `history_expired = true`;
- an expired row keeps a stored summary when it has one. Otherwise it gets a synthesized summary
  whose artifacts are its rows in `workflow_reports` (one `ArtifactRef` per report, with
  `artifact_id` = the kind, `media_type` `application/json`, and `location` = the report's
  location). Its status stays `unknown` unless a summary says otherwise.

`GET /workflows/{id}` keeps the live query. On `WorkflowNotFound` it answers from the stored
row: the summary, or the synthesized one. After a successful live read it upserts the summary.
`get_artifact` resolves through the same fallback, so the artifacts of an expired workflow
still download.

### 3.5 Backfill

`thoth-control workflows backfill` inserts one run row for every `workflow_id` matching
`^wf_[0-9a-f]{24}$` that has a `source_report` in `workflow_reports` and no row yet. There are
264 today. Each row gets:

- `project_id = NULL`;
- the owner actor (`user`/`owner`, the only actor the bearer maps to);
- `display_url` and `platform` from the report's `source.canonical_url` and `source.platform`,
  with the query and fragment stripped as in `safe_workflow_source`;
- `created_at` = the earliest of its reports;
- status `unknown`.

Settling on read then fills in the real status from Temporal, or marks the row expired.

The command is idempotent and prints `inserted=N present=M invalid=K`. `deploy-stage1.sh` runs
it after `migrate`, on every deploy.

### 3.6 Studio documents per project

`GET /api/v1/projects/{project_id}/edit-documents?cursor&limit` returns
`{"items": [EditDocumentListItem], "next_cursor"}`, newest revision first. Each item has:

- `document_id` and `revision` (the latest);
- `updated_at` (that revision's `created_at`);
- `label`: the first non-empty text clip heading of the latest revision, else `Untitled draft`,
  trimmed to 120 characters;
- `imported`: true when a `studio_import_drafts` row exists.

Like the other editor routes, it does not require the project to exist in `projects`.

### 3.7 Media artifact download from the store

In `download_workflow_artifact`, a non-report artifact is served from `app.state.media_store`
through `ranged_response` (`api/ranged.py`) at its `location`, using the same size and range
handling as the render download. The local `FileResponse` path is removed, and so is the
dependency on the artifact root for this route.

| Failure | Answer |
|---|---|
| A missing object | 404 `artifact_not_found` |
| `MediaStoreUnavailable` | 503 |

## 4. Dashboard

### 4.1 Routing

- **Dependency:** `react-router` v7, declarative mode, with `BrowserRouter` in `main.tsx`.
- **Routes:**

| Path | Page |
|---|---|
| `/` | redirect to `/workflows` |
| `/workflows` | start form + the active project's runs + unassigned runs |
| `/workflows/:workflowId` | monitor, approval, artifacts |
| `/studio` | the active project's Studio documents |
| `/studio/:projectId/:documentId` | `GuidedStudio` |
| `/discovery`, `/content-set`, `/profiles`, `/legacy` | existing pages |
| `/accounts`, `/accounts/proxies` | existing pages |
| `*` | redirect to `/workflows` |

- **Navigation:** the sidebar uses `NavLink`. The page heading derives from the route. "Creator
  Studio" goes to `/studio`; it no longer silently opens the Content Set page.
- **State:** state passed between pages moves into the URL or navigation state. "Send to render"
  carries its content-set path as `/legacy` navigation state.

### 4.2 Active project

- **Hook:** `useActiveProject()` stores the ID in `localStorage` (`thoth.activeProject`). Every
  read and write is wrapped in `try`/`catch`.
- **Fallback:** an ID that no longer exists falls back to the first project.
- **`ProjectSwitcher`:** moves to the control-plane client (`listProjects`, `createProject`).
- **`ProjectRecord`:** stays in `api.ts` for the Rust Profiles page only.

### 4.3 Workflows

- **`/workflows`:**
  - The start form posts to `POST /projects/{active}/workflows`. With no active project, the
    button is disabled and shows "Select or create a project to start a workflow."
  - The runs table lists the active project's runs (source, status, last update, artifact count)
    with "Load more".
  - A collapsed "Unassigned" section lists runs without a project. Each row has a "Move to
    project" select that calls `PATCH`.
  - A row opens `/workflows/:id`.
  - The in-session "Recent runs" state, its table and its dialog are removed.
- **`/workflows/:id`:**
  - shows the existing `WorkflowMonitor`;
  - shows a "Results" list in which each artifact is a download button. The button fetches with
    the bearer and saves a blob, because a plain link cannot carry the header;
  - says "History expired; showing the stored result" when `history_expired`.
- **`DashboardSearch`:** searches the active project's loaded runs, not the session list.

### 4.4 Studio

- **`/studio`:** lists `edit-documents` of the active project, and each row opens
  `/studio/:projectId/:documentId`. With no documents it says "No Studio drafts in this project
  yet. Open a Content Set in Studio to start one."
- **`/studio/:projectId/:documentId`:**
  - renders `GuidedStudio` from the URL alone;
  - the title is the document's label;
  - Back goes to `/studio`.
- **"Resolve source items":** opens `StudioImportGate` in a resolve-only mode. That mode needs
  only `projectId` and `documentId`, skips `inspect` and the create flow, loads the inventory,
  and saves decisions as today.
- **Content Set:** the "Open in Studio" flow is unchanged. Its `onOpen` navigates to the
  document's URL.

### 4.5 Clean-up (UI phase 0)

| Remove or change | Where |
|---|---|
| The four "—" metric cards | Workflows page |
| The "New workflow" button and `WorkflowDraftDialog` (session-only local draft) | Workflows page |
| The disabled "Approval at every stage · unavailable" review option | `WorkflowWizard` |
| The heading "From source to finished cut" → "From source to content set" | `WorkflowWizard` |
| "Approval before publishing" → "Approval before the content set is final" | `WorkflowWizard` |
| The "Format: Unavailable" row | `RenderPanel` |
| The disabled rename button | `GuidedStudio` |
| The Vite `/api` and `/health` proxy: 9090 → 8787, matching the server default and the docs | `vite.config.ts` |

## 5. Contract artifacts

- `python/openapi.json` is regenerated.
- `dashboard/src/api/generated/control-plane.ts` is regenerated
  (`bun run generate:control-plane-types`).
- The hand-written client `api/control-plane.ts` gains:
  - `listProjects`, `createProject`, `getProject`;
  - `startProjectWorkflow`, `listProjectWorkflows`, `listUnassignedWorkflows`, `moveWorkflow`;
  - `listEditDocuments`;
  - `downloadWorkflowArtifact`.

## 6. Testing

**Python:**
- store tests for projects and runs on SQLite and on PostgreSQL (`make test-postgres`);
- an Alembic upgrade to 0012 from 0011 with existing rows;
- route tests for every new route, including 404, 422 and 503;
- `record_start` idempotency on a retried start;
- settling with a fake gateway for each outcome (live, completed, failed, cancelled, expired,
  Temporal error);
- backfill counts and idempotency;
- the CLI import, including an invalid row;
- media artifact download: a full read, a range, missing, and store down.

**Dashboard:**
- routing with `MemoryRouter`: a deep link renders its page, `*` redirects, and Creator Studio
  goes to `/studio`;
- the active project persists and falls back;
- the start form is disabled with no project;
- the Workflows list, "Load more", and move;
- the detail page with an expired workflow;
- Studio list to deep link;
- the import gate's resolve-only mode;
- each clean-up row is gone.

**Voice adapter:** the tests in section 9.4.

**Stack smoke:** `docker/test-renderer-offline.sh` gains three checks:
`project_created_and_listed=true`, `project_workflows_listed=true` (an empty page, 200), and
`edit_documents_listed=true` (the smoke's seeded document appears).

**Full gates:** the full Python suite, `ruff`, dashboard tests and build. `build_cuda.bat` is
not affected: no Rust code changes.

**After deploy:** the Edge headless UI walk from the audit is repeated as evidence:

- every route is reloaded directly;
- the 264 backfilled runs are listed under "Unassigned";
- an artifact downloads;
- `/studio` lists the imported project's documents.

## 7. Rollout

Operator gates, each authorized separately: push, PR, CI, merge, digest pin, and deploy.

The deploy then runs:

1. `migrate` (0012).
2. `workflows backfill`. It is part of `deploy-stage1.sh`; expect `inserted=264`, and `0` on
   later deploys.
3. **Once, by the operator:** export the Rust projects (`curl` against the Rust server's
   `/api/projects` with its key, or the JSON saved during this work), then
   `thoth-control projects import -` in the `api` container. Expect `imported=1`.
4. The dashboard runs through `vite dev` until UI phase 3, with the Rust server on 8787 for
   the legacy pages.
5. **Voice adapter:** nothing is required at deploy. To use `voice say` in the worker, the
   operator adds `THOTH_ELEVENLABS_API_KEY` (and optionally the `openai_compatible` settings)
   to the worker's provider file.

## 8. Known limits

- A run that nobody lists for more than 30 days after it closes is settled as expired. Its
  status stays `unknown` unless a stored summary exists. Its JSON reports still download.
- Projects have no rename or delete in this phase.
- Profiles and the Legacy Console work only for projects that exist in Rust.

## 9. Voice adapter

This section was added at the operator's request on 2026-10-18. The research behind it is
`docs/research/2026-10-18-auto-video-engine-python-research.md`, sections 4 and 4a.

### 9.1 Port (`thoth_control_plane/voice/ports.py`)

**Models:**
- **`VoiceRequest`:**
  - `text` (1–5,000 characters);
  - `language` (default `"id"`);
  - `voice_id`;
  - `model: str | None`;
  - `speed` (0.7–1.5, default 1.0).
- **`WordTiming`:** `text`, `start_seconds`, `end_seconds`.
- **`SynthesizedVoice`:**
  - `audio: bytes`;
  - `media_type` (`audio/mpeg` or `audio/wav`);
  - `duration_seconds`;
  - `word_timings: list[WordTiming] | None`.

**Interface:** `class VoiceSynthesizer(Protocol)` with
`async def synthesize(self, request: VoiceRequest) -> SynthesizedVoice`.

**Errors:**

| Error | Raised when | Retryable |
|---|---|---|
| `VoiceUnavailable` | timeout, connection failure, HTTP 429 or 5xx | yes |
| `VoiceRejected` | any other 4xx, such as an unknown voice or quota exhausted; carries the provider's error code, never the key | no |
| `VoiceNotConfigured` | the provider has no credentials or base URL | no |

A failed provider never falls back silently to another one. The caller, later a preset, chooses
its fallback.

`duration_seconds` comes from the timings when there are any. Otherwise PyAV, which is already
installed, probes the audio.

### 9.2 Providers (`thoth_control_plane/voice/adapters/`)

**`elevenlabs.py`, the primary.** It sends
`POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128`
with the header `xi-api-key` and a body of `text`, `model_id` (default `eleven_multilingual_v2`,
the Rust engine's setting) and `voice_settings.speed`. `language_code` is not sent, because the
v2 multilingual models ignore it.
- The response's `audio_base64` is decoded.
- `alignment` (characters with start and end seconds) becomes words. A word is a maximal run of
  non-whitespace characters: its start is its first character's start, and its end is its last
  character's end.
- **Credential:** `THOTH_ELEVENLABS_API_KEY` (`SecretStr`).

**`openai_compatible.py`.** It calls `openai.AsyncOpenAI(base_url=..., api_key=...)` and then
`.audio.speech.create(model=..., voice=..., input=..., response_format="wav", speed=...,
extra_body={"language": ...})`. It returns no word timings.
- This one adapter serves VoiceStudio (`model` selects its engine, for example Supertonic-3),
  OpenAI, and any other compatible server.
- **Configuration:** `THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL` (`AnyHttpUrl`) and
  `THOTH_VOICE_OPENAI_COMPATIBLE_API_KEY` (`SecretStr`, optional).

**`factory.py`:** `build_voice(settings, provider) -> VoiceSynthesizer`, where `provider` is one
of `elevenlabs` or `openai_compatible`. It raises `VoiceNotConfigured` for a provider
without its settings.

A direct Supertonic-3 adapter is not part of this phase. Supertonic-3 is reachable through
`openai_compatible` when a VoiceStudio container runs, and a direct adapter is decided after the
listening test.

**edge-tts is excluded** (operator, 2026-10-18), even as a fallback: it is an unofficial service
with no SLA that blocks IPs with 403 and can change or close without notice, so narration could
fail all at once.

### 9.3 CLI

```text
thoth-control voice say --provider {elevenlabs,openai-compatible} --voice VOICE_ID
    [--model MODEL] [--speed 1.0] [--language id] (--text TEXT | --file PATH) --out AUDIO_PATH
```

- It writes the audio to `AUDIO_PATH` and the word timings to `AUDIO_PATH.words.json`, an empty
  list when the provider has none.
- It prints `provider=... duration_seconds=... words=N`.
- An error prints its class and the provider's code and exits 1.
- This is a live call, for the operator only. No test calls a provider.

### 9.4 Tests

All tests are offline; the conftest guard already blocks non-loopback traffic.
- **ElevenLabs** through `httpx.MockTransport`: alignment to words (including punctuation and
  repeated spaces), base64 decoding, the 401, 422 and 429 mapping, and that the key never
  appears in an error.
- **OpenAI-compatible** through a mocked transport: the request carries `model`, `voice`,
  `speed` and `language`; WAV duration via PyAV; the mapping of 5xx and 4xx.
- **Factory:** each unconfigured provider raises `VoiceNotConfigured`.
- **CLI** with a fake adapter: both files are written, and the exit codes are correct.

