# Studio Timeline against common editors: audit and research

Input to step 1 (spec) of the Studio Timeline track in `docs/ROADMAP.md`. The operator asked on
2026-11-08 for a full, deep e2e test of the Studio and for research so the Studio works like the
editing studio of a common application. This report holds both. It is not a design; the spec decides.

## 1. Summary

- The Timeline is a working base: drag, both trims, snap, Escape, frame nudges, Ctrl+Z / Ctrl+Y,
  toolbar split / move / trims at the playhead, zoom buttons, Play and ruler seek, hide / mute /
  lock, and Inspector start and end frames all pass a real-mouse e2e run on the deployed stack.
- What every benchmark editor has and Thoth lacks is the **editing grammar**: Delete, S to split,
  a right-click menu, multi-select, copy / paste / duplicate, close a gap, Ctrl+wheel zoom, click
  a lane to seek, and a track you can select. Most of these need no new server operation.
- The look still carries the 2026-11-05 design findings: raw track names (`main_video`), clips
  without pictures or waveforms, a short lane area, and an empty Inspector that takes a third of
  the screen at 1024.
- Proposed scope, in three tiers (section 6): editor basics first, then comfort, then the
  pro tools that need new backend work (filmstrips, waveforms, roll and slip, speed).

## 2. What was tested

All on stage1 at `a764c4bc` (master `5b20306e`), 2026-11-08.

**Write run** (`e2e/e2e.write.config.ts`, target `rw1440`, the throwaway project
`E2E write test 2026-11-04`, no model, the write guard closed to narration, Assist, proposals,
runs and imports): `tests-write/timeline-audit.e2e.ts` and `tests-write/studio-write.e2e.ts`,
38 tests, **29 passed, 9 failed**.

| Failed test | Why |
|---|---|
| drag: a clip can be dragged to another track | not built (server has `move_clip.target_track_id`) |
| keyboard: Delete removes the selected clip | not built (server has `remove_clip`) |
| keyboard: S splits the selected clip at the playhead | not built (the toolbar split works) |
| toolbar: Ctrl+wheel zooms the lanes | not built |
| playback: a click on an empty part of a lane moves the playhead | not built |
| tracks: clicking a track header selects the track for the Inspector | not built |
| inspector: Fit, Crop and Position can be changed on a video clip | fields are locked |
| right click: a clip opens an editing menu | not built |
| studio-write: a video longer than the canvas is cut to fit | **test fragility, not an app bug**: the test expects the newest `Upload · Video` to be the 80 s fixture, but an earlier test in the same run uploaded a 20.1 s video; the app correctly said "Cut to 5.0 s of 20.1 s". Fix the test to use its own upload. |

The eight timeline failures are the red tests written on 2026-11-05; none of them is a regression.

**Read-only look** (`e2e/e2e.config.ts`, read-scope token, the narrated draft
`edoc_b410cf36…`, Timeline mode, judged from screenshots):

| Width | Seen |
|---|---|
| 1440 | Seven lanes fit, but the lane area is about a fifth of the height while the preview sits small in a large dark area. Track names are raw ids (`main_video`, `b_roll`). Clips are text only; short clips read "P…", "Co…". The Inspector shows timing in **frames** (225 / 334) with the time small beside it. Fit, Crop and Position are greyed out. "Ownership: AI managed / User edited / Locked" is internal language. No delete, duplicate or replace in the Inspector. The Assets column has no search, and uploads are named `Upload · Image · 13`. |
| 1024 | The empty Inspector ("Select a clip or track to edit it") takes about a third of the width; the lanes show about 8 s; the SFX lane is cut at the bottom. |
| 430 | Lanes are view-only by design ("Best on a larger screen"), and Preview and Timeline are separate panes, so you cannot watch while scrubbing. Undo and Redo are not in the phone header by design; they sit in the workspace menu (final review I5). |

Previews do not load under the read scope, so pictures in the preview were not judged.

## 3. What Thoth has today

**Server operations** (`EditDocumentPatch`): `add_clip_from_asset`, `add_text_clip`,
`add_caption_clip`, `add_track`, `move_clip` (with `target_track_id`), `remove_clip`,
`remove_empty_track`, `reorder_track`, `reorder_scene`, `replace_clip_asset`, `replace_text`,
`split_clip`, `trim_clip_start`, `trim_clip_end`, `set_clip_hidden`, `set_clip_locked`,
`set_clip_position`, `set_clip_motion`, `set_clip_volume`, `set_clip_blur`, `set_clip_emphasis`,
`set_text_place`, `set_track_locked`, `set_track_muted`, `set_track_visibility`,
`set_caption_cue_text`, `set_caption_cue_timing`, `set_caption_style`, `set_ownership`,
`set_scene_duration`. There is no `duplicate`, `copy`, `speed` or `fade` operation.

**Timeline UI:** Play, time, clip actions at the playhead (move, trim start, trim end, split),
Ripple and Snap switches, zoom out / slider / in, a draggable playhead, per-track hide / mute /
lock, clip drag and edge trims, arrow nudges on a focused clip, Escape cancels a drag, Undo and
Redo in the top bar and on Ctrl+Z / Ctrl+Y, an Assets column with Add and Preview, a Sound
effects list, a Timeline issues bar, and an Inspector with Timing, Transform, Clip, Audio and
Content sections.

## 4. Benchmarks

Read on 2026-11-08. Official pages are marked; the rest are third-party guides and indicative only.

| Editor | Timeline grammar worth copying |
|---|---|
| Clipchamp (official shortcut page) | Ctrl+Z / Ctrl+Y, **S split**, Delete / Backspace, **Ctrl+C / Ctrl+V / Ctrl+D**, Ctrl+A, Esc deselects, Ctrl+G group; Space play; Ctrl+Left / Right to start / end; Left / Right step, Shift for larger; Ctrl+= / Ctrl+- / **Ctrl+0 zoom to fit**; X+arrows move an item, X+Up / Down to another track; Z+arrows and C+arrows trim start and end. Hovering or right-clicking a **gap offers "delete this gap"** and "delete all visual gaps"; Shift or Ctrl adds to a selection. Up to 50 undo steps. |
| Descript (official help) | A for select, **B blade**, R range, Y slip, H hand; S adds a clip boundary; Shift+Delete replaces with a gap; Ctrl+scroll zooms; zoom to playhead, fit selection; Ctrl+D duplicate layer; ] [ bring forward / send back; Alt+H hide, Alt+L lock; Ctrl+/ opens the **shortcut list**; markers on the ruler; a storyboard view of scenes beside the timeline view. |
| Remotion Editor Starter (official features page) | Draggable playhead with edge scroll; drop assets on the timeline; **filmstrip thumbnails**; **audio waveforms** with a draggable volume line; **fade in / out handles**; max-trim outline; split; **marquee multi-select**; hide / mute track; **rolling edits**; follow playhead while playing; snapping with a magnet toggle (Shift+M); cut / copy / paste / duplicate; right-click bring to front / send to back; a zoom slider; a resizable timeline panel. Thoth's renderer is Remotion, so these are the nearest patterns. |
| DaVinci Resolve (Blackmagic page and guides) | One smart trim tool picks ripple, roll, slip or slide by pointer position; blade B, select A, trim T; snapping N; linked selection Ctrl+Shift+L; delete all gaps from the menu. |
| Premiere Pro (guides) | Ripple delete Shift+Delete, and from a right-click on a gap; right-click a clip for Speed/Duration, Unlink, Nest, Enable; slide with Alt+, and Alt+. ; a keyboard customisation panel. |
| CapCut desktop (guides only; no official list found) | Split (Ctrl+B), Delete Left / Delete Right of the playhead, freeze frame, right-click split scenes, a rebindable shortcut panel. |
| Web editors (Clipchamp, OpenCut, Slate, Motionbox) | A context menu on items for delete and copy; a toolbar that changes with the selection; batch actions on a multi-selection, each tracked by undo. |

## 5. Gaps

Legend: **UI** = server ready, needs dashboard work; **op** = needs a new server operation;
**backend** = needs new processing.

| Gap | Where the benchmark has it | Kind |
|---|---|---|
| Delete / Backspace on the selected clip, and a delete button | all | UI |
| S splits the selected clip at the playhead | Clipchamp, Descript | UI |
| Right-click menu on a clip (split, delete, ripple delete, duplicate, copy, paste, replace media, move to track, hide, lock) | Premiere, Remotion, OpenCut | UI, plus op for duplicate / paste |
| Right-click or hover on a gap: close this gap, close all gaps | Clipchamp, Premiere, Resolve | UI (a ripple `move_clip` batch) |
| Drag a clip to another track | all | UI |
| Select a track from its header; move a track up / down; remove an empty track | Descript, Premiere | UI |
| Click an empty part of a lane to seek | all | UI |
| Ctrl+wheel zoom, Ctrl+= / Ctrl+- / Ctrl+0 fit | Clipchamp, Descript | UI |
| Multi-select (Shift / Ctrl click, marquee), batch move / delete | Clipchamp, Remotion | UI |
| Copy, paste, duplicate | Clipchamp, Remotion, Descript | op |
| Readable track names; timing in time, not frames | all | UI |
| Fit, Crop, Position editable; fade in / out | Remotion | UI (position / motion ops exist), op for fades |
| A shortcut list (Ctrl+/ or ?) | Descript, CapCut | UI |
| Playback keys: Space, Home / End, J / K / L | Clipchamp, Descript | UI |
| Replace media from the Timeline | Story mode already has Replace | UI |
| Search and filter in the Assets column; drag an asset onto a lane | Remotion | UI |
| Filmstrip thumbnails and waveforms; a volume line | Remotion | backend |
| Roll and slip edits | Resolve, Remotion, Descript | UI, maybe op |
| Speed / duration | Premiere | op and renderer |
| Markers on the ruler | Descript | op |
| Phone editing (the lanes are view-only at 430) | CapCut mobile | UI; product decision |

## 6. Proposed tiers (for the spec to confirm)

1. **Editor basics.** Delete, S, right-click menus on clip, gap and track, drag to another track,
   track selection and order, click-to-seek, Ctrl+wheel and fit zoom, readable names, time instead
   of frames, the 1024 and 1440 layout findings, Replace media in the Timeline, the shortcut list.
   All but duplicate and paste use existing operations.
2. **Comfort.** Multi-select and marquee with batch actions, copy / paste / duplicate (new
   operation), close all gaps, Fit / Crop / Position and fades in the Inspector, Assets search and
   drag-to-lane, playback keys.
3. **Pro.** Filmstrips and waveforms with a volume line (backend), roll and slip, speed, markers,
   and editing on a phone.

## 7. Sources

- Clipchamp keyboard shortcuts (official): https://support.microsoft.com/en-us/Clipchamp/keyboard-shortcuts-for-clipchamp
- Clipchamp gaps (official): https://support.microsoft.com/en-US/Clipchamp/how-to-remove-gaps-on-the-timeline
- Clipchamp undo / redo (official): https://support.microsoft.com/en-us/Clipchamp/how-to-undo-or-redo-actions-on-the-timeline
- Descript keyboard shortcuts (official): https://help.descript.com/descript-tour/keyboard-shortcuts
- Descript timeline overview (official): https://help.descript.com/timeline/timeline-overview
- Descript advanced timeline tools (official): https://help.descript.com/hc/en-us/articles/10249344527501
- Remotion Editor Starter features (official): https://www.remotion.dev/docs/editor-starter/features
- DaVinci Resolve edit page (official): https://www.blackmagicdesign.com/products/davinciresolve/edit
- Resolve shortcuts (guide): https://davinciresolveclub.com/davinci-resolve-keyboard-shortcuts-guide/
- Premiere Pro ripple delete and speed (guides): https://www.ledet.com/premiere-pro-ripple-delete/, https://helpwiki.evergreen.edu/wiki/index.php/Speed_and_Duration
- CapCut shortcuts (guides): https://tutorialtactic.com/blog/capcut-shortcuts/, https://primalvideo.com/guides/capcut-for-pc-mac-tutorial/
- OpenCut multi-select (pull request): https://gh.hhj520.top/OpenCut-app/OpenCut/pull/18
- Earlier Studio research (2026-10-25): `docs/research/2026-10-25-studio-design-research.md`
