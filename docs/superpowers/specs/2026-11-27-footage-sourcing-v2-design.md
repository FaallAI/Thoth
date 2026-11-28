# Footage Sourcing v2: Resilient TikTok Downloads, Credit-to-YouTube Tracing & Multi-Hour YouTube Cutting

**Date:** 2026-11-27
**Status:** Approved (operator, 2026-11-27)
**Branch:** `feat/footage-sourcing-v2` (cut from `master` `1f77dae9`)
**Brainstorm log:** `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md` (items 111–113)

---

## 1. Problem & Live Evidence (`wf_af610964fe3742b70823ebbc`)

The live commentary run `wf_af610964fe3742b70823ebbc` proved PR #146's context card, gating, and mid-story B-roll cutaways, but exposed three high-leverage sourcing bottlenecks that kept the run to 2 admitted clips instead of filling up to `MAX_FOOTAGE = 8`:

1. **14 TikTok candidates (including both operator references `@podmuses` & `@pikiranrakyat`) failed with `ClipError(TikWmError)`:**
   - `activities/footage.py:295-301` relies solely on `tikwm.com` with no fallback.
   - `TikWmRateGate` (`acquisition/adapters/tikwm.py:131-154`) gates only `1.0 s` from request *start*, allowing `concurrency = 3` workers to hit `tikwm.com` concurrently while each response takes 20–30 s. `TikWmResolver.resolve()` has no retry on `cdn_rate_limited`, and `downloader.py:72` hides `TikWmError.code` and hardcodes `"proxy": ""`.
2. **Credit-to-YouTube tracing (`footage/service.py:_trace`) was completely skipped and too narrow:**
   - Line 786 (`if kept >= MAX_FOOTAGE * 2: return`) short-circuited all tracing as soon as 16 candidates were pending (52 were pending in `wf_af610964`), even though many TikTok hits are subtitled reposts or fail TikWm.
   - `footage/reposts.py` misses common Indonesian credit markers (`sc:`, `cr:`, `credit:`, `kredit:`, `yt:`, `"Sumber YT :"`, `"Source YT:"`), `service.py:797` switches to YouTube only when the literal word `"youtube"` appears in the caption, bare `via` false-matches Indonesian prose (`"Merbabu via Tekhelan"`), and direct handle listing (`listing_of("youtube", normalized_handle)`) fails when display names differ from official YouTube handles.
3. **Multi-hour YouTube surgical cutting (`_sections`, `captions.py`, `moments.py`, `downloader.py`) missed long official videos and visual peaks:**
   - `footage/adapters/downloader.py` already supports partial HTTP range downloads (`download_ranges` + `force_keyframes_at_cuts`), but omits `"js_runtimes": {"bun": {}}` (which `acquisition/youtube_service.py:80` sets), `python/pyproject.toml` lacks `yt-dlp-ejs` (`0.8.0`) alongside `yt-dlp==2026.11.23` (already latest on PyPI), and `downloader.py` has no proxy fallback on YouTube `bot_check`/`403`/`429`.
   - `footage/adapters/captions.py:22-28` only checks exact language key `"id"` (missing `id-orig` / `id-*` and `en` fallback).
   - `yt-dlp`'s metadata-only `extract_info(download=False)` already returns `chapters` and `heatmap` ("Most Replayed") with zero extra network requests, yet `moments.py` ignores both — missing ceremony/stage videos with no auto-captions and missing peak replay moments inside 60 s windows.

---

## 2. Scope, Goals & Non-Goals

**Approved scope (operator, 2026-11-27: `"3 sekaligus"` + `yt-dlp` latest / FFI channel live test):** Packages A + B + C together in one cohesive release on `feat/footage-sourcing-v2`.

**Goals:**
1. Eliminate burst `TikWmError` losses via serialized TikWm pacing + bounded footage timeout + single rate-limit retry, and add a budget-aware, profile-free leased `yt-dlp` fallback (reusing `StoreLeases` + `SessionAccess.yt_dlp_options`) when TikWm fails (TikTok) or direct YouTube hits `bot_check`/`403`/`429`.
2. Ensure social reposts crediting YouTube channels are traced even when `kept >= 16`, recognize Indonesian credit markers without prose/URL false positives, preserve `@handle` punctuation verbatim, and fall back to cached targeted YouTube search when direct handle listing yields no on-story video.
3. Make multi-hour YouTube cutting reliable and zero-full-download: keep `yt-dlp` at latest (`2026.11.23`) and add `yt-dlp-ejs>=0.8.0,<1`, add `js_runtimes: {"bun": {}}` to `downloader.py`, support `id*`/`en` caption fallback, and incorporate `chapters` and `heatmap` from `extract_info` into `pick_discussions()`.
4. Preserve 100% backward compatibility on all existing ports, tests, schemas, and security rules (never log URLs/proxy credentials; zero DB migrations; normal downloads stay direct with `proxy=""`, leasing an account/proxy ONLY on fallback failure and honoring `policy.mode`).

**Non-Goals:**
- No OCR subtitle gate relaxation (21 subtitled news clips remain a separate decision).
- No Scrapling browser launch per footage clip (too heavy inside a 12-minute screening deadline; leased `yt-dlp` with DataImpulse proxy is lightweight and already supported by `SessionAccess.yt_dlp_options`).
- No full download of multi-hour YouTube videos under any condition; long videos remain cut strictly via `download_ranges`.

---

## 3. Package A: Resilient TikTok & Fallback Clip Downloader

### 3.1 Serialized TikWm Pacing, Bounded Timeout & Single Retry (`acquisition/adapters/tikwm.py`, `activities/footage.py`)

1. **`TikWmRateGate` (`acquisition/adapters/tikwm.py`):**
   - Keep `TikWmRateGate.__init__(self, min_interval_seconds: float = 1.0)` unchanged so existing tests (`test_rate_gate_waits_out_the_remainder_of_one_second`) remain green.
   - Set `SHARED_TIKWM_RATE_GATE = TikWmRateGate(min_interval_seconds=1.2)`.
   - Add `@asynccontextmanager async def hold(self, clock, sleep)` holding `self._lock` across the entire request and sleeping `min_interval_seconds` after the *previous request finished* (`_last_end`). Keep `wait()` intact for existing callers/tests.
2. **`TikWmResolver.resolve()` (`acquisition/adapters/tikwm.py`):**
   - Add optional `timeout_seconds: float = REQUEST_TIMEOUT_SECONDS` and `rate_limit_backoff: float = RATE_LIMIT_BACKOFF_SECONDS` (`2.5`) on `TikWmResolver.__init__` (defaults preserve Stage 3 acquisition's `45.0 s` timeout and allow `0.0` in tests).
   - Acquire `async with self._rate_gate.hold(self._clock, self._sleep):` around each HTTP call.
   - On `TikWmError("cdn_rate_limited")`, sleep once (`self._rate_limit_backoff`) *outside* the lock and retry **once** (at most 2 attempts). Never retry `cdn_unavailable` (502/timeout) inside TikWm so failed clips fall back immediately.
3. **Bounded footage timeout (`activities/footage.py`):**
   - In `_tiktok_direct_url`, pass `timeout_seconds=FOOTAGE_TIKWM_TIMEOUT` (`20.0`) to `TikWmResolver` (and matching `httpx.AsyncClient(timeout=FOOTAGE_TIKWM_TIMEOUT)`), preventing queued workers (`concurrency = 3`) from blowing `FootageBuilder`'s `per_candidate_seconds = 90.0` budget on slow TikWm hangs.

### 3.2 Error Code Visibility, Budgeted Timing & Leased Fallback Download (`footage/adapters/downloader.py`, `activities/footage.py`)

1. **Preserve `TikWmError.code` in `ClipError`:**
   - When `_resolve_tiktok` raises `TikWmError`, format the sanitized cause as `f"tikwm_{error.code}"` (`tikwm_cdn_rate_limited` or `tikwm_cdn_unavailable`). Never include URLs or response bodies.
2. **Platform detection & fallback triggers (`footage/adapters/downloader.py`):**
   - Use `platform_of(url)` from `acquisition/platforms.py` (handles `tiktok.com`, `youtube.com`, `youtu.be`, etc. cleanly).
   - Add optional `fallback_session: Callable[[str, Path], AbstractAsyncContextManager[dict[str, Any] | None]] | None = None` to `YtDlpClipDownloader.__init__`.
   - **Shared wall-clock budget:** Track `deadline = time.monotonic() + self._timeout` across direct + fallback so one clip download never exceeds `self._timeout` (`75.0 s`, leaving headroom inside `per_candidate_seconds = 90.0` for OCR/vision/copy checks).
     - Direct attempt gets `min(direct_cap, remaining)` (for TikTok direct CDN download or YouTube direct download, cap direct at `40.0 s` when `fallback_session` is configured so at least `35.0 s` remains for fallback if direct fails!).
     - Fallback attempt runs only if `remaining >= MIN_FALLBACK_SECONDS` (`10.0 s`) and receives `remaining` as its timeout.
   - **Separate scratch directories:** Direct and fallback `yt-dlp` attempts MUST each use their own `tempfile.TemporaryDirectory(prefix="thoth-footage-", dir=target.parent, ignore_cleanup_errors=True)` so an abandoned timed-out direct thread can never overwrite or collide with fallback `clip.mp4`.
   - **Normal path (unchanged):** direct download with `"proxy": ""`, zero account/proxy usage.
   - **TikTok fallback:** If `_resolve_tiktok` fails OR direct `yt-dlp` on the resolved URL fails, and `fallback_session` is configured, enter `async with fallback_session("tiktok", fallback_scratch) as extra:` and attempt one `yt-dlp` download on `original_url` with `{**base_options, **extra}` (overriding `"proxy": ""`).
   - **YouTube fallback (shared with Package C):** If direct `yt-dlp` fails with cause in `{"bot_check", "http_403", "http_429"}` and `fallback_session` is configured, enter `async with fallback_session("youtube", fallback_scratch) as extra:` and retry once with `{**base_options, **extra}`.
3. **Profile-free `StoreLeases` & exact `Outcome` mapping (`activities/footage.py`):**
   - In `build_production_footage`, construct a separate **profile-free** `dl_leases = StoreLeases(accounts)` (no `_account_profiles`, avoiding unnecessary disk profile unseal/seal because `SessionAccess.yt_dlp_options(scratch)` uses only cookies + proxy).
   - Inside `fallback_session(platform, scratch)`:
     - Check `if await dl_leases.mode(platform) == "anonymous": yield None; return` first (honoring platform access policy!).
     - Call `lease = await dl_leases.lease(platform)`; if `None`, `yield None; return`.
     - Yield `lease.access.yt_dlp_options(scratch)`.
     - Catch `ClipError` raised out of the `async with` body to map `Outcome`:
       - normal exit → `"success"`
       - cause == `"http_429"` → `"rate_limited"`
       - cause in `{"bot_check", "http_403"}` → `"blocked"`
       - any other failure (`TimeoutError`, `"no file"`, generic `DownloadError`, `CancelledError`) → `None` (release without penalizing account health).
     - Release via `await dl_leases.release(lease, outcome)` in `finally`, then re-raise the exception.

---

## 4. Package B: Credit-to-YouTube Source Tracing

### 4.1 Richer Credit & Platform Detection (`footage/reposts.py`)

Keep `credited_account(text: str) -> str | None` backward-compatible (returning `ref.account if (ref := credited_source(text)) else None`), and add:

```python
@dataclass(frozen=True)
class CreditRef:
    account: str          # exact @handle (without "@") when written as @handle, else normalized name
    display: str          # cleaned human-readable name for search fallback (e.g., "Kompas TV")
    platform: str | None  # explicit platform ("youtube", "tiktok", "instagram", "x") or None
```

Rules for `credited_source(text: str) -> CreditRef | None`:
1. Check `text_rule_credit(text)` first (`CAMERA_CREDIT` → `"instagram"`, `TIKTOK_CREDIT` → `"tiktok"`).
2. Check explicit named credits (`NAMED_CREDIT`):
   - Match prefixes (word-bounded, case-insensitive, optional space before `:`):
     - `(?:sumber|source|kredit|credit|cr|sc)\s*(?:(?P<plat>youtube|yt|tiktok|tt|instagram|ig|x|twitter)\s*)?:\s*` (handles `"Sumber: YouTube Curhat Bang"`, `"Sumber YT : Ernest Prakasa"`, `"Source YT: Rhenald Kasali"`, `"sc: KompasTV"`, `"cr: @denny.sumargo"`!)
     - `(?:youtube|yt)\s*[/:]\s*` (handles `"YouTube/curhatbang"`, `"yt: TVR Parlemen"`, `"yt/kompastv"`)
     - `via\s*:\s*` OR `via\s+(?=@|(?:youtube|yt|tiktok|tt|instagram|ig|x|twitter)\b)` (handles `"via YouTube/CURHAT BANG"` and `"via @handle"`, while **blocking** Indonesian prose false positives like `"Merbabu via Tekhelan"`, `"via WA"`, `"via chat"`, `"via transfer"`, `"via link"`!).
   - Capture up to `|`, `\n`, `#`, or 60 chars; strip whitespace.
   - **URL guard:** Reject captured values starting with `http://`, `https://`, or `www.` (fixes `"Model Source: https://makerworld.com/..."`).
   - Extract explicit platform either from the prefix (`(?P<plat>)` / `youtube` / `yt`) or from a leading `PLATFORM_WORD` in the captured label.
   - Strip leading `PLATFORM_WORD` to get `raw_label`:
     - If `raw_label` starts with `@` (e.g., `@denny.sumargo`): extract the `@handle` via `AT_HANDLE`, preserve exact handle punctuation (`handle.rstrip(".")`, NOT `normalize()`!) for `account` and `display` (keeps `test_reposts.py:38` `"denny.sumargo"` green!).
     - Otherwise: `display = raw_label.strip()`, `account = normalize(display)`.
   - Skip if `normalize(account)` is empty or in `PLACEHOLDERS`.
   - Prefer an explicit YouTube named credit over an earlier bare `@handle` in the caption (so `"@ernestprakasa Sumber: YouTube Kompas TV"` traces Kompas TV on YouTube instead of stopping at `@ernestprakasa`).
3. Fallback: first usable handle from `text_handles(text)` (exact punctuation preserved for `account` & `display`), setting `platform = "youtube"` if `"youtube"` or `\byt\b` (word-bounded, case-insensitive) appears in `text`, else `None`.

### 4.2 Lift `kept >= 16` Block for YouTube Credits & Add Cached YouTube Search Fallback (`footage/service.py:_trace`)

Update `FootageBuilder._trace()` (`footage/service.py:776-850`):
1. Keep `if self._ports.creator is None: return` (preserving unit tests without a creator port).
2. Compute `full = kept >= MAX_FOOTAGE * 2`. When `full` is `True`, continue scanning pending search candidates **only** for those whose resolved trace target is `platform == "youtube"` (skipping non-YouTube same-platform traces). Still cap at `MAX_TRACE_LISTINGS = 3` total traced keys per run.
3. Resolve credit via `ref = credited_source(c.caption)`:
   - `platform = ref.platform or c.platform`.
   - Skip if `platform not in CREATOR_PLATFORMS`, or `normalize(ref.account) == normalize(c.owner_handle)`, or (`ref.platform is None` and `is_own_account(c.owner_handle, card)`).
4. **Direct listing + cached YouTube search fallback:**
   - First try `self._ports.creator.listing_of(platform, ref.account, CREATOR_LISTING)` as today.
   - Evaluate its videos through `text_gate(..., long_ok=platform == "youtube")` and `not self._off_story(...)`, keeping ALL rows (including rejected rows such as `"main"` so `test_a_traced_original_that_is_the_main_post_is_rejected_main` stays green!).
   - If `platform == "youtube"` and **0 pending on-story originals** came from `listing_of`:
     - Build one targeted YouTube query from `ref.display` + up to 2–3 distinctive terms from `card` (e.g., `people[1].name` if commentary else `people[0].name`, plus top non-person `event_terms(card)`, `<= 80` chars, e.g., `"Kompas TV Fadli Zon FFI 2026"`).
     - Check `self._store.cached_search("youtube", query)` first; on miss, call `self._ports.search.search("youtube", [query], RESULTS_PER_QUERY)` wrapped in `try/except Exception` (re-raising `ToolMissing`) and save results via `self._store.save_search("youtube", query, found)`.
     - Cache the combined listing+search videos in `listings[key]` so duplicate credits don't re-search, and append any newly passing videos as `source="trace"`, `story_score=OWN_SCORE`.
   - Any surviving originals mark the repost rejected as `"repost"` and immediately flow into `_sections()` on the next line (`service.py:551`).

---

## 5. Package C: Multi-Hour YouTube Surgical Cutter

### 5.1 `yt-dlp-ejs` & `js_runtimes` (`python/pyproject.toml`, `python/uv.lock`, `footage/adapters/downloader.py`)

1. Keep `yt-dlp==2026.11.23` (verified latest on PyPI) and add `"yt-dlp-ejs>=0.8.0,<1"` to the `acquisition` optional-dependency extra in `python/pyproject.toml`, updating `python/uv.lock` via `uv lock --project python`.
2. Add `"js_runtimes": {"bun": {}}` to `YtDlpClipDownloader.download()` options (matching `acquisition/youtube_service.py:80`), enabling `yt-dlp` to solve YouTube JS challenges cleanly during partial `download_ranges` clips without downloading full videos.

### 5.2 Caption Language Fallback + Zero-Extra-Call `chapters` & `heatmap` (`footage/adapters/captions.py`, `footage/moments.py`)

1. **Data models & parsers in `footage/moments.py`:**
   ```python
   @dataclass(frozen=True)
   class Chapter:
       start: float
       end: float
       title: str

   @dataclass(frozen=True)
   class HeatPoint:
       start: float
       end: float
       value: float  # 0.0..1.0 from yt-dlp heatmap

   @dataclass(frozen=True)
   class LongVideoHints:
       captions: bytes | None = None
       chapters: list[Chapter] = field(default_factory=list)
       heatmap: list[HeatPoint] = field(default_factory=list)
   ```
   - Add pure parsers `parse_chapters(raw: object) -> list[Chapter]` and `parse_heatmap(raw: object) -> list[HeatPoint]` ignoring malformed entries.

2. **`YtDlpCaptionFetcher` (`footage/adapters/captions.py`):**
   - **Language fallback in `_json3_url(info, language)`:**
     - **Outer loop = language priority:** (1) exact `language` (`"id"`), (2) prefix `k.startswith(f"{language}-")` (e.g., `"id-orig"`), (3) `"en"`, (4) prefix `"en-"`.
     - **Inner loop = sources:** `("automatic_captions", "subtitles")` — so `subtitles["id"]` always beats `automatic_captions["en"]`.
   - Add `async def hints(self, url: str, language: str) -> LongVideoHints`:
     - Calls `self._client.extract(url, comments=False)` **once** (metadata only, 0 video bytes).
     - Parses `chapters = parse_chapters(info.get("chapters"))` and `heatmap = parse_heatmap(info.get("heatmap"))`.
     - Fetches `json3` bytes if `_json3_url(info, language)` is found (keeping the 1× `429` retry after `retry_seconds`).
     - Returns `LongVideoHints(captions=data, chapters=chapters, heatmap=heatmap)` even when `captions` is `None`.
   - Keep `async def captions(self, url: str, language: str) -> bytes | None` returning `(await self.hints(url, language)).captions`.

3. **Combined Scoring in `pick_discussions()` (`footage/moments.py`):**
   - Backward-compatible signature:
     `pick_discussions(lines, subject, others, words, limit=MAX_MOMENTS, *, chapters=(), heatmap=()) -> list[Discussion]`
   - **Case 1 — Transcript `lines` present (existing path enhanced):**
     - Keep `INTRO_SECONDS = 30.0`, `WINDOW_SECONDS = 60.0`, `MIN_SCORE = 4`, `MIN_WORDS = 2`, `APART_SECONDS = 60.0`, and `subject`-required guard unchanged.
     - **Chapter boost (`CHAPTER_BOOST = 2`):** If any overlapping chapter has a normalized `title` naming `subject`/`others` or matching a discussion `word`, add `+CHAPTER_BOOST` to the window's `score` (still requiring `len(distinct) >= MIN_WORDS`).
     - **Heatmap peak refinement (`HEAT_PEAK = 0.7`):** Inside `moment(first, last)`, add `+1` weight when `lines[i].start` falls inside a `HeatPoint` with `value >= HEAT_PEAK`, snapping the 8-second cut to the most replayed punchline/gesture inside that discussion.
   - **Case 2 — No transcript windows matched AND `chapters` present:**
     - For each chapter, compute safe moment bounds so `section(moment)` (`[moment - 1.0, moment + 7.0]`) stays inside `[chapter.start, chapter.end]` and `moment >= INTRO_SECONDS`:
       - `low = max(chapter.start + LEAD_SECONDS, INTRO_SECONDS)`
       - `high = chapter.end - (SECTION_SECONDS - LEAD_SECONDS)`
       - If `high < low`: skip (chapter too short or ends inside intro).
     - Score `norm_title = norm(chapter.title)`:
       - If `subject` is non-empty and `_names(norm_title, subject) == 0`: skip (preserves `incident` strictness).
       - `score = 2 * bool(_names(norm_title, subject)) + bool(_names(norm_title, others)) + _count(norm_title, words)`
       - Keep chapters with `score >= 2`.
     - Select up to `limit` highest-scoring chapters whose chosen `moment`s stay `>= APART_SECONDS` apart:
       - If any `HeatPoint` overlaps `[low, high]`, take the midpoint of the highest-`value` overlapping `HeatPoint`, clamped to `[low, high]`.
       - Otherwise take `min(low + 5.0, high)` (skipping chapter bumper cards while staying inside `[low, high]`).
     - **Re-sort kept chapter discussions chronologically by `moment` ascending** before returning `[Discussion(moment=round(m, 1), said=[]) ...]`.

4. **`FootageBuilder._sections()` (`footage/service.py:852-900`):**
   - Call `await self._ports.captions_text.hints(c.url, CAPTION_LANGUAGE)` when `hasattr(self._ports.captions_text, "hints")`, else wrap `captions()` in `LongVideoHints`.
   - Run `pick_discussions(parse_json3(hints.captions) if hints.captions else [], subject, others, words, chapters=hints.chapters, heatmap=hints.heatmap)` whenever `hints.captions or hints.chapters`.
   - For section `visual`: keep `PERSON_VISUAL` when `discussion.said` is non-empty (preserving `test_service.py:2289`), and use `c.visual or PERSON_VISUAL` when `not discussion.said` (chapter-only ceremony/stage cuts where the parent visual is already name-stripped).

---

## 6. Verification Plan

1. **Offline unit & integration tests (test-first):**
   - `python/tests/acquisition/test_service.py` / `test_tikwm.py`: `TikWmRateGate.hold` serializes 3 concurrent calls; `TikWmRateGate()` default stays `1.0`; `TikWmResolver` retries once on `cdn_rate_limited` and does not retry `cdn_unavailable`.
   - `python/tests/footage/test_clip_adapters.py`: `tikwm_cdn_rate_limited` / `tikwm_cdn_unavailable` cause codes; `"js_runtimes": {"bun": {}}` set; direct-then-fallback for TikTok (on TikWm error or CDN failure) and YouTube (on `bot_check`/`http_403`/`http_429`); separate scratch dirs; shared wall-clock budget; `mode == "anonymous"` skips leasing; exact `Outcome` mapping (`success`, `rate_limited`, `blocked`, `None`).
   - `python/tests/footage/test_reposts.py` & `test_service.py`: `credited_source` handles `Sumber YT :`, `Source YT:`, `sc:`, `cr: @denny.sumargo` (preserving dot!), `yt:`, rejects URLs (`https://...`) and Indonesian `via` prose (`"Merbabu via Tekhelan"`, `"via WA"`), prefers explicit YouTube credit over leading `@handle`; `_trace()` traces YouTube credits even when `kept >= 16`, falls back to cached YouTube search when `listing_of` yields 0 on-story originals while preserving rejected rows.
   - `python/tests/footage/test_moments.py` & `test_service.py`: `_json3_url` language-outer priority (`subtitles["id"]` > `automatic_captions["en"]`, `id-orig` fallback); `hints()` single-extract returning `chapters` + `heatmap` even without captions; `pick_discussions` chapter boost, heatmap peak snapping, chapter-only fallback with safe `[low, high]` clamping, short-chapter skip, and ascending chronological sort; `_sections` compatibility with both `hints()` and legacy `captions()` stubs.
2. **Full verification before push:** `make lint`, `make test`, `make dashboard-test`, `make dashboard-build`, `graphify update .`.
3. **Live acceptance test (after CI green & stage1 deploy, on explicit operator authorization):**
   - Point at the official **FFI YouTube channel**'s multi-hour FFI 2026 ceremony video (or trigger via a commentary run) and prove the surgical cutter locates the exact seconds where the award winner's speech mentions **Fadli Zon** and downloads **only that ~8-second window** (zero full download), plus verify TikTok fallback recovers clips when TikWm fails.

---

## 7. Files Touched

- `python/pyproject.toml` & `python/uv.lock` (`yt-dlp-ejs>=0.8.0,<1`, keeping `yt-dlp==2026.11.23`)
- `python/src/thoth_control_plane/acquisition/adapters/tikwm.py`
- `python/src/thoth_control_plane/footage/adapters/downloader.py`
- `python/src/thoth_control_plane/activities/footage.py`
- `python/src/thoth_control_plane/footage/reposts.py`
- `python/src/thoth_control_plane/footage/adapters/captions.py`
- `python/src/thoth_control_plane/footage/moments.py`
- `python/src/thoth_control_plane/footage/service.py`
- Unit tests under `python/tests/acquisition/` and `python/tests/footage/`
