# Roadmap and Priorities

This file is the single list of work that is not done yet, in the order it should be done. The
migration stages keep their detail in
[python-scout-migration-roadmap.md](python-scout-migration-roadmap.md); finished work is recorded
in `CHANGELOG.md`. Update this file when an item finishes or the operator changes an order.

As of 2026-10-18. Nothing is in flight: every PR through #22 is merged and deployed.

## Priority order

| # | Item | Why it comes here | Blocked by |
|---|---|---|---|
| 1 | UI foundation (UI phase 0+1) | Every later UI item needs projects in the control plane, stored workflows, and URL routing | Nothing; the design is approved |
| 2 | Workflow to Studio with media (UI phase 2) | It opens the only end-to-end path: today a workflow's output cannot reach Studio and the main video must be uploaded by hand | 1 |
| 3 | Decide the Rust engine's direction | Items 4 and 6 depend on it | Operator decision |
| 4 | Stage 5c: post cards, carousel photos, creator profile | Completes the Content Set that Studio imports; card overlays were left out of item 2 | 2 |
| 5 | Dashboard serving and Google/GitHub sign-in (UI phase 3) | The control-plane key ships in the JS bundle today; this must land before the stack is reachable from another host | 1 |
| 6 | Auto-draft and Rust Profiles as its presets | Restores "source to finished video" (script, voice, subtitles, clip order) on the new path, if item 3 picks porting | 2, 3 |
| 7 | Stage 6: enrichment | Gives auto-draft narration its context | 6 |
| 8 | Stage 8: discovery in Python, then UI phase 4 (retire the legacy pages) | Discovery starts workflows; the Content Set page, Scout discovery, Legacy Console and "Send to render" go | 2 |
| 9 | Stage 7: durable orchestration | Restart-safe, resumable runs before the final acceptance | 8 |
| 10 | Stage 9: cutover and the final live acceptance | Runs every live smoke deferred under ADR 0001 | 1-9 |
| 11 | Stage 10: retire Scout TypeScript (and the Rust engine, if item 3 picks porting) | Last | 10 |

Items that wait on operator input run in parallel whenever the input arrives; see
"Waiting on the operator".

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
- **Phase 4, legacy retirement:** together with Stage 8.

## Open decision: the Rust engine

`thoth-core` (about 48k lines) holds the automatic video engine: ingest, Whisper transcription
(CUDA), moment selection, cut and reframe with subtitles, narration and TTS, profile cards, and
NVENC render. The migration roadmap never moves it, and it runs natively on Windows with CUDA,
outside the containers.

| Option | What happens |
|---|---|
| A. Port gradually (recommended) | Auto-draft builds a full Studio document from a Content Set and Remotion renders it. Rust is frozen, then retired at Stage 10. |
| B. Keep Rust as a render worker | Rust sits behind an adapter. The stack stays tied to Windows and CUDA, with two render engines. |
| C. Freeze without a replacement | Videos are assembled by hand in Studio. |

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
