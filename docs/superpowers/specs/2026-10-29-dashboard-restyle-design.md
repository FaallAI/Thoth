# Dashboard and Studio restyle: design and plan

Date: 2026-10-29. Status: draft for operator approval.

| Item | Where |
|---|---|
| Design reference | `docs/DESIGN.md`, approved 2026-10-25, with the rulings in §12 and Studio §13 |
| Screens | `design/thoth-dashboard-v2.pen` and its exports in `design/exports/v2/` |
| Backend it consumes | the run-progress stack: the stage plan, steps, `current_step`, estimates, the inbox, render frames (`docs/superpowers/specs/2026-10-25-run-progress-contract-design.md`) |
| Roadmap | "Dashboard redesign track", step 7. The operator assigned the execution to Claude (2026-10-29) |

## 1. Where the code is today

**Stack:**
- React 19, React Router 7, Tailwind v4, shadcn on Base UI, lucide, Remotion Player;
- about 8,800 lines of TSX and 70 kB of CSS (`dashboard.css`, `pen.css`, `pen-studio.css`, `pen-source-accounts.css`).

**Gaps against DESIGN.md:**

| Area | Today | DESIGN.md |
|---|---|---|
| Tokens | F3 tokens in `index.css`: gold means succeeded, `#ef4444` means failed, radii 4/6/8, Inter declared but Geist shipped | §5.1 canonical tokens with the F3 mapping, Geist, radii 6/10 |
| Language | English strings inline in components; no catalogue; dates through ad-hoc `toLocale*` | §12.1 English and Indonesian with a switch saved per user; step sentences from codes |
| Runs | `WorkflowsPage` list plus `WorkflowMonitor` with a flat stage list | §8.1-8.6: live rows with a segmented stage bar, stepper, activity log, estimate, approval card, results grid |
| Decisions | none | §8.7 inbox, top-bar bell, run tray |
| Notifications | none | §12.3 in-page offer, then browser notifications |
| Management | accounts, proxies, usage, billing, tokens exist; styled ad hoc | §8.9-8.11 restyled, plus a Settings page (language, notifications) |
| Studio | Guided Studio (F3 scenes), advanced Timeline, review, render, Prompt Lab inside Studio | §13: Story / Script / Timeline modes, Materials with provenance, render with frames, Prompt Lab moved to a project page |

**What the backend does not have yet:** a per-user language, which is added in R1.

## 2. Decisions this spec proposes (need operator approval)

**D1. The language is saved per user in the database.**
- Migration `0022_user_locale` adds `users.locale TEXT NULL CHECK (locale IN ('en', 'id'))`.
- `GET /me` returns it, and a new `PATCH /me` sets it.
- With no saved value, the browser language decides (`id*` gives `id`, anything else `en`).
- A caller without a user, such as a developer token, keeps the browser default, cached in `localStorage`.

**D2. No new i18n dependency.**
- The catalogue is two typed TypeScript objects (`en`, `id`) with the same keys, which the compiler enforces.
- `t(key, values)` uses ICU-free placeholders; `Intl.DateTimeFormat`, `NumberFormat` and `RelativeTimeFormat` handle dates and numbers.
- Plurals use `Intl.PluralRules`. Indonesian has no plural forms, so this stays small.

**D3. Story mode is a view over the draft, not a new document model.**
- Beats group the draft's scenes by their import inventory role:

  | Beat | Inventory roles |
  |---|---|
  | Main | `main`, `main_footage`, `slide` |
  | Evidence | `post_card`, `profile_card`, `profile_page` |
  | Reactions | `comment_card`, `comment` |
  | Footage | `footage`, `creator_footage`, `creator_photo` |

- Hook and Outro show only when the draft has them; auto-draft (roadmap item 6) creates them.
- Every edit in Story mode is an existing revision-bound operation, with no schema change.

**D4. Script mode waits for auto-draft.** It needs narration and voice, roadmap item 6. Until then the mode switch shows Story and Timeline only; it does not show a disabled Script.

**D5. Out of scope here:**
- bulk archive (it needs an archive field and endpoint; see §9 of DESIGN.md);
- full-text global search: ⌘K only navigates to pages, projects, recent runs and Studio documents;
- the light theme;
- publishing to platforms.

Each of these becomes a follow-up row in the roadmap when this ships.

**D6. Release in two parts.**

| Part | Phases | When |
|---|---|---|
| A | R1-R4: foundation, runs, inbox and tray, management | Merges and deploys with the run-progress stack, after the live gate (roadmap step 8) |
| B | R5-R7: Studio | Its own branch and release afterwards, so a Studio problem never holds back the runs work |

## 3. Phases (one branch per part, one commit per task, test first)

**R1. Foundation.**
- **Tokens:** `index.css` moves to the §5.1 canonical tokens (status colours, `faint`, radii 6/10, Geist and Geist Mono). The F3 names stay as aliases for the duration of this work, so nothing breaks mid-way; they are removed in R7.
- **Catalogue:** `lib/i18n.ts` (D2) and a `LocaleProvider`.
- **Backend:** the D1 migration and endpoint.
- **App shell:**
  - the sidebar per §4, collapsible, with a bottom sheet on narrow screens;
  - the top bar: project switcher with "All projects", inbox bell, run tray slot, avatar menu with the language switch;
  - ⌘K navigation (D5).
- **Components (§6):** StatusPill, StageStepper (vertical and compact), StepRow, SegmentedStageBar, MetricTile, EmptyState, Skeleton, ConfirmDialog. The existing buttons and inputs are restyled through the tokens.
- **Step catalogue:** the 25 step codes from the run-progress spec §5 have English and Indonesian sentences. An unknown code shows its stage label.

**R2. Runs.**
- **The list (§8.1):**
  - live rows: status, thumbnail and title, platform, the project in "All projects", the segmented stage bar, the current step, started, duration;
  - filters persisted in the URL;
  - metrics only when real.
- **The New run dialog (§8.2):**
  - live platform detection;
  - options: preset, approval on, output language;
  - no cost hint (§12.4).
- **Run detail (§8.3-8.6):**
  - the stepper with durations and the current step;
  - the activity log from `GET /workflows/{id}/steps`, in the 1 s loop;
  - the estimate ("about N min left", or "a few minutes" when `null`);
  - the approval card;
  - the failed state with "Retry run";
  - the done state with the results grid and "Open in Studio".
- **Notifications (§12.3):** the in-page offer, then browser notifications for approval needed, done and failed, once each per run.
- **Accessibility:** an `aria-live` region announces stage changes only.

**R3. Inbox and run tray.**
- **The inbox page (§8.7):** approvals, failed runs with "Acknowledge", and accounts for admins.
- **The top-bar bell:** the inbox count.
- **The run tray (§7.6):** "2 running · 1 waiting" and a popover with compact steppers.
- **Polling cadence:** as DESIGN §7.6 (the inbox on focus, after an action, and at most every 15 s).

**R4. Management.**
- Accounts and proxies (§8.9).
- Usage: a bar chart as hand-written SVG, no chart library, plus a table.
- Billing: "go-live deferred" stated honestly.
- Tokens.
- Sign-in (§8.11).
- A new Settings page: language, desktop notifications with the permission state, tokens.

**R5. Studio shell.**
- The documents list with the states of §13.5.
- Import progress (§13.3) and the inventory restyle.
- Review and Render restyled; Render shows frames, fps and an estimate from the phase 5 fields.
- Prompt Lab moves to a project "Presets & prompts" page; the route stays reachable from Studio.

**R6. Story mode (D3).**
- **Materials panel:** with provenance and a "why" popover.
- **Preview:** the 9:16 preview with a safe-zone toggle.
- **Beat strip:** selecting a beat moves the playhead.
- **Inspector:** timing, position preset, motion, emphasis, through existing operations.
- **States:** drag, missing material, conflict, Assist.

**R7. Timeline mode and clean-up.**
- The advanced timeline restyled as the Timeline mode, desktop only.
- The issues bar.
- The F3 aliases and the dead CSS (`pen*.css` rules no screen uses) are removed.

## 4. Verification for every phase

- **Dashboard:**
  - `bun test` (now deterministic after N5) and `bun run build`;
  - new components get behaviour tests, not snapshots;
  - every new string has both languages, and a test fails on a missing key.
- **Screens:** each screen is checked against its `.pen` export at 1440 and 430 widths, in both languages, through the local stack in a browser, with screenshots kept under `D:/thoth-tmp/restyle-shots/`.
- **Backend (R1 only):** the migration pair test, `make test-postgres`, the contract regenerated (additions only), the full Python suite, and `make lint`.
- **Accessibility:**
  - the keyboard paths in §10;
  - the focus ring;
  - reduced motion;
  - the contrast of new token pairs, checked once in R1 against §10's table.

## 5. Gates

- **Part A:** merges and deploys with the run-progress stack after roadmap step 8. That is one dashboard `produce_video` run with a TikTok main, watched end to end on the new screens. Push, PR, merge and deploy are operator gates; the renderer and Thoth deploy as one package.
- **Part B:** its own PR and deploy afterwards.
