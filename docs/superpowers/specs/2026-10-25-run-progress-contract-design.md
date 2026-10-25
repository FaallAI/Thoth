# Run progress contract: design

Date: 2026-10-25. Status: draft for operator approval.
Implements the backend contract of `docs/DESIGN.md` §7.7, as amended in §3 below.

**Design sources:**
- `docs/DESIGN.md` §7 (run progress model), §12.1 (two languages) and §13.3 (progress inside Studio);
- the approved pen.dev screens in `design/exports/v2/` (`run-running.png`, `run-waiting-for-you.png`, `run-tray-open.png`, `studio-import-progress.png`, `studio-render.png`).

## 1. Problem

Since PR #67, a dashboard run lasts about 6 to 10 minutes. The approved screens show the whole stage plan, a live current step in each stage, timings, an estimate, an activity log, a run tray and an inbox. The backend gives none of that.

| Gap | Evidence |
|---|---|
| The summary holds one stage | `SourceInvestigationWorkflow._summary` always returns a single `source` stage, "Investigate original source", whose status mirrors the run |
| The API cannot name the chain stages | `StageSummary.id` allows only `validation\|source\|assets\|narration\|render\|review\|delivery`; there is no `approval`, `attribution`, `footage` or `assembly`, and no `skipped` status |
| Nothing is visible inside an activity | The source acquisition (about 2.5 min), footage and assembly report only when they end |
| No timing, estimate or inbox | The summary has no stage start or finish times; there is no inbox query; a failed run cannot be acknowledged |

## 2. Goals

**G1. Stage plan.**
- The workflow builds its plan at start from the intent and the flags:
  - `source`;
  - `approval` (`produce_video`);
  - `attribution` (`attribute_source`);
  - `footage` (`assemble_content` and `build_footage`);
  - `assembly` (`assemble_content`).
- Every planned stage is in `WorkflowSummary.stages` from the first snapshot. Stages that will not run show `skipped` with a reason.
- **`StageSummary` gains:**
  - the ids `approval`, `attribution`, `footage`, `assembly`;
  - the status `skipped`;
  - `started_at` and `finished_at` (RFC 3339);
  - `skip_reason` (a code);
  - `current_step` (§G2, filled by the API).
- All new fields are optional with defaults, so stored summaries and older clients stay valid. The OpenAPI file and the dashboard types are regenerated.
- **Temporal:** the plan and timings live in workflow fields set at stage transitions with `workflow.now()`, and they are read by the existing `summary` query.
  - No new command is issued, so replay is unaffected and no `workflow.patched` gate is needed.
  - A test proves an old history replays.

**G2. Steps from inside activities.**
- **Recording:** activities record steps through `progress.step(code, *, n=None, total=None, wait_until=None, params=None)`. The stage comes from the activity type:
  - `inspect_source_candidates` → `source`;
  - `attribute_source` → `attribution`;
  - `build_footage` → `footage`;
  - `assemble_content` → `assembly`.
- **Storage:** a `ProgressScopeInterceptor` sets the workflow id, stage and attempt for each activity, like `MeterScopeInterceptor`. A sink appends rows to `workflow_steps`.
- **Like metering, the recorder never fails the work:** a sink error is a `warn`, and with no sink nothing is recorded.
- **Write rate:** progress updates of the same code (`n` of `total`) are coalesced to at most one row per second.
- **Steps are codes, not prose** (§12.1). `code` comes from a closed catalogue (§5). `params` is a small whitelisted map (`verdict`, `platform`, `count`). It never holds a URL, a cookie, a token or raw exception text.

**G3. API.**
- `GET /workflows/{id}/steps?after=<seq>&limit=200` returns steps in order. The dashboard polls it in the same 1 s loop as the event stream.
- The snapshot fills each running stage's `current_step` from the latest step of the current attempt.
- After the run ends, the steps stay and the log is complete.

**G4. Estimates.**
- The snapshot gains `estimate_seconds_remaining`. It is the sum of the median duration of each remaining planned stage, taken from the workspace's last 20 succeeded runs on the same platform (stage timings come from stored summaries).
- Fallback defaults: source 120 s, attribution 60 s, footage 240 s, assembly 60 s.
- `null` below 5 runs; the UI then says "a few minutes".
- A wait step (`wait_until`) counts its remaining wait.

**G5. Inbox.** `GET /inbox` lists, for the caller's workspace:
- runs awaiting approval;
- failed runs not yet acknowledged. A new `workflow_runs.acknowledged_at` column and `POST /workflows/{id}/acknowledge` support this; opening a failed run's detail does not acknowledge it, only an explicit action does.
- for platform admins only, source accounts in cooldown or flagged unhealthy, with `cooldown_until`.

**G6. Render frames.**
- The renderer already reports `progress_percent` from Remotion's `onProgress`. It now also reports `rendered_frames`, `encoded_frames`, `total_frames` and `stage` (`preparing | rendering | encoding | uploading`), stored on the render job (new nullable columns).
- With them the Render screen shows "862 of 1440 frames · 41 fps" and an estimate.

## 3. Amendment to `docs/DESIGN.md` §7.7

§7.7 proposed sending steps as heartbeat details and reading them with `describe().pending_activities`. The Temporal Python SDK throttles heartbeats by default: `default_heartbeat_throttle_interval` is 30 s and `max_heartbeat_throttle_interval` is 60 s (Context7, `/temporalio/sdk-python`, `_autodocs/configuration.md` and `temporalio/worker/_worker.py`). A step could therefore reach the UI 30 to 60 s late, and a "next in 30 s" countdown could never be right.

**Steps are written by the activity straight to Postgres** (G2), the pattern metering already uses for `usage_events`.
- Heartbeats stay for liveness only.
- `workflow.set_current_details()` is not used for the UI.
- §7.7 is updated to say so.

## 4. Data

**Migration `0019_workflow_steps`** (Alembic revision plus the paired SQL file, as 0012-0018).

**The `workflow_steps` table:**

| Column | Type |
|---|---|
| `workflow_id` | text, indexed; **no** foreign key |
| `seq` | bigserial |
| `attempt` | int |
| `stage` | text, CHECK in the stage ids |
| `at` | timestamptz |
| `kind` | text, CHECK in `info \| progress \| wait \| done \| warning \| error` |
| `code` | text |
| `n` | int, null |
| `total` | int, null |
| `wait_until` | timestamptz, null |
| `params` | jsonb, null, ≤ 1 kB |

- **Index:** `(workflow_id, seq)`.
- **Why no foreign key:** `WorkflowRunService.start` writes the `workflow_runs` row only after Temporal accepted the start (`application/workflow_runs.py`). The first activity can record a step before the row exists, and a foreign key would drop that step.
- **Retention:** steps are kept as long as the run row.
- **`workflow_runs`:** gains `acknowledged_at timestamptz null`.
- **`render_jobs`:** gains `rendered_frames`, `encoded_frames`, `total_frames` (int, null) and `render_stage` (text, null).

## 5. Step catalogue (first version)

Codes are `stage.name`. The dashboard holds the English and Indonesian text for each.

| Stage | Codes |
|---|---|
| source | `read_link`, `fetch_post`, `download_media` (n/total), `capture_post_card`, `capture_comment_cards` (n/total), `gate_covered` (count, warning), `page_gap` (wait), `capture_embed_cards` (n/total), `capture_profile`, `login_wall` (warning), `save_report` |
| attribution | `read_text`, `ask_vision`, `search_candidates` (count), `compare_frames` (n/total), `verdict` (verdict) |
| footage | `plan_queries` (count), `search_platforms` (n/total), `screen_clips` (n/total), `creator_listing`, `keep_clips` (count) |
| assembly | `read_subtitles`, `judge_comments` (count kept, total), `find_figures` (count), `save_content_set` |

Every platform acquirer emits the `source` codes that apply to it. Codes are added in later releases, never renamed. An unknown code is shown as its stage label, so an older dashboard never breaks.

## 6. Plan (one branch per phase, test first)

1. **Stage plan** (G1): domain fields, the workflow plan and timings, OpenAPI and dashboard types, plus a replay test of an old history.
2. **Steps** (G2, G3): migration 0019, the recorder, the interceptor, the sink, the API endpoint and `current_step` in the snapshot.
3. **Instrumentation** (§5): the X, TikTok, Instagram, YouTube and Threads acquirers, attribution, footage and assembly emit the catalogue codes.
4. **Estimates and inbox** (G4, G5): the `acknowledged_at` migration and the endpoints.
5. **Render frames** (G6): the renderer adapter, the render job columns and the API.

Each phase: the full Python suite, the dashboard tests and `make lint`. The redesign of the dashboard screens that consume this is a separate spec, after this one.

**Live gate (operator), after phases 1-4 are deployed:** one dashboard `produce_video` run, so the stage plan, live steps, the estimate and the inbox can be watched. It joins the pending TikTok `produce_video` gate.

## 7. Non-goals

- The dashboard and Studio restyle (its own spec).
- Retrying a single stage.
- Auto-draft stages (they join the catalogue when auto-draft lands).
- Desktop notifications (frontend, §12.3).

## 8. Decisions for the operator

1. Store steps in Postgres, written by activities, instead of heartbeats (§3)?
2. Inbox "accounts": cooldown or unhealthy accounts for platform admins only (G5)?
3. Include render frame progress (G6) in this spec, or later?
4. Phase order: backend phases 1-5 first, then the dashboard restyle spec?
