# Stage 4 Source Intelligence: Jev, Agno, and Open-Source Tools

- Date: 2026-10-08
- Status: research for the operator, before any specification. Companion to
  `docs/research/2026-10-08-stage4-source-intelligence-ideas.md`, whose flow-part codes
  (S1 to S8) and idea numbers this document uses.
- Question: which of TypeSafe Jev, the Agno framework, and open-source GitHub tools fit the
  Stage 4 flow, and where.

## Summary

| Candidate | Fit | Where |
|---|---|---|
| TypeSafe Jev | Good for text-only typed decisions | S2 handle and platform choice, S3 "repost or not", S5 caption relevance prefilter |
| Agno | Useful as the model-call layer, not as the orchestrator | Vision and LLM calls inside Temporal activities |
| Frame hashing (PDQ / pHash) | Strong; the core of idea 1 | S5 and S6 visual match |
| Local OCR (RapidOCR) | Strong; replaces per-frame vision calls | S1d credit scan, S5 step 7, S8d |
| Whole-video hash (`videohash`) | Poor | A repost is a cut, so a whole-video hash differs |

## TypeSafe Jev

What it is: a "System One" decision model released by TypeSafe AI on 2026-09-15. It answers
typed questions about text or JSON and returns only structured values with calibrated
probabilities, never prose.

- Primitives: `choice` (one of named options, with a probability per option and a
  confidence), `score` (an ordered rubric of 2 to 10 levels), and `noul` (a yes probability).
- Input: text only. A string, a JSON object, or a JSON array of text; no images, audio, or
  video.
- Context: about 32,000 tokens for the state plus the longest question.
- Latency: 70 to 500 ms end to end, most around 100 ms.
- Price: $0.042 per million input tokens; output tokens are free.
- Access: TypeSafe's API (`POST https://api.typesafe.ai/v1/systemone`, Python SDK
  `typesafe-sdk`), OpenRouter (`typesafe/jev-1.13`, Decisions API), Vercel AI Gateway, and
  Cloudflare.
- Many questions on one state run in parallel in one call; 13 questions were reported 12.2
  times cheaper and 10 times faster than 13 sequential calls.
- Weak at math and counting, dates, indirection and complex logic, contradictory
  instructions, and anything generative. A score ranks; it does not interpolate magnitude.

Fit for Stage 4:

- S3, idea 4 ("repost or not"): one `noul` over the caption, OCR text, and found handles.
  Calibrated probabilities replace today's ad hoc high and low confidence.
- S2: the resolver today generates an account name and then verifies it against the
  evidence. With Jev, the handles found in S1 become the options of a `choice` ("which of
  these is the source credit, or none"), plus a `choice` over platforms. The answer can never
  be a handle the evidence does not contain.
- S5 step 4: a `noul` or `score` on whether a candidate caption tells the same story. It is
  only a prefilter, because captions are often empty (the reference source's was).
- Not a fit: S1c, S1d, S5 steps 3, 6, and 7, and S8d need vision. The plausibility window
  (dates, durations) stays in code, because Jev is weak at dates and numbers. A cited
  explanation still needs a generative model.
- Risks: the model is three weeks old, it adds a vendor and a key, and it needs recorded
  responses for offline golden fixtures. Put it behind a port so it can be swapped.

Sources: [OpenRouter: What is Jev](https://openrouter.ai/blog/insights/what-is-jev/),
[OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev),
[Deep dive (flaviocopes)](https://flaviocopes.com/jev/),
[Let's Data Science launch report](https://letsdatascience.com/news/typesafe-ai-launches-jev-decision-model-889a38c0),
[Cloudflare model page](https://developers.cloudflare.com/ai/models/typesafe/jev/).

## Agno

- Already selected: `docs/decisions/2026-08-28-source-investigator-sdk.md` (accepted
  2026-08-30) chose Agno over PydanticAI after a six-case spike, both passing. `agno>=3,<4` is
  a production dependency, locked at 3.0.1, behind the framework-neutral `SourceInvestigator`
  protocol. Nothing in production imports it yet.
- Capabilities that matter here (Context7, `/agno-agi/docs`): agents with a Pydantic
  `output_schema`; image input (`agno.media.Image` from a path, bytes, or URL); OpenAI-like
  providers by `base_url` (Novita is OpenAI-compatible); workflows of `Step`, `Parallel`,
  `Condition`, and `Loop`; and AgentOS as its own runtime.
- No native Temporal integration was found; PydanticAI documents one (`TemporalAgent`).
  Agno's workflows and AgentOS duplicate what Temporal already does here (retries,
  cancellation, history, parallel activities).
- One web source reports Agno at v2.7.3 in July 2026, which conflicts with the locked 3.0.1.
  Confirm the current release on PyPI before the spec pins anything.

Recommendation: keep Temporal as the only orchestrator. Use Agno as the model-call layer
(structured vision and LLM calls, provider switching) inside Temporal activities. Do not run
the core flow as an agent loop: it is deterministic, must match golden fixtures, and an agent
would add cost and variance. An Agno investigator agent stays an option for the hard
leftovers (no credit, no visual match), proposing and never deciding, as the existing decision
already requires.

Sources: [Agno repository](https://github.com/agno-agi/agno),
[Agno docs via Context7](https://docs.agno.com),
[PydanticAI Temporal integration](https://ai.pydantic.dev/temporal).

## Open-source tools

### Visual match (idea 1)

- **PDQ / vPDQ** (Meta, `facebook/ThreatExchange`, BSD). vPDQ samples frames (for example one
  per second), hashes each with PDQ, keeps a per-frame quality score, and matches two videos as
  an unordered bag of frame hashes. Matching takes a PDQ distance threshold (for example 31), a
  quality filter (for example 50), and two match percentages, one per side. This fits the
  repost case: require a high share of the repost's frames to be found in the candidate, and
  no share the other way, because the original is longer. The Python binding (`vpdq` 0.2.2,
  BSD-2-Clause) builds from source with C++14, CMake, and FFmpeg libraries, ships no wheels,
  and does not support Windows. That suits the Linux worker image, not the Windows dev host.
- **imagehash** (pure Python): pHash and dHash per image. It is the simplest way to build the
  same bag-of-frames matching with no native build, at some loss of robustness against PDQ.
- **videohash / videohash2**: one 64-bit hash per whole video. **Not suitable**: a repost cut
  (90 s out of 124 s in the reference pair) changes a whole-video hash.
- Hash the center crop of each frame, so credit bars and overlay text do not dominate.

### Frame sampling

- ffmpeg is already in the stack. PySceneDetect can pick shot boundaries when a fixed rate
  samples too many near-identical frames.

### OCR without a vision model (S1d, S5 step 7, S8d)

- **RapidOCR** (RapidAI): PaddleOCR models converted to ONNX, run by ONNX Runtime, light and
  CPU-friendly. It can read `@handles` and watermark text from the first frames locally,
  instead of one vision call per frame.
- **videocr-PaddleOCR**: a reference for burned-in subtitle extraction with region cropping,
  useful for the subtitle detection in S5 step 7 and S8d.

### Audio (secondary to idea 1)

- Chromaprint with `pyacoustid`: an audio fingerprint for reposts that keep the sound. It
  cannot be the only signal; the reference repost replaced its audio.

### Logo (idea 9)

- OpenCV template matching against a small set of logo images is local and deterministic, and
  removes the Gemini embedding plus Supabase pgvector lookup. Reposts scale the logo, so the
  match needs a few scales.

Licenses still to confirm before a spec adopts a tool: RapidOCR, imagehash, PySceneDetect,
Chromaprint (LGPL), and OpenCV.

Sources: [ThreatExchange vPDQ](https://github.com/facebook/ThreatExchange/tree/main/vpdq),
[vpdq on PyPI](https://pypi.org/project/vpdq),
[videohash](https://github.com/akamhy/videohash),
[RapidOCR](https://github.com/RapidAI/RapidOCR),
[videocr-PaddleOCR](https://github.com/devmaxxing/videocr-PaddleOCR),
[Mixpeek video deduplication tools](https://mixpeek.com/curated-lists/best-video-deduplication-tools).

## Proposed shape, for discussion only

```
S1  evidence     RapidOCR (frames) + one Agno vision call (cover) + text rules
S3  repost?      Jev noul
S2  credit       Jev choice over the handles S1 found, Jev choice over platforms
S4  candidates   Stage 3 discovery (metadata: publish time, duration, thumbnail)
S5  filter       code: plausibility window + curated list   (free)
    match        frame hashes: thumbnail first, then frames  (local)
    finalists    Agno vision + RapidOCR subtitle check       (1 to 3 candidates)
S6  select       tiers + match share + early exit
```

Each piece is a Temporal activity. Every model call is recorded once for the golden fixtures,
so parity tests replay them offline.
