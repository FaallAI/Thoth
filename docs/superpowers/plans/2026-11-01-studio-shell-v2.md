# Studio Shell v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Studio's shell match the corrected `Shell v2` frames. That means a one-row header with an overflow menu and narration status, Story and Timeline as panes on phone and tablet, human labels instead of IDs, a truthful beat strip, a clamped scene heading, and a grouped, clickable issues list.

**Architecture:**
- **Pure helpers first.** Labels and a beat's own time come before any UI, each with its own unit test.
- **Header and phone shell move out.** `GuidedStudio.tsx` (1170 lines) gives the header and the phone shell to new components. Its editing state stays where it is.
- **Each task leaves Studio working.** There is no feature flag.

**Tech Stack:** React 19, TypeScript, Bun test with happy-dom, Tailwind, lucide icons, the `useLocale` en/id dictionaries.

**Spec:** `docs/superpowers/specs/2026-11-01-studio-shell-v2-design.md`.
**Design:** `design/thoth-dashboard-v2.pen`, the frames `Studio shell v2 · Components`, `Studio shell v2 · README` and `Shell v2 · …`. PNG exports are in `D:/thoth-tmp/pen-review/` and `v2/`.

## Global Constraints

- **Font:** Geist (`--font-sans`). No other font.
- **Copy:** every new string goes in both `en` and `id`. The Indonesian 1024 frame is the width test.
- **Breakpoints:** from `studio_viewport.ts`: phone under 768, tablet under 1024, compact desktop under 1440, full desktop from 1440.
- **Header:** 56 px and one row from 1024 up. The jobs never stack.
- **No horizontal page scroll** at any width from 375 px up.
- **No IDs:** an `asset_…` or `clip_…` ID never appears as visible text.
- **No lost tools or fields:**
  - the Timeline keeps trim start, trim end, split and ripple delete, plus Ripple, Snap and the zoom slider;
  - the clip inspector keeps Start/End, the Transform presets, Fit, Crop, Offset, Hidden, Locked and Ownership.
- **No uneven card timing:** nothing shows "each card N s". Cards follow the voice.
- **Version 1 drafts** keep the scene board at every width.
- **Verification after every task:** `cd dashboard && bun test`, `bun x tsc -b` and `bun run lint`, all green before the commit.
- **Commits:** a single-line subject (`git commit -m "<subject>"`), with no body and no attribution.

## Review Focus

1. **A long title and Indonesian copy at exactly 1024 px.** The header must stay one row. Test: Task 2 "the header stays one row in Indonesian at 1024".
2. **A narration that fails or is cancelled.** The status must say so and offer Create again, never a dead button. Test: Task 3 "a failed narration offers Create narration again".
3. **An uploaded asset that no material or clip names.** It must show "Upload · Image", never its ID. Test: Task 1 "an asset nothing names is an upload of its kind".
4. **A phone rotated past 768 px with a pending edit.** The edit and the selection must survive the switch from panes to the desktop layout. Test: Task 6 "a pending timeline edit survives phone to tablet to desktop".
5. **An issue whose clip was deleted while the list was open.** Clicking it must do nothing harmful. Test: Task 5 "an issue for a clip that no longer exists selects its lane".

---

### Task 1: Labels for assets and clips

**Files:**
- Create: `dashboard/src/features/studio/studio_labels.ts`, `dashboard/src/features/studio/studio_labels.test.ts`
- Modify:
  - `AssetLibrary.tsx` (row text);
  - `story/MaterialsPanel.tsx` (upload rows);
  - `story/BeatInspector.tsx` (the Shown list, `name()` at :69);
  - `TimelineInspector.tsx` (title);
  - `TimelineClip.tsx` (the visible name; `aria-label` keeps its track wording plus the label);
  - `script/NarrationPresetForm.tsx` (`SfxLibrary` rows);
  - `lib/locale` dictionaries.

**Interfaces:**
- Produces:
  - `type LabelContext = { document: EditDocumentV2; materials: StudioMaterials | null }`
  - `assetLabel(assetId: string, ctx: LabelContext): { label: string; kind: "voice" | "card" | "video" | "image" | "music" | "sfx" | "upload"; seconds: number | null }`
  - `clipLabel(clip: TimelineClip, ctx: LabelContext): string`

**Label rules, first match wins:**
1. **Narration voice:** a clip `clip_narration_<beat>` → "Narration · <Beat>", kind `voice`. The beat names come from the existing `studio.story.beat.*` strings.
2. **Material:** an asset in materials gets "<Role> · <@owner_handle or label>", where the role is "Comment card", "Profile card", "Post card", "Profile page", "Footage", "Photo" or "Main video". Kind is `card` for card roles and the media kind otherwise.
3. **Sound effect:** a clip `clip_sfx_*` → "Sound effect · <sfx id with dashes as spaces>", kind `sfx`.
4. **Audio on a music track** → "Music", kind `music`.
5. **Text clips** → their heading, clamped to one line by the caller.
6. **Anything else** → "Upload · <Image|Video|Audio>", kind `upload`.

`seconds` is `duration_in_frames / fps`, rounded to 0.1.

- [ ] **Step 1: Write the failing tests** in `studio_labels.test.ts`:
  - "a narration voice is named by its beat": `clip_narration_main` → `"Narration · Main"`.
  - "a comment card is named by role and handle": `"Comment card · @lailynisfa"`.
  - "an asset nothing names is an upload of its kind": an image → `"Upload · Image"`, and the result never matches `/asset_|clip_/`.
  - "a sound effect clip is named by its library id": `clip_sfx_whoosh-short_000` → `"Sound effect · whoosh short"`.
- [ ] **Step 2: Run** `cd dashboard && bun test studio_labels`. Expected: FAIL, because the module is not found.
- [ ] **Step 3: Implement** `studio_labels.ts` as above, then wire it into each file listed in Files. Add a test per surface to that surface's existing test file:
  - "asset rows name assets, never by id" in `AssetLibrary.test.tsx`;
  - "the Shown list uses labels" in `story/BeatInspector.test.tsx`;
  - "the timeline inspector title is the clip label" in `TimelineInspector.test.tsx`.
- [ ] **Step 4: Run** `bun test`, `bun x tsc -b` and `bun run lint`. Expected: all green.
- [ ] **Step 5: Commit** `git commit -m "Name Studio assets and clips by kind and source, never by id"`

### Task 2: The one-row header and its overflow menu

**Files:**
- Create: `dashboard/src/features/studio/StudioHeader.tsx`, `dashboard/src/features/studio/StudioHeader.test.tsx`
- Modify:
  - `GuidedStudio.tsx` (replace the `<header>` block at :534–720 with `<StudioHeader …/>`);
  - `GuidedStudio.responsive.test.tsx`;
  - the locale dictionaries.

**Interfaces:**
- Produces:

  ```ts
  StudioHeader(props: {
    title: string;
    job: StudioJob;
    onJob: (job: StudioJob) => void;
    mode: "simple" | "advanced" | null;
    onMode?: (m) => void;
    saveStatus;
    revision: number;
    canUndo: boolean;
    canRedo: boolean;
    onUndo;
    onRedo;
    onBack;
    backDisabled: boolean;
    onRequestReview;
    viewport: StudioViewport;
    narration?: ReactNode;
    menu: ReactNode;
    menuAttention: boolean;
  })
  ```

  - **Overflow button:** it holds a `<details>` with `menu` inside. When `menuAttention` is true the button shows an amber dot.
  - **`narration` slot:** rendered inline only when `viewport === "full_desktop"`. Otherwise the caller puts it at the top of `menu`.
- Consumes: `StudioJobNav` (unchanged).

**Layout:**
- **One row:** a single flex row, `h-14`, with no `flex-wrap`. The title gets `min-w-0 truncate` and a `title` attribute.
- **Tier 1 order:** back, separator, title, jobs, mode, spacer, undo/redo, save status, Request review, overflow.
- **Compact desktop** (1024–1439): the back button is an icon only, with an aria-label.
- **Menu contents, in order:** the narration block (when present and the viewport is below full desktop), Script, Assist (a button that opens the Assist panel, `aria-haspopup="dialog"`), then Settings, which is today's project and workspace controls.

- [ ] **Step 1: Write the failing tests:**
  - **In `StudioHeader.test.tsx`:**
    - "tier 1 controls are always in the header": back, jobs, mode, undo, redo, save, Request review and overflow.
    - "the header row never wraps": the `header` has no `flex-wrap` class and has `h-14`.
    - "the narration chip is inline at full desktop and in the menu below it".
    - "the header stays one row in Indonesian at 1024": render with the `id` locale at 1024 and assert the jobs share the header's single row container.
    - "Assist opens its panel from the menu": a click calls `onAssist`, and there is no `aria-pressed` toggle.
  - **In `GuidedStudio.responsive.test.tsx`:** update "offers the three destinations at every width" so it expects the jobs inside `header`, never in a second row.
- [ ] **Step 2: Run** `bun test StudioHeader GuidedStudio.responsive`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `StudioHeader.tsx` and swap it into `GuidedStudio.tsx`:
  - move Script, Assist and the settings content from the header into `menu`;
  - remove the inline `Script` and `Assist` buttons from the header;
  - keep every existing control reachable.
- [ ] **Step 4: Run** `bun test`, `bun x tsc -b` and `bun run lint`. Expected: all green.
- [ ] **Step 5: Commit** `git commit -m "Keep Studio's header to one row with an overflow menu"`

### Task 3: Narration status instead of the dead button

**Files:**
- Create: `dashboard/src/features/studio/script/NarrationStatus.tsx`, `script/NarrationStatus.test.tsx`
- Modify:
  - `GuidedStudio.tsx`, which passes `<NarrationStatus/>` as the header's `narration` slot;
  - `script/NarrationButton.tsx`, deleted once nothing imports it;
  - the locale dictionaries.

**Interfaces:**
- Consumes: `NarrationState`; `client.startNarration`, `revoiceNarrationBeat` and `restartNarration`; `isNarrationActive` from `script/useNarration.ts`.
- Produces:

  ```ts
  NarrationStatus(props: {
    client;
    projectId;
    documentId;
    state: NarrationState | null;
    beatCount: number;
    onChange(state): void;
    onOpenScript(): void;
  })
  ```

**States:**
- **None, failed or cancelled:** the "Create narration" button. Failed and cancelled add a one-line reason, using `failure_code` for failed.
- **Active:** a chip with a spinner and the status text (`transcribing`, `scripting`, `voicing`, `writing`).
- **`awaiting_approval`:** the chip reads "Script ready to approve" and opens Script.
- **`completed`:**
  - The chip reads "Narrated · N beats". When `stale_beats` is non-empty it adds "· N need re-voice", shown in amber.
  - The chip opens a block holding "Re-voice N changed beats", "Recreate narration…" (today's confirmation, moved here) and "Open script".
  - **Re-voicing:** "Re-voice N changed beats" calls `revoiceNarrationBeat` for each stale beat, one at a time. After each call it applies the returned state with `onChange`, and on the first error it stops and shows the error.

- [ ] **Step 1: Write the failing tests:**
  - "a draft without narration offers Create narration";
  - "a failed narration offers Create narration again";
  - "a completed narration reads Narrated · 4 beats and offers re-voice only for stale beats";
  - "re-voicing changed beats calls each stale beat in order and stops at the first error": stale is `["main", "reactions"]`, and the second call rejects;
  - "Recreate narration asks first".
- [ ] **Step 2: Run** `bun test NarrationStatus`. Expected: FAIL, because the module is not found.
- [ ] **Step 3: Implement** `NarrationStatus.tsx`, wire it in, and delete `NarrationButton.tsx`. Move its tests' cases into the new file or drop them where they duplicate.
- [ ] **Step 4: Run** `bun test`, `bun x tsc -b` and `bun run lint`. Expected: all green.
- [ ] **Step 5: Commit** `git commit -m "Show narration status in Studio's header instead of a dead button"`

### Task 4: Truthful beat strip, clamped heading, voice-led timing

**Files:**
- Modify:
  - `story/story_beats.ts` (add `beatOwnFrames`) and `story/story_beats.test.ts`;
  - `story/BeatStrip.tsx` and its test;
  - `story/BeatInspector.tsx` and its test;
  - the locale dictionaries.

**Interfaces:**
- Produces: `beatOwnFrames(spans: BeatSpan[], totalFrames: number): Map<BeatId, number>`.
  - Spans are sorted by start frame. A beat owns the frames from its start until the next beat starts; the last beat owns them until `totalFrames`; the first beat also owns the frames from 0.
  - The values always sum to `totalFrames`.
- Consumes: `NarrationState.stale_beats` and the narrated beats (beats with a `clip_narration_<beat>` clip), passed into `BeatStrip` as `voiced: Set<BeatId>` and `stale: Set<BeatId>`.

**Rules:**
- **Tile seconds:** each tile shows `beatOwnFrames` seconds, and the strip shows "Total N s · matches canvas".
- **Mic badge:** green when the beat is voiced, amber when it is stale.
- **Outline:** `border-copper` only on the selected tile.
- **Scene heading:** the inspector shows it as a two-line clamp (`line-clamp-2`) with an Edit button. Edit reveals the existing heading and body fields; a `title` attribute holds the full heading.
- **Timing section:** for a narrated beat it reads "Cards follow the voice · N s". It never offers a per-card length.

- [ ] **Step 1: Write the failing tests:**
  - "a beat owns its frames until the next beat starts": spans main 0, evidence 266, reactions 524, footage 766 with a total of 1034 → 266, 258, 242 and 268.
  - "beat seconds always sum to the canvas": with overlapping spans.
  - "only the selected tile is outlined; a stale beat shows an amber mic".
  - "the scene heading is clamped with Edit".
  - "a narrated beat's timing follows the voice": the text "Cards follow the voice" is present, and no input is labelled "Each card".
- [ ] **Step 2: Run** `bun test story_beats BeatStrip BeatInspector`. Expected: FAIL.
- [ ] **Step 3: Implement** the rules above.
- [ ] **Step 4: Run** `bun test`, `bun x tsc -b` and `bun run lint`. Expected: all green.
- [ ] **Step 5: Commit** `git commit -m "Make the beat strip sum to the canvas and clamp the scene heading"`

### Task 5: Grouped, clickable issues

**Files:**
- Modify:
  - `IssuesPanel.tsx` (`IssuesBar`) and `IssuesPanel.test.tsx`;
  - `TimelineInspector.tsx` (an Issues section) and its test;
  - the locale dictionaries.

**Interfaces:**
- Consumes: `timelineIssues` and `issueTarget` from `timeline_domain.ts`; `clipLabel` (Task 1); the existing editor actions (`select_issue`, `select_track`, `select_clip`, `set_playhead`).

**Rules:**
- **Grouping:** the list groups rows under each lane's label, in track order.
- **Row content:** the clip's label (Task 1), the issue sentence, and the clip's start time as `m:ss.s`.
- **Clicking a row:**
  - It does what `select` does today and also dispatches `set_playhead` to the clip's `from_frame`.
  - When the clip no longer exists, it selects the lane only.
- **Where the list opens:** a popover anchored to the bar on desktop, a bottom sheet (fixed, full width) on phone.
- **Inspector:** `TimelineInspector` lists the selected clip's issues under "Issues · N".

- [ ] **Step 1: Write the failing tests:**
  - "issues are grouped by lane in track order";
  - "an issue row names its clip and moves the playhead to it";
  - "an issue for a clip that no longer exists selects its lane";
  - "the inspector lists the selected clip's issues".
- [ ] **Step 2: Run** `bun test IssuesPanel TimelineInspector`. Expected: FAIL.
- [ ] **Step 3: Implement** the rules above.
- [ ] **Step 4: Run** `bun test`, `bun x tsc -b` and `bun run lint`. Expected: all green.
- [ ] **Step 5: Commit** `git commit -m "Group timeline issues by lane and jump to their clip"`

### Task 6: Story and Timeline as panes on phone and tablet

**Files:**
- Create: `dashboard/src/features/studio/PhoneShell.tsx`
- Modify:
  - `GuidedStudio.tsx` (`effectiveMode`, `story`, `quick`, the compact pane logic at :111–183 and the compact branches);
  - `CompactStudioNav.tsx` (it takes the new pane ids);
  - `StudioHeader.tsx` (the phone variant);
  - `story/BeatStrip.tsx` (a chip variant);
  - `Timeline.tsx` (a `readOnly` prop);
  - `GuidedStudio.responsive.test.tsx`;
  - the locale dictionaries;
  - `design/DESIGN.md` §13.5 (record that phones use Story and Timeline panes).
- Delete: `story/QuickEdit.tsx` and its test, once nothing imports them.

**Interfaces:**
- **Panes:**
  - `StudioEditPane` becomes `"materials" | "preview" | "inspector" | "timeline"`.
  - Story uses materials, preview and inspector; Timeline uses materials (titled "Assets"), preview, timeline and inspector.
  - A version 1 draft keeps `scenes | preview | controls`.
- **Mode:** `effectiveMode` stops forcing `"simple"` on compact viewports for a version 2 draft. `story` and `advanced` hold at every width.
- **`Timeline` gets `readOnly?: boolean`.** When set, it renders the lanes and clips but no drag, trim or toolbar edit actions. Tapping a clip selects it, and the phone shows a summary card with "Inspect", which switches to the Inspector pane.
- **`StudioHeader`, phone variant:**
  - **Header contents:** back, the title with a status line ("Story · Saved · rev N") and the overflow button.
  - **Overflow sheet, in order:**
    1. the mode and the jobs;
    2. the save state and undo/redo;
    3. the narration block;
    4. Script, Assist and Settings;
    5. Request review, as a full-width primary action.
- **`BeatStrip` gets `variant: "tiles" | "chips"`.** Chips are one row with `overflow-x-auto`, and the total is pinned on the left.

- [ ] **Step 1: Write the failing tests** in `GuidedStudio.responsive.test.tsx`:
  - "a phone edits a version 2 draft in Story panes": the panes are Materials, Preview and Inspector, and a beat chip row is present.
  - "Timeline on a phone is view-only, with a larger-screen note": no trim handles, and tapping a clip shows Inspect.
  - "the Timeline option is offered at every width for a version 2 draft". This replaces "the Timeline option starts at 1024 px wide".
  - "a pending timeline edit survives phone to tablet to desktop".
  - "nothing scrolls horizontally at 430": the root's `scrollWidth <= clientWidth` under a 430 px viewport mock.
  - "a version 1 draft keeps the scene board on a phone".
  - "desktop Timeline keeps every tool and inspector field": with a clip selected at 1440, the trim start and end, split, ripple delete, Ripple, Snap and zoom controls are present, and so are the inspector's Start, End, Top/Middle/Lower third, Fit, Crop, Offset, Hidden, Locked and Ownership.
  - Rewrite the tests that assert the phone quick edit to assert the Story Inspector instead: "edits caption text on a tablet … and keeps it in the phone quick edit", and the round-trip test.
- [ ] **Step 2: Run** `bun test GuidedStudio.responsive`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the panes, the phone header and sheet, the chips and the read-only Timeline. Delete QuickEdit, and update DESIGN.md §13.5.
- [ ] **Step 4: Run** `bun test`, `bun x tsc -b`, `bun run lint` and `bun run build`. Expected: all green.
- [ ] **Step 5: Commit** `git commit -m "Edit Story and Timeline in panes on phones and tablets"`

### Task 7: Browser walk and records

**Files:**
- Modify: `CHANGELOG.md` and `.superpowers/sdd/2026-11-01-studio-shell-v2/progress.md`.

- [ ] **Step 1:** Run the dashboard dev server with the read-scope token (`THOTH_DEV_TOKEN` from `D:/thoth-tmp/e2e-dev-token`; `bun run dev --port 5199`, opened as `localhost`). Hold a WSL session open while it runs.
- [ ] **Step 2:** Capture the narrated stage1 draft at 1440, 1024 (en and id) and 430 in Story and Timeline into `D:/thoth-tmp/shell-v2-shots/`.
- [ ] **Step 3:** Compare the shots against the `Shell v2 · …` exports. For each:
  - the header must be one row;
  - `scrollWidth` must equal the viewport width;
  - no `asset_` or `clip_` text may appear;
  - the beat total must equal the canvas.

  Fix any difference in the owning task's files, with a test.
- [ ] **Step 4:** Run the full verification: `make test`, `make lint`, and the dashboard's tests, `tsc -b` and build.
- [ ] **Step 5:** Record the work in `CHANGELOG.md` and the progress checkpoint, including Next steps, then commit with `git commit -m "Record Studio shell v2"`.
