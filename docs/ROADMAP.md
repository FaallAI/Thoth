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
| 11. Stage 10: retire Scout and Rust | Nearly done: Scout retired early and deployed 2026-10-31 (PR #97: no legacy activity, no `legacy-cdp`, no `scout/`); the Rust engine, its docs and Rust-only scripts removed 2026-10-31, which also clears the 17 Dependabot alerts (all were Rust crates). Left: dropping the decode-only `activity_mode` workflow input after 2026-11-29 |

Dashboard redesign track: steps 1-7 are deployed (run progress phases 1-5, restyle part A
R1-R4 and part B R5-R7, last on 2026-10-30 at `03741c3`). Step 8, the operator's live gate, is
open.

The backlog item "Scrapling in place of the CDP sidecar" is moot: the sidecar was removed with
Scout on 2026-10-31.

Item 6 (auto-draft), first milestone: the narrated draft is built on `feat/auto-draft-narration`
(2026-10-31, not yet merged): Create narration, script approval in Studio with a TTS estimate,
ElevenLabs voice per beat, word-highlight captions, ducking, licensed SFX, and re-voice per beat.
Spec `docs/superpowers/specs/2026-10-31-auto-draft-narrated-draft-design.md`.

### Open follow-ups from the 2026-10-30 and 2026-10-31 deploys

- **Security:** the 17 Dependabot alerts (2 critical, 4 high, 7 moderate, 4 low) were all in Rust
  crates (`zip`, `quinn-proto`, `rustls`, `tar`); the Rust retirement removes them.
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

## Style template track (added 2026-10-31)

An additional feature, after the base roadmap items; the operator wants the base features first.
Editing styles become **style templates**: one structured template schema that auto-draft turns
into a Studio draft. Research: the 2026-10-31 session (reference-matching tools, LLM-filled
component catalogs, shot detection with TransNetV2, LAVE / ExpressEdit / EditDuet).

| Step | Scope | Status |
|---|---|---|
| 1. Template schema and built-in Style A | Replaces auto-draft slice 3 "presets": the preset is a template | With item 6, slice 3 |
| 2. Prompt to template | An LLM fills the template's fields (pacing, caption style, hook, zoom, music mood) through Prompt Lab; validated, never a free-form timeline | Not started |
| 3. Reference video to template | Shot rhythm, OCR captions, transcript pace, keyframe layout and audio become a **proposed** template with per-field confidence; unsupported effects are flagged | Not started; needs slice 1 (transcript) |
| 4. Template gallery | Templates are private to their workspace; the operator can see, use and copy every template; a template the operator verifies can be published to every workspace with its creator credited, **only after the creator approves**; published versions are frozen snapshots; reference videos are never published | Not started |
| 5. Prompt editing of a draft | An LLM changes a draft only through the typed edit operations (`EditDocumentPatch`), with an editor-critic loop | Not started |
| 6. Shared SFX and assets | SFX live in MinIO/S3 with labels; uploaded SFX follow the template gallery: private to the workspace, operator review, uploader notified and approving, then available to every workspace with the uploader credited | Bundled SFX in MinIO come with auto-draft's first milestone; uploads not started |
| 6a. Workspace asset library (added 2026-11-13) | An Assets page per workspace: bulk upload, rename, labels, preview and delete of SFX, clips, backsound and images, private to the workspace and with no licence gate; Studio's Library panel copies an item into the draft; the script writer picks SFX from the draft's own workspace; the global seed-only SFX list retired | Built on `feat/workspace-assets` (spec and plan 2026-11-13); push, deploy and the import of `assets/` into the operator's workspace pending |

## Reference-faithful editing track (added 2026-11-12)

**Why.** After Style templates shipped (PR #128), the operator judged Style A and Style B "masih terlalu kaku": they do not yet carry the editing taste of the references. Style B was compared with the WinNews reference it copies:

| | WinNews | Our Style B draft |
|---|---|---|
| Shots | 33 in 50.4 s, about 1.5 s each | 19 in 53.9 s, about 2.6 s each |
| Picture sources | Clips from at least six news channels | 79 % of the time from the one main video |
| Cuts | On phrase starts | On sentence ends |
| Camera | Mostly still | A push-in on every shot |
| Extras | A soundbite of the person, used as a refrain | None |

The operator's narration was also too quiet: its beats measured −16.6 to −20.7 LUFS.

**Decisions with the operator (2026-11-12):**
- **Run order:** the run's order stays as it is. Narration-matched footage is added on top.
- **Source of truth:** our own footage library, organised per event and searched by moment. It takes clips from any platform and ranks them by relevance to the narration and its context (person, discussion, topic), never by platform.
- **Signals:** hashtags and audio are weak signals, not deciders.

The full record is in `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`. The research report is `reports/Indeks footage video lintas platform.md`.

The operator agreed this order:

| Step | Scope | Status |
|---|---|---|
| 1. Narration loudness | Every narration voice normalised to −14 LUFS, level with most TikTok videos (true peak −1.5 dB) when stored, by ffmpeg two-pass `loudnorm`, linear; length and word timings unchanged | Merged as `d90cf8bb` (PR #129, 2026-11-12); stage1 runs `42b843a8` |
| 2. Planner, stage 1 | Using materials we already have: a soundbite of the person taken from the main video's transcript and used as a refrain, cuts on phrase starts, fewer camera moves, a credit per clip | Not started; a short design first |
| 3. Footage library | Per event and searched by moment. Fed by trusted accounts on every platform, keyword search, reverse visual search from the main video's frames, OCR of source credits, and earlier runs' downloads. Copies are merged by perceptual hash, and the most original copy is kept. Each main post is read into a "context card" by a model; relevance is judged from a candidate's content, not its metadata. | Not started; needs a written design, after the research report's seven validation tests and a context-card test on three earlier random posts |
| 4. Stressed narration delivery | The script marks stressed words, and the voice settings are tuned to be more expressive | Not started; first one short paid voice sample, with the operator's approval |

## Studio Timeline track (added 2026-11-05)

The operator's audit request of 2026-11-05: every Timeline function must work, and a right click in
Studio must offer editing options like common video editors. The operator decided on 2026-11-05
that this track starts once `chore/e2e-trial` is merged and comes before the remaining slices of
item 6 (reframe, other modes). The numbered items above keep their wording and order. The track
gets its own spec, plan and branch; the scope below is the audit's input, not an agreed design.

| Step | Scope | Status |
|---|---|---|
| 1. Spec | Where the right click applies (Timeline only, or Story too), which menu entries, which server operations are new | Not started; waits on the `chore/e2e-trial` merge |
| 2. Missing functions the server already has | Delete a clip (`remove_clip`), drag to another track (`move_clip.target_track_id`), replace a clip's media (`replace_clip_asset`), track order (`reorder_track`), selecting a track from its name so an empty track can be removed | Not started |
| 3. Missing browser behavior | Right click, Ctrl+Z / Ctrl+Y, S to split, Ctrl+wheel zoom, click an empty lane to seek | Not started |
| 4. Locked or new edits | Fit, Crop, Position, fade, overlay text are locked in the Inspector; Duplicate has no operation yet | Not started; the spec decides which are needed |
| 5. Design findings | The playhead paints over track names when scrolled; raw names such as `main_video`; Ripple and Snap labels touch their switches; the Materials search field is squashed; "34.467s" beside "8.9 s"; Story/Timeline and Request review stay on Review and Render; at 1024 an empty Inspector takes a third of the width and cuts the last lane; Mute on soundless tracks | Not started |
| 6. Not tested yet | Ripple, audio volume and captions in the Timeline; Inspector number fields send one operation per keystroke (noted from the code) | Not started |

Status 2026-11-08: research, spec (`docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md`,
three tiers, Story menus included) and the Tier 1 plan are written; Tier 1 is built on
`feat/studio-timeline-track` (menus, keys, drag to a track, Replace media, plain names), not pushed.
Tier 2 and Tier 3 follow, in that order (operator, 2026-11-08).

Status 2026-11-09: Tier 1 merged as `ccddab63` (PR #122) and runs on stage1 as `c5a848b0`. Tier 2
(select many, copy and paste inside the draft, text paste to a chosen place, Fit/Crop/Position and
fades, close all gaps, asset search and drag, J/K/L, the 11 Tier 1 leftovers) is built and reviewed
on `feat/studio-timeline-tier2`, not pushed. Tier 3 follows.

Status 2026-11-09, later: Tier 2 merged as `1754d852` (PR #123) and runs on stage1 as `7b5d04f8`.
Tier 3 is split in two (operator, 2026-11-09). Tier 3a (clip speed, slip, roll, markers, menu-only
editing on phones, and the two Tier 2 answers) is built and reviewed on
`feat/studio-timeline-tier3a`, not pushed. Tier 3b (filmstrips, waveforms, the audio volume line)
follows.

Status 2026-11-09, last: Tier 3a merged as `d3c89bbb` (PR #124) and runs on stage1 as `573b2c92`.
Tier 3b (filmstrips on video and image clips, waveforms on audio clips, a draggable volume line) is
built and reviewed on `feat/studio-timeline-tier3b`, not pushed. With it the Studio Timeline track's
three tiers are built; the next track is the operator's choice.

The Studio full-width timeline (a resizable bottom row, the player bar under the preview, no text selection) is on `feat/studio-full-timeline` (PR #126), stacked on Tier 3b, and deployed to stage1 for the operator to try.

The Studio effects layer (moves, blur-fill, dim, marks, kinetic and boxed captions, the card place) is built on `feat/studio-effects-layer`, not pushed. Its `effects-v1` golden set waits for the operator's approval.

Style templates (Style template track step 1: the template schema with built-in Style A and Style B, applied in Studio with a cut preview before any voice) are built on `feat/style-templates`, stacked on PR #127, not pushed.

The red tests are `e2e/tests-write/timeline-audit.e2e.ts`. The Studio shell v2 spec
(2026-11-01) lists ripple delete as an existing tool, but git history shows no delete control in
the Timeline, toolbar or Inspector, so it counts as new work here.

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
