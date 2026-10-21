# Roadmap and Priorities

This file is the single list of work that is not done yet, in the order it should be done. The
migration stages keep their detail in
[python-scout-migration-roadmap.md](python-scout-migration-roadmap.md); finished work is recorded
in `CHANGELOG.md`. Update this file when an item finishes or the operator changes an order.

As of 2026-10-19. Nothing is in flight: every PR through #29 is merged, and the stack runs
`master` at `08df791` from `ghcr.io/faallai/*`. The repository lives at `FaallAI/Thoth`.

## Priority order

| # | Item | Why it comes here | Blocked by |
|---|---|---|---|
| 1 | ~~UI foundation (UI phase 0+1)~~ Done 2026-10-19 (PR #24, #26) | Every later UI item needs projects in the control plane, stored workflows, and URL routing | Done |
| 2 | ~~Workflow to Studio with media (UI phase 2)~~ Done: deployed 2026-10-21 (PR #36, `c9c6f0c`) | It opens the only end-to-end path: today a workflow's output cannot reach Studio and the main video must be uploaded by hand | 1 |
| 3 | ~~Decide the Rust engine's direction~~ Decided 2026-10-18: port it into the Python control plane | See "Decision: the Rust engine" | Done |
| 4 | Stage 5c: post cards, carousel photos, creator profile | Completes the Content Set that Studio imports; card overlays were left out of item 2 | 2 |
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

## Backlog after the migration

The operator asked that these not be lost.

- Interactive sign-in through a worker-run browser (never automated password entry).
- Capabilities that need a session: Instagram comment pagination, the grid beyond 12, view counts.
- Rotation of `THOTH_ACCOUNT_VAULT_KEY`.
- Creator Studio: the next legacy mode and the three deferred F3 minors.
- Structured JSON logs across the system.
- Scrapling in place of the CDP sidecar.
