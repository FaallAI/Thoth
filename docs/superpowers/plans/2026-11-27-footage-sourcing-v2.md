# Footage Sourcing v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` (or `superpowers:subagent-driven-development`), `ponytail` (`full` intensity), `karpathy-guidelines`, and `tdd` (test-first) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate burst `TikWmError` footage losses via serialized TikWm pacing + leased `yt-dlp` proxy fallback, make Credit-to-YouTube tracing actually recover original YouTube videos past `kept >= 16` with cached YouTube search fallback, and upgrade multi-hour YouTube surgical cutting (`yt-dlp-ejs` + `js_runtimes: {"bun": {}}`, `id*`/`en` caption fallback, and zero-extra-call `chapters` + `heatmap` moment selection without ever downloading full videos).

**Approved Spec:** `docs/superpowers/specs/2026-11-27-footage-sourcing-v2-design.md` (approved by operator 2026-11-27; brainstorm items 111–114).

**Branch & Baseline:** Work directly on existing local branch `feat/footage-sourcing-v2` (already cut from `master` `1f77dae9` and carrying 2 unpushed docs-only commits: `377f388e` deploy record and `7cd33023` PR #146 live check & merge record). **Do NOT drop, squash, or rewrite those 2 commits; build Tasks 1–7 on top of `7cd33023`.**

**Architecture & Preservation:** Zero database migrations, zero API/OpenAPI/dashboard schema changes, zero Remotion composition/golden changes. Normal downloads stay strictly direct (`proxy=""`), leasing an account/proxy ONLY on fallback failure and honoring `policy.mode == "anonymous"`. Never log URLs, cookies, or proxy credentials.

**Tech Stack:** Python 3.12+ control plane (`uv`, `pytest`, `ruff` via WSL `make test T=<path>`, `make lint`), `yt-dlp==2026.11.23` + `yt-dlp-ejs>=0.8.0,<1`.

---

## Task 1: Add `yt-dlp-ejs` to `acquisition` Extra (`python/pyproject.toml`, `python/uv.lock`)

**Files:**
- Modify: `python/pyproject.toml`
- Modify: `python/uv.lock`

- [ ] **Step 1: Inspect `python/pyproject.toml` and verify `yt-dlp` pin**

Confirm `yt-dlp==2026.11.23` stays pinned in `acquisition` extra, and add `"yt-dlp-ejs>=0.8.0,<1"` next to it.

- [ ] **Step 2: Regenerate `python/uv.lock` from WSL**

```bash
uv lock --project python
```
Inspect `git diff python/pyproject.toml python/uv.lock` to verify ONLY `yt-dlp-ejs` (and its minimal deps, if any) changed and `yt-dlp` remains `2026.11.23`.

- [ ] **Step 3: Run targeted tests and lint**

```bash
make test T="tests/footage/test_clip_adapters.py"
make lint
```

- [ ] **Step 4: Commit Task 1**

```bash
git add python/pyproject.toml python/uv.lock
git commit -m "build(deps): add yt-dlp-ejs for youtube js challenge solving"
```

---

## Task 2: Serialized TikWm Pacing, Bounded Footage Timeout & Single Retry (`tikwm.py`, `activities/footage.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/adapters/tikwm.py`
- Modify: `python/src/thoth_control_plane/activities/footage.py`
- Test: `python/tests/acquisition/test_service.py` (or dedicated `python/tests/acquisition/test_tikwm.py` — check existing location of `test_rate_gate_waits_out_the_remainder_of_one_second`)

- [ ] **Step 1: Write failing tests covering Spec §3.1**

Add unit tests verifying:
1. `TikWmRateGate()` default `min_interval_seconds` remains `1.0` (`test_rate_gate_waits_out_the_remainder_of_one_second` stays untouched and green), while `SHARED_TIKWM_RATE_GATE._min_interval_seconds == 1.2`.
2. `TikWmRateGate.hold(clock, sleep)` serializes 3 concurrent tasks: max in-flight count is strictly `1`, and each subsequent caller sleeps `min_interval_seconds` measured from the *end* of the previous request (`_last_end`).
3. `TikWmResolver.resolve()` retries **once** after `rate_limit_backoff` when TikWm answers `code = -1` (`cdn_rate_limited`), returning the resolved media if attempt 2 succeeds, and raising `TikWmError("cdn_rate_limited")` if attempt 2 also rate-limits.
4. `TikWmResolver.resolve()` does **NOT** retry `TikWmError("cdn_unavailable")` (e.g. HTTP 502 or timeout) — exactly 1 HTTP request is made.
5. `FOOTAGE_TIKWM_TIMEOUT == 20.0` in `activities/footage.py`, passed to `TikWmResolver(..., timeout_seconds=FOOTAGE_TIKWM_TIMEOUT)` inside `_tiktok_direct_url`.

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/acquisition/test_service.py"
```

- [ ] **Step 3: Implement changes in `tikwm.py` and `activities/footage.py`**

Implement per Spec §3.1:
- Keep `TikWmRateGate.__init__(self, min_interval_seconds: float = 1.0)` and `wait()` unchanged.
- Add `_last_end: float | None = None` and `@asynccontextmanager async def hold(self, clock, sleep)` holding `self._lock` for the full request and updating `_last_end = clock()` in `finally`.
- Set `SHARED_TIKWM_RATE_GATE = TikWmRateGate(min_interval_seconds=1.2)`.
- Add `RATE_LIMIT_BACKOFF_SECONDS = 2.5`.
- On `TikWmResolver.__init__`, add `timeout_seconds: float = REQUEST_TIMEOUT_SECONDS` and `rate_limit_backoff: float = RATE_LIMIT_BACKOFF_SECONDS`.
- In `TikWmResolver.resolve()`, run the HTTP call inside `async with self._rate_gate.hold(self._clock, self._sleep):`; on `TikWmError("cdn_rate_limited")` on attempt 0, `await self._sleep(self._rate_limit_backoff)` outside the lock and retry once.
- In `activities/footage.py`, define `FOOTAGE_TIKWM_TIMEOUT = 20.0` and use it for both `httpx.AsyncClient(timeout=FOOTAGE_TIKWM_TIMEOUT)` and `TikWmResolver(client, timeout_seconds=FOOTAGE_TIKWM_TIMEOUT)` in `_tiktok_direct_url`.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/acquisition/test_service.py"
make lint
```

- [ ] **Step 5: Commit Task 2**

```bash
git add python/src/thoth_control_plane/acquisition/adapters/tikwm.py python/src/thoth_control_plane/activities/footage.py python/tests/acquisition/
git commit -m "fix(acquisition): serialize tikwm calls and retry once on rate limit"
```

---

## Task 3: Budgeted `YtDlpClipDownloader` (`js_runtimes`, `tikwm_<code>` Causes & Leased Fallback)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/adapters/downloader.py`
- Modify: `python/src/thoth_control_plane/activities/footage.py`
- Test: `python/tests/footage/test_clip_adapters.py`

- [ ] **Step 1: Write failing tests in `python/tests/footage/test_clip_adapters.py`**

Add tests covering Spec §3.2 & §5.1:
1. Direct `yt-dlp` options always include `"js_runtimes": {"bun": {}}` and `"proxy": ""`.
2. When `_resolve_tiktok` raises `TikWmError("cdn_rate_limited")` (or `"cdn_unavailable"`) with no fallback configured, `download()` raises `ClipError("tikwm_cdn_rate_limited")` (or `"tikwm_cdn_unavailable"`) without leaking any URL.
3. TikTok fallback: when `_resolve_tiktok` fails OR direct CDN download fails, `fallback_session("tiktok", scratch)` is called with a **separate** scratch directory from the direct attempt, and `yt-dlp` runs on the original TikTok URL with `{**base_options, **extra}` (overriding `"proxy"`).
4. YouTube fallback: using `platform_of(url)` (test both `https://www.youtube.com/watch?v=...` and `https://youtu.be/...`), direct failures `bot_check`, `http_403`, and `http_429` trigger `fallback_session("youtube", scratch)`; non-block failure (`"no file"` or generic error) does NOT trigger fallback.
5. Wall-clock budget: when `fallback_session` is set, direct attempt timeout is capped at `min(DIRECT_FALLBACK_CAP_SECONDS, remaining)` (`40.0 s`); if remaining time `< MIN_FALLBACK_SECONDS` (`10.0 s`), fallback is skipped and the direct `ClipError` is raised.
6. Production `_fallback_session` helper in `activities/footage.py` (tested with fake `StoreLeases`):
   - Uses profile-free `StoreLeases(accounts)` (no profile unseal/seal).
   - Yields `None` without calling `lease()` when `mode(platform) == "anonymous"`.
   - Releases with `"success"` on normal exit, `"rate_limited"` on `ClipError("http_429")`, `"blocked"` on `ClipError("bot_check")` or `ClipError("http_403")`, and `None` on other errors (`ClipError("TimeoutError")`, `ClipError("no file")`, `CancelledError`).

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/footage/test_clip_adapters.py"
```

- [ ] **Step 3: Implement changes in `downloader.py` and `activities/footage.py`**

Implement per Spec §3.2 & §5.1:
- Add `"js_runtimes": {"bun": {}}` to base `yt-dlp` options in `YtDlpClipDownloader`.
- Use `platform_of(url)` from `acquisition/platforms.py` for `"tiktok"` and `"youtube"` detection.
- Extract internal helper `_run_attempt(url, window, target, timeout, extra_options)` using its own `tempfile.TemporaryDirectory(prefix="thoth-footage-", dir=target.parent, ignore_cleanup_errors=True)` per attempt.
- Track shared `deadline = time.monotonic() + self._timeout`; cap direct attempt at `min(DIRECT_FALLBACK_CAP_SECONDS, remaining)` (`40.0 s`) when `self._fallback_session` is set; run fallback only when `remaining >= MIN_FALLBACK_SECONDS` (`10.0 s`) and raise `ClipError(cause)` *out of* `async with self._fallback_session(...)` so `__aexit__` inspects the cause cleanly.
- In `activities/footage.py`: add clean `_download_fallback_session(leases)` factory backed by profile-free `StoreLeases(accounts)` checking `mode(platform) == "anonymous"` first and mapping `Outcome` exactly per Spec §3.2. Wire into `YtDlpClipDownloader(..., fallback_session=...)` inside `build_production_footage`.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/test_clip_adapters.py"
make lint
```

- [ ] **Step 5: Commit Task 3**

```bash
git add python/src/thoth_control_plane/footage/adapters/downloader.py python/src/thoth_control_plane/activities/footage.py python/tests/footage/test_clip_adapters.py
git commit -m "feat(footage): add js runtimes and leased proxy fallback to clip downloader"
```

---

## Task 4: Richer Credit & Platform Detection (`footage/reposts.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/reposts.py`
- Test: `python/tests/footage/test_reposts.py`

- [ ] **Step 1: Write failing tests in `python/tests/footage/test_reposts.py`**

Add tests covering Spec §4.1:
1. `credited_source()` parses:
   - `"Sumber YT : Ernest Prakasa"` → `CreditRef("ernestprakasa", "Ernest Prakasa", "youtube")`
   - `"Source YT: Rhenald Kasali"` → `CreditRef("rhenaldkasali", "Rhenald Kasali", "youtube")`
   - `"Sumber: YouTube Kompas TV | FFI 2026"` → `CreditRef("kompastv", "Kompas TV", "youtube")`
   - `"sc: KompasTV"` → `CreditRef("kompastv", "KompasTV", None)`
   - `"kredit: TVR Parlemen"` → `CreditRef("tvrparlemen", "TVR Parlemen", None)`
   - `"yt: DPR RI"` → `CreditRef("dprri", "DPR RI", "youtube")`
   - `"Master Saiful ngamuk cr: @denny.sumargo"` → `CreditRef("denny.sumargo", "denny.sumargo", None)` (preserves dot! Existing `credited_account` test at `test_reposts.py:38` stays green!)
   - `"via YouTube/CURHAT BANG Denny Sumargo"` → `CreditRef(..., platform="youtube")`
   - `"via @kompastv"` → `CreditRef("kompastv", "kompastv", None)`
2. Explicit YouTube named credit beats an earlier bare `@handle`:
   - `"@ernestprakasa Sumber: YouTube Kompas TV"` → `CreditRef("kompastv", "Kompas TV", "youtube")`
3. Rejects URLs and Indonesian prose false positives:
   - `"Model Source: https://makerworld.com/en/models/123"` → `None`
   - `"Sumber: www.kompas.com"` → `None`
   - `"Merbabu via Tekhelan — jalur bersahabat"` → `None`
   - `"Pesan via WA atau via chat atau via transfer atau via link"` → `None`
   - `"cr: @akun"` → `None` (placeholder rejected)

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/footage/test_reposts.py"
```

- [ ] **Step 3: Implement `CreditRef` and `credited_source` in `footage/reposts.py`**

Implement per Spec §4.1, keeping `credited_account(text)` delegating cleanly to `credited_source(text)`.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/test_reposts.py"
make lint
```

- [ ] **Step 5: Commit Task 4**

```bash
git add python/src/thoth_control_plane/footage/reposts.py python/tests/footage/test_reposts.py
git commit -m "feat(footage): parse indonesian credit prefixes and explicit platforms"
```

---

## Task 5: Trace YouTube Credits Past `kept >= 16` + Cached Search Fallback (`footage/service.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py`
- Test: `python/tests/footage/test_service.py`

- [ ] **Step 1: Write failing tests in `python/tests/footage/test_service.py`**

Add tests covering Spec §4.2:
1. When `>= 16` (`MAX_FOOTAGE * 2`) pending candidates already exist:
   - A candidate crediting `"Sumber: YouTube Kompas TV"` IS still traced (`platform == "youtube"`), up to `MAX_TRACE_LISTINGS = 3`.
   - A candidate crediting a same-platform TikTok handle (`"@other_tiktok"`) is skipped when `kept >= 16`.
2. When `listing_of("youtube", ...)` returns `None`, empty, or 0 on-story originals:
   - `_trace()` checks `store.cached_search("youtube", query)` first, falls back to `search.search("youtube", [query], RESULTS_PER_QUERY)`, saves via `store.save_search`, caches combined results in `listings[key]` (a second candidate crediting the same channel does not re-search), adds matching videos (including long videos `long_ok=True`) as `source="trace"` with `OWN_SCORE`, and rejects the TikTok repost as `"repost"`.
   - A non-`ToolMissing` error from `search.search` degrades cleanly (logs warning, does not fail the run).
   - Rejected rows from `listing_of` (e.g., `"main"`) are preserved (`test_a_traced_original_that_is_the_main_post_is_rejected_main` stays green).
3. A long YouTube video added by `_trace()` is picked up and cut into sections by `_sections()`.

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/footage/test_service.py"
```

- [ ] **Step 3: Implement `_trace()` upgrades in `footage/service.py`**

Implement per Spec §4.2:
- Use `credited_source(c.caption)`.
- Keep `if self._ports.creator is None: return`.
- Compute `full = kept >= MAX_FOOTAGE * 2`; when `full`, skip only candidates whose resolved `platform != "youtube"`.
- Build helper `_trace_query(display: str, card: ContextCard) -> str` combining `ref.display` + up to 2–3 distinctive terms from `card` (`<= 80` chars).
- On `platform == "youtube"` with 0 pending on-story originals from `listing_of`, perform cached YouTube fallback search (`cached_search` / `search.search("youtube", [query], RESULTS_PER_QUERY)` / `save_search`), preserving rejected rows from `listing_of`.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/test_service.py"
make lint
```

- [ ] **Step 5: Commit Task 5**

```bash
git add python/src/thoth_control_plane/footage/service.py python/tests/footage/test_service.py
git commit -m "feat(footage): trace youtube credits past queue cap with search fallback"
```

---

## Task 6: Multi-Hour YouTube `chapters` + `heatmap` + `id*`/`en` Captions (`captions.py`, `moments.py`, `service.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/moments.py`
- Modify: `python/src/thoth_control_plane/footage/adapters/captions.py`
- Modify: `python/src/thoth_control_plane/footage/service.py`
- Test: `python/tests/footage/test_moments.py`
- Test: `python/tests/footage/test_service.py`

- [ ] **Step 1: Write failing tests in `test_moments.py` and `test_service.py`**

Add tests covering Spec §5.2:
1. `parse_chapters` & `parse_heatmap`: parse valid yt-dlp entries and ignore malformed items.
2. `_json3_url`:
   - `subtitles["id"]` beats `automatic_captions["en"]` (language-outer loop!).
   - `"id-orig"` matches when exact `"id"` is missing.
   - `"en"` / `"en-US"` matches when no `"id"`/`"id-*"` track exists.
3. `YtDlpCaptionFetcher.hints()`:
   - Calls `client.extract(url, comments=False)` **once** and returns `LongVideoHints(captions, chapters, heatmap)`.
   - Still returns `chapters` and `heatmap` when no caption track exists (`captions is None`).
   - `captions()` delegates cleanly and stays backward-compatible.
4. `pick_discussions()`:
   - Transcript + matching chapter gets `+2` `CHAPTER_BOOST` (still requires `MIN_WORDS = 2`).
   - Transcript + `HeatPoint(value >= 0.7)` snaps `moment` inside the 60 s window to the peak line.
   - Chapter-only fallback (empty `lines` or 0 transcript windows matched):
     - Safe bounds `[low, high] = [max(chapter.start + 1.0, 30.0), chapter.end - 7.0]`: skips chapters where `high < low` (short chapter < 8 s or ending before 37 s).
     - Enforces `subject` requirement when `subject` is non-empty (incident card strictness), and scores `others` + `words` when `subject == []` (commentary card, e.g. FFI ceremony chapter `"Pidato Pemenang Film Terbaik Para Perasuk"`!).
     - Snaps to highest-`value` overlapping `HeatPoint` midpoint clamped to `[low, high]`; without heatmap, picks `min(low + 5.0, high)`.
     - Enforces `APART_SECONDS = 60.0` and returns results **sorted chronologically ascending by `moment`**.
5. `_sections()` in `test_service.py`:
   - Works with a `hints()`-capable port when `captions is None` and `chapters` has a matching FFI ceremony chapter (sets `visual = c.visual or PERSON_VISUAL` when `not discussion.said`).
   - Continues working with legacy `captions()`-only stubs (`visual == PERSON_VISUAL` when `discussion.said` is non-empty).

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/footage/test_moments.py tests/footage/test_service.py"
```

- [ ] **Step 3: Implement changes in `moments.py`, `captions.py`, and `service.py`**

Implement per Spec §5.2:
- Add `Chapter`, `HeatPoint`, `LongVideoHints`, `parse_chapters`, `parse_heatmap`, `CHAPTER_BOOST = 2`, `HEAT_PEAK = 0.7`, `CHAPTER_OFFSET = 5.0` in `footage/moments.py`, and extend `pick_discussions()` with `chapters=(), heatmap=()`.
- Update `_json3_url` (language-outer, sources-inner) and add `hints()` on `YtDlpCaptionFetcher` in `footage/adapters/captions.py`.
- Update `_sections()` in `footage/service.py` to use `hints()` when available (falling back to `captions()`), pass `chapters` & `heatmap` into `pick_discussions`, and choose `PERSON_VISUAL if discussion.said else (c.visual or PERSON_VISUAL)`.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/"
make lint
```

- [ ] **Step 5: Commit Task 6**

```bash
git add python/src/thoth_control_plane/footage/moments.py python/src/thoth_control_plane/footage/adapters/captions.py python/src/thoth_control_plane/footage/service.py python/tests/footage/test_moments.py python/tests/footage/test_service.py
git commit -m "feat(footage): use youtube chapters, heatmap and caption fallback for sections"
```

---

## Task 7: Full Verification, Graphify Update, Checkpoint & `CHANGELOG.md`

**Files:**
- Track spec & plan (force-add since `docs/superpowers/` is gitignored):
  - `docs/superpowers/specs/2026-11-27-footage-sourcing-v2-design.md`
  - `docs/superpowers/plans/2026-11-27-footage-sourcing-v2.md`
- Update: `CHANGELOG.md`
- Create/Update: `.superpowers/sdd/2026-11-27-footage-sourcing-v2/progress.md` (untracked/gitignored checkpoint; do not commit)

- [ ] **Step 1: Run full verification suite**

```bash
make lint
make test
make dashboard-test
make dashboard-build
```
Check every exit code explicitly; fix any failure test-first before proceeding.

- [ ] **Step 2: Refresh local code index**

Run `graphify update .` (never stage `graphify-out/`, `.codegraph/`, or `.superpowers/`).

- [ ] **Step 3: Record completion in `CHANGELOG.md` and `.superpowers/sdd/2026-11-27-footage-sourcing-v2/progress.md`**

Include verification evidence, commit list, and a **Next steps** section listing:
- Push `feat/footage-sourcing-v2` & open PR (pending operator authorization);
- Wait for CI green & deploy branch CI image to stage1 (pending operator authorization);
- Live acceptance test on the official **FFI YouTube channel** multi-hour ceremony video — verify surgical timestamp detection + range-only cut of the award winner's speech mentioning Fadli Zon (and TikTok fallback download), with cost shown first (pending operator authorization);
- Merge PR after operator acceptance.

- [ ] **Step 4: Commit docs & spec/plan**

```bash
git add -f docs/superpowers/specs/2026-11-27-footage-sourcing-v2-design.md docs/superpowers/plans/2026-11-27-footage-sourcing-v2.md
git add CHANGELOG.md
git commit -m "docs: record footage sourcing v2 implementation"
```

- [ ] **Step 5: Hard stop & report back for review**

Do NOT push, open a PR, merge, deploy, or run live/paid calls.
