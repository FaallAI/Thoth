# Planner as the default b-roll placement, and the planned draft's overlap warnings — design

Date: 2026-11-17. Status: draft for the operator's review.
Track: reference-faithful editing; follows the planner stage 1 (`2026-11-13-planner-stage-1-design.md`) and the footage library (`2026-11-15-footage-library-design.md`, sections 10 and 10.12).
Record of the conversation: `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`, items 80-83.

## 1. Why

**The footage never reached the video.**
- Run `wf_783f8d64` admitted 5 clips. Two of them are Denny Sumargo podcast sections, one showing Saiful (`related`).
- Draft `edoc_3ee4719b` was written in Style A, and Style A does not plan (`CutRules.planned` is off). It has one footage beat, 6.5 s long in this draft, filled with materials in order. Only 2 clips fit, and the first one was the same-event creator clip.
- The planner, which picks a picture for each phrase by what it says, runs only for Style B. The planner spec left Style A's explainer collage for a later stage.

**The operator's direction** (item 82): Style B's b-roll placement "akan jadi default saja ... tapi bukan berarti akan menjadi hardcode, tapi tetap bisa dikembangkan lagi atau dikreasikan lagi seperti tambahan effect atau component", "karena style B sudah mendekati perfect editing".

**The same draft in Style B shows 7 timeline warnings, all `clip_overlap`** (revision 19, item 83):

| # | Lane | Clip | Overlaps |
|---|---|---|---|
| 1-3 | b-roll | `clip_style_evidence_plan_1..3` (352-384, 384-455, 509-546) | the import's `clip_profile_card_000` (352-546), left under the planner's shots |
| 4-5 | overlay | `clip_style_main_card_1` (106-166), `clip_style_main_credit_1` (262-311) | the import's hook title `clip_001` (`title_top`, 0-323) |
| 6 | overlay | `clip_style_evidence_credit_3` (509-546) | `clip_style_evidence_card_1` (`card`, 455-515) |
| 7 | overlay | `clip_style_footage_card_1` (1064-1124) | `clip_style_footage_credit_2` (`credit`, 1004-1074) |

- **Warnings 1-3 are a real conflict.** Two pictures fill the b-roll lane at once. The beat's import material stays after the planner placed its own shots over that beat.
- **Warnings 4-7 are not conflicts on screen.** A top title, a centred card and a corner credit are different places on the picture, and the references show them together. They only share one lane.

## 2. Goals

1. **Every style places b-roll with the planner by default.** `CutRules.planned` defaults to on. A style can still turn it off, so nothing is hardcoded.
2. **Each style sets its own rhythm.** The phrase split reads the style's shot band instead of fixed numbers:
   - Style B keeps 0.9-2.4 s, the WinNews measurement;
   - Style A gets 1.5-4.0 s, from its measured median of 1.5-2.7 s and a middle half of 0.8-5.9 s (item 15). It can be tuned after the operator looks.
3. **Each style keeps its own look.** Moves, dim, fit, captions and cards stay per style, so Style A still looks like Style A.
4. **In a planned beat, the planner owns the b-roll.** The beat's import material clips on the b-roll are removed when the planner plans that beat. A phrase without a pick shows the main video (planner spec, goal 4). Re-planning a beat already removes the planner's own clips; this adds the import's.
5. **Clips may stack, as layers do in CapCut** (operator, item 84: "ya itu yang ku maksud").
   - **Remotion already stacks.** The renderer draws every clip as its own `<Sequence>`, and the lower an element is in the tree, the higher it appears (remotion.dev/docs/layers, via Context7). So overlapping clips on one lane already render on top of each other. Only the editor calls them a problem.
   - **A lane holds layers.** Within a lane, clips that overlap in time sit on stacked layers. The layer is computed, not stored:
     - clips are taken by start frame, then document order;
     - each clip goes on the lowest layer whose last clip has ended by its start.
   - **Studio draws each layer as a sub-row** of its lane, the top layer highest, so stacked clips no longer hide each other and each one can be selected.
   - **The render follows the layers.** Within a lane, the composition draws clips by layer, then start frame, so a higher layer is on top in the video just as it is in Studio.
     - **A consequence (final review, 2026-11-17):** a clip already stacked over another stays above a clip that later joins the lower layer.
       - **Example:** A 0-100 (layer 0), Y 50-200 (layer 1), X 100-150 (layer 0). Y is drawn over X, where time order used to draw X over Y.
       - **What it can change:** an existing draft with this shape re-stacks. The three template-release goldens have the shape on their badge lane but still pass pixel parity, because the two presets do not touch on screen.
     - **While a clip is dragged,** each lane keeps the rows it had when the drag began.
   - **`clip_overlap` is no longer a warning,** in Studio (`timelineIssues`) or in the server review (`studio_review`). `main_track_gap` and `clip_exceeds_canvas` stay.
   - **The bug the warning caught stays caught** (operator, item 85, after a side agent's note). The warning is what exposed the profile card left under the planner's shots. Two pictures at once on the b-roll is still a defect:
     - `b_roll_overlaps(document)` names such pairs;
     - a test asserts that no style, planned or not, leaves any;
     - the narration write logs a warning when a styled draft has one.
   - **Moving a clip to another layer by hand** is a later stage (§4).
6. **Extension points are named for later stages.** Memes, SFX and effects are new kinds the planner may pick per phrase, from the workspace library, beside today's base and overlay. They are not built here (§4).

## 3. Cost and taste

- **Cost.** A Style A draft now runs the planner's one paid call when the narration is written. The planner trial spent USD 0.0911 in all. A planner failure still falls back to phrase cuts with cursor picks, as in planner goal 8.
- **Taste.** Style A cuts per phrase, slower than Style B. The explainer collage (evidence cards on a paper texture, cutouts) remains the later stage. The Style A drafts the operator rated "sangat bagus" used the old fixed beats, so the operator compares one new Style A draft with the old one.
- **Credits.** Every footage shot keeps its `@account` credit in every style. The measured Style A references add none, so a style flag to drop it can come later, at the operator's word.

## 4. Out of scope

- The explainer collage of Style A.
- Memes, SFX and effects picked by the planner (goal 6 only names the seam).
- Moving a clip between layers by hand, or a stored layer field. Layers are computed for now.
- Re-planning drafts written before this change. A new narration write plans them.

## 5. Evaluation

- **Offline:**
  - the phrase split follows the style's band;
  - a style without `planned` set is planned;
  - a planned beat leaves no import material clip under the planner's shots;
  - overlapping clips get computed layers;
  - Studio draws them as sub-rows and no longer warns `clip_overlap`, and neither does the server review;
  - the composition draws a lane's clips by layer;
  - the existing planner and Style B tests stay green.
- **Live** (operator gate):
  - one new Style A narration (a paid call, cost shown first) on the Mutant draft;
  - the podcast section showing Saiful appears where the voice talks about the podcast;
  - Studio shows the Mutant Style B draft's stacked titles, cards and credits as layers, with no overlap warning.
EOF