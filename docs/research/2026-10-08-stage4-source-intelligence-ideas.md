# Stage 4 Source Intelligence: Flow Map and Efficiency Ideas

- Date: 2026-10-08
- Status: ideas only, recorded at the operator's request before any specification. Nothing
  here is approved design. The operator directs each flow part before a spec is written.
- Scope: the behavior Scout runs in `scout/pipeline/trace_source.ts` and its support modules,
  which Stage 4 of `docs/python-scout-migration-roadmap.md` moves into Python.

## Current flow in Scout

```
input: main post (url, caption, description, title, platform)
  |
  +- S1 gather evidence
  +- S2 LLM resolver: "@account on platform X" or "no source, search these keywords"
  +- S3 evaluate the input post first -- accepted --> keep the input (no source search)
  |       | rejected
  |       v
  +- S4 discover candidates (credited account + story search)
  +- S5 evaluate each candidate (eight steps, expensive)
  +- S6 select the winner (tiers, score, fallbacks)
  +- S7 replace the main with the original
  +- S8 finalize the main (downloadable, profile card, final OCR)
```

### S1 Evidence

- S1a Text: caption (`inspectPost`), description, title.
- S1b Vision input selection: the cover; an Instagram carousel uses its real first slide
  instead of `og:image` (`trace_source_vision.ts`, `ig_first_slide.ts`).
- S1c Cover vision (Novita `qwen3-vl`): the on-screen headline and a scene description.
- S1d Credit scan (`source_credit_scan.ts`): OCR of the cover and the first frames yields
  `@handles` (reply mentions filtered by `source_credit.ts`), raw frame text (a TikTok
  watermark prints the username without `@`), and icon prose matched by embedding against the
  Supabase `platform_logos` table (`platform_logo.ts`).
- S1e Text rules: `📸 @user` means Instagram, `tt/user` means TikTok; both override the LLM.

### S2 Resolver

`resolve_source.ts` sends all evidence to the LLM. The answer is `{account, platform}` or
keywords, verified against the evidence; placeholder handles are dropped.

### S3 Input evaluation

The input post runs through the same evaluator as S5. Accepted: kept, no search.
Indeterminate: kept with low confidence. Rejected: search continues.

### S4 Candidate discovery

- S4a Credited account, per platform: Instagram profile (10 newest videos), TikTok profile
  grid (30) plus a handle search, YouTube search by channel name, Threads post by keywords.
- S4b Story search: keywords searched on TikTok, X, Instagram, and Facebook through
  `topic_to_urls.ts` (at most 4 each), filtered to downloadable platforms.
- Results are merged and deduplicated by URL.

### S5 Candidate evaluation (`main_candidate.ts`), in order

1. Probe: media available and a video.
2. Curated aggregator account: rejected.
3. Thumbnail described by vision.
4. Similarity: Gemini embedding of the story text against the candidate evidence; below
   0.33 is `off_topic`; no score is `indeterminate`.
5. Media stream resolution.
6. Visual kind: footage, commentary, or unknown; commentary is rejected.
7. Video OCR (`subtitle_vision.ts`): burned-in subtitles mean a reaction upload; rejected.
8. Accepted (footage gives high confidence) or indeterminate.

### S6 Selection (`main_gate.ts`)

- Tiers: credited handle (0), other account (1), repost account or aggregator (2).
- Score: similarity, plus 1 for footage, plus 2 when plausible (published at most 14 days
  before the repost, duration at least 90% of the repost's).
- Fallbacks: a credited indeterminate candidate, then any indeterminate candidate, then the
  input when nothing was credited; otherwise `main_candidate_not_found`.

### S7 Replace the main

URL, platform, uploader, profile, `source_traced`, `source_low_confidence`, and
`source_keywords` are set, with per-platform handling (TikTok and Threads pages become CDN URLs
plus a local mp4).

### S8 Finalize the main

- S8a Make the main downloadable (TikTok and Threads CDN resolution).
- S8b Crop the profile card.
- S8c Fill an empty title and description from the caption.
- S8d Final video OCR: `clean`, `cover` (`trim_start`), or `subtitle` (mute plus blur
  regions), consumed by the renderer.

### External services in this flow

Novita (LLM and vision), Gemini (embeddings), Supabase with pgvector (logo table), yt-dlp,
TikWM, the CDP browser, ffmpeg (frames), and multi-platform search (`topic_to_urls.ts`).

## What Python already provides

- Stage 2 and 3 acquisition returns the caption, materialized media, owner, publish time, and
  real profile cards per platform, so S7, S8a, and S8b are largely unnecessary in Python.
- Profile discovery for TikTok, Instagram, X, and YouTube (ranked by likes, views, and recency)
  can replace S4a.
- Source accounts can serve any lookup that needs a session.
- `agno>=3,<4` is already the selected agent SDK for a source investigator
  (`docs/decisions/2026-08-28-source-investigator-sdk.md`), behind a framework-neutral
  `SourceInvestigator` protocol.

## Open questions for the operator

1. S3 keeps an accepted input without searching, even when the credit names another account.
   Is that intended?
2. Three providers (Novita, Gemini, Supabase) serve this flow. Consolidate?
3. S4b story search overlaps Stage 8 (discovery). Stage 4 or Stage 8?
4. S8d final OCR feeds the renderer (Stage 5, content assembly). Stage 4 or Stage 5?
5. S5 can run for 30 or more candidates, each with vision, embedding, media resolution, and
   OCR.

## Efficiency ideas

Each idea is a hypothesis. It is validated in research and against golden fixtures, including
the reference pair `@detikjatim` to `@vincentius.christ76`
(`docs/superpowers/specs/2026-08-26-source-video-identification-design.md`), before it enters
a spec. Ideas 1, 2, and 4 are the research priority (operator, 2026-10-08).

1. **Visual match instead of story similarity (S5, S6).** A repost is a cut of the original
   footage, so compare frames, not text. A perceptual hash of center-cropped frames (credit
   bars and overlays excluded) is local, free, and deterministic. Two passes: candidate
   thumbnails (already returned by discovery) first, full frames only for the top few. An
   audio fingerprint is a secondary signal; the reference repost replaced its audio with a
   stock track, so audio cannot be the only one.
2. **Free metadata filters before expensive steps (S5).** The plausibility window (published
   at most 14 days before the repost, duration at least 90%) only adds score today. Applied as
   a filter first, with the curated-aggregator check, it removes most profile videos before
   any model call. Order: metadata, thumbnail hash, frame hash, then vision and OCR only for
   finalists.
3. **Early exit (S5, S6).** Stop once a credited (tier 0) candidate matches visually.
4. **Decide "repost or not" first (S3).** Use the S1 evidence before the full evaluator: a
   credit to another account goes straight to the source search; no credit and no repost sign
   keeps the input without the evaluator.
5. **One vision call for several needs (S1).** Read headline, scene, handles, watermark text,
   and icon description from the cover plus a few first frames in one multimodal call with a
   structured JSON answer.
6. **TikTok "original sound" shortcut (S1, S4).** When a repost keeps the audio, the sound's
   owner and the oldest video using it point at the source almost for free.
7. **Cache per post (all parts).** Store OCR, vision, and hash results by post ID and analyzer
   version in Postgres, so a repeated source account is not paid for twice.
8. **Bounded parallelism through Temporal (S4, S5).** Run discovery per platform and candidate
   evaluation concurrently (for example four at a time), with Temporal retries and
   cancellation.
9. **Fewer providers (S1d).** Replace the embedding-plus-pgvector logo match with local
   template matching of logo images, removing two external dependencies from one decision.

Rough expectation, not measured: model calls per repost fall from about 30 candidates times
(vision, embedding, OCR) to one to three finalists.
