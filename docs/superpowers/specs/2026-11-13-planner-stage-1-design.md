# Planner stage 1: content-matched Style B cuts — design

Date: 2026-11-13. Status: draft for the operator's review.
Track: reference-faithful editing, roadmap step 2 (after loudness 5a48e3d7 and the asset library, PR #130).
Record of the conversation: `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`, items 1-40.

## 1. Intent

Style B drafts should cut like the WinNews references the operator chose:

- a new picture on every narration phrase;
- each picture shows what that phrase says;
- the camera stays still;
- each borrowed clip carries a small credit.

Today a Style B draft sits on the main video for about 79% of its length. It cuts on sentence ends and pushes in on every shot, which is the opposite of the references (item 15). The operator accepted the rule-based rhythm. They asked that the picture for each phrase be chosen by content: "gunakan opsi 2 yaitu mencocokan isi per frasa" (item 26). They also asked that the picture itself be checked, because a source's text often does not show what is meant (item 27).

The operator's taste is measured, not ruled (items 11, 15, 16). The numbers set the rhythm. Which moment fits a phrase is a content judgement, and the planner makes it.

## 2. What exists today

The narration write (`activities/narration.py`, `NarrationActivities._write`) calls the pure `narrate_document` (`assembly/narration_timeline.py`). It lays the beats on the voices' timing. When the draft has a style, it applies `style_operations` (`domain/style_apply.py`).

`style_operations` cuts each beat's visible full-frame pictures with `plan_shots` (`domain/style_cuts.py`):

- cuts fall on sentence ends from the voice's word timings, at most `max_shot_seconds` (3.0 s for Style B);
- materials are taken in turn with a forward cursor through each source;
- every shot gets the beat's look, which for Style B is `push_in` plus dim 0.45.

`style_cuts.py` already states the gap: "picking a shot for what is said is the planner's work."

Other facts the design relies on:

- **Speech and timing.** The voices carry word timings (`WordTiming`). The main video has a Whisper transcript of segments only (`TranscriptSegment`, no word times).
- **Credits.** A footage source's bare `@account` becomes a `credit` text clip at import (`application/studio_imports.py`), once per scene, not per shot.
- **Vision access.** The worker can reach OpenRouter (`THOTH_OPENROUTER_API_KEY`). ffmpeg is in the worker image.

## 3. Goals, non-goals, anti-goals

**Goals**

1. Style B beats are cut on narration phrase starts, with shots of about 0.9-2.4 s (measured median 1.4 s).
2. For each phrase, the planner picks a **base** picture, the video shots that fill the screen. It may also pick an **overlay**: one draft card (comment card or post card) shown on top of the base (operator, item 39).
3. When the main video speaks what the phrase says, that moment is the base. This is the soundbite.
4. When nothing in the draft shows the phrase, the planner says so. The phrase falls back to the main video, never to a weak forced pick.
5. Footage shots carry a credit, the source's `@account` in the credit corner, for exactly the shot's span.
6. Style B shots are still: no push-in. The dim on full-bleed footage stays.
7. The planner's result is ordinary edit operations: one revision and one undo, which the operator can rearrange in Studio.
8. A draft without the planner (no key, provider down, a refused or truncated call) still gets the phrase-start rhythm with the current cursor picking. The narration never fails because of the planner.

**Non-goals (later stages)**

- Style A's explainer collage (a separate stage).
- New footage from outside the draft: more channels per video wait for the footage library (step 3).
- Automatic placement of workspace library items (SFX, memes, backsound); the operator places them for now (item 19).
- Stressed narration (step 4).
- Face recognition. Identity comes from what is visible and said (research report, item 28).

**Anti-goals: a failure even if it technically works**

- Filling a phrase with a weak picture just to fill it, such as an empty palace for "pengunduran diri".
- A card replacing the moment the main video says the words ("penjilat nasional", item 38).
- A credit that names the wrong account, or a credit on the main video's own shots.
- A paid call that runs again on every re-render or re-voice that did not change the words.
- Picks that change on every run, so the operator cannot trust a re-run (item 40: the first pick changed in 28 of 62 phrases between two runs of the same model).

## 4. What the trial established (items 29-40)

The trial used throwaway scripts in `D:/thoth-tmp/planner-trial/`, nothing in the repository. Spend was USD 0.0911.

- **Judging must be blind.** Judgments made while the model's answer showed followed that answer both ways (item 37). The operator re-judged 62 held-out phrases and 8 earlier phrases, choosing their own shots before seeing the model's. Those blind picks are the answer key below.
- **Speech must sit on the right shot.** When a shot was given every sentence it touched, the model picked the shot one before the one the sentence fills. A sentence now belongs to a shot only when it covers at least 1 s or half the shot (item 38).
- **Price does not buy accuracy here.** With the two-layer prompt v3 (item 40):
  - the cheapest model (`qwen/qwen3.7-flash`), two runs, scored four ways, loosest first. The loose figure is an upper bound (side-agent note, operator agreed 2026-11-13):

    | Counting | Run A | Run B |
    |---|---|---|
    | Loose: any of the first 3 base shots in the answer key; picks the operator accepted after seeing them count; a pick on the main video where nothing fits counts | 77% | 77% |
    | Blind picks only as the answer key | 68% | 73% |
    | ...and only the first base shot | 60% | 66% |
    | Strict: ...and a pick on the main video where nothing fits counts as wrong | 50% | 52% |

    The loose figures are inflated in three ways. Reaction phrases often have many blind picks (median 4, up to 16; 14 of 40 phrases have 5 or more), so hitting one is easy. Picks accepted after seeing the model's answer can be anchored (item 37). And a main-video fallback is counted as fine;
  - pricier models were no better: `qwen3-vl-30b` 64% (it ignores the 3-shot cap), `gemini-3.1-flash-lite` 61%;
  - `gemma-4-26b` returned nothing.
- **Soundbite matching needs no model.** Phrase content words were matched against each main shot's speech. It fired on 13 of 62 phrases and hit the operator's pick on 12, with the same answer every time and at no cost.
- **Where the model still fails:**
  - shots of people meeting a cardboard cutout are not recognised for "bertemu langsung dengan Rocky Gerung";
  - reaction shots differ from the ones the operator picks;
  - filler lines are still forced onto a picture.
- **Cost:** about USD 0.0015 per draft on the cheapest model. Its shared provider pool answered 429 on many calls; retry with backoff recovered all of them.

## 5. Design

The planner is a new step between the voices and the style cut. It produces a **plan**: per phrase, a window, a base, an optional overlay and a reason. The deterministic assigner turns that plan into shots that `style_operations` places instead of the cursor's choice.

### 5.1 Phrases

Split each voiced beat's words (`WordTiming`) into phrases:

- cut at punctuation, or once a phrase reaches about 2.4 s;
- merge a phrase shorter than 0.9 s into its neighbour;
- a sentence-final word joins the phrase before it.

A phrase's window runs from its first word's start to the next phrase's first word. These windows replace the sentence ends as the beat's cut points for a planned beat. A beat whose phrases would make shots shorter than `min_shot_seconds` merges them.

### 5.2 Shots of the sources

For every video asset in the draft:

- cut it into shots with ffmpeg scene detection (`select='gt(scene,0.3)'`);
- merge shots under 0.8 s, and split shots over 4 s into pieces of about 3 s;
- take each shot's middle frame as its keyframe;
- for the main video, attach to each shot the transcript sentences that cover at least 1 s or half of it.

The cards (post card and comment cards in the draft) are candidates too.

The shot list depends only on the asset, so it is kept per asset checksum and reused across drafts and re-voices. The work is CPU-only and runs in the worker.

### 5.3 Soundbite pass (deterministic, no model)

For each phrase:

- compare its content words (stop words removed) with each main shot's speech;
- when the best match shares at least half the phrase's content words, the phrase's base is the matching shot or shots, earliest first;
- the model's answer for that phrase is ignored.

### 5.4 Vision pass (one paid call per draft)

One call per draft is made to the configured planner model.

**Inputs:**

- contact sheets: 3x3 grids of 384 px keyframes with a yellow shot label, one source per sheet, plus a card sheet;
- each source's role, handle and caption;
- each main shot's speech;
- the full script, then the numbered phrases.

**Rules:** the prompt is v3 from the trial. Two layers; soundbite first; small text does not count; a cutout is not the person, but people meeting it show the meeting; comment cards as overlay for netizen lines; the post card only as overlay for news-report lines; summary lines take reaction shots; quiet places and filler lines answer none.

**Output (JSON):** per phrase:

- `base` (up to 3 shot ids);
- `overlay` (at most one card id);
- `fit` (`shows` or `none`);
- `why` (one Indonesian sentence).

**Call settings:**

- temperature 0, JSON response format, `reasoning: {effort: "low"}`, and `provider.data_collection: "deny"`;
- a call that comes back truncated (`finish_reason` other than `stop`) is a failed call;
- 429, 502 and 503 answers retry with backoff;
- after the retries, a configured fallback model is tried once;
- after that the draft falls back to the rhythm-only cut (goal 8).

**Settings** (new, all with defaults):

| Setting | Default |
|---|---|
| `THOTH_PLANNER_MODEL` | `qwen/qwen3.7-flash` |
| `THOTH_PLANNER_FALLBACK_MODEL` | `google/gemini-3.1-flash-lite` (operator, 2026-11-13: in the trial it kept the 3-shot cap and added no unpicked cards; every fallback use logs a warning and the plan records the model that answered) |
| `THOTH_PLANNER_ENABLED` | on |

Cost goes through the existing metering scope of the narration write.

**Answers are kept.** The plan is stored per draft, per beat, keyed by the beat's word texts in order, not by their timing. Each stored phrase records which word indices it covers.

- A re-render, a style re-apply, or a re-voice whose words are unchanged reuses the stored picks with no new call, even if the new timing splits the phrases differently. *My call:* each new phrase takes the picks of the stored phrase that covers most of its words.
- A beat whose words changed is planned again, with one call for that beat's phrases.

### 5.5 Assigner (deterministic)

The assigner fills each phrase window:

1. **Base:** the soundbite, else the model's first base shot that is not yet used in the beat and has enough length, else its next base shot. With no usable base, the main video plays, continuing where it is at that point.
2. **A main-video base** plays the chosen moment from its own start. This is a jump cut on the main video, as the references do.
3. **A card with no base** fills the screen. With a base, it sits on top as a positioned card.
4. **No shot repeats inside a beat,** so a repeated pick falls to the model's next pick or the fallback.
5. **A shot shorter than its window** plays out and then holds its last frame. Only if it is much shorter does the next base shot follow it.
6. **Each footage shot gets a `credit` text clip** with that source's `@account` over the same frames. The main video keeps its existing single credit.

The assigner's output feeds `style_operations` as the beat's shots, in place of `plan_shots`' cursor picks. How the shots map onto tracks is in 5.7. Everything else in `style_operations` stays as it is (captions, locked or hidden clips left alone, the re-voice rule that re-cuts only untouched beats), except card lines in a planned beat, which 5.7 places.

### 5.6 Style B template revision

Style B's beat look changes from `push_in` to `none` (still camera), keeping dim 0.45. Its cut rules gain the phrase-start rhythm (0.9-2.4 s) and a `planned` flag. The template becomes revision 2.

*My call:* only the current revision of a built-in style exists in code (`BUILT_IN_STYLES`). A draft styled at revision 1 therefore takes revision 2 the next time it is narrated, re-voiced or styled. The existing re-voice rule still protects hand edits: only beats whose shots are as the last write left them are re-cut. No old-revision storage is built.

### 5.7 Layers, tracks and the draft's materials (*my calls*, from items 25 and 39)

- **Candidates are the draft's materials, not only its timeline.** They are:
  - the video assets on the timeline;
  - the footage, post card and comment card items in the draft's Materials (`ports.studio.materials`).

  The post card lives in Materials only (`studio_imports.py`), so using it adds its asset ref to the draft. Unused materials are never added.
- **The main video keeps running underneath.** On the `main_video` track it plays under hook to reactions as today (`BACKGROUND_BEATS`).
  - A soundbite (main-video base) is a jump cut on that track.
  - A footage base is a shot on the b-roll track above the main video, for its phrase window. The main video stays underneath, with its audio ducked under the narration as every movie already is (stage1, 2026-11-12).
  - This is how footage appears inside the main beats, so the main video no longer dominates (item 25).
- **The footage beat** after reactions is planned like any other beat, from all candidates. A footage clip already used earlier may be used again there only when nothing unused fits.
- **No repeats across the whole draft**, beats included, unless a phrase has nothing unused that fits. Then it falls back to the main video, not to a repeat.
- **Cards follow the phrase that names them.**
  - A card picked as an overlay is placed as a positioned card over that phrase's window.
  - In a planned beat, an unlocked comment or post card clip the import positioned is moved to the phrase that uses it. A card no phrase uses stays where it was.
  - A locked card is never moved.
- **Style B card lines never push shots** in a planned beat, because the phrase windows must stay on the voice.
  - A spoken card line (`card_at`) sits over the phrase that says it, as today.
  - An unspoken one sits on top of the window of the beat's third phrase, or its last phrase in a shorter beat, for `card_seconds`. It does not take a full-screen slot of its own.
- **Credits.**
  - In a planned beat, the unlocked per-scene credit text clips that the import made for footage sources are removed.
  - The planner places its own, one per footage shot, with a `clip_style_credit_` prefix, so a later re-plan replaces only its own.
  - The main video's `clip_credit` and any locked credit stay untouched.
- **Budget:** no budget check exists before a call today (`metering` only records usage), and none is built in this stage. A refused call (402 or any non-200) counts as a failed call.

### 5.8 Where it runs

The planner runs inside the narration write, before `style_operations`, only for drafts whose style asks for planned cuts (Style B in this stage). Shot detection and contact sheets run in the worker on CPU. The paid call runs once per draft as described.

## 6. How it is checked

**Fixtures from the trial** (recorded once, so the tests need no paid call):

- the 4 held-out drafts' shot lists, their v3 model answers, and the operator's blind picks: 62 phrases;
- the 8 re-checked phrases.

**Offline tests:**

- the phrase splitter;
- the speech-to-shot rule, including the 1 s or half-shot boundary cases from item 38;
- soundbite matching (12 of 13 on the fixtures);
- the assigner: no repeats, the fallback to the main video, card overlay versus full card, credit spans;
- the rhythm-only fallback when the call fails;
- plan reuse on a re-voice with unchanged words.

**Regression guard on the fixtures:** the recorded answers keep at least the trial's figure on the middle counting: blind picks only, first base shot, main-video fallback counted as fine. That is 60-66% today. The tests report all four countings from section 4 so none is hidden. This guards the assigner and the soundbite pass; it is not the product's target.

**The target is set on new stories, not on these fixtures.** The trial's 50-77% range comes from one story family. The operator judges the first planned drafts of new stories blind, and the accuracy target is agreed from those results.

**Final check:** one live narration on a fully new story (a paid gate), viewed by the operator, before the stage is called done.

## 7. Risks

- **Model instability:** the first pick changes between runs in about 45% of phrases. The soundbite pass, the stored plan and the deterministic assigner keep a draft stable once planned. A re-run only happens when words change.
- **Shared-pool 429s** on the cheapest model: handled by the retries and the fallback model.
- **Privacy:** keyframes of the sources go to the provider. `data_collection: deny` is set, and only frames already in the draft are sent.
- **Rule over-correction:** the trial's v2 rules taught the model to refuse too much. The v3 rules carry that lesson, and the fixtures will show it if a later prompt change brings it back.
- **The answer key comes from one story family** (Rocky, Gibran). The final check on a new story is still needed.

## 8. Left to the builder

- Where the shot index per asset is stored (a table or object storage) and its exact schema.
- The phrase splitter's exact punctuation set.
- How the plan is recorded on the draft; the requirement is only that a re-voice can find it.
- Contact sheet tile size within the trial's 384 px, as long as the fixtures still pass.

## 9. Next steps

- The operator reviews this design.
- Then an implementation plan (superpowers:writing-plans) on a new branch.
- Gates after implementation, each needing its own authorization: push, merge, deploy, and the live paid check on a new story.
- Carried forward: the narration script typo "Tobat, TG!" should read "Tobat, EGE!" (outside the planner); the footage library (step 3); stressed narration (step 4).
