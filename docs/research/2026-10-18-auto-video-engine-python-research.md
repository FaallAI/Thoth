# Automatic Video Engine in the Python Control Plane (Research)

**Date:** 2026-10-18
**Question:** can the Rust engine's automatic video production move into the Python control
plane, how should its flow look, and which open-source tools help?
**Operator direction (2026-10-18):** move it into the Python control plane only; optimize the
flow; prefer open-source support.

**Answer:** yes, and most of the platform it needs already exists.

The new path already has three of the pieces:

- the Temporal workflow, which already declares the `narration`, `render`, `review` and
  `delivery` stages;
- the Studio document v2, which already has `narration`, `music`, `sfx` and `caption` tracks,
  caption cues, and video crop;
- the Remotion renderer.

What is missing is one new workflow phase, **auto-draft**. It turns a Content Set into a
complete, pre-resolved Studio draft: transcript, script, voice, caption timing, and clip plan.
Remotion then renders the draft, so the Rust engine and its Windows-and-CUDA dependency can
retire.

The one new dependency is a TTS adapter. Transcription reuses `faster-whisper`, which is
already in the worker image.

## 1. What the Rust engine does today

| Capability | Rust module (lines) | Notes |
|---|---|---|
| Transcription | `transcribe` (1.4k) | whisper.cpp `large-v3`, CUDA, `language = "id"` |
| Moment selection | `analyze` (6.6k) | LLM over the transcript; trend and vision helpers |
| Narration script | `narration` (1.1k) | LLM `deepseek/deepseek-v3.1`, ~45 s target, structure RAG from Supabase |
| Voice | `reaction/tts.rs` | ElevenLabs (configured), MiniMax, Fish Audio, OpenAI, Edge |
| Audio mix | `narration/timeline.rs`, `edit` | source ducked to 0.12 under the narrator, 0.45 in pauses, 1.6 s lead-in |
| Edit and render | `edit` (13.6k), `gpu` (1.4k) | ffmpeg filter graphs: cut, reframe, subtitles, hook title, cover, profile card, comment cards, callouts, SFX, BGM, transitions, color grading, NVENC |
| Modes | `news` (1.5k), `reaction` (1.1k), `main_footage` (4.9k), montage | news formatter, reaction avatar, forced main footage, intercut montage |
| Jobs, projects, profiles | `thoth-jobs`, `thoth-server` | SQLite queue, the Legacy Console's backend |

The whole engine is about 56k lines and has not changed since 2026-09-21. It runs natively on
Windows with CUDA, outside the containers the rest of the stack uses.

## 2. What the Python control plane already has

- **Orchestration:** the Temporal workflow `SourceInvestigationWorkflow` already runs source →
  attribution → content assembly → footage. `StageSummary` already allows the `narration`,
  `render`, `review` and `delivery` stages.
- **Transcription:** `faster-whisper` runs in the worker on CPU with `int8`
  (`attribution/adapters/speech.py`), with the model baked into the image. `sherpa-onnx` is
  installed too.
- **LLM access:** `agno` and `openai` clients, with OpenRouter keys in the worker's provider
  file (attribution and assembly already call vision and LLM models).
- **Storage:** `MediaStore` (MinIO) with `copy`, ranged reads, and editor assets.
- **Document:** Studio document v2:
  - tracks `main_video`, `b_roll`, `overlay`, `caption`, `narration`, `music` and `sfx`;
  - video clips with `crop`, `position` and `source_from_frame`;
  - audio clips with `volume` and fades;
  - caption clips with frame cues;
  - overlay presets.
- **Review and render:** Studio review with approve and request-changes; Remotion render through
  the control plane.

## 3. Target flow

```text
URL or discovery candidate
  -> acquire -> attribute -> assemble Content Set -> footage          (exists)
  -> enrich (Stage 6)                                                  (planned)
  -> auto-draft                                                        (new)
       1. transcribe the main video (word timings)
       2. write the script (LLM; Content Set + transcript + enrichment + preset)
       3. synthesize the voice (TTS adapter)
       4. time the captions (TTS timestamps, or align the voice)
       5. plan the timeline (main segments, b-roll under narration, cards, music, ducking)
       6. write a pre-resolved Studio document v2 (assets already in the store)
  -> review gate (optional, the existing approval)                     (exists)
  -> Remotion render -> delivery                                       (exists)
```

How it improves on the Rust flow:

- **One editable document instead of an ffmpeg filter graph.** The operator can fix any
  line, clip or cue in Studio before the render, and re-render without re-running the pipeline.
- **Every step is a retryable Temporal activity** with its artifact in MinIO. A crash resumes at
  the failed step, not at the start.
- **No Windows host, CUDA, or NVENC are required.** The same containers run on any host, as the
  move to object storage intended.
- **New projects work everywhere.** Projects, presets and jobs live in one control plane, so
  the issue that a project new in the control plane is unknown to Rust disappears.

## 4. Tool choices

| Need | Choice | License | Why | Rejected, and why |
|---|---|---|---|---|
| Transcription with word timings | [faster-whisper](https://pypi.org/project/faster-whisper/), already installed | MIT | Runs today in the worker on CPU `int8`; `word_timestamps=True`. CTranslate2 is about 4x faster than reference Whisper on CPU, within ~0.5% WER at `int8` | whisper.cpp through Rust (Windows and CUDA) |
| Alignment, only if faster-whisper's word timings fall short | [WhisperX](https://github.com/m-bain/whisperX) | BSD-2 | wav2vec2 forced alignment on top of faster-whisper. Indonesian alignment support must be verified first | — |
| Voice, production | ElevenLabs (the current Rust setting), with MiniMax, Fish Audio and OpenAI behind one adapter | commercial APIs | Best Indonesian quality available today. Keeps the operator's voices | — |
| ~~Voice, free fallback~~ | ~~[edge-tts](https://pypi.org/project/edge-tts/)~~ | LGPL-3.0 client of an unofficial service | **Excluded by the operator (2026-10-18)** | No SLA; IP rate limits answer 403; can stop without notice |
| Voice, self-hosted on CPU (candidate) | [Supertonic-3](https://huggingface.co/Supertone/supertonic-3) (Supertone) | SDK MIT, weights OpenRAIL-M (use restrictions, commercial use allowed) | ~99M-parameter ONNX, CPU-only by design, 31 languages including Indonesian, 44.1 kHz, 7 preset voices. Fits the CPU worker; needs an Indonesian listening test | — |
| Voice, any OpenAI-compatible server | One `openai_compatible` adapter (`/v1/audio/speech`) | — | Covers [VoiceStudio](https://github.com/debpalash/VoiceStudio) (section 4a) and other self-hosted servers with no new code per engine | — |
| Voice, self-hosted (later, GPU) | [grandhigh/Chatterbox-TTS-Indonesian](https://huggingface.co/grandhigh/Chatterbox-TTS-Indonesian) | Apache-2.0 | Indonesian fine-tune of Chatterbox with voice cloning. Quality not yet measured | [MMS-TTS ind](https://huggingface.co/facebook/mms-tts-ind): CC-BY-NC 4.0, 16 kHz. [Chatterbox Multilingual v3](https://www.resemble.ai/resources/chatterbox-multilingual-v3-tts-with-embedded-watermarking-for-25-languages): no Indonesian among its 25 languages. CosyVoice 3: no Indonesian. F5-TTS Indonesian fine-tunes: base weights' license to be checked before any use |
| Caption pages and active-word highlight | `@remotion/captions` `createTikTokStyleCaptions` | Remotion license (already in use) | Pages and word tokens straight from timed words; runs in the renderer | Burned-in ffmpeg subtitles |
| Ducking | Remotion `volume` as a function of the frame | same | Exact ducking per frame inside the composition | Pre-mixing audio with ffmpeg (no longer editable) |
| Reframe 16:9 to 9:16 | [PySceneDetect](https://www.pypi.org/project/scenedetect/) shots + MediaPipe face boxes → one crop per shot | BSD-3 / Apache-2.0 | Per-shot static crops fit `TimelineVideoClip.crop` without a new schema | Frame-by-frame tracking (needs keyframed crops; later if needed) |
| Moment selection (clip mode) | The LLM over the word-timed transcript (port the Rust prompts) | — | Same method as Rust; providers already wired | — |

**Projects used as design references, not dependencies:**
- [MoneyPrinterTurbo](https://www.sourcepulse.org/projects/1843149) (MIT): topic → script →
  TTS → subtitles → clips → MoviePy render;
- [AutoClip](https://github.com/artbyjazi/autoclip): WhisperX diarization, LLM moment
  selection, speaker-tracking reframe, animated captions;
- [Clips AI](https://contentcreators.com/tools/clips-ai): MediaPipe- and MTCNN-based 9:16
  resizing.

**Not ported:** the wgpu color grading and the 21 GPU transitions. Studio users have not asked
for them. Remotion CSS filters, or a LUT, can come back later if they are missed.

## 4a. VoiceStudio (debpalash/VoiceStudio), reviewed 2026-10-18

The operator asked for this project to be reviewed. Its code was read from a shallow clone
(v0.5.6+, commit of 2026-10-17); nothing was run.

**What it is:** a complete voice product, not a library. It is an Electron desktop and web app
over a FastAPI backend: about 3,300 files and 275k lines of Python. Its features are cloning,
voice design, dubbing, transcription (WhisperX by default), dictation, and audiobooks, with
17 TTS engines and 10 ASR engines.

| Aspect | Finding |
|---|---|
| Activity | 72.8k stars; release v0.5.6 (2026-09-23); last push 2026-10-17; 208 open issues. One maintainer wrote ~3,375 of ~3,700 commits |
| Licence | Application **AGPL-3.0-only**, under a CLA to Yupcha Softwares. A paid commercial licence and "Pro" features exist (open core). Modifying it and offering it over a network obliges publishing the modified source |
| Default model | k2-fsa/OmniVoice: 646 languages, 6,328 h of Indonesian. Its **weights are CC-BY-NC**, so they cannot voice a monetized channel |
| Indonesian engines with permissive weights | **Supertonic-3**: OpenRAIL-M, CPU ONNX, 99M. **Confucius4-TTS**: Apache-2.0, cloning, CPU ~17x realtime, GPU recommended. **MOSS-TTS-v1.5**: Apache-2.0, 8B, ~16 GB GPU |
| Licence hygiene | Its own registry (`backend/config/model_licenses.json`) marks no model as commercially cleared |
| Integration surface | OpenAI-compatible `POST /v1/audio/speech` (the engine is chosen by `model`), and `POST /v1/audio/transcriptions` with word timestamps. Documented "production private API" pattern: a pinned Docker image, `OMNIVOICE_API_KEY` bearer, loopback or internal network only. Images are `linux/amd64`, CUDA or ROCm; ~2.4 GB of weights download on first run; analytics are opt-in (`OMNIVOICE_ANALYTICS_DISABLED=1`) |

**Verdict:**

- **Do not vendor or embed its code.** The AGPL copyleft and a 275k-line surface would come
  into Thoth for one feature.
- **Running it unmodified as a separate internal service is acceptable.** Thoth would call it
  over the OpenAI-compatible endpoint. That is the right way to get GPU engines (Confucius4,
  MOSS) and voice cloning once a GPU host exists.
- **On today's CPU-only workers, its only practical Indonesian engine is Supertonic-3.**
  Supertonic-3 can also run directly from its MIT SDK, without the 2+ GB application.
- **Never select its default OmniVoice weights for published videos** (CC-BY-NC).

**Effect on the plan:** the TTS adapter has two implementations from slice 2 on:

1. `elevenlabs`, the primary, with timestamps;
2. `openai_compatible`, which serves VoiceStudio or any compatible server, chosen per preset.

**Operator decision (2026-10-18): edge-tts is excluded, even as a fallback.** It is an unofficial
service with no SLA that blocks IPs with 403, so narration could fail all at once. Before
Supertonic-3 or a VoiceStudio engine becomes a default, the operator runs a listening test.

### Listening test, first pass (2026-10-18)

**Method:** one Indonesian script of 57 words, with numbers ("30 detik", "2,5 juta"). Each
sample was transcribed back with faster-whisper `medium` (CPU, `int8`) and scored by word error
rate (WER) against the script. Every sample also lost one word to a scoring artifact: the
script's "dua hari" comes back as "2 hari". The adjusted column removes it.

| Sample | Audio | Synthesis time | WER | WER, adjusted | Notes |
|---|---|---|---|---|---|
| ElevenLabs `plgKUYgnlZ1DCNh54DwJ`, `eleven_multilingual_v2` | 21.8 s | 6.6 s (API) | 1.8% | 0% | 363 character timings |
| edge-tts `id-ID-GadisNeural` | 27.9 s | 7.8 s | 1.8% | 0% | 51 word boundaries |
| edge-tts `id-ID-ArdiNeural` | 21.1 s | 6.4 s | 5.3% | ~3.5% | "trik kamera" heard as "trika merah" |
| Supertonic-3 `M1` (CPU) | 28.0 s | 13.5 s, RTF 0.48; first load 89 s including a ~400 MB download | 10.5% | ~8.8% | numbers misread: "30" → "32", "2,5" → "2,1" |
| Supertonic-3 `F3` (CPU) | 28.7 s | 13.8 s, RTF 0.48 | 12.3% | ~10.5% | "heboh" → "hebo"; "kali" dropped |

**Reading:**
- ElevenLabs and edge-tts Gadis are intelligible word for word.
- Supertonic-3 runs faster than real time on CPU, but it mispronounces digits. If it is used,
  the script step must spell numbers out in words.
- Naturalness and pacing are for the operator's ears.

Samples: `D:/thoth-tmp/voice-samples/` (operator copy, not in the repository).

## 5. Schema and composition gaps

| Gap | Change |
|---|---|
| Ducking needs a volume curve | Studio document v2 audio clips gain `volume_keyframes` (frame, volume). The composition interpolates them in the `volume` callback |
| Word-highlight captions | A caption style slot that renders `createTikTokStyleCaptions` pages. The caption cues carry word timing |
| Cards (hook title, cover, profile, comment, callout) | Overlay components fed by the real crops that Stage 5c produces. Never a synthetic card (standing operator decision) |
| Still images on the timeline | An image clip kind; `AssetKind` already has `image` |

Each is a schema change in `edit_document_v2.py`, the shared Remotion composition, and the
regenerated types.

## 6. Rust Profiles become auto-draft presets

The Rust profile fields map onto a control-plane preset that each project selects:

| Rust profile field | Preset field |
|---|---|
| narration enabled | narration enabled |
| language | language |
| `target_secs` | target length |
| model | model |
| — | voice provider and voice |
| `visual_edit.layout`, `clip_style` | Studio template and caption style |
| music and SFX | music and SFX |

This is the "Rust Profiles" item of `docs/ROADMAP.md`. It lands with the first auto-draft
slice, so a preset has a consumer from day one.

## 7. Interim limit (until auto-draft ships)

After the UI foundation moves projects into the control plane, the Legacy Console and Profiles
only recognize projects that also exist in Rust. Today that is the imported project "test". An
automatic video needed before auto-draft ships is run in "test".

## 8. Implementation slices

Each slice is its own spec, plan and PR.

1. **Transcript:** a workflow activity transcribes the main video with the existing
   faster-whisper and writes `transcript.json` (words with times) as a report.
2. **Voice:** a TTS adapter with two implementations (`elevenlabs` with timestamps, and `openai_compatible` for VoiceStudio or another self-hosted server; edge-tts is excluded) and a
   `voice` media artifact. Provider keys stay in the worker's provider file.
3. **Script and presets:** the LLM script from the Content Set, transcript and preset. This
   includes the Rust Profiles → presets item.
4. **Draft:**
   - the timeline planner writes a pre-resolved Studio document v2;
   - the composition gains volume keyframes and the word-highlight caption style.
   This builds on UI phase 2 (the Content Set to Studio asset copy).
5. **Reframe:** per-shot crops for 16:9 sources.
6. **Other modes:** clip mode, news, reaction, montage, in the order the operator uses them.
   Then the Legacy Console and the Rust engine retire (Stage 10).

## 9. Risks

| Risk | Detail |
|---|---|
| CPU transcription time | The worker uses CPU `int8`. Measure `medium` and `large-v3-turbo` on a 60 s clip before choosing. A GPU worker is optional later |
| Render time | Remotion renders through headless Chrome and ffmpeg on CPU, slower than NVENC. Renderer concurrency is the lever |
| TTS cost and quotas | Commercial APIs bill per character. edge-tts may refuse with 403 under load |
| Licenses | Every self-hosted voice model's weight license is checked before use. Remotion's company license terms already apply to the existing renderer |

## Sources

- [faster-whisper on PyPI](https://pypi.org/project/faster-whisper/)
- [Whisper variants comparison (Towards AI)](https://pub.towardsai.net/whisper-variants-comparison-what-are-their-features-and-how-to-implement-them-c3eb07b6eb95)
- [Chatterbox Multilingual v3 (Resemble AI)](https://www.resemble.ai/resources/chatterbox-multilingual-v3-tts-with-embedded-watermarking-for-25-languages)
- [grandhigh/Chatterbox-TTS-Indonesian](https://huggingface.co/grandhigh/Chatterbox-TTS-Indonesian)
- [facebook/mms-tts-ind](https://huggingface.co/facebook/mms-tts-ind)
- [CosyVoice](https://github.com/QwenAudio/CosyVoice)
- [edge-tts on PyPI](https://pypi.python.org/pypi/edge-tts)
- [MoneyPrinterTurbo overview](https://www.sourcepulse.org/projects/1843149)
- [AutoClip](https://github.com/artbyjazi/autoclip)
- [VoiceStudio](https://github.com/debpalash/VoiceStudio): README, `LICENSE-NOTICE.md`, `docs/licensing/model-inventory.md`, `backend/config/model_licenses.json`, `docs/engines/*.md`, `docs/install/docker.md`, `docs/production-private-api.md`, `backend/api/routers/openai_compat.py`
- [Supertonic-3](https://huggingface.co/Supertone/supertonic-3)
- [PySceneDetect](https://www.pypi.org/project/scenedetect/0.5.6.1/)
- Remotion docs via Context7: `@remotion/captions` (`createTikTokStyleCaptions`, `Caption`) and
  the audio `volume` callback
