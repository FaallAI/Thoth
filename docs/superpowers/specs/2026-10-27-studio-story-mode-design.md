# Studio Story mode (restyle R6, full): design

Date: 2026-10-27. Status: draft for operator approval.

| Item | Where |
|---|---|
| Design reference | `docs/DESIGN.md` §13 (Studio), approved 2026-10-25 |
| Screens | `design/exports/v2/studio-story*.png`, `studio-quick-edit*-narrow.png` |
| Parent spec | `docs/superpowers/specs/2026-10-29-dashboard-restyle-design.md` (R6; this document revises its D3) |
| Operator decision | 2026-10-27: "jalankan opsi 2" — full Story mode with the backend it needs, rather than a view-only Story mode |

## 1. Why

**What Story mode is for.** The person editing is finishing a video from a run. They think in story beats: the hook, the main clip, the evidence, the reactions, the footage, the outro. They want to change:

- which cards show, and in what order;
- where a card sits and how long it stays;
- whether a card moves or is highlighted;
- the hook text;

without the frame-level Timeline.

**What exists today.** The editor's Simple mode:

- edits one scene at a time: text, duration, captions, audio;
- has no notion of a beat;
- cannot move a card, animate it, highlight it, or swap it for another comment.

**What the parent spec decided.** Its D3 said Story mode is "a view over the draft, with no schema change". That keeps the beat strip and the materials list possible, but rules out every edit the design's inspector shows: position presets, motion, emphasis, swapping a card, Assist. Option 2 accepts the schema, operation and renderer work those need.

## 2. Revision of the parent spec

**D3 (revised).** Story mode stays a view: beats are computed from the draft, never stored. Its edits are revision-bound operations sent through the existing patch path, as before, and this document adds:

- clip fields;
- the operations that set them;
- the composition that draws them.

Every new field is optional with a default that draws exactly what is drawn today, so every existing document, revision and render is unchanged.

**D4 (unchanged).** Script mode waits for auto-draft (roadmap item 6). The mode switch shows **Story · Timeline** only.

## 3. Goals, non-goals, anti-goals

**Goals:**
- **Desktop:** the Story screen of DESIGN §13.1 and the exports. It has:
  - a Materials panel with provenance and a "why" popover;
  - the 9:16 preview with a safe-zone toggle;
  - the beat strip;
  - a beat inspector with shown cards, timing, position, motion and emphasis;
  - Assist proposals;
  - the drag, missing-material and conflict states.
- **Phone:** the quick edit of §13.5 (hook text, captions, swap a comment card), with no timeline and no reordering.
- **Parity:** every visual choice renders the same in the preview and the final video.

**Non-goals:**
- Script mode and narration (D4).
- Publishing.
- Review requests as a new event kind: "Request review" opens Review (§9).
- Who saved a conflicting revision: revisions record no author, so the conflict banner names the revision, not a person.

**Anti-goals** (failures even if everything else works):
- A card's pixels changed or a card drawn for a comment that has none (DESIGN §13.2: card pixels are evidence).
- A preview that differs from the render.
- Any existing draft rendering differently after this ships.

## 4. The beat model

**Roles.** A beat is a set of clips sharing a role group:

| Beat | Clip roles |
|---|---|
| Hook | text clips whose `source_role` is `hook` (made by "Add beat", §8) |
| Main | `main`, `main_footage`, `slide` |
| Evidence | `post_card`, `profile_card`, `profile_page` |
| Reactions | `comment_card` |
| Footage | `footage`, `creator_footage`, `creator_photo` |
| Outro | text clips whose `source_role` is `outro` (§8) |

**Where a clip's role comes from.**
- A new optional field `source_role` on every timeline clip (§5.1). The importer sets it for the clips it attaches.
- For drafts made before this, the role falls back to the clip id the importer already writes (`clip_<item_id>`) and the inventory item behind it.
- A clip with neither belongs to the beat of the scene it sits in, through that scene's main clip; else it belongs to no beat. The importer's own scene text clips (titles, quoted comments) sit on the overlay track too: they take their scene's beat, never Hook or Outro, which only `source_role` names.

**Beat order, start and length.**
- Beats are ordered by their first clip's start.
- A beat's start is its earliest clip start and its length the span to its latest clip end.
- Beats can overlap in time: reactions play over the main clip, as the importer lays them out. The strip shows order and length, not a partition of the canvas.
- Selecting a beat moves the playhead to its start (§13.4).

**Where the rule lives.** One pure TypeScript module, `story_beats.ts`, tested on its own. The server needs no copy: beats are never stored or validated server side.

## 5. Document and operations

### 5.1 New clip fields (schema v2, additions only)

| Field | On | Type | Default | Meaning |
|---|---|---|---|---|
| `source_role` | every clip | `StoryRole \| null` | `null` | The inventory role the clip came from, or `hook` / `outro` for a clip "Add beat" made. `StoryRole` is the import's `SourceRole` plus those two |
| `motion` | `video` clips | `"none" \| "slow_zoom" \| "pan"` | `"none"` | Movement across the clip's own duration |
| `emphasis` | `video` clips | `{ highlight: bool, arrow: bool }` | both `false` | A copper frame around the clip, an arrow pointing at it |

**How the fields are added:**
- Python first (`edit_document_v2.py`), then the OpenAPI contract, then the generated TypeScript types (additions only).
- No database migration: documents are JSONB.
- A document without the fields validates to the defaults.

### 5.2 New operations

Each operation is revision-bound and applied the same way in `apply_edit_operations` (Python) and `timeline_domain.ts` (TypeScript). Both sides get tests from the same cases.

| Operation | Fields | Rule |
|---|---|---|
| `set_clip_position` | `clip_id`, `position {x, y, scale}` | `video` clips only; a locked clip refuses |
| `set_clip_motion` | `clip_id`, `motion` | as above |
| `set_clip_emphasis` | `clip_id`, `highlight`, `arrow` | as above |
| `replace_clip_asset` | `clip_id`, `asset_id` | Keeps timing, fit, position, motion and emphasis. The asset must be ready and of the same kind (image for a card). `source_from_frame` resets to 0. The clip's duration is clamped to a video asset's length, and refused if that would drop below one frame. |
| `add_text_clip` | `clip_id`, `track_id`, `from_frame`, `duration_in_frames`, `heading`, `body`, `style_slot`, `source_role` (`hook` or `outro`) | Overlay track only (`track_overlay`, which every v2 draft has); inside the canvas; no scene (`scene_id` null), so it may span scenes |

**Position presets** are an editor convenience, not a document field. Top, Middle and Lower third write `y` offsets of `-0.24`, `0`, `+0.22` with the clip's current `x` and `scale`. Lower third's lower edge stays above the bottom 18 % safe area for the importer's card size.

**Existing operations** cover the rest:
- moving a card in time: `move_clip`;
- each card's length: `trim_clip_end`;
- reordering shown cards: `move_clip` on each card, swapping their starts;
- removing a card from a beat: `set_clip_hidden`;
- the hook text: `replace_text`;
- captions.

### 5.3 The composition

`packages/remotion-composition` draws the new fields for preview and render alike:

- **Motion.** `slow_zoom` scales the clip frame from 1.00 to 1.08 across its duration; `pan` translates it from −3 % to +3 % of the canvas width. Both are linear in the clip's own frame (`useCurrentFrame` inside the clip's `Sequence`) and multiply the stored position transform; neither changes a card's pixels.
- **Emphasis.** `highlight` draws a 6 px copper (`#d49a79`) outline outside the clip frame. `arrow` draws a fixed copper arrow, 120 px, pointing at the frame's top edge from above. Both sit on top of the clip.
- **Defaults** draw nothing new.

**Parity.**
- The renderer and the dashboard bundle the same package, so preview and render share the code.
- Composition tests cover each new field.
- The template parity job's golden set gains a document using each field. Approving that golden set is an operator gate, as today.
- Renderer and Thoth deploy as one package.

## 6. Materials and provenance

### 6.1 `GET /projects/{project}/studio-imports/documents/{document}/materials`

**What it returns.** Every material the draft's run collected, grouped as the panel shows them: Main, Cards, Footage, Photos, Figures, Comments (judged), Uploads. Each item carries:

| Field | Source |
|---|---|
| `item_id`, `role`, `label`, `media_kind`, `disposition`, `asset_id` | the import inventory (as today) |
| `platform`, `owner_handle`, `published_at`, `url` (host only) | the run's Content Set (`main`, `footage[]`, `photos`) |
| `engagement` (likes, views, …) | the Content Set |
| `story_score`, `shows_object`, `query` | footage and photos |
| `likes`, `author` | comments |
| `verdict` | `attribution_verdict` (main) |
| `ocr_outcome`, `trim_start_seconds` | `main.ocr` / footage OCR |
| `name`, `type`, `role` | figures (context only, no media) |
| `used_in` | the beats whose clips use the material's asset (computed client side; not returned) |

**Where the data comes from.**
- The inventory, plus the run's Content Set read through `source_workflow_id` (B9), plus the project's ready uploads.
- It is read on every call and never stored, so the import's hashed source key is untouched.

**Degrading.**
- A draft not opened from a run returns its inventory only, without provenance.
- A run whose Content Set is gone returns the same, with `provenance_available: false`.
- Comments without a card are listed as quotes and never offered as cards.

**Access.** Project-scoped, as the other import routes. No signed URL or storage location is returned; thumbnails come through the existing run card and media routes (B3, B6) when the run is the caller's.

### 6.2 `POST /projects/{project}/studio-imports/documents/{document}/materials/{item_id}/asset`

**What it does.** Returns the editor asset for one material, copying it from the run's media store on first use. It reuses the workflow importer's idempotent copy: same media, same asset.

**Why it is needed.** "Add from materials", drag and "Swap card" all need an asset for a material the import did not place. A not-placed comment card was already copied but never attached; footage left out has not been copied.

**Answers:**
- `item_not_attachable`: a material without media (a figure, a comment without a card).
- `content_set_unavailable` / `503`: as the existing workflow import routes.

### 6.3 What the "why" popover says

**Per material type:**
- **Main:** the verdict ("Original" / "Repost of @…") and the OCR outcome with its trim.
- **Footage:** the query that found it, its story score, and whether it shows the object.
- **Comment cards:** likes and author.
- **Posts and profiles:** capture time and platform.

**Missing data.** A missing value is not shown.

## 7. Assist

**Shape.** Assist is a toggle in Edit with the `purple` accent (§13.1). On, it opens the Assist panel beside the inspector.

**What it proposes.** One proposal at a time for the selected beat. v1 proposes **text** only:
- a shorter or clearer hook;
- a caption line;
- an outro credit line.

Each proposal carries a short reason (for example "31 characters instead of 56, readable in the 4-second hook at 15 chars/s").

**Backend.** `POST /projects/{project}/edit-documents/{document}/assist` takes `{ base_revision, beat, clip_ids }`. It:
- builds the prompt from the beat's text, the run's main title and description, and the reading-speed rule;
- calls the project's Prompt Lab provider and model for a new stage `story_assist` (added to `PromptStageId` with its starter), through the same provider registry and preference lookup as Prompt Lab proposals;
- returns `{ proposal_id, title, reason, operations[] }`, where `operations` are `replace_text`, `set_caption_cue_text` or `add_text_clip` against `base_revision`.

**Apply and Dismiss.** Nothing changes until Apply, which sends the operations through the normal patch, so the revision conflict rules hold. Dismiss forgets it.

**Thinking state.** Shown while the call runs. A failure says so and leaves the draft untouched.

**Where proposals live.** The proposal is not stored. The existing Prompt Lab proposal tables stay for prompt templates.

**Metering.** The call is metered with the existing usage events, as a model call of the workspace.

**Not in v1.** Proposals that pick a different evidence clip or reorder cards; the design's "looking for a stronger evidence clip" waits for v2.

## 8. Hook, Outro and "Add beat"

**What "Add beat" offers.** Hook (when the draft has none) and Outro (when it has none). Hook and Outro are text clips on the overlay track made with `add_text_clip`:
- **Hook:** at frame 0, for 4 s, text from the run's title.
- **Outro:** ending at the canvas end, for 4 s. Its text is the credit line "Video: @<owner> · <platform>" (DESIGN §13.2: on by default, placement editable) when the run's verdict names an owner, else empty for the person to write.

**What it does not do.** Neither changes the canvas length; both sit over existing clips, as overlays do. The Main, Evidence, Reactions and Footage beats are never added or removed as wholes: their materials are.

## 9. The screens

**Top bar.** Today's (task 6b) gains:
- the mode switch **Story · Timeline** (Simple → Story, Advanced → Timeline; the stored modes keep their names);
- Undo and Redo as icons;
- the Assist toggle;
- "Request review". It switches to Review with the comment box focused; review requests as events are out of scope.

**Materials panel (left, desktop).**
- Groups with counts, collapsible: Main, Cards, Footage, Photos, Figures, Comments (judged), Uploads.
- Each item shows its thumbnail, title, provenance line (platform · @owner · kind · length or score), "Used in <beat>" chips, and an ⓘ "why" popover.
- "Show n more" pages long groups.
- Search filters by text.

**Preview (centre).**
- The canvas label (`9:16 · 1080 × 1920`).
- A **Safe zone** toggle that overlays the platform's unsafe areas: top 10 % and bottom 18 % for TikTok, from the style preset's target platform when known, else TikTok.
- The shared player.

**Beat strip (bottom).**
- One tile per beat: name, length, thumbnails of its first clips.
- The selected tile is outlined in copper.
- A beat with a missing material shows a red dot.
- The total length is on the left; "Add beat" is on the right.

**Beat inspector (right), for the selected beat.**
1. **Header.** Name and "Beat n of m · length · n materials", with "· 1 missing" when one is missing.
2. **Missing material.** An alert naming the unresolved inventory item and its reason. Its actions are a fitting alternative (for example "Use profile card" when the profile page is missing and the profile card exists) and "Remove from beat" (an exclude decision, as the import gate does).
3. **Shown cards / materials.** The beat's clips in time order, each with:
   - a thumbnail and label;
   - ↑ ↓ to swap start times with the neighbour (`move_clip`);
   - remove (`set_clip_hidden`).

   "Add from materials" opens a picker of materials not yet shown in this beat. Picking one gets its asset (§6.2) and places it after the last clip of the beat (`add_clip_from_asset`, with the card size and position the importer uses).
4. **Timing.** For a beat of cards (Reactions, Evidence), "Each card" in seconds (`trim_clip_end` on each card), with the reading-speed check "Reading speed 15 chars/s · longest card needs n s". For Hook and Outro, the text clip's length. For Main and Footage, the length is shown read-only: it follows the video, and Timeline trims it.
5. **Position.** Top · Middle · Lower third (§5.2), with the safe-zone note.
6. **Motion.** None · Slow zoom · Pan.
7. **Emphasis.** Highlight box and Arrow switches.

Sections 5 to 7 apply to every card clip of the beat at once. A beat without card clips hides them.

**States.**
- **Drag.** A material dragged from the panel onto a beat tile adds it to that beat. The tile shows a dashed copper outline, and the material shows "+ Add to <beat>".
- **Missing material.** Point 2 of the inspector, plus the red dot on the tile.
- **Conflict.** Today's banner, restyled: "A newer revision n was saved · your changes are kept on this device", with Keep editing locally and Reload latest.
- **Assist.** §7.

**Phone (quick edit, §13.5).** Header "Quick edit · Rev n", the preview, and three rows:
- Hook text (`replace_text`);
- Captions (the existing caption editor);
- Swap comment card: a bottom sheet listing the run's comment cards with avatar, handle, text and likes, the one in use marked. "Swap card" uses `replace_clip_asset` after §6.2.

The note "Beats and timeline editing need a larger screen" closes the screen. No reordering, no timeline, no render start.

**Language.** Every new string is in the English and Indonesian catalogue, as in part A.

## 10. Phases

One branch, `feat/dashboard-restyle-studio`, continuing part B. Each phase is test first and committed per task.

| Phase | What | Verification |
|---|---|---|
| S1 | Document fields and the five operations, Python and TypeScript; contract regenerated (additions only); the importer writes `source_role` | Python suite, `make test-postgres`, lint; dashboard tests and build; shared operation cases on both sides |
| S2 | Composition draws motion and emphasis; golden documents for the parity job | composition tests; renderer tests; parity job locally (golden approval is the operator's) |
| S3 | Materials route and material asset route | API tests on SQLite and Postgres |
| S4 | Story screen: mode rename, Materials panel, preview safe zone, beat strip, beat inspector, drag, missing material, conflict | dashboard behaviour tests, both languages; screens at 1440 and 1024 against the exports |
| S5 | Assist route and panel | API tests with a fake provider; dashboard tests |
| S6 | Add beat (Hook, Outro), phone quick edit and swap sheet | dashboard tests; screens at 430 |

R7 (Timeline restyle and clean-up) follows, then part B's release.

## 11. Gates

**Within the operator's earlier approvals.** Push, PR, merge and deploy are each the operator's. Renderer and Thoth deploy as one package (S2 changes the composition).

**New gates:**
- The parity golden set for the new fields.
- A live check of Assist against the real provider, after deploy (the offline rule holds until then).

## 12. Left to the builder

- Exact component split and file names.
- Thumbnail sizes and paging size in the Materials panel.
- The arrow's exact shape within the composition: one fixed SVG, copper, no text.
- The Assist prompt wording, in English, stored with the other prompt starters.

## 13. My calls (for the operator to check while reading)

1. **Beats are computed, not stored** (`source_role` plus the clip-id fallback). Storing beats would mean keeping them in step with every operation.
2. **Hook/Outro and cards:** Hook and Outro are text clips; Evidence holds the post card, profile card and profile page. The export lists the post and profile under "Hook". I follow the parent spec's table, because the importer places the post card as evidence over the main clip.
3. **Position presets** are fixed `y` values, not a stored preset name.
4. **Motion and emphasis values:** zoom 1.00 → 1.08, pan ±3 %, a 6 px copper outline, a 120 px arrow.
5. **Assist v1 proposes text only,** one proposal at a time, not stored.
6. **"Request review" opens Review;** no review-request event.
7. **The conflict banner names the revision, not who saved it,** because revisions record no author.
