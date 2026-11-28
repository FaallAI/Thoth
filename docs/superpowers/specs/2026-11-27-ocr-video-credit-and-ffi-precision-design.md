# OCR In-Video Credit Tracing & Commentary Precision Fixes

**Date:** 2026-11-27
**Status:** Approved (operator, 2026-11-27)
**Branch:** `feat/footage-sourcing-v2` (PR #147 refinement before merge)
**Brainstorm log:** `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md` (items 118–120)

---

## 1. Problem & Live Evidence (`wf_aea765e4a89a42014e0135a2`)

Live testing of PR #147 on `https://www.instagram.com/p/DgFu-6szNpk/` (`@ernestprakasa`, run `wf_aea765e4a89a42014e0135a2`) proved Package A's TikWm fix (0 `TikWmError` losses out of 40+ TikTok clips), but failed to retrieve the actual FFI 2026 protest / Siera Tamihardja stage moment (operator reference: `@jawaposofficial/video/7710453760140643585`) while admitting two off-topic FFI vlogs (`@wulanguritno81`, `@theidnpageant`).

Four verified root causes in `wf_aea765e4`:

1. **Burned-in video credits on rejected subtitled news reposts are thrown away:**
   - 20 TikTok news clips of the actual FFI 2026 protest / Siera Tamihardja moment (`@suaradotcom` ×2, `@whatpop.id`, `@besokajanonton`, `@freakind.official`, etc.) were downloaded and read by `analyze_main_ocr` (`RapidOcrReader`), then rejected as `"subtitle"` with all extracted OCR text discarded.
   - News reposts like `@jawaposofficial` and `@suaradotcom` routinely burn `"Sumber: YouTube / Festival Film Indonesia"` or `"Dok. YouTube/FFI"` into a frame corner rather than writing it in the caption. Extracting those credits from the already-read OCR text costs **zero extra OCR compute** and leads directly to the clean, unsubtitled official YouTube source for `_sections()` surgical cutting.
2. **Context Card prompt drift dropped key transcript figures & sub-events:**
   - `OpenRouterCardModel` already sends `"temperature": 0` (`footage/adapters/context_model.py:62`), yet provider/prompt drift on the exact same Ernest post caused `wf_af610964` to extract `[Ernest, Fadli Zon, Irini Dewi Wanti, Siera Tamihardja]` + `"aksi sineas FFI 2026 salam 3 jari"`, whereas `wf_aea765e4` extracted only `[Ernest Prakasa, Irini Dewi Wanti]` — omitting Fadli Zon, Siera Tamihardja, and `"3 jari"` completely, which caused `youtube/@tribunkaltimofficial` (*"Menang Piala Citra! Produser Film Para Perasuk Kritik Fadli Zon..."*) to be rejected `"story"` again.
3. **Generic FFI vlogs (`@wulanguritno81`, `@theidnpageant`) passed `story` + Vision and starved real protest clips:**
   - Both vlogs matched only `"FFI"` + `"2026"` (no card person, no controversy/topic word), yet passed `context_reason()`.
   - Because their query `"Irini Dewi Wanti FFI 2026"` named a person, `context_objects()` collapsed `visual` to `PERSON_VISUAL = "a person on camera"` (`footage/context.py:382-383`), so Vision accepted Wulan Guritno speaking in a room and an unrelated award winner hugging on stage.
   - Those two wrong clips immediately filled `PER_QUERY = 2` for `"Irini Dewi Wanti FFI 2026"`, leaving two spot-on YouTube clips in the same queue (`@MediaCakra` *"Sentilan Keras Siera Tamihardja untuk Fadli Zon di Panggung FFI 2026"* and `@tribunnews` *"Sejumlah Sineas Gunakan Panggung FFI 2026 untuk Suarakan Protes"*) stranded as `pending` until the run ended.
4. **YouTube videos between 3 and 15 minutes bypassed `_sections()`:**
   - `footage/service.py:931-999` only cuts YouTube videos longer than `MAX_SECONDS` (`900.0 s` = 15 min), so 4–9 minute YouTube speech/news clips (`259 s`–`516 s`) skipped `_sections()` and ran arbitrary `clip_window()` downloads instead of surgical moment cuts.

---

## 2. Scope, Goals & Non-Goals

**Approved direction (operator, 2026-11-27: `"ya setuju"`):** Add all 4 tightly scoped fixes directly to active branch `feat/footage-sourcing-v2` (PR #147) before re-testing live and merging.

**Goals:**
1. Capture per-frame OCR text already read by `analyze_main_ocr` on footage clips (zero extra OCR passes), parse burned-in source credits (ignoring bare uploader watermarks & generic labels like `"Istimewa"` / `"Pribadi"`), trace those sources via existing `_trace_listing` + cached `_trace_search`, cut long originals via re-entrant `_sections()`, and inject clean originals/sections into a dedicated `ocr_trace` queue so they are screened on the very next batch.
2. Strengthen `CARD_PROMPT` and `REFINE_PROMPT` so commentary cards reliably scan the entire transcript for every discussed figure/controversy and absorb newly surfacing viral figures/moments in Round 2.
3. Block generic event vlogs on `commentary` cards from passing `story` without a card person or topic/controversy signal (while keeping all existing `ffi_candidates.json`, `test_context.py`, and `test_service.py` tests green), and stop collapsing commentary event-figure queries to `"a person on camera"`.
4. Lower YouTube `_sections()` threshold to `180.0 s` (3 min), prioritize `> 900 s` ceremonies ahead of `180–900 s` medium videos inside `MAX_LONG_VIDEOS = 6`, track already-sectioned URLs so `_sections()` is safely re-entrant, and keep `180–900 s` videos `pending` as fallback when 0 sections match.

**Non-Goals:**
- No relaxation of the `"subtitle"` / `"overlay"` rejection gate (clean originals from YouTube via OCR credit tracing remain the quality bar).
- No changes to `MainOcr` Pydantic schema, `EditDocumentV2`, Remotion composition, OpenAPI, `context_model.py`, or database migrations.
- No extra OCR passes or extra frame extractions per clip.

---

## 3. Detailed Design

### 3.1 Capture Per-Frame OCR Text Without Extra Compute (`assembly/ocr.py`)

Add an optional keyword-only parameter to `analyze_main_ocr()` (`assembly/ocr.py:136-151`):

```python
collected_frames: list[list[str]] | None = None,
```

Right after coverage verification (`assembly/ocr.py:173`, before `classify_ocr_frames` at line 175):
- If `collected_frames is not None`: append `[text for box in frame.boxes if (text := box.text.strip())]` for each `frame` in `read` (skipping empty frames).
- Keeping per-frame lists preserves adjacent box order within each frame (preventing a blurred earlier frame from breaking a two-box corner credit like `["Sumber:", "YouTube / FFI"]` on a later clear frame).
- Zero extra OCR calls, zero extra frame extractions, zero changes to `MainOcr`, and 100% compatible with all existing callers and test monkeypatches (`*args, **kwargs`).

### 3.2 Parse Burned-In Frame Credits (`footage/reposts.py`)

1. **Extend `NAMED_CREDIT` with guarded `dok` / `dok.` (`footage/reposts.py:32-38`):**
   - Add word-bounded `dok` support:
     - Colon form: `sumber|source|kredit|credit|cr|sc|dok\.?` (matches `"Dok: YouTube/FFI"`, `"Dok.: KompasTV"`).
     - Period + platform/handle form: `\bdok\.\s+(?=@|(?:{_PLATFORM})\b)` (matches `"Dok. YouTube Festival Film Indonesia"`, `"Dok. @festivalfilm_id"` while **blocking** `"dokter"`, `"dokumen"`, `"dokumenter"`, `"Dok. Pribadi"`, `"Dok. Istimewa"`!).
2. **Extract explicit-credit helper `_explicit_credit(text: str) -> CreditRef | None`:**
   - Runs ONLY `text_rule_credit(text)` and `NAMED_CREDIT.finditer(text)` — **never** falls back to bare `text_handles(text)`!
   - `credited_source(text)` calls `_explicit_credit(text)` first, then falls back to `text_handles(text)` (exact existing behavior for captions).
3. **Add `frame_credited_source(frames: Sequence[Sequence[str]]) -> CreditRef | None`:**
   - Non-account Indonesian corner labels rejected in frame credits: `FRAME_PLACEHOLDERS = PLACEHOLDERS | frozenset({"istimewa", "pribadi", "dokumentasi", "arsip", "net", "internet", "repro", "dokpribadi", "dokistimewa"})`.
   - For each frame's lines `lines`:
     - Build explicit-credit candidates from:
       1. each single line `line`, and
       2. adjacent pairs `(a, b)` where `a` matches a credit prefix (`_CREDIT_PREFIX`: `sumber`, `source`, `kredit`, `credit`, `cr`, `sc`, `dok\.?`, `via`, `youtube`, `yt`, optionally followed by platform word and/or `:` or `/`). If `a` already ends with `:` or `/`, join as `f"{a} {b}"`; otherwise insert `:` (`f"{a}: {b}"`) so colon-less split boxes like `["Sumber", "YouTube Festival Film Indonesia"]` or `["YouTube", "Festival Film Indonesia"]` match `NAMED_CREDIT`!
     - Run `_explicit_credit(candidate)` on each candidate; reject if `normalize(ref.account) in FRAME_PLACEHOLDERS`.
     - Prefer the first `ref.platform == "youtube"` match across frames; otherwise return the first valid explicit match (never a bare uploader `@handle` watermark!).

### 3.3 Live OCR-Credit Tracing & Dedicated Queue Injection (`footage/service.py`)

1. **State on `_Build` (`footage/service.py:186-218`):**
   - `traced_keys: set[tuple[str, str]] = field(default_factory=set)` — shared between pre-check `_trace()` and mid-check `_trace_ocr_credits()` so an account already traced from captions is never re-traced from OCR.
   - `ocr_credits: list[tuple[CandidateView, CreditRef]] = field(default_factory=list)`
   - `ocr_traced_count: int = 0`
   - `sectioned: set[str] = field(default_factory=set)` — URLs already inspected by `_sections()` (making `_sections()` safely re-entrant).
   - Constants: `MAX_OCR_TRACES = 3`, `OCR_TRACED = "ocr_trace"`.
2. **Dedicated quota key for OCR-traced items (`quota_key`):**
   - Update `quota_key(candidate)` (`footage/service.py:339`):
     - `if candidate.source == "section": return SECTIONS`
     - `if candidate.source == "ocr_trace": return OCR_TRACED`
     - `return candidate.query`
   - Also keep `OCR_TRACED` in `queues` inside `_check_all()`. Why: OCR-traced clean YouTube originals start at `admitted[OCR_TRACED] == 0`, so `select_batch()` picks them **immediately** on the next batch and can NEVER starve or skip them when `repost.query` or `SECTIONS` is already at `PER_QUERY = 2`!
   - When `_sections()` cuts a video whose `c.source == "ocr_trace"`, assign `query=OCR_TRACED` and `source="ocr_trace"` (or allow `SECTIONS` / `OCR_TRACED` — keeping `source="section"` with `query=OCR_TRACED`? Careful: `candidate.source == "section"` skips `commentary` vision rejection at line 1331 and sets `person=True` at line 1257! So keep `source="section"` for cut sections, and route sections cut from `ocr_trace` parents into `OCR_TRACED` by checking `OCR_TRACED if candidate.query == OCR_TRACED else SECTIONS` inside `quota_key()`! That preserves `source == "section"` behavior while giving OCR-traced sections their own fresh `OCR_TRACED` quota!).
3. **Collect inside `_check()` (`footage/service.py:1357-1375`):**
   - Pass `collected_frames=ocr_frames` into `analyze_main_ocr(...)` when `state.card is not None and candidate.source != "carousel"`.
   - When `ocr.outcome in ("subtitle", "overlay")`:
     - If `ocr_frames` and `state.card is not None`:
       - Call `ref = frame_credited_source(ocr_frames)`.
       - If `ref is not None` and `normalize(ref.account) != normalize(candidate.owner_handle)`:
         - Append `(candidate, ref)` to `state.ocr_credits`.
     - Reject the dirty clip as `"subtitle"` as before (zero network I/O inside `_timed()`'s 90-second budget).
4. **Trace & inject between batches in `_check_all()` (`footage/service.py:1209-1275`):**
   - Pass `identity: MainIdentity` into `_check_all()` (already built in `_build()` at line 527; for carousel branch, construct or pass `None` since carousel never traces).
   - Track `total_pending = len(pending)` and increment `total_pending += len(injected)` whenever `_trace_ocr_credits()` injects new candidates, so `progress.step("footage.screen_clips", n=screened, total=total_pending)` never overruns `n > total`.
   - Between batches (after `state.displaced.clear()`), if `state.ocr_credits` is non-empty and `state.card is not None` and `self._ports.creator is not None` and `identity is not None` and `total < MAX_FOOTAGE` and `time.monotonic() - started < self._deadline`:
     - Call `injected = await self._trace_ocr_credits(workflow, main, identity, state, queues)`.
   - Inside `_trace_ocr_credits`:
     - Drain `credits = list(state.ocr_credits); state.ocr_credits.clear()`.
     - Sort `credits` so `ref.platform == "youtube"` runs first.
     - For each `(repost, ref)` while `state.ocr_traced_count < MAX_OCR_TRACES`:
       - Resolve `platform = ref.platform or ("youtube" if "youtube" in ref.display.lower() else repost.platform)`.
       - Skip if `platform not in CREATOR_PLATFORMS` or `normalize(ref.account) == normalize(repost.owner_handle)`.
       - `key = (platform, normalize(ref.account))` — skip if `key in state.traced_keys`.
       - Add `key` to `state.traced_keys`; increment `state.ocr_traced_count`.
       - Reuse `_trace_listing(platform, ref.account)` + `_trace_rows(...)` (with `source="ocr_trace"`, `query=OCR_TRACED`) + cached YouTube `_trace_search(trace_query(ref.display, state.card))` fallback when `platform == "youtube"` and 0 pending originals came from listing.
       - Persist new rows via `add_candidates`, score pending originals `OWN_SCORE`.
     - If any new pending YouTube originals have `(source_duration or 0.0) > LONG_SECTION_SECONDS`, call `await self._sections(workflow, state.card, state.sectioned)`.
     - Reload newly added `status == "pending"` video candidates whose URL is not yet in `known_queued`, prepend them to `queues.setdefault(quota_key(c), [])`, increment `total_pending`, and log `logger.info("footage ocr trace credits=%d added=%d", traced_now, len(injected))`.

### 3.4 Context Card Stability & Commentary Precision (`footage/context.py`)

1. **`CARD_PROMPT` & `REFINE_PROMPT` (`footage/context.py:35-78`):**
   - `CARD_PROMPT` commentary rules: explicitly instruct the model to **read the entire `transcript` from start to finish** (not only the opening sentence) and list in `people[1:]` **every public figure named anywhere in the transcript or caption** (e.g., both the official replied to AND any minister/figure cited in the argument), plus include the specific historical/protest event or gesture cited in `queries` and `related`.
   - `REFINE_PROMPT`: explicitly instruct Round 2 to **add any newly surfacing key figures, award winners, films, or protest gestures repeated in `results` titles** (e.g., `"Siera Tamihardja"`, `"Para Perasuk"`, `"salam 3 jari"`) to `people` and `related`.
2. **Stop collapsing commentary event-figure queries to `PERSON_VISUAL` (`footage/context.py:context_objects`):**
   - On `card.main_kind == "incident"` (default): 100% unchanged (`elif person: visual = PERSON_VISUAL`).
   - On `card.main_kind == "commentary"`: use `PERSON_VISUAL` **only** when the query targets `people[0]` alone (`names_subject(norm(query), card)` and no `discussed_names` and no `has_event_term`). For event/discussed-figure queries (`"Irini Dewi Wanti FFI 2026"`, `"Pernyataan Fadli Zon FFI 2026"`), use `strip_names(card.event, card) or DEFAULT_VISUAL` while keeping `person=True` (`PERSON_PROMPT` still treats real speakers/officials on camera as `kind="footage"`, while `shows_object` actually checks the controversy/event instead of `"a person on camera"`).
3. **Block generic event vlogs in `context_reason()` (`footage/context.py`):**
   - Add pure helper `_topic_signals(card: ContextCard) -> set[str]`:
     - `named = _named_words(card)`
     - `ev = set(event_terms(card))`
     - `query_words = {w for text in (*card.queries, *(r.query for r in card.related)) for w in content_words(text)} - named - ev - {"indonesia", "indonesian"}`
     - Return `set(card.spoken) | query_words`.
   - On `card.main_kind == "commentary"`, when `signals = _topic_signals(card)` is non-empty and a candidate names **neither** `people[0]` (`names_subject`) **nor** any `people[1:]` (`names_discussed_with_context`):
     - Passing via `card.event + card.place` or a single `related.event` requires:
       - the existing `_event_match` (`>= 2` non-person terms, year+place guarded), **AND**
       - **either** `>= 1` whole word from `signals` (`any(_says(said, w) for w in signals)`) **OR** `>= 3` matched non-person terms including `>= 2` non-year terms!
   - **Verified against all existing fixtures & live cases:**
     - `@wulanguritno81` (*"Semalam menghadiri Festival Film Indonesia 2026..."*): 0 people, 0 `signals`, only 2 terms (`ffi`+`2026`) → **rejected `"story"`**!
     - `@theidnpageant` (*"Peraih penghargaan pemeran utama perempuan terbaik Festival Film Indonesia 2026"*): 0 people, 0 `signals`, only 2 terms (`ffi`+`2026`) → **rejected `"story"`**!
     - `STAGE = "Sineas acungkan 3 jari di panggung FFI 2026"` (`test_service.py:2732` with query `"FFI 2026 3 jari"`): matches `"jari"` in `signals` → **passes (zero existing test regressions!)**
     - All 9 `FFI_ON_STORY` captions in `ffi_candidates.json` → **all 9 pass**!
   - When `card.main_kind == "incident"` or `_topic_signals(card)` is empty: 100% unchanged.

### 3.5 Lower YouTube `_sections()` Threshold & Safe Re-Entrancy (`footage/service.py`)

- Add `LONG_SECTION_SECONDS = 180.0` (3 minutes) in `footage/service.py` (leaving `MAX_SECONDS = 900.0` in `footage/gates.py` untouched).
- Update `_sections(self, workflow: str, card: ContextCard, sectioned: set[str] | None = None) -> None` (`footage/service.py:931-999`):
  - Track `already = sectioned if sectioned is not None else set()`.
  - Sort eligible pending YouTube videos (`duration > LONG_SECTION_SECONDS`, `SECTION_MARK not in c.url`, `c.url not in already`) by:
    `key=lambda c: (-(c.story_score or 0.0), (c.source_duration or 0.0) <= MAX_SECONDS)`
    so `> 900 s` ceremonies (which cannot fall back to `clip_window()`) always take priority over `180–900 s` medium videos inside `MAX_LONG_VIDEOS = 6`!
  - Add `c.url` to `already` once inspected (`hints()` called) so a second `_sections()` call from `_trace_ocr_credits()` NEVER re-fetches `hints()` for previously inspected `180–900 s` videos.
  - When building section rows for a parent with `c.query == OCR_TRACED`, preserve `query=OCR_TRACED` so the cut sections enter the fresh `OCR_TRACED` queue (while keeping `source="section"`).
  - Rejection rule after cutting:
    - If `rows` (sections) were created **OR** `(c.source_duration or 0.0) > MAX_SECONDS`: reject parent as `"duration"` (same as today for `> 900 s`, and replaced by surgical sections for `180–900 s`).
    - If `0` sections were created AND `(c.source_duration or 0.0) <= MAX_SECONDS`: leave parent `pending` so `clip_window()` remains a safe fallback!

---

## 4. Verification Plan

1. **Offline unit & replay tests (test-first):**
   - `python/tests/assembly/test_ocr.py`: `analyze_main_ocr(..., collected_frames=out)` populates per-frame text lists with zero extra `text.read` calls; `collected_frames=None` unchanged.
   - `python/tests/footage/test_reposts.py`: `frame_credited_source` parses single-line (`"Dok. YouTube Festival Film Indonesia"`, `"Sumber: YT/FFI"`), colon-less split two-box credits (`["Sumber", "YouTube Festival Film Indonesia"]`), prefers YouTube over other platforms, rejects bare `@jawaposofficial` watermarks, `"dokter"`/`"dokumen"`, `"Dok. Pribadi"`, `"Sumber: Istimewa"`, and URLs.
   - `python/tests/footage/test_context.py` & `test_replay.py`: commentary card with `spoken`/queries rejects `@wulanguritno81` & `@theidnpageant` vlogs as `"story"` while passing all 9 `ffi_candidates.json` captions and existing `test_service.py` `STAGE` tests; `context_objects` on commentary keeps `strip_names(card.event, card)` for `"Irini Dewi Wanti FFI 2026"` while keeping `PERSON_VISUAL` on commentator-only & incident queries.
   - `python/tests/footage/test_service.py`:
     - `_check_all()` + `_check()` on a subtitled TikTok clip with OCR `["Sumber:", "YouTube Festival Film Indonesia"]`: rejects TikTok as `"subtitle"`, traces YouTube via `_trace_ocr_credits`, cuts a long YouTube ceremony video via `_sections()` into `OCR_TRACED` queue (even when `repost.query` and `SECTIONS` are already at `PER_QUERY = 2`!), admits the clean section in the same run, respects `MAX_OCR_TRACES = 3`, shares `state.traced_keys` with `_trace()`, and never overruns `progress.step` `n > total`.
     - `_sections()` cuts a 260 s YouTube video into sections and rejects parent `"duration"`; leaves a 260 s video `pending` if 0 sections match; does NOT re-fetch `hints()` for that 260 s video on a second `_sections()` call; prioritizes `> 900 s` ceremonies ahead of `180–900 s` videos inside `MAX_LONG_VIDEOS`.
2. **Full verification before push:** `make lint`, full `make test`, `make dashboard-test`, `make dashboard-build`, `graphify update .`.
3. **Live verification after push/CI/stage1 deploy (separate operator gate, cost shown first):**
   - Re-run Ernest FFI post (`https://www.instagram.com/p/DgFu-6szNpk/`): verify `Fadli Zon` + `Siera Tamihardja` / `3 jari` stay on the card, `@wulanguritno81` / `@theidnpageant` are rejected `story`, OCR credit tracing fires on subtitled news clips (`footage ocr trace`), and clean FFI 2026 stage / Siera Tamihardja / Fadli Zon clips are admitted.

---

## 5. Files Touched

- `python/src/thoth_control_plane/assembly/ocr.py`
- `python/src/thoth_control_plane/footage/context.py`
- `python/src/thoth_control_plane/footage/reposts.py`
- `python/src/thoth_control_plane/footage/service.py`
- Unit & replay tests under `python/tests/assembly/` and `python/tests/footage/`
