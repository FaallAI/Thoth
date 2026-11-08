# Studio Timeline track: an editor that works like common editors

Status: draft for the operator's review, 2026-11-08.
Inputs: `docs/ROADMAP.md` ("Studio Timeline track", added 2026-11-05) and
`docs/research/2026-11-08-studio-timeline-editor-research.md` (e2e audit plus benchmarks).

## 1. Intent

The operator wants the Studio to work like the editing studio of a common application: every
Timeline function works, and a right click offers editing options as common video editors do.
The operator has not explored the Studio fully and asked for a deep e2e audit and research first;
both are in the research report. The benchmarks are Clipchamp, Descript, the Remotion Editor
Starter, DaVinci Resolve, Premiere Pro and CapCut.

What "works like a common editor" means here: the editing grammar people already know (Delete,
S to split, a right-click menu, drag to another track, Ctrl+wheel zoom, close a gap, select many,
copy and paste, undo every step), and a screen whose names and numbers read as plain language.

## 2. Goals, non-goals, anti-goals

**Goals**

- Tier 1 (editor basics), then Tier 2 (comfort), then Tier 3 (pro), in that order (operator,
  2026-11-08).
- A right-click menu in both Timeline mode and Story mode (operator, 2026-11-08).
- Seven of the eight red tests in `e2e/tests-write/timeline-audit.e2e.ts` turn green in Tier 1; the
  eighth (Fit, Crop and Position editable) belongs to Tier 2.

**Non-goals**

- Keyframes and animation of layer properties over time.
- Effects, colour grading, transitions beyond fades.
- Rebinding shortcuts.
- Collaboration features (cursors, comments on the timeline); review stays in Review.

**Anti-goals** (would make this a failure even if it works)

- A menu entry or shortcut that spends money without the existing confirmation. Re-voice,
  narration, Assist and render stay behind their current buttons and confirmations; no menu
  triggers them.
- An edit that bypasses the typed operations (`EditDocumentPatch`) or the evidence rules: cards
  are never redrawn, provenance stays attached, locked clips and tracks stay untouchable.
- A shortcut that fires while the person types in a field (text boxes, the heading, caption text).
- One user action that becomes several undo steps, or several actions that undo as one.

## 3. Constraints

- Every edit is a typed operation saved through the existing autosave and revision flow; one user
  action is one patch (one revision, one undo step), even when it carries several operations
  (ripple delete is `remove_clip` plus the `move_clip` of every later clip on every track).
- New operations (Tier 2 and 3) get defaults on every new field so stored documents and older
  clients still decode (`AGENTS.md`), and are mirrored in `timeline_domain.ts` and
  `domain/timeline_operations.py` with tests on both sides.
- Dashboard strings in English and Indonesian (`id` locale).
- Keyboard shortcuts act only while focus is inside the Studio editing area and not in an input,
  textarea, select or contenteditable.
- E2E rules from `AGENTS.md`: deterministic tests with `screen` locators and `expect`; write tests
  only in the throwaway project with a one-day write token (the operator approves each new token).
- Each tier is its own plan, branch and PR, deployed from the branch image before merge.

## 4. What the operator decided

1. Order: Tier 1 → Tier 2 → Tier 3.
2. Right click exists in Story mode as well as Timeline mode, with the entries in section 5.2.
3. Re-voice is not in any menu (it is paid).
4. Tier 1 as played back on 2026-11-08 ("ya sudah pas").

## 5. Tier 1: editor basics

### 5.1 Timeline mode

**Keyboard** (Clipchamp's grammar, the most common in web editors):

| Key | Action |
|---|---|
| Delete, Backspace | Delete the selected clip (`remove_clip`) |
| Shift+Delete | Ripple delete: delete and pull later clips on every track left |
| S | Split the selected clip at the playhead (`split_clip`) |
| Space | Play / pause |
| Home, End | Playhead to start, to end |
| Left, Right | Playhead one frame (as today on a focused clip, the clip nudges) |
| Ctrl+wheel | Zoom the lanes around the pointer |
| Ctrl+=, Ctrl+-, Ctrl+0 | Zoom in, zoom out, zoom to fit |
| Ctrl+Z, Ctrl+Y (Ctrl+Shift+Z) | Undo, redo, in Story and Timeline. The buttons exist; the keys are not wired (the 2026-11-08 test passed through a text field's own undo) |
| Escape | Close a menu, drop a drag (exists), then clear the selection |
| ? or Ctrl+/ | Open the shortcut list |

**Right-click menu on a clip:** Split at playhead · Delete · Ripple delete · Replace media…
(`replace_clip_asset`, on video-kind clips, cards included: the server swaps media of the same
kind, so a card's image is replaced by an image; today's Replace dialog was a placeholder with a
disabled button, so Tier 1 builds a real picker of ready assets of that kind) · Move to track ▸ (compatible tracks only,
`move_clip.target_track_id`) · Hide / Show (`set_clip_hidden`) · Lock / Unlock
(`set_clip_locked`) · Show in Story (switches to Story mode with that beat open, when the clip
belongs to a beat). Entries that do not apply stay visible and disabled with the reason as a
tooltip (a locked clip, a playhead outside the clip).

**Right-click or hover on a gap** between two clips on one track: "Close this gap" (one patch of
`move_clip` for every later clip on every track).

**Ripple across tracks** (operator, 2026-11-08, like Premiere's sync lock): ripple delete and close
gap move the later clips of **every** track, so narration, captions, overlays and music stay in sync
with the video. The edit is refused, with the reason shown, when a clip on another track lies in the
removed stretch ("Another track has a clip here; trim or delete it first") or when a clip that would
move is locked or sits on a locked track.

**Right-click on a track name:** Select track (the Inspector shows the track) · Move up / Move
down (`reorder_track`) · Hide / Mute / Lock (existing toggles) · Remove empty track
(`remove_empty_track`, disabled while it holds clips).

**Pointer:**

- Drag a clip onto another compatible lane moves it there; an incompatible lane shows a
  not-allowed state and drops nothing.
- A click on an empty part of a lane moves the playhead there and clears the clip selection.
- A click on a track name selects the track for the Inspector.

**Look:**

- Track names in plain language: Main video, B-roll, Overlay, Captions, Narration, Music, Sound
  effects (and their Indonesian strings); the raw id never shows.
- The Inspector shows timing as time (`0:07.5`), with the frame number small beside it; typing a
  time or a frame both work.
- "Ownership" reads as plain language (for example "Made by Thoth" / "Edited by you" / "Locked"),
  same values underneath.
- 1440: the lane area takes more of the height (the preview shrinks before the lanes do).
- 1024: an empty Inspector collapses to a narrow rail until something is selected; every lane is
  reachable (the SFX lane is not cut).
- Clip labels keep the start of the name readable on short clips (ellipsis at the end, full name
  in the tooltip).

### 5.2 Story mode

**Right-click on an item in a beat's "Shown" list:** Move earlier · Move later · Remove from beat
· Replace media… (video clips) · Position ▸ Top / Middle / Lower third · Emphasis ▸ Highlight
/ Arrow (cards only) · Play from here (the preview plays from the item's start) · Show in Timeline (switches to Timeline mode with that clip
selected).

**Right-click on a beat in the beat strip:** Open beat · Add from materials… · Show in Timeline
(playhead at the beat's start). Beats keep their fixed order (Hook, Main, Evidence, Reactions,
Footage, Outro), so there is no "move beat".

**Right-click on a material in the Materials panel:** Add to the open beat · Show where it is used
(plays the preview from its clip; disabled when unused) · Why this material.

Every Story entry calls the same edit helpers the existing buttons use (`story_edits.ts`); no new
server operation.

### 5.3 Shared menu behaviour (both modes)

- One menu component; it opens at the pointer, stays inside the viewport, and closes on Escape,
  a click outside, scroll, or after an action.
- Keyboard: Shift+F10 or the Menu key opens it on the focused item; arrows move, Enter acts.
- Touch: a long press opens it.
- Each entry shows its shortcut where one exists.
- Accessible names: the menu is `role="menu"` with `menuitem` entries, so tests and screen
  readers find it by name.

### 5.4 Tests (Tier 1)

- Unit tests for every new handler and helper (dashboard), and for ripple delete and close gap as
  operation batches.
- Seven red tests in `timeline-audit.e2e.ts` pass (all but Fit / Crop / Position); new write tests cover the Story menus,
  ripple delete, close gap, the shortcut list and the 1024 layout.
- Fix the fragile `studio-write` test ("a video longer than the canvas…") so it uses the video it
  uploads itself.
- A read-only e2e look at 1440, 1024 and 430 after deploy, judged from screenshots.

## 6. Tier 2: comfort

- **Multi-select:** Shift or Ctrl click adds a clip; a marquee drag on empty lane space selects
  every clip it touches; Ctrl+A selects all; Escape clears. Delete, ripple delete, move (drag) and
  hide / lock act on the whole selection as one patch.
- **Copy, paste, duplicate clips:** Ctrl+C / Ctrl+V / Ctrl+D and menu entries. Paste puts the
  clips at the playhead on their own tracks. Needs a new operation (a `duplicate_clip` that copies
  a clip with a new id, its asset reference and provenance untouched).
  - Clips and media never go through the system clipboard (operator, 2026-11-08). Copied clips
    live in the open page only, so they paste within the open draft.
  - Media from outside Thoth is added only by uploading it (the existing Upload). A pasted image
    or file is not turned into an asset.
- **Text through the system clipboard, to a place the person chooses** (operator, 2026-11-08):
  - Copy: "Copy text" on a text clip, caption cue or heading puts its plain text on the system
    clipboard (`copy` event or `navigator.clipboard.writeText`).
  - Paste into a field (heading, body, caption text, overlay text) works as normal browser paste.
  - Paste onto the timeline (Ctrl+V with plain text and no copied clips, or the menu's "Paste
    text…") opens a small chooser naming where the text goes:
    - a new text clip on the Overlay track at the playhead (`add_text_clip`);
    - replace the text of the selected text clip (`replace_text`);
    - a new caption cue at the playhead (`add_caption_clip`), or replace the selected cue's text
      (`set_caption_cue_text`).
  - Entries that do not apply are disabled. Nothing is placed until the person picks one.
    Escape cancels.
  - Reading for the menu entry uses `navigator.clipboard.readText()`. Chromium asks once;
    Firefox and Safari show their own Paste button. Both need a secure context (https, or
    localhost on stage1). When reading is refused, the entry says to use Ctrl+V.
  - Pasted text is plain text only (no HTML), trimmed, and held to the same length limits as
    typed text.
- **Close all gaps** on a track (track menu) and in the whole timeline.
- **Inspector:** Fit, Crop and Position become editable on video and image clips (existing
  `set_clip_position` / `set_clip_motion`; Crop may need a field on the operation); fade in and
  fade out for visual and audio clips (new fields with defaults, and the renderer honours them).
- **Assets column:** search and a type filter (video, image, audio); drag an asset onto a lane
  places it at the drop point.
- **Playback keys:** J / K / L (back, pause, forward), Shift+Left / Shift+Right for one second.

## 7. Tier 3: pro

- **Filmstrip thumbnails and waveforms** on clips, with a draggable volume line on audio
  (backend: frame strips and audio peaks per asset, stored beside the asset; the roadmap already
  lists this).
- **Roll and slip edits:** drag the cut between two touching clips (roll); drag the content inside
  a clip (slip). May need a `slip` field on trims.
- **Speed:** a per-clip speed (new operation; the Remotion renderer plays at that rate).
- **Markers** on the ruler (new document field).
- **Phone editing:** today the lanes are view-only at 430 by design. Tier 3 decides with the
  operator whether phones get editing (tap to select, the same menu by long press, a stacked
  preview above the lanes) or stay view-only with a better layout.

## 8. Left to the builder

- Component structure, state shape and file layout.
- The exact zoom curve, the marquee hit test, menu placement maths.
- Icons, spacing and colours within the existing design system.
- Plain-language wording, as long as both locales get it.

## 9. Next steps

- The operator reviews this spec.
- Then a Tier 1 implementation plan (`superpowers:writing-plans`) on branch
  `feat/studio-timeline-track`, which already holds the research report.
- Operator gates, each separate: a one-day write-scope e2e token, push and PR, deploy of the
  branch image, merge.
