# Thoth Dashboard: Design

Status: direction approved by the operator on 2026-10-25, together with the rulings in §12.

This is the single design reference for the dashboard. The `.pen` designs are made from it. The dashboard is the product: every workflow, review, edit, render, account and bill is reached through it, so this document covers how it looks, how it is organised, and above all how a long run explains itself while it works.

**Sources:**
- the current dashboard code (`dashboard/src`) and API (`python/src/thoth_control_plane/api`);
- `docs/ROADMAP.md`;
- the UI audit of 2026-10-18;
- `design/thoth-dashboard.pen`, the current design file, about 50 frames;
- Temporal Python SDK docs read through Context7: activity heartbeat details and `describe().pending_activities`, `workflow.set_current_details`.

---

## 1. Why a redesign now

1. **Runs are long.** Since the `produce_video` chain (PR #67), a dashboard run is source, then approval, then attribution, footage and assembly. That takes about 6 to 10 minutes; the source step alone takes 1 to 2.5 minutes. A screen that only says "running" for ten minutes reads as broken.
2. **The progress model is too coarse.**
   - `WorkflowSummary.stages` always holds a single stage (`source`, "Investigate original source") whose status mirrors the whole run. The attribution, footage and assembly stages exist only as events, and the monitor never lists them.
   - Inside one activity (the source acquisition, the footage build) nothing is visible: no "cropping comment cards 4 of 10", no "waiting 30 s before the next X page".
3. **The design file has drifted.** It still holds Discovery, Content Set, Profiles and Legacy Console, all retired on 2026-10-18. It has no screens for Usage, Billing, Tokens or Sign-in, which exist in code. It has no screen for a run that waits for approval, fails, or finishes with a Content Set.
4. **Management is thin.** There is no approval inbox, no "what is running right now" across projects, and no history filter beyond the project list.

## 2. Principles

1. **Always say what is happening, what comes next, and how long it should take.** Every running state names its stage, its current step, and an estimate.
2. **One path:** source, review, content set, Studio, render. Every screen shows where the run is on that path and what the next action is.
3. **Honest states.** Never show placeholders, fake metrics or dead buttons. A disabled action says why. A missing card says "Not captured" and why.
4. **Decisions first.** Anything waiting on a person (approval, a failed run, an expired account) is pulled to the top: the top bar badge, then the inbox, then the run.
5. **Calm density.** Dark, quiet surfaces, with one accent and status colours that mean only status. Few boxes: group by spacing and type, not by borders around everything.
6. **Same component, same meaning.** A status pill, a stage stepper or a step row looks the same wherever it appears.

## 3. People and jobs

| Person | Main jobs | Notes |
|---|---|---|
| Creator (workspace member) | Paste a source link, approve the run, check the Content Set, edit in Studio, render | Most time is spent on the run detail, the review and Studio |
| Workspace owner | The above, plus usage, billing and tokens | |
| Platform admin | The above, plus source accounts and proxies | `/accounts` is admin-only today (`me.platform_admin`) |

## 4. Information architecture

**Routes** (existing ones are kept, so links never break):

| Route | Screen | Status |
|---|---|---|
| `/workflows` | Runs: list, filters, start a run | redesign |
| `/workflows/:id` | Run detail: live progress, approval, results, Open in Studio | redesign (the core of this document) |
| `/inbox` *(new)* | Decisions waiting: approvals, failed runs, expiring accounts | new |
| `/studio`, `/studio/:project/:doc` | Studio documents and editor | keep; restyle the shell only |
| `/accounts`, `/accounts/proxies` | Source accounts and proxies (admin) | restyle |
| `/usage`, `/billing`, `/settings/tokens` | Workspace management | design (none in the `.pen` file today) |
| `/login`, `/login/verify` | Sign-in (Google or GitHub, emailed code) | design |

**Navigation:**
- **Sidebar**, top to bottom:
  - Runs (with a live count of running runs);
  - Inbox (with a count of pending decisions);
  - Studio;
  - a divider;
  - Usage;
  - Billing;
  - Accounts (admin only);
  - Settings.
- **Top bar:** project switcher, global search (⌘K), the **run tray** (a small live indicator, see §7.6), the inbox bell, and the avatar menu (account, language switch §12.1, sign out).
- **Project scope:** runs and Studio documents belong to the selected project. The inbox and the run tray span every project in the workspace, showing each item's project name.

## 5. Visual language

### 5.1 Tokens

The existing `.pen` variables are kept, so code and design agree. New entries are marked with *.

| Token | Value | Use |
|---|---|---|
| `bg` | `#18191B` | App background |
| `well` | `#101113` | Insets: logs, code, video wells |
| `surface` | `#242628` | Panels, table header, dialogs |
| `raised` | `#2A2C2E` | Hover, popovers, selected row |
| `border` | `#47494A` | Hairlines (1 px), used sparingly |
| `ink` | `#F5F3EE` | Primary text |
| `muted` | `#C5C6C7` | Secondary text |
| `faint`* | `#8E9092` | Tertiary text and timestamps (5.49:1 on `bg`) |
| `copper` | `#D49A79` | The single accent: primary actions, focus ring, the current stage |
| `status-running`* | `#22D3EE` (the existing `cyan`) | Running and live |
| `status-waiting`* | `#D7AF5F` (the existing `gold`) | Needs a person: approval, attention |
| `status-done` | `#78C69B` (the existing `status-healthy`) | Succeeded, healthy |
| `status-failed` | `#E8918F` (the existing `status-expired`) | Failed, expired, blocked |
| `status-idle`* | `#6B6E70` | Queued, pending, skipped, cancelled: dots and bars only (3.43:1), with text labels in `muted` |
| `purple` | `#AF87FF` | Studio-only: timeline and scene accents |

**Colour rules:**
- Status colours appear only on status pills, stage dots, step icons and progress fills, never on decoration.
- `copper` marks the one action or element that matters most on a screen.

### 5.2 Type

**Family:** Geist Variable (already shipped through `@fontsource-variable/geist`), plus Geist Mono for IDs, durations and logs.

| Role | Size / line height | Weight |
|---|---|---|
| Page title | 24 / 1.25 | 600 |
| Section title | 16 / 1.4 | 600 |
| Body | 14 / 1.5 | 400 |
| Label, table | 13 / 1.4 | 500 |
| Caption, timestamp | 12 / 1.4 | 400, `faint` or `muted` |
| Metric | 28 / 1.1 | 600, tabular numbers |
| Log, mono | 12.5 / 1.55 | 400, Geist Mono |

### 5.3 Space, radius, elevation, motion

- **Spacing scale:** 4, 8, 12, 16, 24, 32, 48. The page gutter is 24 (16 on narrow screens).
- **Radius:**
  - 6 for inputs and buttons;
  - 10 for panels and dialogs;
  - pills fully round.
  - No radius on table rows.
- **Elevation:** surfaces are separated by tone (`bg`, `surface`, `raised`), not shadows. Only dialogs and popovers get one soft shadow.
- **Motion:**
  - 150 ms ease-out for hover and expand;
  - the running pulse on a stage dot is 1.6 s and respects `prefers-reduced-motion`;
  - progress fills animate width only.
- **Icons:** lucide, 16 px in text rows and 20 px in the sidebar, stroke 1.75.

### 5.4 Layout

**App shell:**
- the top bar is 64 px high;
- the sidebar is 232 px wide, collapsible to 64 px;
- the content is 1200 px max for lists and forms; the run detail and Studio use the full width.

**Breakpoints:**
- **1440:** the design reference.
- **1024:** the sidebar collapses.
- **430:** narrow. The sidebar becomes a bottom sheet menu; the run detail stacks the stepper above the log.

## 6. Components

| Component | Variants and states | Notes |
|---|---|---|
| Button | primary (copper), secondary (surface), ghost, danger; default, hover, focus, loading, disabled with a reason tooltip | A label verb plus an object: "Approve and continue" |
| Input, select, textarea | default, focus, error with message, disabled | The URL input shows the detected platform icon inline |
| Status pill | queued, running, waiting, succeeded, failed, cancelled, expired | A dot plus a label; running pulses |
| **Stage stepper** | vertical (run detail) or compact horizontal (list rows, run tray); each stage pending, running, waiting, done, failed, skipped | Each stage shows its label, duration (or elapsed for the current one), and a one-line current step |
| **Step row** | info, progress (n/total bar), wait (countdown), warning, error | One line in the activity log: time, icon, text, optional right-aligned metric |
| Progress bar | determinate, indeterminate, segmented by stage | The segmented bar sits in the list rows |
| Metric tile | value, label, delta | Only real numbers; no tile when there is no data |
| Table row | default, hover, selected, live (row updates in place) | A run row: status, source thumbnail and title, platform, project, stage bar, started, duration |
| Approval card | summary of what was found, plus approve and reject | Shows the evidence the person needs: source post card, media count, comment count |
| Artifact card | Content Set, source report, attribution | A preview and a "what is inside" line |
| Card thumbnail | post, comment, profile, embed | A real crop; when missing, "Not captured" with the reason |
| Dialog, sheet, popover, toast | | Toasts: run finished, approval needed, failure (each with an action) |
| Empty state | per screen | One sentence and one action; no illustration |
| Skeleton | list, detail, artifact | Never a spinner on a full page |

## 7. Run progress model (the core)

### 7.1 Stage plan

Every run shows its **whole plan from the start**. Stages that will not run show as skipped, with the reason.

| Stage id | Label (UI) | Runs when |
|---|---|---|
| `source` | Fetch the source | always |
| `approval` | Your review | `produce_video` |
| `attribution` | Find the original | the attribution flag is on |
| `footage` | Collect footage | assembly and footage are on |
| `assembly` | Build the content set | assembly is on |

Stage states: `pending`, `running`, `waiting` (needs a person), `done`, `failed`, `skipped`, `cancelled`.

### 7.2 Steps inside a stage

Each stage reports **steps**. A step is a short sentence, optionally with a count (`n of total`), a wait (`next in 30 s`), or a result (`10 of 19 replies carded`).

| Stage | Steps |
|---|---|
| Fetch the source | Read the link · Fetch the post (FxEmbed / page) · Download media (n of total) · Capture the post card · Capture comment cards (n of total) · Wait before the next page (countdown) · Capture embed cards (n of total) · Capture the profile · Save the report |
| Your review | Waiting for you (since …) · Approved by … / Rejected by … |
| Find the original | Read on-screen text · Ask the vision model · Search candidates (n found) · Compare frames · Verdict |
| Collect footage | Plan searches (n queries) · Search platforms (n of total) · Screen clips (n of total) · Creator listing and profile page · Keep n clips |
| Build the content set | Read subtitles (OCR) · Judge comments (n kept of m) · Find people and organisations · Save the content set |

### 7.3 Timing and estimates

- **Elapsed time:** each stage shows the elapsed time while running and the duration when done.
- **The run's estimate:** the run header shows "about N min left". It is the sum of the median duration of the remaining stages from the workspace's last 20 successful runs for the same platform, with a fallback to fixed defaults: source 2 min, attribution 1 min, footage 4 min, assembly 1 min.
- **No precision before there is data:** below 5 recorded runs the estimate reads "a few minutes".
- **A wait is time, not a hang:** a deliberate wait (the 30 s X page gap, an account cooldown) shows as a countdown step.

### 7.4 Activity log

- **What it is:** a chronological, append-only list of step rows under the stepper. Rows of finished stages collapse into their stage after the stage finishes.
- **Layout:** monospace timestamps on the left, plain sentences on the right. Warnings (`problems`, skipped embeds) are amber; errors are red, with the reason and a fix.
- **Copy rules:**
  - say what happened in plain words;
  - put numbers in;
  - never show URLs with query strings, cookies, tokens or raw exception text (the same rule as the backend log sanitizer).

### 7.5 Failure, cancel, retry

- **A failed stage** shows the reason in one sentence, what it means, and what to do. Examples:
  - "X showed a login wall; cards were skipped. The run continues without them."
  - "Assembly could not read the main video. Retry the run."
- **Cancel** is always available while running. It asks for confirmation and states what is kept (the source report).
- **Retry** appears on a failed run. Until per-stage retry exists, it starts a new run with the same link.

### 7.6 Live surfaces

- **Run detail (`/workflows/:id`):**
  - header: source title, platform, project, status pill, estimate, cancel;
  - left: the stage stepper;
  - right: the activity log;
  - below, when done: the results.
- **Runs list:** each running row has a segmented stage bar and the current step text, updating in place.
- **Run tray (top bar):**
  - collapsed, it shows "2 running · 1 waiting";
  - opened, it is a popover listing every active run in the workspace, each with its compact stepper and current step.
- **Notifications:**
  - toasts for approval needed, run done and run failed;
  - the browser tab title shows "(1) Thoth" while a decision waits;
  - optional desktop notification after the person opts in.
- **Accessibility:** step updates go to an `aria-live="polite"` region at no more than one announcement per stage change, never per countdown tick.

### 7.7 Backend contract this needs

This is for the implementation spec, not the design file.

1. **The stage plan in `WorkflowSummary.stages`.**
   - The workflow builds the list at start from the intent and flags, and updates each stage's `status`, `started_at`, `finished_at` and `current_step`.
   - This replaces the single hard-coded `source` stage.
   - It is a workflow-code change, so it goes behind a `workflow.patched` gate like `produce-video-chain`.
2. **Steps from inside activities.**
   - Activities call `activity.heartbeat({"stage", "step", "done", "total", "wait_until"})` at each step.
   - The gateway reads the latest one through `handle.describe()`, from `raw_description.pending_activities[].heartbeat_details`, and merges it into the snapshot as the running stage's `current_step`.
   - No workflow-history writes happen per step, and steps are lost harmlessly on retry.
   - `workflow.set_current_details()` mirrors the same sentence into the Temporal UI for operators.
3. **The step log.**
   - Steps the gateway sees are appended to a `workflow_steps` table (run, stage, sequence, time, kind, step code, n, total, wait_until), so the log survives a page reload and the run's end.
   - Steps are stored as codes and numbers, never prose. The UI renders them in the chosen language (§12.1).
   - The SSE stream already reconnects every second (`streamWorkflow`) and only needs to include new step rows after `Last-Event-ID`.
4. **Estimates:** median stage durations per workspace and platform, from the stored stage timings.
5. **The inbox:** one query over runs in `awaiting_approval` or `failed` (unacknowledged) and accounts expiring within 3 days.

## 8. Screens

**8.1 Runs (`/workflows`).**
- **Header:** "Runs", the project name, and a primary button "New run".
- **Filter bar:** status (all, running, waiting, done, failed), platform, and a search over titles and links.
- **Table:** live rows as in §6. A click opens the run detail.
- **Empty state:** "Paste a TikTok, X, Instagram or YouTube link to start." with an inline URL field.
- **Metrics:** shown only when real. Runs this week, median run time, success rate, and Content Sets made, all from `usage_events` and `workflow_runs`.

**8.2 New run (dialog).**
- **Step 1, the link:**
  - the platform is detected live (an icon and a name);
  - a link from an unsupported host is refused inline with the list of supported platforms.
- **Step 2, options:**
  - the style preset;
  - "Review before production work" (on by default; this is the approval);
  - output language.
- **Confirm:** a "Start run" button. A cost hint ("about 6–10 min; uses about 15 model calls") appears once metering prices exist; until then it is hidden (§12.4).
- **After Start run:** the run detail opens with the notification offer (§12.3) under the header, the first time only.

**8.3 Run detail: running.**
- Implements §7.6.
- The source post card appears at the top of the log as soon as it is captured, so the person sees the post early.

**8.4 Run detail: waiting for you.**
- The approval card leads the page and holds the source post card, the video thumbnail(s), the counts of comments, cards and media, and the creator.
- **Actions:** "Approve and continue" (copper) and "Stop here" (ghost). The second explains that the source report is kept.

**8.5 Run detail: failed.**
- **Header:** red status, then the failed stage in the stepper with its reason sentence, the log scrolled to the error, and "Retry run".
- **What is kept:** listed under the header, for example the source report.

**8.6 Run detail: done.**
- **Results grid:**
  - the main (video, title, owner, attribution verdict "Original" or "Repost of @…");
  - the cards (post, profile, profile page, comments with the count of page and embed cards);
  - footage clips;
  - figures;
  - kept comments.
- **Primary action:** "Open in Studio", which imports and opens the draft. Secondary: download the Content Set JSON.

**8.7 Inbox (`/inbox`).**
- Three groups: Approvals, Failed runs, Accounts.
- Each item: what, project, since when, and one action.
- Empty: "Nothing needs you."

**8.8 Studio.** The editor is out of scope. Only the shell (top bar, sidebar) and the import overlay ("Bringing the content set into Studio: n of m media") follow this document.

**8.9 Accounts and proxies (admin).**
- Restyled to the new components.
- Each account row shows its platform, health, cooldown countdown, proxy, leases today against the budget, and the last outcome.

**8.10 Usage, Billing, Tokens.**
- **Usage:** metered counts by kind and by day, as a bar chart, plus a table.
- **Billing:**
  - shows the plan and its limits;
  - "go-live deferred" is stated honestly while billing is off.
- **Tokens:** a list, plus a create dialog showing the token once.

**8.11 Sign-in.** Google, GitHub, then the emailed code. A centred single column with the Thoth wordmark (the existing feather mark).

## 9. Management in the dashboard

- **Projects:**
  - the switcher shows recent projects and "All projects" for the inbox and the run tray;
  - creating a project is inline in the switcher.
- **History:**
  - runs are kept and listed per project;
  - a run whose Temporal history expired still shows its stored summary, labelled "Details expired";
  - filters persist in the URL.
- **Bulk actions:** select runs to archive or retry. Archive hides runs from the list; nothing is deleted from the UI.
- **Roles:** admin-only items are hidden, not disabled, for members.
- **Consistency:** every destructive action (cancel a run, remove an account, revoke a token) uses the same confirm dialog pattern, with the object named.

## 10. Accessibility and quality bar

- **Contrast (measured, WCAG 2.x):**

  | Token | On `bg` | On `surface` |
  |---|---|---|
  | `ink` | 15.86:1 | 13.69:1 |
  | `muted` | 10.28:1 | 8.88:1 |
  | `faint` | 5.49:1 | 4.74:1 (AA for body text on both) |
  | `copper` | 7.29:1 | |

  All four status colours are 7.4:1 or more on `bg`. `status-idle` is 3.43:1: dots, bars and icons only, never text.
- **Focus and keyboard:**
  - a visible 2 px copper focus ring on every focusable element;
  - full keyboard paths: ⌘K, `g r` runs, `g i` inbox, `a` approve on a waiting run.
- **Live regions:** as in §7.6.
- **Motion:** reduced motion is honoured.
- **States:** every screen has its loading (skeleton), empty, error and narrow variants designed.

## 11. Design file workflow

- **Backup:** the current file is backed up byte-for-byte at `D:/thoth-tmp/bu/design/thoth-dashboard-backup-2026-10-24.pen` (sha256 `eca501d5…`).
- **New file:** the redesign is made in a **new** file, `design/thoth-dashboard-v2.pen`. The old file stays untouched as the reference.
- **Order:** tokens, then components, then screens, then states, then narrow variants. See `docs/design/pen-dev-prompts.md`.
- **Exports:** PNGs of each finished screen go to `design/exports/v2/`.

## 12. Language, theme, notifications (operator rulings 2026-10-25)

### 12.1 Two languages with a switch

**The switch:**
- The UI ships in English and Indonesian.
- Each user picks the language in the avatar menu ("Language: English / Bahasa Indonesia") and in Settings. The choice is saved per user, with the browser language as the first default.

**Copy:**
- Every string is a key in one message catalogue per language. No sentence is assembled from fragments, so word order can differ between languages.
- Step and log sentences come from the backend as a step code plus numbers (for example `capture_comment_cards`, n=4, total=10), and the UI renders them in the chosen language. Logs are never stored as pre-translated prose.

**Formats:** dates, times and numbers follow the language (`id-ID`: "25 Okt 2026, 14.03", "1.533"; `en`: "Oct 25, 2026, 2:03 PM", "1,533"). Durations stay compact in both ("2m 24s" / "2 mnt 24 dtk").

**Layout:** Indonesian runs about 20 to 30% longer than English. Buttons, pills and stepper lines must wrap or truncate with a tooltip, never clip. Every screen is checked in both languages.

### 12.2 Theme

- **For now:** dark only.
- **Later:** a light theme.
- **Prepare for it now:** every colour in code and in the `.pen` file is a semantic token (§5.1), never a raw hex value. Status colours are checked for contrast on both a dark and a light surface when the light theme is designed.

### 12.3 Desktop notifications

- **When to ask:** the browser permission prompt is never shown on a first visit. After a person starts a run, an in-page offer appears under the run header: "This run takes about 6–10 minutes. Notify me when it needs me or finishes?" with "Notify me" and "Not now". Only "Notify me" triggers the browser prompt.
- **When "Not now" is chosen:** the offer stays away for 7 days.
- **Settings:** a "Desktop notifications" switch shows the current permission, and when the browser has blocked it, how to unblock it.
- **What triggers one:** approval needed, run done, run failed, each once per run. Never per step.

### 12.4 Cost hint

The New run dialog shows a cost hint only after metering prices are set. Prices are deferred until every feature is done.
