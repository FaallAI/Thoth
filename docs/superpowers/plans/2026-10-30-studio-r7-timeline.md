# Studio R7: Timeline Mode and Clean-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the advanced timeline as the desktop-only Timeline mode of DESIGN §13.1, replace the issues list with the issues bar, and remove the F3 token aliases and dead `pen*.css` rules.

**Architecture:** The editing behaviour stays: `Timeline.tsx` keeps its gesture, snap, ripple, split and trim logic, and every edit stays a typed revision-bound operation. New pure helpers (`timecode`, ruler ticks, clip labels) live in `timeline_domain.ts` and carry the tests; the components only lay them out with the §5.1 tokens. Every visible string moves into `lib/i18n.ts` in both languages.

**Tech Stack:** React 19, Tailwind v4 with the §5.1 tokens in `dashboard/src/index.css`, lucide-react icons, Bun test with Testing Library and happy-dom.

**Spec:** `docs/superpowers/specs/2026-10-29-dashboard-restyle-design.md` §3 R7 and §4; `docs/DESIGN.md` §13.1, §13.5; target export `design/exports/v2/studio-timeline.png` and `note-timeline-is-desktop-only.png` (operator machine, not in git).

## Global Constraints

- Branch `feat/studio-r7-timeline`, worktree `D:/thoth-tmp/wt-r7`; one commit per task; local until the operator's push gate.
- "Every new string has both languages, and a test fails on a missing key" (`lib/i18n.test.ts` already enforces it).
- "New components get behaviour tests, not snapshots."
- Timeline is desktop only: below 1024 px (`studio_viewport.ts`: phone and tablet) Studio shows Story only, and a Timeline document opens in Story with "Open on a larger screen to edit the timeline."
- Colours come from the §5.1 tokens only (`--playhead` for the playhead, `--copper` for the selection, `--studio-ai` stays AI only); no hex in components.
- Keyboard parity (DESIGN §13 keeps it from F3): every pointer gesture keeps a keyboard path.
- No new dependency.

**Out of scope, deviations from DESIGN §13.1 for the operator to confirm:** clip thumbnails and audio waveforms (nothing produces frame strips or audio peaks today; drawing fake ones would misrepresent the media), canvas drag handles on the preview, and Scale and Opacity fields (no edit operation exists for them; `set_clip_position` is used through the existing position presets).

## Review Focus

- A zero-length or one-frame document: the ruler, the timecode and the zoom slider must not divide by zero or draw `NaN` (Task 1 and Task 2 tests).
- A clip with no label source (no cues, no heading, no `source_role`): it reads as its kind, never as an empty pill (Task 3 test).
- A locked track or clip: icon toggles and clip actions stay disabled exactly as before the restyle (Task 3 and Task 1 keep the existing locked tests).
- The issues bar while issues change under a background save: the list must not steal focus; focus moves only on a click (Task 4 keeps the existing focus test).
- Indonesian strings are longer: the transport row and the issues bar must not overflow at 1024 px (Task 8 screenshot in `id`).

---

### Task 1: Timecode, transport bar

**Files:**
- Modify: `dashboard/src/features/studio/timeline_domain.ts`, `TimelineToolbar.tsx`, `Timeline.tsx`, `lib/i18n.ts`
- Test: `dashboard/src/features/studio/timeline_domain.test.ts`, `Timeline.test.tsx`

**Interfaces:**
- Produces: `formatTimecode(frame: number, fps: number): string` in `timeline_domain.ts`; `TimelineToolbar` gains `playheadFrame`, `durationInFrames`, `fps`, `playing`, `onPlay`, `onPause` props.

- [ ] **Step 1: Failing tests.** `formatTimecode(0, 30) === "0:00.0"`, `formatTimecode(906, 30) === "0:30.2"`, `formatTimecode(1440, 30) === "0:48.0"`, `formatTimecode(3600 * 30, 30) === "60:00.0"`, `formatTimecode(5, 0) === "0:00.0"` (fps 0 never divides). In `Timeline.test.tsx`: the transport shows `"0:00.0 / 0:48.0"` for a 1440-frame, 30 fps document; the play button's name is `t("studio.timeline.play")` and becomes `t("studio.timeline.pause")` while `state.playing`; the Snap switch is `role="switch"` with `aria-checked` following `state.snapping`; the zoom slider (`aria-label` `t("studio.timeline.zoom")`) dispatches `set_zoom` within `MIN_ZOOM..MAX_ZOOM`, and the − / + buttons halve and double as before.
- [ ] **Step 2: Run** `bun --cwd=dashboard test src/features/studio/timeline_domain.test.ts src/features/studio/Timeline.test.tsx` — FAIL.
- [ ] **Step 3: Implement.** Minutes are not wrapped into hours. The transport row is the design's: play/pause icon button (lucide `Play`/`Pause`), mono timecode `current / total`, then right-aligned Ripple switch, Snap switch, zoom − slider +. The four clip actions stay, as icon buttons (lucide `ArrowRightToLine` move, `BetweenHorizontalStart` trim start, `BetweenHorizontalEnd` trim end, `Scissors` split) with `aria-label`s from i18n, disabled exactly as today. The zoom slider moves in log2 steps. Remove the old "Play preview" button and the `{frame}/{duration}f` readout. New keys (en and id): `studio.timeline.play`, `.pause`, `.snap`, `.ripple`, `.zoom`, `.zoomIn`, `.zoomOut`, `.moveToPlayhead`, `.trimStart`, `.trimEnd`, `.split`, `.locked`.
- [ ] **Step 4: Run** the same command — PASS.
- [ ] **Step 5: Commit** `git commit -m "Restyle the timeline transport with timecode, snap and zoom"`

### Task 2: Ruler and playhead

**Files:**
- Modify: `timeline_domain.ts`, `Timeline.tsx`, `lib/i18n.ts`
- Test: `timeline_domain.test.ts`, `Timeline.test.tsx`

**Interfaces:**
- Produces: `rulerTicks(durationInFrames: number, fps: number, zoom: number): { frame: number; label: string }[]`.

- [ ] **Step 1: Failing tests.** The tick step is the smallest of `[1, 2, 5, 10, 15, 30, 60]` seconds whose spacing `framesToPixels(step * fps, zoom) >= 80`; ticks start at 0 and stop at or before the duration; labels are `formatTimecode` without the tenth (`"0:05"`). `rulerTicks(0, 30, 1)` returns `[{ frame: 0, label: "0:00" }]`; `fps` 0 returns the same. In `Timeline.test.tsx`: the ruler is `role="slider"` named `t("studio.timeline.playhead")` with `aria-valuenow` = playhead frame and `aria-valuetext` = its timecode; ArrowRight / ArrowLeft move one frame, Shift+Arrow one second, Home / End to 0 / last frame, each dispatching `set_playhead` and calling `onSeek`; a pointer down at x on the ruler seeks to `Math.round(x / zoom)`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** The ruler replaces the `<input type="range" aria-label="Playhead">` row. It sits above the lanes in the same scroll container, offset by the 192 px header column. The playhead is a 1 px `bg-[var(--playhead)]` line through the ruler and every lane, with a small round head on the ruler. Pointer drag on the ruler keeps seeking until pointer up.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "Add a timeline ruler that seeks by pointer and keyboard"`

### Task 3: Track headers and clips

**Files:**
- Modify: `timeline_domain.ts`, `TimelineTrack.tsx`, `TimelineClip.tsx`, `lib/i18n.ts`
- Test: `timeline_domain.test.ts`, `Timeline.test.tsx`

**Interfaces:**
- Produces: `clipLabelSource(clip: TimelineClip): { text: string } | { role: SourceRole } | { kind: TimelineClip["kind"] }` (pure; the component turns `role` into `t("studio.inventory.role.<role>")` and `kind` into `t("studio.timeline.kind.<kind>")`).

- [ ] **Step 1: Failing tests.** A caption clip reads as its first cue's text; a text clip as its `heading`; a clip with `source_role: "comment_card"` as `{ role: "comment_card" }`; a clip with none of these as `{ kind }`; empty strings fall through to the next source. In `Timeline.test.tsx`: a track header shows the track kind in mono (`main_video`) with its lucide icon (`Film`, `Clapperboard`, `Layers`, `Captions`, `AudioLines`, `Music`, `Zap` for main_video, b_roll, overlay, caption, narration, music, sfx); the hide, mute and lock toggles are icon buttons named `t("studio.timeline.hideTrack", { track })` etc. with `aria-pressed`, and the existing locked-track tests keep passing unchanged except for names.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** Lanes are 44 px with a hairline divider; the header column stays 192 px. Clip fill by track kind: video tracks `bg-[var(--raised)]`, overlay `bg-[var(--surface)]`, caption `bg-[var(--surface)]` with a hairline border, audio tracks `bg-[var(--well)]`; label pill top-left in `text-xs`. The selected clip has a 2 px copper border (`border-[var(--copper)]`); a locked clip shows a lucide `Lock` icon instead of the " · locked" suffix. Trim handles stay 8 px, copper at 40 % on the selected clip only. New keys: `studio.timeline.kind.<video|overlay|text|caption|audio>`, `.hideTrack`, `.showTrack`, `.muteTrack`, `.unmuteTrack`, `.lockTrack`, `.unlockTrack`, `.clip`, `.trimStartOf`, `.trimEndOf` (with `{track}` / `{clip}` placeholders).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "Restyle timeline tracks and clips with labels from the draft"`

### Task 4: Issues bar

**Files:**
- Modify: `IssuesPanel.tsx` (renamed export `IssuesBar`, same file), `GuidedStudio.tsx` (import), `lib/i18n.ts`
- Test: `IssuesPanel.test.tsx`

**Interfaces:**
- Consumes: `timelineIssues`, `issueTarget` (unchanged).
- Produces: `IssuesBar` with the same props as `IssuesPanel`.

- [ ] **Step 1: Failing tests.** With no issues the bar reads `t("studio.issues.none")` with a done-coloured check icon; with n issues it reads `t("studio.issues.warnings", { count: n })` with a waiting-coloured dot, then the first issue's sentence, then a `t("studio.issues.review")` button with `aria-expanded`. Pressing it reveals the list (the existing items and click behaviour, unchanged); pressing it again hides it. Timeline issues are warnings: none of today's four codes blocks a render (render readiness owns the blocking checks, DESIGN §13.4), so the bar shows no "blocking" count. The existing focus test (focus moves only on a click) passes unchanged.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** A 32 px row on `bg-[var(--well)]` with a top hairline, `text-xs`; the list opens upward above the bar, capped at 40 % of the viewport height and scrollable. The four sentences move to i18n as `studio.issues.<code>` with `{track}`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "Replace the timeline issues list with the issues bar"`

### Task 5: Timeline inspector sections

**Files:**
- Modify: `TimelineInspector.tsx`, `lib/i18n.ts`
- Test: `TimelineInspector.test.tsx`

**Interfaces:**
- Consumes: `formatTimecode` (Task 1), `setPositionPreset` and `PositionPreset` from `story/story_edits.ts`, keys `studio.inspector.position.*`.

- [ ] **Step 1: Failing tests.** The heading is the clip's label (Task 3 rule) and a sub-line `"{track} track"`. Sections, each a `role="group"` with an uppercase mono heading: Timing (the existing start and end frame inputs, each followed by its timecode, e.g. `0:28.4`), Position (only for a clip with `position`: Top / Middle / Lower third buttons committing `setPositionPreset(document, [clipId], preset)`), Audio (the existing volume for audio and video clips; for any other clip a disabled field and `t("studio.timeline.noAudio")`), Track (hidden, muted, locked, ownership as today). Every label comes from i18n.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with the existing operations only.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "Group the timeline inspector into timing, position, audio and track"`

### Task 6: Desktop only

**Files:**
- Modify: `Timeline.tsx` (drop the `lg:hidden` paragraph and the `hidden lg:block` gate), `lib/i18n.ts`
- Test: `GuidedStudio.responsive.test.tsx`

- [ ] **Step 1: Failing test.** At a tablet width with a stored Timeline mode, the mode switch has no Timeline option and the note reads exactly "Open on a larger screen to edit the timeline." (id: "Buka di layar yang lebih besar untuk mengedit timeline."); at 1024 px the Timeline option shows.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement:** change `studio.editor.compactAdvanced` in both languages; remove the timeline's own narrow-screen paragraph, which `compact` already makes unreachable.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "Say plainly that the timeline opens on a larger screen"`

### Task 7: Remove the F3 aliases and dead CSS

**Files:**
- Modify: `dashboard/src/index.css`, `tokens.test.ts`, `pen.css`, `pen-studio.css`, `pen-source-accounts.css`, `dashboard.css`, `features/studio/studio.css`
- Create: `dashboard/src/css_usage.test.ts`

- [ ] **Step 1: Failing test** `css_usage.test.ts`: every class selector in those five CSS files is used by a non-test `.ts`/`.tsx` source, either literally or through a template prefix (`"sa-dot--${"` counts for `sa-dot--healthy`; so does `studio-job-${`). It lists the unused classes in its failure message. Extend `tokens.test.ts`: `--status-queued`, `--status-succeeded`, `--status-cancelled`, `--spine` and their `--color-*` twins are absent.
- [ ] **Step 2: Run** `bun --cwd=dashboard test src/css_usage.test.ts src/tokens.test.ts` — FAIL with the class list.
- [ ] **Step 3: Implement:** delete each listed rule (a rule whose selector list mixes used and unused classes keeps the used part); delete a CSS file that ends empty and its `@import`; remove the four aliases and their old assertions in `tokens.test.ts`.
- [ ] **Step 4: Run** the full suite `bun --cwd=dashboard test` and `bun --cwd=dashboard run build` — PASS.
- [ ] **Step 5: Commit** `git commit -m "Remove the F3 token aliases and the CSS no screen uses"`

### Task 8: Screens, record

- [ ] **Step 1:** Run `vite dev` from the worktree with the read-scope `THOTH_DEV_TOKEN` (`D:/thoth-tmp/e2e-dev-token`) against stage1's API, open the draft `/studio/db766411-3cb0-47a4-9dc9-b67d22f6f34e/edoc_2927f3009eb64ba6bb9a41534ad2dff5` in Timeline mode, and capture it with Playwright's Chromium at 1440 and 1024 wide in `en` and `id`, plus 430 wide (Story with the note), into `D:/thoth-tmp/restyle-shots/r7/`. Compare with `studio-timeline.png`; any difference beyond the out-of-scope list is fixed in the owning task.
- [ ] **Step 2:** `bun --cwd=dashboard test` and `bun --cwd=dashboard run build` once more; CHANGELOG entry with Next steps; SDD checkpoint `.superpowers/sdd/2026-10-30-studio-r7/progress.md`.
- [ ] **Step 3: Commit** `git commit -m "Record R7: Timeline mode and clean-up"`
