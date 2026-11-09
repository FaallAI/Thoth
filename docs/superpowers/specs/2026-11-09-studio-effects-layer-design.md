# Studio effects layer for Style A and Style B (design)

| | |
|---|---|
| Roadmap | `docs/ROADMAP.md` item 6 (auto-draft), the slice after the narrated draft; it comes before the style template step 1 |
| References | Style A = IsseiNugroho (`AcmArpQ_7Tc`); Style B = WinNews (TikTok `7704331952681241863`), operator 2026-11-09 |
| Evidence | Editor readings in `D:/thoth-tmp/research/editor-eye/*/editor-reading.md`, made with the `breaking-down-short-videos` skill (FaallAI/editor-eye) |

## 1. Intent

Thoth's drafts cannot yet look like either reference. The gap is not the material, which Stage 5c
already gathers, but the effects an editor applies to it. Both references depend on effects the
document and the composition cannot express today:

- **Style A** pushes in hard on the punchline (+33% to +47% in a fraction of a second), pans along a
  post's text, scrolls a feed, puts non-9:16 media on a blurred copy of itself, draws a box around one
  word and an arrow at one person, and uses small boxed subtitles.
- **Style B** reveals big white words two to four at a time with the voice, puts the narrator's own
  questions on white cards with black text, dims the footage under the words, and pushes in slowly.

This slice adds those effects to the edit document, draws them identically in the Studio preview and
the render, and lets a person apply and adjust them in Studio. Choosing them automatically per word,
the planner's editor logic, is the next slice.

## 2. What exists (read 2026-11-09)

- Video clips (video and image assets) have `fit` (`cover`, `contain`, `fill`), `crop`, `position`
  (x, y, scale), fades, speed, blur regions, and `volume_keyframes`.
- `motion` is a preset: `none`, `slow_zoom` (to 108%, linear over the whole clip) or `pan` (±3%).
- `emphasis` is two booleans: a border around the whole clip and one arrow.
- Caption styles: `caption_default`, `source`, `word_highlight`. Cues carry word timings from
  narration.
- Text clips have a heading, a body and a style slot.
- The composition (`packages/remotion-composition`) draws the preview and the render from one
  definition; style names are allow-listed and an unknown name falls back to the default.

## 3. Goals

### 3.1 Moves: keyframed scale and position

A video clip gains an optional `moves` list: keyframes, each with a frame relative to the clip's
start (timeline frames), `scale`, `x`, `y` and an easing (`linear`, `ease_out`, `ease_in_out`, `hold`).
Frames between keyframes interpolate. When `moves` is present it replaces the `motion` preset for that
clip; `motion` keeps working for drafts that use it.

Moves stack on the clip's `position`, as `motion` does today: a keyframe's `scale` multiplies
`position.scale` and its `x` and `y` add to `position.x` and `position.y`. A keyframe of scale 1 at
0, 0 is the clip's placement, so Story's placement presets keep working on a clip with moves.

Moves cover every camera move in the references: a punch-in on a word, a slow push-in, a pan along
text, a scroll down a tall screenshot, and a pull-out.

Editing a clip keeps its moves where they belong, by the same rules for every operation, in the
server operations and their mirror in the Studio client:

- trimming the start shifts the keyframes and keeps the value at the new start;
- a split gives each half its keyframes, with the value at the cut;
- speed does not change them;
- a change of length by retiming (narration and re-voice mapping a clip onto its new beat window, or a
  scene's new duration) stretches the keyframes with the clip, so a push-in across the clip stays
  across the clip;
- cutting the end (a later scene taking over) drops the keyframes past the new end and keeps the value
  there, as fades are fitted today.

### 3.2 Blur-fill background

A video clip gains `background`: `none` (today) or `blur_fill`. With `blur_fill`, a blurred copy of
the same media, scaled to cover the canvas, sits behind the clip. It does not follow the clip's moves,
and it fades with the clip. Choosing Blur-fill in Studio also sets the clip's fit to `contain` in the
same step, since a covering picture leaves no room to see it.

### 3.3 Dim

A video clip gains `dim`, from 0 (today) to 0.8: a black veil over the clip's own picture, as Style B
puts its words on darkened footage. Tracks drawn above the clip stay above the veil.

### 3.4 Marks: a box or an arrow on part of the picture

`emphasis` gains an optional `marks` list. A mark is a `box` (x, y, w, h) or an `arrow` (the point it
points at, and the side it comes from), in fractions of the media frame, with a time window in source
frames, as blur regions have, and a colour slot (`accent`, `alert`). Marks stick to the media: they
follow the clip's crop, position and moves, and trimming, moving, splitting or retiming a clip never
shifts them. Replacing the clip's media drops them, as it drops the crop and blur regions. A box draws
itself in; an arrow pops in. The existing booleans keep their meaning.

### 3.5 Caption styles

Two allow-listed caption styles join the three:

- `boxed`: small white text on a black box, lower middle, a cue at a time (Style A).
- `kinetic`: big bold white words in the centre, revealed in groups of two to four following the
  cue's word timings, each group replacing the last (Style B). A cue without word timings shows
  whole.

### 3.6 Text cards

A text clip style `card` draws a full-frame white card with the heading in large black bold type
(Style B's narrator cards).

### 3.7 Studio

In the Timeline Inspector, for the selected clip:

- **Background:** None or Blur-fill. **Dim:** a slider.
- **Moves:** presets that write keyframes, each one undo step:
  - Punch in at the playhead;
  - Push in across the clip;
  - Pan across;
  - Scroll down;
  - Pull out.

  The list of keyframes, each removable; a clear-all.
- **Marks:** add a box or an arrow, with numeric fields and its time window. Its place starts at the
  middle of the picture.
- **Caption style** and **text style** selections include the new styles.

The Timeline shows a small mark on a clip that has moves or marks, so they are not invisible.

Story keeps its beat-level controls, which apply to every card of a beat (or the photos of the
Footage beat) at once: it gains Background and Dim, and the moves presets that do not need a playhead
(Push in, Pan across, Scroll down, Pull out). Marks and Punch in at the playhead are Timeline tools,
and Story names the clips that have them.

### 3.8 New drafts

New auto-drafts put full-frame media whose shape is not 9:16 (the main video, footage, slides,
photos and stills) on `blur_fill` with `fit` `contain`. Cards placed over the main video (post,
profile and comment cards) keep their place and fit. Nothing else in the planner changes in this
slice.

## 4. Non-goals (later slices)

- Choosing moves, marks, cards and pictures per word: the planner's editor logic, built from the
  reference readings.
- The style template schema and the built-in Style A and Style B templates.
- Drawing marks and keyframes directly on the preview with the mouse.
- Style A's hook collage (cut-out faces, layered big title) and a post card with its video playing
  inside.
- Stage 6 enrichment (story context, claims checked against sources), person-targeted footage search,
  and the SFX library.

## 5. Anti-goals

- An existing document that renders differently.
- A preview that differs from the render.
- An effect a person cannot see, find or remove in Studio.
- An effect that only the planner can set.

## 6. Constraints

- Every new field is optional with a default that renders exactly as today, and an unused field is not
  stored (`exclude_if`), so a rollback stays safe for drafts that do not use the effects. A draft that
  uses a new style or field will not load on older images; say so in the rollback note.
- Style names stay allow-listed in the composition, and every coordinate and frame is bounded by the
  schema, as blur regions are.
- Edit operations stay typed and each is one undo step, through the existing operation path.
- Render time: measure a 60 s draft with blur-fill on every clip against the same draft without it.
  If it costs more than 25%, use the cheaper way for video sources.
- Verification is offline only: domain tests, composition maths tests, Studio tests, and golden
  frames for each new effect in a new release capsule, so `story_mode-v1` and its approved goldens
  stay as they are. Approving and promoting the new goldens is the operator's own gate, as for every
  capsule. The render-time measurement runs locally with fixture media.

## 7. Calls made while writing (not asked of the operator)

- The slice splits the effects from the planner logic that chooses them, as Tier 3 was split into
  3a and 3b.
- Marks are placed with numeric fields first; drawing them on the preview is a later slice.
- Only blur-fill reaches new auto-drafts now, because both style families and the third reference
  use it; the rest waits for the planner slice.
- Moves use timeline frames relative to the clip, as `volume_keyframes` do, so a person reasons in the
  timeline they see. Marks use source frames, as blur regions do, because they sit on the picture's
  content.
- Moves stack on `position` rather than replacing it, so placement presets keep working.
- Retiming stretches moves; cutting an end drops what falls past it.
- Story stays beat-level; per-clip marks and punch-ins live in the Timeline.
- Dim veils only its own clip, whatever the track order.
- The new goldens go in a new capsule.

## 8. Left to the builder

- The exact easing curves, preset amounts (for example a punch-in of 35% over 8 frames) and the
  number of keyframes allowed.
- How blur-fill is drawn for video sources within the render-time limit.
- The Inspector layout, within the existing Inspector sections.
