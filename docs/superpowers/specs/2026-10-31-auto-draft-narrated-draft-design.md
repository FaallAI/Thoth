# Auto-draft, first milestone: the narrated draft (design)

Date: 2026-10-31. Status: draft for operator approval.

| Item | Where |
|---|---|
| Roadmap | `docs/ROADMAP.md` item 6 (auto-draft); this milestone merges slices 1-4 |
| Prior research | `docs/research/2026-10-18-auto-video-engine-python-research.md` (re-checked 2026-10-31, section 2 below) |
| Studio design | `docs/DESIGN.md` §13.1 (Script mode), §13.3 (Re-voice), §13.4 (render readiness) |
| Later work this must not block | "Style template track" in `docs/ROADMAP.md` |

## 1. Intent

A `produce_video` run today ends in a Studio draft that is visual only: the main video, the post,
profile and comment cards, and footage, placed automatically by the Studio import (Stage 5c).
There is no narration. The retired Rust engine used to write a narration script, voice it, sync
subtitles and duck the source audio, but every part of that was hard-coded (prompt, model,
length, voice, ducking levels) and could not be inspected or corrected before the render.

This milestone brings narration back as **one watchable result**: a run's draft gains a narrator,
word-timed captions, ducking and sound effects, and renders to a narrated video. The operator's
words: "seperti yang dilakukan rust sebelumnya tapi kita lebih improve ... sebelumnya full
dipegang rust yang tidak bisa kita control (hardcode) tapi sekarang kita bisa control".

**Success:** one `produce_video` run with a TikTok main, opened in Studio, produces a script the
operator approves in Studio after seeing its TTS cost estimate; the draft then gains voice,
captions, ducking and SFX without further input, and renders to a narrated 9:16 video. Every
value the Rust engine hard-coded is a visible, changeable setting.

## 2. What exists (re-checked 2026-10-31)

| Need | State |
|---|---|
| Transcript | `attribution/adapters/speech.py` runs faster-whisper (CPU `int8`, model baked into the image) on the first 180 s, segment-level only, not stored, used only for reaction attribution |
| LLM calls with an editable prompt | Prompt Lab stages (`domain/prompts.py`): `narrative_plan` (Indonesian starter), `visual_plan`, `caption_copy`, `story_assist`. Story Assist runs as a short workflow on the prompt-proposal queue through the stage1 OpenRouter catalog |
| Voice | `voice/` port with `elevenlabs` (word timings) and `openai_compatible` adapters; used only by `thoth-control voice say` |
| Draft | Studio document v2 with `narration`, `caption`, `sfx`, `main_video` tracks, caption cues, audio volume and fades. Caption styles: `caption_default`, `source` |
| Placement | The workflow-to-Studio import (`application/workflow_studio_imports.py`) projects the Content Set and places every material |
| Approvals, notifications | The workflow's source approval (`wait_condition` on a decision), the inbox and run tray (run progress phase 4) |
| Cost | `metering.py` records `character` units; `estimate()` prices them when a price exists (prices are unset until billing go-live) |
| SFX | 21 files in `assets/sfx` with labels in `assets/ASSET_CATALOG.md` / `asset_catalog.json` (category, intensity, beats, trigger moments, description) |

Missing: the narrated-draft orchestration, the script approval in Studio, Script mode, word-
highlight captions, volume keyframes for ducking, and SFX in the media store.

## 3. Operator decisions (2026-10-31)

1. **First milestone is a watchable narrated draft**, built on the existing Studio import, not a
   transcript-only slice and not a new timeline planner.
2. **Nothing hard-coded:** prompt, model, target length, language, voice, ducking and lead-in are
   settings with the Rust values as defaults.
3. **The script is approved before any voice is made**, so no TTS spend is wasted on a script
   that will be replaced.
4. **The approval happens in Studio**, with the draft visible, and shows a **TTS cost estimate**.
5. **No editing at the approval.** Approve, or reject. Editing opens once every component is made.
6. **Voice: ElevenLabs**, as in Rust. The key in the old root `.env` moves into the stage1
   provider file at deploy, under its own operator gate.
7. **SFX are in; background music is out.** The bundled SFX may be used by everyone (operator:
   open-source or widely used clips).
8. **The SFX live in MinIO/S3** and appear in Studio's asset library with their labels.
9. **Uploaded SFX are later work** (see section 9).
10. **Narration starts only when the operator presses "Create narration"** on a draft, never on
    import, so a draft that is never narrated spends no transcription or LLM tokens.

## 4. Flow

```text
produce_video run (exists) -> operator opens it in Studio (exists: import + placement)
  -> the operator presses "Create narration" on that draft      <- nothing is spent before this
       1. transcribe the main video (word timings, whole video)
       2. write the script + SFX cues (LLM, Prompt Lab stage, Content Set + transcript facts)
       3. wait: "Script awaiting approval" in Studio, with the TTS estimate     <- no TTS spend yet
            reject (optional note) -> back to 2
            approve -> continue
       4. synthesize the voice per beat (ElevenLabs, word timings)
       5. write into the draft: narration clips, word-highlight caption cues, ducking keyframes
          on the main video's audio, SFX clips
  -> Studio unlocks editing: Script mode (edit a line -> that beat is "voice out of date" ->
     re-voice that beat only), Story and Timeline as today -> Review -> Render
```

Each numbered step is a retryable activity whose output is stored, so a failure resumes at that
step. A cancelled or rejected narration spends no TTS.

## 5. Behaviour

- **Script.** One paragraph per Story beat (Hook, Main, Evidence, Reactions, Footage, Outro), in
  the preset's language, sized to the preset's target length at about 3 words per second. It
  uses only facts present in the Content Set, the attribution verdict and the transcript; it
  never invents a name, number or quote (same rule as Story Assist). Figures appear as name
  tokens.
- **SFX cues.** The same LLM call proposes at most N cues (preset field), each naming a catalog
  SFX and the beat moment it marks (`comment_appear`, `emphasis_word`, ...), chosen from the
  catalog labels. They show on the approval screen with the script.
- **Approval screen (Script mode, read-only).** The script by beat beside the 9:16 preview, the
  SFX cues, and the estimate: characters, provider, voice, and a price when one is set
  (otherwise "unpriced", as `estimate()` reports). Approve, or Reject with an optional note.
- **Voice.** One synthesis per beat, so a later re-voice replaces one beat. Word timings come from
  ElevenLabs.
- **Captions.** Word-timed cues on the `caption` track, rendered with a new word-highlight style
  (`@remotion/captions` `createTikTokStyleCaptions` pages, the active word highlighted).
- **Ducking.** The main video's audio follows a volume curve: lead-in at full level, the duck
  level under speech, the leak level in pauses.
- **After completion.** Script mode becomes editable: changing a beat's text marks it out of date;
  "Re-voice" synthesizes that beat and updates its captions and the ducking around it, with the
  §13.3 progress steps. Re-voice needs no new approval (the operator's own action) but is metered.
- **Editing lock.** While narration runs, the draft shows its progress and is not editable;
  this keeps the narration's writes from conflicting with edits.
- **The narration is the spine (my call, as in Rust).** Each beat lasts as long as its voice plus
  the lead-in; the imported visuals of that beat are retimed to fit (a card holds, a footage clip
  is trimmed or held). The beats keep the order and the materials the import chose.
- **A rejection has no retry limit (my call);** each new script is metered like the first.
- **The button** shows on a draft opened from a `produce_video` run with no narration yet,
  including drafts imported before this milestone; it is unavailable while a narration runs or
  waits, and shows why when the voice key or prompt provider is missing.

## 6. Settings (the narration preset) and defaults

| Setting | Default (from the Rust `config.toml`) |
|---|---|
| Script prompt | A new Prompt Lab stage for the narration script; its starter is written fresh, structured Hook -> Tension -> Solution -> Call-To-Value |
| Script model | The Prompt Lab catalog's model for that stage |
| Language | `id` |
| Target length | 45 s (about 3 words per second) |
| Voice | ElevenLabs `plgKUYgnlZ1DCNh54DwJ`, model `eleven_multilingual_v2` |
| Duck level / leak level / lead-in | 0.12 / 0.45 / 1.6 s |
| Maximum SFX cues | 3 (my call) |

The preset is per project and shaped so the style template schema can absorb it later. Values
changed on one draft (a clip's volume, a beat's text) stay on that draft.

## 7. Constraints

- Every new document field is optional with a default that renders exactly what renders today;
  existing documents, revisions and renders are unchanged (as the Story mode spec required).
- Secrets: the ElevenLabs key stays in the worker's provider file; never printed, logged or put in
  a document, event or report.
- Metering: transcription seconds, LLM tokens and TTS characters are recorded per workspace.
- Degrades gracefully: without a voice key or prompt provider the draft stays as today, with the
  reason shown; the visual draft is never lost.
- Workspace isolation as everywhere: a draft's narration is visible only in its workspace.
- The render stays Remotion; no ffmpeg pre-mix (ducking is in the composition).

## 8. Goals, non-goals, anti-goals

- **Goals:** sections 4-6 for `produce_video` drafts.
- **Non-goals (later):** background music; uploaded or shared SFX; style templates; other modes
  (clip, news, reaction, montage); 16:9 reframe; AI cover and hook-title images; editing the
  script at the approval.
- **Anti-goals:** spending TTS before approval; a narration that states something the evidence
  does not support; a narration run that breaks or replaces the operator's visual draft.

## 9. Later work recorded in the roadmap

The operator decided on 2026-10-31 that uploaded SFX follow the template model: an upload is
private to its workspace; the operator reviews it; the uploader is notified and must approve
publishing; then it is available to every workspace with the uploader credited. This joins the
style template gallery as one shared gallery for templates and assets.

## 10. Left to the builder

- Whether narration runs as its own workflow per draft or as a phase of an existing one, provided
  approvals, cancellation, retries and the run tray behave as section 4 says.
- Where the script and SFX cues are stored before approval and how Studio reads them.
- The volume-keyframe and word-cue schema shape, the caption style name, and how the composition
  draws them.
- The transcription model size (measure `medium` and `large-v3-turbo` on a 60 s clip on the
  worker's CPU first) and whether the attribution transcriber is shared.
- How the 21 SFX reach MinIO (a seed command or a migration) and how their labels are stored.
- How a rejected script's note reaches the prompt.
