# pen.dev prompts: Thoth dashboard v2

Use these prompts in order, one at a time, in pen.dev. Each one stands on its own, because the pen.dev assistant cannot read this repository. The source of truth is `docs/DESIGN.md`.

**Before you start:**
- A byte-identical backup of the current design exists at `D:/thoth-tmp/bu/design/thoth-dashboard-backup-2026-10-24.pen` (sha256 `eca501d5…`).
- Work **only** in the new file `design/thoth-dashboard-v2.pen`. Never edit `design/thoth-dashboard.pen`.
- After each prompt, check the result against that step's checklist before you send the next one.

---

## Prompt 0: new file and ground rules

```text
Create a NEW document saved as design/thoth-dashboard-v2.pen. Do not open, edit, copy over, or
delete anything in design/thoth-dashboard.pen; it is the read-only reference.

This file will hold the redesign of "Thoth", a dark web dashboard that turns a social media post
(TikTok, X, Instagram, YouTube) into a content set and then a short video. Desktop reference width
1440, narrow width 430. Layout: top bar 64 high, left sidebar 232 wide (collapsible to 64), content
gutter 24.

Ground rules for every later step:
- Use only the variables we define in the next step, never raw hex values in nodes (a light
  theme comes later and must be a variable swap, not a redraw).
- Font: Geist for UI, Geist Mono for timestamps, IDs, durations and logs.
- Icons: lucide-style icon nodes, 16 px in rows, 20 px in the sidebar.
- No drop shadows except dialogs/popovers; separate surfaces by tone, not borders.
- No placeholder numbers or lorem ipsum: use the realistic sample content I give you.
- Build reusable components first, screens from instances.
Create one empty frame named "README" at the top-left with these rules as text, then stop.
```

**Check:** a new file exists, the old file is untouched, and a README frame is present.

## Prompt 1: design tokens

```text
In thoth-dashboard-v2.pen define these variables (dark theme only):
Colors - bg #18191B, well #101113, surface #242628, raised #2A2C2E, border #47494A,
ink #F5F3EE, muted #C5C6C7, faint #8E9092, copper #D49A79 (the single accent),
status-running #22D3EE, status-waiting #D7AF5F, status-done #78C69B, status-failed #E8918F,
status-idle #6B6E70 (dots/bars only, never text), purple #AF87FF (Studio only).
Numbers - space-4 4, space-8 8, space-12 12, space-16 16, space-24 24, space-32 32, space-48 48,
radius-control 6, radius-panel 10.
Strings - font-ui "Geist", font-mono "Geist Mono".

Then make a "Tokens" frame (fill bg) that shows: every color as a swatch with its name and hex,
the type scale as live text samples - Page title 24/600, Section title 16/600, Body 14/400,
Label 13/500, Caption 12/400 (faint), Metric 28/600, Log 12.5 mono - and the spacing scale as bars.
Screenshot it when done.
```

**Check:** every swatch uses a variable, the type samples render in Geist, and nothing is clipped.

## Prompt 2: core components

```text
Create a "Components" frame and build these as reusable components using only the variables:

1. Button: variants primary (fill copper, text bg), secondary (fill surface, text ink), ghost
   (text muted), danger (text status-failed); radius-control; height 36; label 14/500. Also a
   "loading" state (spinner icon + label) and "disabled" (50% opacity) with a small tooltip
   "Available after approval".
2. Input: label 13/500 muted above, field fill well, 1px border, radius-control, height 40,
   placeholder faint. Variant "url" shows a platform icon + platform name chip at the left inside
   the field ("TikTok"). States: focus (2px copper ring), error (status-failed message below).
3. Status pill: a 8px dot + label 12/500 on fill raised, fully rounded. Variants: Queued (dot
   status-idle), Running (dot status-running), Waiting for you (dot status-waiting), Done (dot
   status-done), Failed (dot status-failed), Cancelled (dot status-idle).
4. Metric tile: value 28/600 ink, label 13 muted, optional delta 12 status-done. No border.
5. Table row (run row): status pill | 40x40 thumbnail + title (14 ink) + link domain (12 faint) |
   platform icon | project 13 muted | compact stage bar (component 7) | started 13 muted |
   duration 13 mono muted. Hover fill raised.
6. Toast: fill raised, icon + title 14/600 + one line 13 muted + one action button (ghost).
7. Stage bar (compact): 5 equal segments with 2px gaps, height 6, radius 3; segment fills:
   done = status-done, current = status-running, waiting = status-waiting, failed =
   status-failed, pending/skipped = status-idle at 40% opacity.
8. Empty state: one sentence 14 muted + one primary button, centered, no illustration.
Screenshot the Components frame.
```

**Check:** the components are reusable, the variants are distinct, and the focus ring is visible.

## Prompt 3: the run progress components (most important)

```text
Add to the Components frame:

A) Stage stepper (vertical), a reusable component made of 5 "Stage item" instances in a column.
   Stage item = left rail: a 12px status dot on a 2px vertical line (line color border; the line
   segment above a done stage is status-done); right: label 14/600 ink, a duration on the right
   in mono 12 muted ("1m 52s"), and under the label one "current step" line 13 muted.
   States per item: pending (dot status-idle hollow, label muted), running (dot status-running
   with a soft pulse ring, label ink, duration shows elapsed "0:48 elapsed"), waiting (dot
   status-waiting, current step "Waiting for you · since 14:02"), done (dot status-done check),
   failed (dot status-failed x, current step in status-failed), skipped (dot status-idle dashed,
   label muted, current step "Skipped - assembly is off").
   Stages and labels, in order: Fetch the source / Your review / Find the original /
   Collect footage / Build the content set.

B) Step row (activity log line): mono timestamp 12 faint ("14:03:21") | 16px icon | sentence
   13 ink | optional right side: a mini progress "4 / 10" with a 60px bar, or a countdown chip
   "next in 24s" (status-waiting), or a result chip "10 of 19 carded" (status-done).
   Variants: info (icon circle-dot muted), progress (loader status-running), wait (hourglass
   status-waiting), done (check status-done), warning (triangle status-waiting, text muted),
   error (x status-failed, text ink, plus a second line "What to do: Retry the run" 12 muted).

C) Run header: source thumbnail 56x56, title 20/600 ("Air quality in Central Kalimantan keeps
   getting worse"), meta line 13 muted ("X · @namelesid · Project: Haze watch"), status pill,
   "about 4 min left" 13 muted, and a ghost "Cancel run" button on the right.

D) Approval card: title "Review the source before production work" 16/600; a 2-column body:
   left a post card image placeholder area (a real screenshot will go here - use a frame with
   fill well and label "Post card"), right a facts list (Media: 2 videos · Comments: 19 ·
   Comment cards: 10 · Creator: @namelesid); footer: primary "Approve and continue", ghost
   "Stop here" with helper text "The source report is kept."
Screenshot each of A-D.
```

**Check:** every stepper state is legible without colour (an icon plus the text), the dots align on the rail, and the long step text wraps.

## Prompt 4: app shell

```text
Create the reusable "App shell" from instances: Top bar (64h, fill bg, bottom hairline border):
left the Thoth wordmark (text "Thoth" 16/600 with a small feather icon) and a project switcher
button ("Haze watch" + chevron); center a search field "Search runs, documents… ⌘K"; right a
"Run tray" button (status-running dot + "2 running · 1 waiting"), a bell icon with a status-waiting
badge "1", and a 32px avatar. Also an "Avatar menu - open" variant: account name and email, "Language"
row with a two-option segmented switch "English | Bahasa Indonesia", "Settings", "Sign out".
Sidebar (232w, fill bg, right hairline): items with 20px icons - Runs (badge "2"), Inbox (badge
"1"), Studio, divider, Usage, Billing, Accounts (admin), Settings. Active item: fill raised, text
ink, 2px copper left marker. Collapsed variant 64w shows icons only.
Screenshot.
```

## Prompt 5: Runs list (`/workflows`)

```text
Screen "Runs - list" 1440x900 using the App shell. Content: header "Runs" 24/600 with subtitle
"Project: Haze watch" and primary button "New run". Metrics row (only these, no others): Runs this
week 14 · Median run time 7m 40s · Success rate 92% · Content sets 11. Filter bar: segmented
status (All, Running, Waiting, Done, Failed), platform select, search input. Table with 8 run rows
using the Table row component - mix: 2 running (stage bars mid-way, current step under the title
"Collect footage · Screening clips 6 of 12"), 1 waiting (status-waiting, "Your review"), 4 done,
1 failed ("Build the content set failed").
Then make a copy "Runs - empty" with the Empty state: "Paste a TikTok, X, Instagram or YouTube
link to start." plus the url Input inline and "Start run".
Screenshot both.
```

## Prompt 6: New run dialog

```text
Screen "New run - dialog" 1440x900: dim the Runs list (bg at 70%) and center a dialog 560 wide,
fill surface, radius-panel. Title "New run". Step 1: url Input filled with
"https://x.com/namelesid/status/2113895024895070537" and its platform chip "X". Step 2 options:
Style preset select ("News vertical"), a switch "Review before production work" (on) with helper
"You approve the source before footage and the content set are built.", Output language select
("Indonesian"). Footer: ghost "Cancel", primary "Start run". Also a variant "unsupported link"
where the input shows error "Unsupported link. Use TikTok, X, Instagram or YouTube."
Screenshot both.
```

## Prompt 7: Run detail, running

```text
Screen "Run - running" 1440x1000 with the App shell. Top: Run header (component C) with status
pill Running and "about 4 min left". Body in two columns (gap 32): left 360w the Stage stepper
with: Fetch the source done 2m 24s ("10 of 19 replies carded"), Your review done 0m 40s
("Approved by you"), Find the original done 0m 52s ("Original - no repost signals"),
Collect footage RUNNING 1:12 elapsed ("Screening clips 6 of 12"), Build the content set pending.
Right column: section title "Activity" and a log in fill well, radius-panel, 16 padding, with ~14
Step rows in order, e.g.
14:01:02 info "Read the link - X post by @namelesid"
14:01:05 done "Fetched the post - 2 videos, 19 replies"
14:01:31 done "Downloaded media" 2/2
14:01:48 done "Captured the post card"
14:01:52 done "Captured comment cards from the page" 4/4
14:01:53 warning "2 replies were under X's 'See all the replies' gate - using embeds"
14:02:23 wait "Waiting before the next X page" next in 30s
14:02:58 done "Captured embed cards" 6/6
14:03:26 done "Saved the source report"
14:03:26 info "Waiting for your review"
14:04:06 done "Approved by you"
14:04:58 done "Original found - no repost signals"
14:05:10 progress "Screening footage clips" 6/12
The newest row is at the bottom with a subtle running highlight. Above the log, the post card
thumbnail appears as a small preview ("Post card captured").
Under the Run header add a slim inline offer bar (fill raised, no shadow): bell icon, text "This
run takes about 6-10 minutes. Notify me when it needs me or finishes?", primary small "Notify me",
ghost small "Not now". Make a copy "Run - running (no offer)" without it.
Screenshot.
```

**Check:** you can tell what is happening, what comes next and how long is left within 3 seconds of looking.

## Prompt 8: Run detail, waiting, failed and done

```text
Make three copies of "Run - running":
1) "Run - waiting for you": status pill Waiting for you, stepper with Your review in waiting state;
   the Approval card (component D) spans the top of the body, above the stepper/log; the log ends
   at "Waiting for your review".
2) "Run - failed": status pill Failed; Build the content set failed with step text "Could not
   read the main video"; a red-tinted error Step row at the end with "What to do: Retry the run";
   header gets a primary "Retry run" and a line "Kept: source report, footage (8 clips)".
3) "Run - done": status pill Done, all stages done with durations, total "8m 12s". Replace the
   log column with a Results area: Main (video thumbnail, title, @owner, chip "Original"),
   Cards row (Post, Profile, Profile page, "Comments 10 - 4 from the page, 6 embeds"), Footage
   strip (8 thumbnails with platform icons), Figures chips, Kept comments (5 lines with likes).
   Primary "Open in Studio", secondary "Download content set". The log collapses into a
   "Show activity (42 steps)" disclosure.
Screenshot all three.
```

## Prompt 9: run tray, inbox and notifications

```text
1) "Run tray - open": the App shell with the Run tray popover open under its button (360w,
   fill raised, radius-panel, one shadow): two active runs, each with title, project, compact
   stage bar and current step, and one waiting run with an "Approve" button; footer link
   "All runs".
2) Screen "Inbox" (/inbox) 1440x900: title "Inbox", three groups - Approvals (1 item: run title,
   project, "waiting 12 min", primary "Review"), Failed runs (1 item, "Retry"), Accounts (1 item:
   "TikTok account operator-1 cooldown ends in 2h", "Open accounts"). Plus an empty variant
   "Nothing needs you."
3) Three Toast instances stacked bottom-right on a copy of Runs: "Approval needed", "Run done -
   Open in Studio", "Run failed - Retry".
Screenshot.
```

## Prompt 10: management screens

```text
Using the App shell and existing components, design:
1) "Usage": bar chart of metered items per day for 14 days (workflows completed, model calls,
   media stored), a totals row, and a table by kind. No prices (they are not set yet).
2) "Billing": current plan card, limits list, and an honest banner "Billing goes live after the
   remaining features ship" (status-waiting).
3) "Settings": Language switch (English | Bahasa Indonesia), Desktop notifications switch with
   its current state ("Allowed" / "Blocked by your browser - how to unblock"), then "Tokens":
   list of developer tokens (name, created, last used, revoke), "Create token" dialog,
   and the one-time "Copy your token now" state.
4) "Accounts (admin)": table of source accounts - platform icon, label, health pill, cooldown
   countdown, proxy (masked), leases today "3 / 40", last outcome; a "Proxies" tab.
5) "Sign in": centered column, Thoth wordmark, "Continue with Google", "Continue with GitHub",
   then a "Check your email" code step.
Screenshot each.
```

## Prompt 11: narrow (430) variants

```text
Create 430-wide versions of: Runs - list (rows become stacked cards: title, status pill, stage
bar, current step), Run - running (Run header, stepper first, then Activity log), Run - waiting
for you (Approval card first, sticky bottom bar with "Approve and continue"), and Inbox. Sidebar
becomes a bottom-sheet menu opened from a top-left menu icon. Keep 16 gutter.
Screenshot.
```

## Prompt 12: states and QA pass

```text
For Runs - list and Run - running add: a loading skeleton variant (no spinners) and an error
variant ("Could not load runs. Retry"). Then make Indonesian copies of "Run - running" and
"Run - waiting for you" (the UI has an English/Indonesian switch); translate every visible string,
e.g. stages "Ambil sumber / Tinjauan Anda / Cari yang asli / Kumpulkan footage / Susun content
set", "sekitar 4 mnt lagi", "Setujui dan lanjutkan", "Berhenti di sini", "Aktivitas", dates like
"25 Okt 2026, 14.03" and numbers like "1.533". Fix any button, pill or stepper line that clips -
wrap or truncate with a tooltip; Indonesian runs 20-30% longer than English. Then run a QA pass over every screen in this file:
no clipped or overflowing content, no raw hex outside variables, text contrast - never
status-idle for text, focus rings shown on one example per screen, every disabled action has a
reason. List any fixes you made. Finally export every finished screen as PNG to
design/exports/v2/.
```

---

## Review fixes, round 1 (2026-10-25)

These come from reviewing the first 34 exports. Run them in order in `design/thoth-dashboard-v2.pen` only. They fix what is wrong and add what is missing; they do not redo the screens that are right. Studio has its own prompts, from Prompt 20, after its research.

## Prompt 13: resting states and a States board

```text
Work only in design/thoth-dashboard-v2.pen. In every screen frame, put controls back to their
resting state: the top-bar search field and the narrow menu button must NOT show the copper focus
ring, and no other control may show focus, hover or pressed. Then create one frame "States" next to
"Components" that shows, for Button, Input, url Input, Status pill, Table row and the sidebar item:
rest, hover, focus (2px copper ring), pressed and disabled-with-reason - each labelled. Screenshot
the States board and two fixed screens (Runs - list, Run - running).
```

## Prompt 14: honest run rows

```text
Work only in design/thoth-dashboard-v2.pen. In "Runs - list" (and its loading/error/toast/tray
copies) make every row's stage bar match its status - 5 segments for Fetch the source / Your review /
Find the original / Collect footage / Build the content set:
- Running at Collect footage: 3 done (status-done), 1 running (status-running), 1 idle.
- Running at Find the original (use this for the second running row): 2 done, 1 running, 2 idle.
- Waiting for you: 1 done, 1 waiting (status-waiting), 3 idle.
- Done: all 5 status-done.
- Failed at Build the content set: 4 done, 1 status-failed.
Remove the "Project" column (this list is already scoped to one project) and let Post take the
width; add a copy "Runs - all projects" where the Project column is present with mixed projects
(Haze watch, Banjir Jakarta, Pemilu 2029). Replace the checkerboard thumbnail with the
missing-thumbnail tile: fill well, the platform icon centered in muted. Screenshot both.
```

## Prompt 15: real card crops

```text
Work only in design/thoth-dashboard-v2.pen. Cards are real screenshots of the platform - the
product's core - so placeholders with icons are wrong. Build four reusable "Card crop" components
that LOOK like real platform crops (layout only, no logos drawn by hand; use icon nodes):
1. X post card (dark): avatar circle, name "Nameless" + verified icon, handle "@namelesid",
   text "Perhari ini, kondisi udara di KALTENG semakin meburuk...", a 2-tile media row with orange
   haze photos (stock images), the "7:27 AM · Oct 24, 2026 · 705K Views" line and an action row.
2. Comment card (dark): avatar, "konoh @konoholicx", "Tadi katanya ada yang keluarganya ngabarin
   juga masih pekat banget di sana huhuhu ya Allah", "1 like", plus a small "embed" badge variant.
3. Profile card: avatar, "Nameless", "@namelesid", bio "Pundit nigeria-backup", "1,864 Following
   8,516 Followers".
4. Profile page: the profile card above a 3-column grid of 6 post thumbnails.
Use them in: "Run - waiting for you" (replace the empty "Post card" box with the X post card) and
"Run - done" (replace the four icon boxes in Cards with small crops: Post, Profile, Profile page,
and a stack of 3 comment cards labelled "Comments 10 - 4 from the page, 6 embeds"). Add one slot in
a copy "Run - done (missing card)" showing a well tile "Not captured - X showed a login wall".
Screenshot the components and both screens.
```

## Prompt 16: figures are people, not statistics

```text
Work only in design/thoth-dashboard-v2.pen. In "Run - done" (and its Indonesian copy if present),
"Figures" means the people, organisations or communities the post is about - never numbers.
Replace the chips (212 hotspots, PM2.5 ...) with a compact list of 3 rows, each: a 16px type icon
(user for person, building for organisation, users for community), name 14/500 ink, type + role
13 muted:
- Sabran · Person · Governor of Central Kalimantan
- BMKG · Organisation · Indonesian weather and climate agency
- Warga Palangka Raya · Community · residents affected by the haze
In "Kept comments", add a small card icon next to comments that have a comment card.
Screenshot.
```

## Prompt 17: missing overlays and menus

```text
Work only in design/thoth-dashboard-v2.pen. Using the App shell, add these screens over the Runs
list (dim the page beneath to 70% where it is a modal):
1. "Avatar menu - open": popover under the avatar with name "Alya Putri", email
   "alya@hazewatch.id", a "Language" row with the segmented switch "English | Bahasa Indonesia",
   "Settings", "Sign out".
2. "Command palette - open" (Cmd+K): centered 640w panel, input "Search runs, documents,
   settings...", groups Runs (3 results with status pills), Studio documents (2), Actions
   ("New run", "Open inbox", "Switch language"), each row with its shortcut on the right.
3. "Project switcher - open": popover listing projects with their running counts, a search field,
   and "New project" at the bottom; plus "New project - dialog" with name input and "Create".
Screenshot each.
```

## Prompt 18: missing run states and bulk actions

```text
Work only in design/thoth-dashboard-v2.pen. Add:
1. "Run - cancelled": status pill Cancelled (status-idle dot, muted text), stepper stopped at
   Collect footage with step text "Cancelled by you at 14:06", header line "Kept: source report",
   primary "Start again" and the log ending with the cancel row.
2. "Run - details expired": an older done run whose live details are gone - stepper shows stage
   durations only, a quiet notice "Activity details have expired. Results are kept.",
   results still shown.
3. "Runs - selection": the Runs list with 3 rows checked (a checkbox column appears on hover and
   when anything is selected) and a bottom action bar "3 selected · Retry · Archive · Clear".
Screenshot each.
```

## Prompt 19: narrow fixes and re-export

```text
Work only in design/thoth-dashboard-v2.pen. In every 430-wide screen, the run tray button shows
icons, not abbreviations: a status-running dot with "2" and a status-waiting dot with "1"
(tooltip "2 running · 1 waiting"). Check "Run - waiting for you" narrow has the sticky bottom
bar "Approve and continue" / "Stop here". Then re-export ONLY the screens changed in Prompts 13-19
as PNG to design/exports/v2/ (overwrite same names; new screens get new names) and list them.
```

---

## After pen.dev

When the screens are approved, the implementation gets its own spec, with backend work first, from `docs/DESIGN.md` §7.7:
1. the stage plan in the summary;
2. activity steps through heartbeat details;
3. the step log table;
4. estimates;
5. the inbox query.

The dashboard restyle comes after that.
