# Roadmap and Priorities

This file is the single list of work that is not done yet, in the order it should be done. The
migration stages keep their detail in
[python-scout-migration-roadmap.md](python-scout-migration-roadmap.md); finished work is recorded
in `CHANGELOG.md`. Update this file when an item finishes or the operator changes an order.

As of 2026-10-19. Nothing is in flight: every PR through #29 is merged, and the stack runs
`master` at `08df791` from `ghcr.io/faallai/*`. The repository lives at `FaallAI/Thoth`.

## Status as of 2026-10-31

The stack runs `master` at `716b580` (PR #97). This section maps the items below to what has
shipped since 2026-10-19; the items themselves keep their original wording and order.

| Item | Status on 2026-10-31 |
|---|---|
| 4. Stage 5c | Done: 5c-1 deployed 2026-10-22 (PR #39), 5c-2 deployed 2026-10-23 (PR #41) |
| 6. Auto-draft | Not started; the first open item, starting with slice 1 (transcript) |
| 7. Stage 6: enrichment | Not started; waits on 6 |
| 8. Stage 8: discovery in Python | Not started. The old curated Instagram account list (`attribution/curated_accounts.json`, local and gitignored) fed Scout's viral-content discovery; the operator decides its future with this item. Since 2026-10-31 it filters nothing |
| 9. Stage 7: durable orchestration | Not started; waits on 8 |
| 10. Stage 9: cutover and final live acceptance | Waits on 1-9; the final soak is Python-only (no parity samples) |
| 11. Stage 10: retire Scout and Rust | Half done: Scout retired early and deployed 2026-10-31 (PR #97: no legacy activity, no `legacy-cdp`, no `scout/`). Left: `crates/`, the Rust-era docs (README, `.env.example`, CLI/INSTALL/MODELS/FEATURES, main-footage), and dropping the decode-only `activity_mode` workflow input after 2026-11-29 |

Dashboard redesign track: steps 1-7 are deployed (run progress phases 1-5, restyle part A
R1-R4 and part B R5-R7, last on 2026-10-30 at `03741c3`). Step 8, the operator's live gate, is
open.

The backlog item "Scrapling in place of the CDP sidecar" is moot: the sidecar was removed with
Scout on 2026-10-31.

### Open follow-ups from the 2026-10-30 and 2026-10-31 deploys

- **Security:** 17 Dependabot alerts on `master` (2 critical, 4 high, 7 moderate, 4 low), untriaged.
- **Studio:** the header overflows at 430 px; the seven deferred R7 minors; Timeline thumbnails
  and waveforms need a backend that produces frame strips and audio peaks.
- **Audit:** B2 (central error handlers) and B5 (`UnavailableWorkflowGateway`, the browser
  `apiKey`, duplicate fetch clients), deferred by the operator on 2026-10-30.
- **Operations:** done 2026-10-31: `THOTH_STAGE1_ACTIVITY_MODE` left `.env.stage1.local` and the
  1.4 GB `browser-profile` was deleted; the preflight still passes.

## Priority order

| # | Item | Why it comes here | Blocked by |
|---|---|---|---|
| 1 | ~~UI foundation (UI phase 0+1)~~ Done 2026-10-19 (PR #24, #26) | Every later UI item needs projects in the control plane, stored workflows, and URL routing | Done |
| 2 | ~~Workflow to Studio with media (UI phase 2)~~ Done: deployed 2026-10-21 (PR #36, `c9c6f0c`) | It opens the only end-to-end path: today a workflow's output cannot reach Studio and the main video must be uploaded by hand | 1 |
| 3 | ~~Decide the Rust engine's direction~~ Decided 2026-10-18: port it into the Python control plane | See "Decision: the Rust engine" | Done |
| 4 | Stage 5c: post cards, carousel photos, creator profile. 5c-1 (Studio: cards, slides, subtitle blur) deployed 2026-10-22 (PR #39); 5c-2 (style A materials: post card, profile page, creator clips and photos) built 2026-10-22 on `feat/stage5c2-style-a-materials` | Completes the Content Set that Studio imports; card overlays were left out of item 2 | 2 |
| 5 | ~~Dashboard serving and Google/GitHub sign-in (UI phase 3)~~ Done 2026-10-19 as SaaS sub-project 1 (PR #27, #29) | The control-plane key no longer ships in the JS bundle; GitHub sign-in is live | Done |
| 6 | Auto-draft, in six slices (transcript, voice, script + Profiles rebuilt as Python presets, draft, reframe, other modes) | Restores "source to finished video" on the new path, and the Profiles page removed on 2026-10-18; see the research below | 2 |
| 7 | Stage 6: enrichment | Gives auto-draft narration its context | 6 |
| 8 | Stage 8: discovery in Python, then the Discovery and Content Set pages rebuilt on it | The Rust-backed pages are already gone (2026-10-18); discovery starts workflows | 2 |
| 9 | Stage 7: durable orchestration | Restart-safe, resumable runs before the final acceptance | 8 |
| 10 | Stage 9: cutover and the final live acceptance | Runs every live smoke deferred under ADR 0001 | 1-9 |
| 11 | Stage 10: retire Scout TypeScript and the Rust engine | Last | 10 |

Items that wait on operator input run in parallel whenever the input arrives; see
"Waiting on the operator".

## SaaS track

The operator decided on 2026-10-19 that Thoth becomes a usage-priced SaaS: a subscription
priced per workflow and per video, plus developer access (internal API and CLI, a local
dashboard without sign-in, and an external API). The work splits into four sub-projects, each
with its own spec, plan and rollout. They run **before item 2**, in this order:

| Sub-project | Scope | Status |
|---|---|---|
| 1. Accounts, sign-in, developer access | Google/GitHub sign-in with an emailed code, sessions, trusted browsers, developer tokens, the Caddy `web` container | Done 2026-10-19 (item 5) |
| 2. Multi-tenancy | Every user gets an isolated workspace; data and access are scoped to it | Done: deployed 2026-10-20 (PR #30, `d71665d`) |
| 3. Metering and cost model | Count workflows and videos per workspace; estimate what each costs; a per-workspace quota on source-account leases and proxy use, required before public sign-up | Done: deployed 2026-10-20 (PR #32, `f8acc10`) |
| 4. Billing | Plans, payment and limits on top of the meter | Done: deployed 2026-10-20 (PR #34, `240397b`); go-live deferred until every feature is finished |

## Dashboard redesign track

The operator started this on 2026-10-24/25, because a dashboard run now takes 6 to 10 minutes (PR #67) and every flow goes through the dashboard. The steps run in this order; the numbered priority items above are unchanged.
- **The design:** `docs/DESIGN.md`, `docs/design/pen-dev-prompts.md`, `design/thoth-dashboard-v2.pen`.
- **The backend contract:** `docs/superpowers/specs/2026-10-25-run-progress-contract-design.md`.

| Step | Scope | Status |
|---|---|---|
| 1. Design | Dashboard and Studio design reference, pen.dev screens (Prompts 0-30), Studio research and §13 | Done 2026-10-25 (PR #68, #70, #71, #72) |
| 2. Run progress, phase 1: stage plan | Every planned stage in the summary from the start, `skipped` with a reason, stage timings, new stage ids | Done 2026-10-25 (branch `feat/run-progress-stage-plan`), awaiting review |
| 3. Run progress, phase 2: steps | `workflow_steps` (migration 0019), the step recorder in activities, `GET /workflows/{id}/steps`, `current_step` | Done 2026-10-25 (branch `feat/run-progress-steps`), awaiting review |
| 4. Run progress, phase 3: instrumentation | The step catalogue in the X, TikTok, Instagram, YouTube and Threads acquirers, attribution, footage and assembly | Done 2026-10-25 (branch `feat/run-progress-instrumentation`), awaiting review |
| 5. Run progress, phase 4: estimates and inbox | `estimate_seconds_remaining`, `GET /inbox`, acknowledging failed runs | Done 2026-10-26 (branch `feat/run-progress-estimates-inbox`), awaiting review |
| 6. Run progress, phase 5: render frames | Rendered and encoded frames and the render stage from the renderer | Done 2026-10-26 (branch `feat/run-progress-render-frames`) |
| 7. Dashboard and Studio restyle | Its own spec: the token migration (§5.1), the English/Indonesian switch, notifications, run tray, inbox, Studio Story / Script / Timeline (§13) | After steps 2-6 |
| 8. Live gate (operator) | One dashboard `produce_video` run with a TikTok main. Check the progress model, the Content Set in Studio, the TikTok profile page, the comment filter, and the comment-card count | After step 7 |

## UI phases

From the 2026-10-18 UI audit.

- **Phase 0+1, foundation:**
  - projects move into the control plane (the one Rust project is imported with its ID);
  - a `workflow_runs` table with a backfill of the existing workflows, listed per project;
  - React Router v7 in declarative mode;
  - the placeholders and the misleading copy are removed.
- **Phase 2, workflow to Studio:** a server-side import that copies the main video (with its OCR
  trim) and the footage into editor assets and creates a draft with every item resolved.
- **Phase 3, serving:** a Caddy `web` container serves the SPA with a fallback and proxies
  `/api/v1` with the bearer injected on the server. Sign-in uses Google and GitHub.
- **Phase 4, legacy retirement:** done early, on 2026-10-18 (see "Removed pages to rebuild in
  Python"). Stage 8 rebuilds Discovery and Content Set on the Python control plane.

## Decision: the Rust engine

The operator decided on 2026-10-18 to move the Rust engine's automatic video production
(`thoth-core`: transcription, script, voice, ducking, cards, render) into the Python control
plane. It arrives as a new workflow phase, **auto-draft**, that writes a pre-resolved Studio
draft for Remotion to render. Rust is frozen and retires at Stage 10.

Tool choices, flow and slices:
[research/2026-10-18-auto-video-engine-python-research.md](research/2026-10-18-auto-video-engine-python-research.md).

**Interim:** the dashboard no longer reaches the Rust server (operator, 2026-10-18). Until
auto-draft ships, an automatic video can only be made with the Rust CLI outside the dashboard.

## Removed pages to rebuild in Python

The operator removed every dashboard path to the Rust server on 2026-10-18, before Python
replacements existed. These four pages are gone from the UI and must be rebuilt on the Python
control plane:

| Page | What it did on Rust | Rebuilt in |
|---|---|---|
| Discovery | Topic search through Scout, starting a Content Set run | Item 8 (Stage 8: discovery in Python) |
| Content Set | Viewed a Scout Content Set; "Open in Studio" and "Send to render" | Item 2 for "Open in Studio" from a workflow; item 8 for the page itself |
| Profiles | Reusable run presets (provider, voice, layout, style) | Item 6 (auto-draft slice 3: presets) |
| Legacy Console | Started and monitored Rust render jobs | Item 6 (auto-draft produces the video; Workflows and Studio monitor it) |

The control plane's read-only legacy job bridge (`/api/v1/legacy/jobs`,
`THOTH_LEGACY_API_BASE_URL`) went with them. The Studio import gate's Content Set mode and its
projection helper stay in the code for item 2.

## Waiting on the operator

- Stage 4, Task 16: one paced probe of the signed-in Instagram reels listing. The 24-48 h wait
  after `feedback_required` on 2026-10-13 has passed.
- Answers to the five questions in
  [the reaction-as-original research](research/2026-10-13-reaction-as-original-research.md),
  and about six golden URLs for it.
- Golden URLs for attribution spec section 9, case 2 (caption credit) and case 5 (commentary).
- Labels for the newly admitted footage calibration clips.
- Whether to remove the unused DigitalOcean proxies.

## Follow-ups (no fixed slot)

- **Attribution:**
  - a repost that credits no source (`unresolved: no_credit`);
  - acquiring `DeVlbTORhmq`;
  - the 3 pending Instagram reactions;
  - negative reaction examples;
  - recalibrating tau.
- **Footage:**
  - structured INFO logging;
  - blur or crop for subtitled footage (deferred by the operator).
- **Operations:**
  - re-import the X cookies when an account shows `expired`;
  - the Camoufox layer's venv `chown` size.
- **Persistence:**
  - convert the seven psycopg editor repositories to the SQLAlchemy ORM. Spec: `docs/superpowers/specs/2026-10-26-editor-repositories-orm-design.md`. Done 2026-10-26 on `refactor/editor-repositories-orm` (its own PR and deploy).

## Backlog after the migration

The operator asked that these not be lost.

- Interactive sign-in through a worker-run browser (never automated password entry).
- Capabilities that need a session: Instagram comment pagination, the grid beyond 12, view counts.
- Rotation of `THOTH_ACCOUNT_VAULT_KEY`.
- Creator Studio: the next legacy mode and the three deferred F3 minors.
- Structured JSON logs across the system.
- Scrapling in place of the CDP sidecar.
