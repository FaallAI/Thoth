# Stage 5b footage: research

Date: 2026-10-14. Input to the Stage 5b brainstorm; no decision here is final until the operator
approves a spec.

## 1. Question

Stage 5b ports footage (cutaway b-roll) from Scout to Python. This note answers three questions:

1. What does Scout do today, and what does each part cost?
2. Which open-source tools fit the flow and the Python stack already in place?
3. Where can the Python port do better than a line-by-line port?

## 2. What Scout does

`scout/pipeline/build_footage.ts` (967 lines) with `footage_queries.ts`, `lib/footage_objects.ts`,
`lib/footage_candidate_selection.ts`, `lib/footage_candidate_ocr.ts`, `lib/embed.ts`, and
`pipeline/topic_to_urls.ts`.

**Queries.** `dossier.search_queries` (Stage 6 enrichment, not ported) or, as fallback, an LLM
call (`footage_objects`) that returns `subjects`, `objects`, and `people` from the title,
description, and top 12 comments. It expands generic terms to concrete ones ("ojol" to gojek,
grab). Query = object + primary subject, plus one query with a known person.

**Sources, in order:**

1. Main is an Instagram carousel with at least two videos: its other slides are the footage, and
   nothing else is searched.
2. The traced creator's Instagram profile grid (12 posts, reels and feed posts), ranked by
   embedding similarity to the event (floor 0.30); at most `per + 1`.
3. Each query: `topic_to_urls` over TikTok, X, Instagram, and Facebook. Videos (TikTok, YouTube)
   go through OCR; posts (X, Instagram, Facebook, Threads) are cropped to card images, carousel
   slides included. Target mix: half videos, half posts, then cross-fill.
4. X cards searched by the main's title (non-video tweets only).

**Gates:**

- the main itself: same URL, same platform id, or near-identical caption;
- curated aggregator accounts (`ig_accounts.json`) and their cross-posts;
- reaction or reupload: a keyword regex (`reaction|reaksi|ngereact|reupload|nonton bareng`);
- spam: link-first text or a shortener domain;
- relevance: every token of 3 or more characters of the object appears in the text;
- subtitle: OCR over sampled frames; a clip with burned-in subtitles is dropped;
- story gate, last: cosine of the main's story against each footage description, floor 0.33
  (`THOTH_FOOTAGE_STORY_MIN`), with a provider embedding (`qwen3-embedding`).

**Costs that matter:**

- Every query runs one `topic_to_urls` subprocess with a 200 s timeout, platform after platform.
  Browser navigation is globally serialized. A five-query run can take many minutes.
- Posts are cropped, and videos are probed and OCR'd, **before** the story gate. The story gate
  only needs the text, but it runs last, after every download and crop is paid for.
- Reactions are caught by keywords only. A talking-head clip with a neutral caption passes.
- Relevance trusts the caption. A hashtag-stuffed caption passes even when the clip shows
  something else.

## 3. How the renderer uses footage

`crates/thoth-core/src/ingest/content_search.rs` (`ContentResult`) and `edit/service.rs`:

- A cutaway lasts 2.5 to 6 s (`intercut_segment_secs`), up to `intercut_max_cuts` per video.
- Each cutaway is placed where its `description` best matches a narration sentence (embedding
  cosine). The description is therefore a placement key, not decoration.
- Video items carry the OCR fields, `trim_start`, and `mute_audio`; subtitle-classified footage
  is refused (`subtitle-classified footage is not renderable`). Image items carry `image_path`.
- `relevance: "unverified"` items are dropped.

Two consequences follow. The renderer uses a few seconds of each clip, so a full download of a
long YouTube video is waste. And a description that says what the clip *shows* places it better
than a caption written to attract views.

## 4. What Python already has

| Need | In place | Where |
|---|---|---|
| TikTok keyword search | yes | `acquisition/discovery.py` (`kind="keyword"`, `/search?q=`) |
| Instagram, X, YouTube profile listing | yes | `instagram_discovery.py`, `x_discovery.py`, `youtube_discovery.py` |
| Instagram signed-in reels listing | yes | `instagram_reels.py` (Camoufox) |
| Signed-in leases with proxy, spacing, budget, cooldown | yes | `acquisition/accounts/` |
| Download | yes | `acquisition/materializer.py` (yt-dlp) |
| Card crops | yes, comments | `acquisition/cards.py`, `card_browser.py` |
| OCR and subtitle classifier | yes | `assembly/ocr.py`, `assembly/subtitles.py` (RapidOCR) |
| Footage vs commentary vision call | yes | `attribution/adapters/vision.py` |
| Visual identity match (ORB+RANSAC) | yes | `attribution/adapters/visual.py` |
| Structured LLM calls | yes | Agno over OpenRouter (`assembly/figures.py`) |
| `ContentSet.footage` | placeholder | `assembly/models.py` (always empty) |

Installed and reusable: `yt-dlp`, `opencv-python` 5, `onnxruntime`, `rapidocr`, `av`, `pillow`,
`huggingface-hub`, `tokenizers`, `scrapling`, `camoufox`. Not installed: `torch` (and it should
stay that way; the image is already 15 GB).

**Missing:** keyword search on X, YouTube, Instagram, Threads, and Facebook; any Facebook
support; embeddings; post crops; footage-specific gates.

## 5. Open-source tools

| Need | Tool | License | Fit | Verdict |
|---|---|---|---|---|
| YouTube search | `yt-dlp` `ytsearchN:` / `ytsearchdate` | Unlicense | installed; no login | **Use** |
| Clip a short window | `yt-dlp --download-sections "*a-b"` | Unlicense | installed | **Use** |
| TikTok search | own `discovery.py` | own | in place | **Use** |
| X search | own `x_discovery.py` pattern on `x.com/search?q=…&f=media` | own | same leases, fingerprint, cooldown | **Use** |
| X search, alternative | `twscrape` 0.18 (async, account pool, SQLite) | MIT | plain HTTP outside our browser, own account store | Skip; fallback only |
| Instagram keyword search | none that works without the mobile API | — | the mobile private API is banned here | **Skip** |
| Facebook | `facebook-scraper` | MIT | unmaintained; no adapter in Python | **Skip** |
| Text embeddings, local | `fastembed` + `paraphrase-multilingual-MiniLM-L12-v2` | Apache-2.0 | ONNX, no torch, 0.22 GB, Indonesian | **Use** |
| Visual relevance, local | `fastembed` CLIP `clip-ViT-B-32` (vision + text) | MIT | ONNX, 0.34 + 0.25 GB, English text | **Use** |
| Multilingual CLIP | `jina-clip-v2` | CC BY-NC 4.0 | 0.9B params, non-commercial | Skip |
| Talking-head detection | OpenCV `FaceDetectorYN` (YuNet, opencv_zoo) | MIT/Apache | in OpenCV; 0.2 MB model | **Use** |
| Shot boundaries | `PySceneDetect` | BSD-3 | OpenCV backend, `frame_skip`, downscale | Use for window choice |
| Near-duplicates | dHash with NumPy + OpenCV; ORB from attribution | own | no new dependency | **Use** |
| Stock b-roll | Pexels API (200 req/h, free use) | Pexels terms | licensed footage for generic objects | Option |
| Stock b-roll | Pixabay API (100 req/min, 24 h cache required) | Pixabay license | same | Option |

Sources: [fastembed](https://github.com/qdrant/fastembed) (Context7 `/qdrant/fastembed`),
[twscrape](https://github.com/vladkens/twscrape) (Context7 `/vladkens/twscrape`),
[PySceneDetect](https://github.com/breakthrough/pyscenedetect) (Context7
`/breakthrough/pyscenedetect`), [jina-clip-v2](https://huggingface.co/jinaai/jina-clip-v2),
[Pexels API](https://www.pexels.com/api/documentation/),
[Pixabay API](https://pixabay.com/api/docs/),
[what still works in 2026](https://www.xpoz.ai/blog/guides/open-source-social-media-scrapers-what-still-works-2026/).

No open-source library does cross-platform keyword search; each platform needs its own route.
That matches what Python already does: one module per platform behind the acquisition service.

## 6. Where the port can do better

Ranked by value for the effort.

1. **Gate cheap before expensive.** Order: identity, aggregator, spam, and reaction text gates;
   metadata (duration, resolution); the story gate on text (it needs no media); then frames;
   then download. Scout runs the story gate after paying for every crop and probe.
2. **Look at the frames, not only the caption.** Sample about 6 frames from the stream (ffmpeg
   seek on the direct URL, no full download) and run, locally:
   - OCR subtitle check (5a classifier, unchanged);
   - CLIP similarity between the frames and the object's English visual description;
   - YuNet face area: a large face across most frames is a talking head, so a reaction even
     when the caption says nothing;
   - dHash against the main's frames and the footage already admitted, so a repost of the main
     or the same clip twice never gets in.
3. **Download only the window the renderer uses.** Pick the best 8 to 12 s window (CLIP score per
   shot from PySceneDetect) and fetch it with `--download-sections`. A 10-minute YouTube video
   then costs seconds of video, not the whole file.
4. **Write a description of what the clip shows.** The renderer places cutaways by description.
   Use the object's visual description plus the caption, instead of the caption alone.
5. **Search platforms concurrently.** TikTok, YouTube, and X each have their own lease, proxy,
   and spacing. Queries within one platform stay sequential; platforms run side by side. Stop
   as soon as the quota is met.
6. **Cache searches.** One cache entry per platform and query for 24 hours. Retries and reruns
   of the same story stop hitting platforms again.
7. **One LLM call for queries.** Extend the 5a structured call so it returns, per object, an
   Indonesian search query and an English visual description (needed by CLIP). The figures
   prompt can then also read footage descriptions, as Scout's does, if figures run after
   footage.
8. **Local embeddings.** fastembed replaces the remote `qwen3-embedding`: no key, no network,
   deterministic in tests, same choice as local transcription.

## 7. Risks

- **Proxy traffic.** DataImpulse bills per GB. Public TikTok and YouTube media need no login.
  Downloads should go direct or through a separate route, not through the account proxies;
  only signed-in searches need the account's proxy.
- **Account safety.** X search is a signed-in action and counts against X's budget and spacing.
  Instagram keyword search stays out: the only working route is the banned mobile API.
- **Copyright.** Social clips are the creators' work; the renderer already uses them this way.
  Stock sources (Pexels, Pixabay) are licensed, but generic.
- **Image size.** fastembed models add about 0.8 GB; they belong in the heavy layer before the
  source, like the speech models.
- **CLIP is English-only.** The LLM must supply an English visual description per object; the
  Indonesian query is for search only.

## 8. Open decisions for the operator

1. Scope: video b-roll first (TikTok, YouTube, carousel slides), post cards and creator profile
   later; or full parity now.
2. Sources: add stock b-roll (Pexels and/or Pixabay) as a fallback for generic objects or not.
3. Visual gates: CLIP relevance and talking-head detection as hard gates, or scores only.
4. Download policy: windowed downloads, and whether media downloads bypass the account proxies.
5. Query source until Stage 6 exists: the LLM extraction only.

## 9. Addendum: frame checks, revised (2026-10-14)

The operator asked for a closer look at the CLIP and face-detection gates of section 6.2. The
result changes the recommendation.

**CLIP has no usable absolute threshold.** Its cosine scores depend on the model's training
temperature; a "relevant" score for one object is an "irrelevant" score for another. It can only
rank candidates against each other, or against hand-written negative prompts. ViT-B/32 also
knows brands and named entities poorly (about 85% zero-shot on logo crops in published work),
and its text side is English-only. A hard CLIP gate would need per-object calibration we cannot
do offline.

**A face detector cannot tell a reaction from valid footage.** A large face across the frames
is a reaction when a creator talks to the camera, but it is also the footage we want when the
object is a person (a minister at a press conference, a CEO on stage). Telling the two apart
needs context the detector does not have.

**Python already has the right classifier.** Stage 4's vision reader
(`attribution/adapters/vision.py`, `CLASSIFY_PROMPT`) answers "raw footage of an event, or
commentary (a person talking to the camera, a news anchor, a slideshow, or a reaction)" from
three frames, and Stage 4 calibrated it on live cases. Its model, `qwen/qwen3-vl-30b-a3b-instruct`
through OpenRouter, costs $0.15 per million input tokens and $0.60 per million output tokens
(OpenRouter model list, 2026-10-14): a three-frame call is well under a tenth of a cent, so 30
candidates per run cost about two cents.

**Revised recommendation.** One structured vision call per candidate that passed the text gates
and the subtitle OCR, on three frames, answering three things:

- `kind`: `footage` or `commentary` (the Stage 4 classes; commentary is rejected);
- `shows_object`: whether the frames show the object's visual description (`yes`, `partly`,
  `no`; `no` is rejected);
- `description`: one sentence on what the clip shows, written into the footage entry for the
  renderer's narration placement.

A provider error or timeout drops that candidate (it is optional), never the stage. Calibration
uses recorded answers on real candidates, replayed offline as golden fixtures, as in 5a.

This drops the CLIP and YuNet models from section 5 (about 0.6 GB less in the image). The local
multilingual text embedding stays: it runs the story gate on captions before any media is
touched, which keeps vision calls to the candidates worth looking at.
