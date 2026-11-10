# Style templates: Style A and Style B as data (design)

Date: 2026-11-10. Status: draft for operator approval.

| Item | Where |
|---|---|
| Roadmap | `docs/ROADMAP.md` item 6 (auto-draft), and step 1 of the "Style template track": template schema and built-in styles |
| Builds on | The effects layer (`docs/superpowers/specs/2026-11-09-studio-effects-layer-design.md`, PR #127). The narrated draft (`docs/superpowers/specs/2026-10-31-auto-draft-narrated-draft-design.md`) |
| References | Style A is IsseiNugroho, YouTube `AcmArpQ_7Tc`. Style B is WinNews, TikTok @winnews_ `7704331952681241863`. Editor readings are in `D:/thoth-tmp/research/editor-eye/*/editor-reading.md` |
| Research | This conversation, 2026-11-10: Submagic custom templates, OpusClip brand templates, Shotstack and Creatomate JSON templates, CapCut replaceable clips, Remotion schema-driven props editing, EditDuet and LAVE |

## 1. Intent

Today a draft gets one look. The import places the materials, and the effects from PR #127 can
only be set by hand. The operator wants to pick a style on an opened draft and get the whole draft
in that style, then only check it: "user tinggal mengecek kesesuaiannya".

The operator also asked why styles are hard-coded and cannot be set from the front. The answer
this design builds on is that **a style is data, not code**:

- A style is a stored, versioned template.
- Style A and Style B are the first two templates, built in.
- A later slice adds an editor that copies a template and changes its fields through a form built
  from the template's schema, the way Submagic copies a theme and Remotion builds a props editor
  from a schema.
- New kinds of effect still need code, but every combination and value of the existing ones
  becomes data.

**Success:** on one narrated `produce_video` draft, the operator does the following and judges the
result fit to check rather than to rebuild:

1. Chooses Style A, approves the new script after seeing its TTS estimate, and gets a draft that
   reads as Style A.
2. Chooses Style B on the same draft and gets a draft that reads as Style B.

## 2. Operator decisions (2026-11-10)

- **Where the style is chosen.** It is chosen on a draft that is already open in Studio. Runs and
  the import stay as they are. The style can be changed later.
- **Hand edits are replaced.** Applying a style replaces the draft's hand edits. A clear warning
  comes first.
- **A style owns the cuts, not only the look.** A style also decides how the video is cut: shot
  length, where the cuts fall, and which material shows in each shot. Applying a style rebuilds the
  draft's arrangement from its materials, so hand cuts and moves are replaced too. The operator
  confirmed this split: **cut rhythm** comes from the style now, and **content-aware cuts** come
  from the planner later. Content-aware cuts are, for example, a person's clip when their name is
  said, or a punch-in on the punchline.
- **Both styles ship now.** Style A and Style B are both in this slice. Style B uses the materials
  a run already gathers. Gathering Style B's own materials, such as a news photo of each person
  named, is a later flow.
- **Narration follows the style.** Applying a style rewrites the narration script in that style's
  voice. The voice is made again **only through a separate step** that shows the TTS cost first:
  the existing script approval with its estimate. Trying A, then B, then A again pays for voice
  only when the operator approves a script.
- **The style editor comes later.** It is the next slice. This slice builds the mechanism and the
  two built-in styles.
- **The style's script prompt can be changed in Prompt Lab now.** This gives front-end control
  over how each style speaks from day one.

## 3. What exists (checked 2026-11-10)

| Need | State |
|---|---|
| Effects | Moves, blur-fill, dim, marks, `kinetic` and `boxed` captions, and the `card` text place, all as typed edit operations (PR #127) |
| Story beats | Six beats in a fixed order: hook, main, evidence, reactions, footage, outro (`domain/narration.py` `BEAT_ORDER`). A clip's beat comes from its `source_role` (`domain/story_beats.py`) |
| Narration | Create narration. The script is written from the project's `narration_script` Prompt Lab prompt (else the starter) and waits for approval in Studio with the TTS estimate. On approval the voice is made per beat, then captions, ducking and SFX. The narration is the spine: beats are retimed to the voice. Re-voice per beat exists |
| Prompt Lab | Prompt templates per stage, bound per project, with proposals and a model catalog. The stages are `narrative_plan`, `visual_plan`, `caption_copy`, `story_assist` and `narration_script` |
| Narration preset | Per project: language, target length, words per second, voice, duck, leak, lead-in, maximum SFX cues |
| Hard-coded today | The beat order, the import's layout numbers (`domain/studio_layout.py`), the caption styles a narration writes, and the single document template `vertical_text_story` |

## 4. The style template

One schema is the single contract. A template has an id, a name, a version and an origin
(`built_in` for now). It holds three groups of fields.

**Beats.** For each of the six beats:
- whether the style uses it;
- the beat's look:
  - the move preset for its pictures: `none`, `push_in`, `pan_across`, `scroll_down` or `pull_out`;
  - background `none` or `blur_fill` for pictures that are not 9:16;
  - a dim level;
  - card emphasis: the existing highlight box and arrow;
  - the heading place: `title_top`, `title`, `title_lower` or `card`.

The six beats keep their order (see §7).

**Cuts.** Rules that need no understanding of the content:
- the longest a shot may last;
- whether cuts fall on the narration's sentence ends, taken from the voice's word timings;
- how a beat cycles through its materials (main, footage, cards, photos);
- whether a `card` line sits between facts.

Each shot takes the beat's move preset, so the picture keeps moving from shot to shot.

**Captions.** The caption style written for the narration (`boxed`, `kinetic`, or the
word-highlight style today's narration uses) and the words per caption.

**Narration.**
- the style's own script prompt, as a Prompt Lab stage for that style with its own starter;
- the target length;
- whether the script also writes a short **card line** per beat (my call: at most 6 words), which
  the style shows as a `card` text clip at the beat's start;
- the maximum SFX cues.

The voice, duck, leak and lead-in stay the project's narration preset unless the template sets them.

Templates are stored per workspace with a revision, the way Prompt Lab stores prompts. Built-in
templates are read-only rows available to every workspace. A draft records the style and template
version applied to it as an optional field, left out of the stored document when unset, so
rollbacks stay safe.

## 5. The two built-in styles

Values come from the editor readings. Exact numbers are the builder's within these shapes; every
row is my call unless §2 says otherwise.

| | Style A (IsseiNugroho, story explainer) | Style B (WinNews, kinetic-text news) |
|---|---|---|
| Hook | Heading `title_top` (the title is the thumbnail). `push_in` on the main picture | A `card` line asking the viewer's question, then the main picture dimmed. `push_in` |
| Main | The post as the frame: `pan_across` for a tall text post, `push_in` otherwise. `blur_fill` for media that is not 9:16 | The main video dimmed to about 0.45, with a slow `push_in` |
| Evidence | Cards with the highlight box and the arrow. `push_in` | Pictures dimmed. A `card` line for the narrator's reaction |
| Reactions | Comment cards. `scroll_down` for a tall card | A `card` line, then the cards dimmed |
| Footage | `blur_fill`, `push_in` | Dimmed, slow `push_in` |
| Outro | Opinion close on the main subject. `push_in` | A `card` line that returns to the hook's metaphor |
| Cuts | A shot of at most about 5 s, cut on sentence ends. A text post is read with a pan, then the beat moves to the next material | A shot of at most about 3 s, cut on sentence ends, alternating between a fact picture and a `card` line |
| Captions | `boxed`: small white subtitles on black, 3-5 words, lower middle | `kinetic`: big white words, 2-4 at a time, mid-frame |
| Card lines | None | One per beat, at most 6 words |
| Script voice (starter) | Claim, then the evidence that tests it, then the twist; casual Indonesian; Hook → Tension → Solution → Call-To-Value | Commentary in questions and reactions: the hook states a metaphor and returns in the outro; each fact is followed by the narrator's reaction |

The punch-in on the punchline word and the marks on the exact proof are **not** in this slice. They
need the planner to read the content (§8). Moves here are per beat, from the presets.

## 6. Behaviour

**Choosing a style.** Studio gains a **Style** control on a draft, showing the current style or
"None". Choosing Style A or Style B opens a confirmation. It says:
- that the draft's arrangement, its cuts and every hand edit will be replaced;
- that a new script will be written for approval;
- that the voice is made only after the approval, with its cost shown.

It does not list the edited clips. Every edit operation marks its clip `user_edited`, so after one
style every clip would be listed (my call).

**Applying a style** happens in this order:
1. **The arrangement is rebuilt and the look applied, as one edit.**
   - The beats' picture clips are removed and placed again from the draft's materials, in the
     style's order, with the template's look.
   - This is done only through the typed edit operations: remove, add from asset, and the effect
     operations.
   - It is committed as **one undo step**, so a single Undo restores the draft before the style.
   - Clips the user added outside any beat (no `source_role`) stay where they are (my call).
   - The narration, caption and SFX clips stay until a new voice replaces them.
2. **A new narration is started** with the style's script prompt. It is the existing Create
   narration or Recreate flow, and the editing lock applies while it runs.
3. **The script waits for approval** with the TTS estimate, as today. Reject with a note writes it
   again. Approving makes the voice, then:
   - the captions in the style's caption style;
   - the card lines as `card` text clips;
   - the ducking and SFX.
4. **Beats are retimed to the voice and cut by the style.** Each beat lasts as long as its voice, as
   today. Then the style's cut rules split the beat's picture into shots at the voice's sentence
   ends, cycling through its materials, each shot with its move. The cuts can only be placed here,
   because they follow the voice's timing.

**Changing style** repeats the same steps. Cancelling at the script step keeps the rebuilt
arrangement with the old narration, uncut by the new style until a voice is made. Undo restores the
draft before the style.

**Without a narration.** A draft that has none still takes the look, and the script starts as a
first narration.

**Failure and degrade.**
- A missing script provider or voice key leaves the look applied and shows why the narration
  cannot start, as the Create narration button does today.
- A beat with no clips is skipped.
- A rule that does not fit a clip is skipped and logged at `warning`. For example, `scroll_down` on
  a clip that is not tall.

## 7. Constraints

**Documents and rollback**
- Every new document field is optional and left out when unused (`exclude_if`), so a rollback
  stays safe for drafts with no style.
- New template and payload fields have defaults.
- A migration adds the template table and seeds the two built-in templates. The rollback note
  says how to roll back past it.

**Edits and spending**
- Applying the look goes only through the typed edit operations; it never writes a free-form
  timeline.
- Nothing is spent until the operator approves a script. The script call itself is metered as
  today.

**Scope of this slice**
- The six beats keep their order. Reordering beats per style is out of this slice.
- **The style's script prompt lives in Prompt Lab as one style stage whose prompt is kept per
  template (my call).** This means no new stage per style, so a copied style in the next slice
  needs no code. Each built-in template has its own starter, written fresh from its reference.
- **The model is shared with `narration_script` (my call).** The style stage uses that stage's
  model preference, so a project that can narrate today can apply a style with no new setting.
- **Templates are kept per workspace, and a prompt override per project (my call),** as Prompt
  Lab keeps prompts today. Built-in templates belong to no workspace and are read-only.

**Verification**
- Offline only: domain tests of the style-to-operations compiler for both styles, client tests of
  the Style control and the confirmation, and a narration test of the card lines with a stubbed
  model.
- Write e2e on stage1 later uses a stubbed or zero-cost path. No paid voice runs in tests.

**Logs:** `info` for a style applied, `warning` for a rule skipped, `debug` for each operation.

## 8. Goals, non-goals, anti-goals

**Goals:**
- A draft in Style A or Style B with one choice, the operator only checking it.
- Styles stored as data, with front-end control of each style's script voice through Prompt Lab.

**Non-goals in this slice:**
- the style editor (next slice);
- prompt-to-template;
- reference-video-to-template;
- the template gallery and publishing;
- Style B's own material gathering (news photos of the people named);
- the planner: content-aware cuts, such as a person's clip when their name is said, a punch-in on
  the punchline word, or a mark on the exact proof;
- reordering beats;
- music.

**Anti-goals:**
- **A style that silently spends.** Voice is never made without an approved script and its
  estimate.
- **A style that cannot be undone.**
- **A style whose result cannot be edited** with the ordinary Studio tools afterwards.
- **A style baked into code** so that changing a value needs a deploy, except for new kinds of
  effect.

## 9. Left to the builder

- The schema's field names and file layout, and the table design.
- How the Style control sits in the Studio header or Story, within the existing design.
- Exact move amounts, dim levels and caption sizes within §5.
- How "one undo step" is achieved: one batch of operations, or a snapshot.
- The cut algorithm within §4 and §5: how materials are cycled and how short a last shot may be.
- How the card lines extend the script's answer contract while old scripts stay valid.
