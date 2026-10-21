# Stage 5c-1: Cards, Carousel Slides and Subtitle Blur in Studio

**Date:** 2026-10-21
**Status:** Approved in conversation (sections 1–3, 2026-10-21); this document awaits operator review.
**Roadmap:** item 4, Stage 5c. The operator split 5c into 5c-1 (this spec: Studio) and 5c-2
(acquisition of post cards, photo slides and creator-profile footage), Studio first.
**Builds on:** `2026-10-20-workflow-to-studio-design.md` (roadmap item 2, deployed 2026-10-21, PR #36).

## 1. Goal

"Open in Studio" leaves out every card and every carousel slide past the first; the gate lists
them as "Cards wait for Stage 5c" and "Carousel slides wait for Stage 5c". After 5c-1, a draft
opened from a workflow holds them, laid out the way the legacy Rust render did, with the timing
corrected for reading speed. Subtitle blur becomes a capability of the editor document, the
renderer and the preview. It is stored on the clip but switched off until narration exists
(section 6).

Success: a draft opened from a Content Set whose main is a video with a profile card and comment
cards shows, without any manual step:

- the creator's profile card over the main video from 3 s to 6 s;
- up to three comment cards over the main video in its reaction beat;
- the remaining comment cards in the project's asset library and in the gate as "not placed";
- for an `images` main, every slide in order on the main track;
- on a main or footage clip with detected subtitles, the regions stored and switched off, with
  one inspector action that switches on blur and mute together.

## 2. Evidence the layout rests on

Measured on the 23 Content Sets stored in the deployed stack (2026-10-21):

| Measure | Value |
|---|---|
| Comments | 108, every one with a real card crop |
| Comments per Content Set | 2 (15 sets), 3 (2 sets), 12 (6 sets) |
| Comment text length (characters) | p10 13, median 39, p75 58, p90 84, max 155 |
| Main kind | `video` in all 23; every main has a profile card |
| Main length after trim | 11.2 s to 49.1 s, median 46.5 s |
| Profile card crop | about 1114 × 416 px |
| Comment card crop | about 608–768 × 150–206 px |
| Main OCR outcome | `clean` 17, `cover` 2, `subtitle` 4 (mute plus 1–3 timed blur regions) |
| Footage OCR outcome | `clean` 68, `cover` 37, `overlay` 2 |

External references:

- The Netflix Indonesian Timed Text Style Guide limits adult subtitles to 17 characters per
  second. The Netflix general guide caps one event at 7 seconds.
- Szarkowska & Gerber-Morón (2018) and the 2024 eye-tracking replication found that reading slows
  while video plays under the text.
- Indonesian university readers read 150–200 words per minute in field studies, and the
  comments average 6.09 characters per word, spaces included. That is 15–20 characters per
  second; 15 follows the slower readers.
- Eye-tracking puts the processing latency after text appears at 400–700 ms, before the time
  spent finding where the text is.
- Safe zones on a 1080 × 1920 frame, taking the strictest edge of three platforms:
  - TikTok, measured from the alpha channel of TikTok's own in-feed template: 240 px top, 660 px
    bottom, 120 px on each side, widening to 300 px on the right below the vertical midpoint,
    where the like, comment and share column sits;
  - Reels, from Meta's ads guide: 14 % top, 35 % bottom, 6 % each side;
  - Shorts, from Google's ads spec: 10 % top, 25 % bottom, 10 % right.

  Combined, the safe area is **x 120–960, y 269–1248**, and below y 960 only up to x 780 on the
  right. The platforms publish these figures for ads; no organic safe zone is published.
- Retention guidance (secondary sources) recommends a visual change every 2–4 s and a re-hook
  mid-video, and notes that most mobile viewing is muted.

The legacy render showed comment cards for a fixed 3.5 s. At 17 characters per second a p90
comment needs about 5 s, so it was cut off.

No primary source gives a typical short-video retention curve. The beat's 40 % start is kept
from the legacy render as a starting point for the operator's evaluation (section 3.5).

**Blur strength was measured** (2026-10-21, read-only, on the two distinct subtitled mains).
Frames were scaled to the canvas and each OCR region was blurred with a Gaussian of standard
deviation σ, which is what CSS `blur(σ)` applies.

- RapidOCR still read 4 of 18 regions at σ 4 and none from σ 8.
- By eye, a two-line subtitle in a 169 px band stayed plainly readable at σ 6–12, was faint at
  σ 16 and gone at σ 24. A "SNAP!" logo in a 145 px band stayed readable up to σ 16.
- The legacy render's `boxblur=12:2` is about σ 10, so its blurred subtitles were most likely
  still readable.

## 3. Layout rules

All positions are on the 1080 × 1920 canvas. A card is a `TimelineVideoClip` of its image asset
with `fit = "contain"` and a `position` (scale and canvas-fraction offsets). It sits on
`track_b_roll` inside the main scene. Footage occupies its own scenes, so a card never overlaps
a footage clip.

### 3.1 Profile card

- From 3.0 s to 6.0 s of the main scene, clamped to the scene: start at most at its length minus
  0.5 s, duration at least 0.5 s. This is the legacy `[profile_card]` default.
- The same upper slot as the comment cards: 76 % of the canvas width (about 820 px), centred
  horizontally, vertical centre at 500 px (`CARD_CENTER_Y = 0.26`). A 1114 × 416 crop then
  spans y ≈ 347–653, inside the safe area.
- The two never overlap in time: the profile card ends at 6 s, and the reaction beat starts at
  40 % of the main. The legacy "lower" position would have put the card's right edge at
  x ≈ 999, under TikTok's action column, and on the original video's own subtitles, which in
  the stored data sit around y 1250.
- Placed only from a real crop (`main.profile_card`). There is never a synthetic card.

### 3.2 Comment cards: the reaction beat

A pure function `reaction_beat(main_seconds, cards)` lays them out. `cards` lists the comment
cards in projection order: likes descending, ties in Content Set order.

- **Reading time** per card: `characters / 15 + 1.0` seconds, clamped to [2.5, 7.0]. 15 rather
  than 17 characters per second because the video keeps playing; the extra second is for finding
  the card.
- **Beat:** starts at 40 % of the main scene's length and ends 0.3 s before the scene ends.
- **Filling:** cards are taken in order, each starting 0.5 s after the previous one ends. A card
  that does not fit before the end of the beat is not placed, and no card after it is tried. A
  card is never shortened below its reading time. At most three are placed.
- **Spreading:** whatever time is left over in the beat is shared out evenly as extra gaps, so
  the cards spread across the beat as the legacy render's did instead of bunching at its start.
- **Position:** 76 % of the canvas width (about 820 px, inside x 120–960), centred
  horizontally, vertical centre at 500 px (`CARD_CENTER_Y = 0.26`). A comment card then spans
  y ≈ 394–606.
- Typical results: an 11 s main gets one or two cards, a 46 s main gets three.

A comment card that gets no slot is not placed. Its asset is still imported and registered, and
its gate item ends `excluded` with the reason "Not placed: no room in the reaction beat". A
person can still place it by hand.

### 3.3 Carousel slides

- For an `images` main, the main scene lasts 3.0 s × the number of images.
- Image *k* (counting from 0) sits on `track_main_video` from *k* × 3.0 s for 3.0 s, with
  `fit = "contain"`.
- The main item still carries image 0; images 1 onward are `slide` items.

### 3.4 Blur strength

- σ = max(24, 0.2 × the region's height in canvas pixels). A 109 px band gets σ 24, and a
  169 px band gets σ 34.
- The height is measured on the canvas, after the clip's fit, crop and scale, so the blur stays
  strong enough when the clip is scaled.
- Each region is widened by σ on every side, so that letter edges at the region's border are
  blurred too.

### 3.5 Tuning

Every layout and blur number lives in one constants module:

- the reading rate, orientation time, clamps, beat start, gap and card count;
- the card width and centre;
- the slide length;
- the blur factor and floor.

The operator evaluates the result once 5c-1 runs, and these values are tuned from that
evaluation.

### 3.6 Out of scope for 5c-1

- The legacy notification SFX on each comment card: Studio has no SFX library yet.
- Entrance animations: the composition has none.
- Footage scenes, comment cards without a crop, and anything the projection leaves out today keep
  their current behaviour. A comment without a card stays a text scene.

## 4. Gate and projection (`assembly/studio.py`, `domain/studio_imports.py`)

### 4.1 Roles

`SourceRole` gains `slide`, `profile_card` and `comment_card`. The role order becomes:

```
main, main_footage, slide, footage, profile_card, comment_card, comment
```

Each role is numbered from zero without gaps, as today. Overlay roles (`slide`, `profile_card`,
`comment_card`) get no scene of their own: their inventory entry carries the main scene's id.

### 4.2 Projected items

| Content Set | Item |
|---|---|
| `main.images[1:]` | `slide` items, `media_kind = "image"` |
| `main.profile_card` | one `profile_card` item, `media_kind = "image"`, title `@<owner_handle>` |
| `comments[i]` with `card` | `comment_card` item: title `@<author>`, text = the comment, `media_kind = "image"`, ordered by likes descending |
| `comments[i]` without `card` | `comment` text item, as today |
| `main.ocr` / `footage[i].ocr` with `subtitle_blur` | the regions on the main or footage item (section 5.1) |
| `main.ocr.mute_audio` / `footage[i].ocr.mute_audio` | `mute_audio` on that item |

`StudioSourceItem` gains:

- `mute_audio: bool = False`;
- `blur_regions: list[SourceBlurRegion] = []`, in source seconds, video items only;
- `reading_seconds: float | None`, set on `comment_card` items from section 3.2.

The inventory entry (`StudioImportItem`) carries `reading_seconds` and the item's projection
rank. That lets placement be recomputed from the stored inventory alone, both for a workflow
import and for a person attaching by hand.

The unsupported list no longer reports `main.images`, `main.profile_card`, `comments.card`,
`*.mute_audio` or `*.subtitle_blur`. `figures` stays unsupported.

Drafts made before 5c-1 keep the inventory they were created with. The workflow source key is
derived from the Content Set's bytes, not from the projection, so their "Resume" link keeps
working. A new draft of the same workflow gets the 5c-1 items.

## 5. Editor document, renderer and preview

### 5.1 `blur_regions` on a video clip

`TimelineVideoClip` gains two additive fields, so every stored document stays valid:

```
blur_regions: list[ClipBlurRegion] = []   # max 200
blur_enabled: bool = False

ClipBlurRegion:
  x, y, w, h: float          # fractions of the SOURCE frame, inside [0, 1]
  from_frame: int | None     # source frames; both or neither
  to_frame: int | None       # exclusive
```

- Times are in **source** frames, so trimming, moving or splitting a clip never shifts its blur.
  A split copies the regions to both halves.
- Import converts seconds to frames at the canvas fps.
  - A region whose window ends before the clip's trim start is dropped.
  - A window that starts before the trim is clamped to the trim.
- A new operation `set_clip_blur { clip_id, blur_enabled }` switches blur on or off. Regions are
  never drawn by hand in 5c-1.
- The TypeScript document types and the OpenAPI schema are regenerated.

### 5.2 Composition (`packages/remotion-composition`)

The renderer and the dashboard preview share the composition. For a video clip with
`blur_enabled` and regions, it draws one absolutely positioned element per region inside the
clip frame, with `backdrop-filter: blur(σ)`. σ and the widened region follow section 3.4.

- **Position:** the region is mapped from source fractions to the displayed media box. The
  mapping uses the asset's width and height from `asset_refs`, plus the clip's `fit`, `crop` and
  `position`, so the blur follows the media when it is scaled or cropped. When the asset's size
  is unknown, the region is mapped onto the clip frame.
- **Timing:** a region's window becomes a `Sequence` relative to the clip, offset by
  `source_from_frame`. A region without a window lasts the whole clip.
- An image clip ignores blur.

### 5.3 Studio (dashboard)

- The clip inspector shows "Subtitles detected (N regions)" when a clip has regions.
  - With blur off, a single action **Blur subtitles and mute** sets `blur_enabled` and mutes the
    clip's track (`set_track_muted`, which already exists), in one patch.
  - With blur on, **Remove blur** sets `blur_enabled = false`. The track mute stays under the
    existing track control.
- The import gate shows the new roles with labels "Profile card", "Comment card @author" and
  "Slide N". It also shows the "Not placed" reason.

## 6. Mute and blur stay off until narration exists

On 2026-10-21 the operator agreed with a side note. Muting a subtitled main and blurring its
subtitles leaves the viewer with neither the speech nor the text. The legacy render was safe
because narration always replaced the original audio. Studio has no narration until roadmap
item 6 (auto-draft).

5c-1 therefore imports the regions and the mute flag as **data, switched off**:

- `blur_enabled = false` and the track unmuted;
- the inspector action from 5.3 turns both on in one step.

Item 6 turns them on automatically when it adds narration. That change belongs to item 6's spec.

## 7. Attach (`infrastructure/studio_import_repository.py`)

`_attached` places by role:

- **`main`:** as today. For an `images` main, it also sets the scene to 3.0 s × the image count
  (section 3.3). For a video main with regions, the regions are converted and stored on the clip
  with `blur_enabled = false`.
- **`footage`:** as today, plus the regions when present.
- **`slide`:** the main scene must already hold the main clip. The slide goes on
  `track_main_video` at the slot from 3.3.
- **`profile_card`:** on `track_b_roll`, at the slot and position from 3.1.
- **`comment_card`:**
  - `reaction_beat` runs over the main scene's length and every `comment_card` entry's
    `reading_seconds`, in rank order.
  - With a slot, the card goes on `track_b_roll` at that slot and position.
  - With no slot, attach is refused with `StudioImportDecisionRejected("no_room_in_reaction_beat")`.

Every overlay role is refused with `main_not_attached` while the main item is not `attached`;
the scene's length is unknown until then. The workflow importer attaches items in role order,
so the main always comes first.

The workflow importer (`application/workflow_studio_imports.py`) maps refusals as follows:

- `no_room_in_reaction_beat` → an `ExcludeImportItem` decision with the reason "Not placed: no
  room in the reaction beat", and a new outcome `not_placed`. The asset stays registered.
- `main_not_attached` → `unresolved`, so a replay of the same key retries it after the main
  succeeds.

## 8. Errors

| Condition | Result |
|---|---|
| Main not attached (its media failed) | overlay items `unresolved` (`main_not_attached`); the replay finishes them |
| A card or slide object missing in MinIO | that item `unresolved` (`media_unavailable`), as today; others unaffected |
| No room in the reaction beat | `excluded`, "Not placed: no room in the reaction beat"; asset registered |
| Blur window entirely before the trim | that region dropped |
| Asset size unknown | blur mapped onto the clip frame |
| Renderer drops `backdrop-filter` | the template release parity golden fails; no silent fallback |

## 9. Verification

All offline. Live checks wait for the final acceptance (ADR 0001).

- **Python unit:**
  - the projection: cards, slides, ordering by likes, a comment without a card staying text,
    regions and mute carried, the unsupported list shrinking;
  - `reaction_beat`: the 11 s case gives one or two cards, the 46 s case three. Also: a 155-char
    comment held at 7 s, the 0.5 s gaps, leftover time spread, and nothing placed after the
    first card that does not fit;
  - the seconds-to-frames conversion of regions, with the trim drop and clamp.
- **PostgreSQL integration** (`scripts/dev/pytest-postgres.sh`):
  - opening a workflow places the profile card and the comment cards at their slots and
    positions;
  - a fourth card ends `excluded`;
  - a subtitled main carries regions with `blur_enabled = false` and an unmuted track;
  - `main_not_attached` resolves on replay.
- **Composition (bun):**
  - the blur box under `fit` cover and contain, a crop and a position;
  - a window as a `Sequence` with the source offset;
  - blur off draws nothing.
- **Template release parity:** one new golden case with blur on, showing that the render and the
  preview match pixel for pixel.
- **Dashboard (bun):**
  - the gate shows the new labels and the "Not placed" reason;
  - the inspector's "Blur subtitles and mute" sends one patch with both operations;
  - "Remove blur" works.
- **Stack smoke:** `workflow_opens_in_studio` grows a Content Set with a profile card, two
  comment cards and a subtitled main. It asserts that the draft holds two card clips on
  `track_b_roll` and a main clip with regions and blur off.

## 10. Operator gates

Push, merge, deploy and the final live acceptance stay separate gates. On 2026-10-21 the operator
authorised the next steps of this roadmap item, but each gate is still reported as it is taken.

## 11. Follow-ups

- **5c-2:** acquisition of post cards (X, Threads, Instagram), carousel photo slides and
  creator-profile footage. These flow through the 5c-1 overlay path.
- **Roadmap item 6:** turn mute and blur on automatically when narration is added (section 6).
- A notification SFX on comment cards and entrance animations, once Studio has an SFX library
  and composition animations.
- Drawing blur regions by hand in the editor.
