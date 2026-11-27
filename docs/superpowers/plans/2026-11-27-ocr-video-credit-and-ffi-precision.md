# OCR In-Video Credit Tracing & Commentary Precision Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` (or `superpowers:subagent-driven-development`), `ponytail` (`full` intensity), `karpathy-guidelines`, and `tdd` (test-first) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract burned-in source credits (such as `"Sumber: YouTube Festival Film Indonesia"`, `"Dok. YouTube/FFI"`) from the OCR text already read on rejected subtitled news reposts at zero extra OCR cost, trace and section clean YouTube originals into a dedicated `ocr_trace` queue in the same run, stop generic FFI/event vlogs (`@wulanguritno81`, `@theidnpageant`) from passing `story` + Vision and stealing `PER_QUERY` slots, tighten commentary Context Card prompts, and lower YouTube `_sections()` threshold from 15 min (`900 s`) to 3 min (`180 s`) with safe re-entrancy.

**Approved Spec:** `docs/superpowers/specs/2026-11-27-ocr-video-credit-and-ffi-precision-design.md` (approved by operator 2026-11-27; brainstorm items 118–121).

**Branch & Baseline:** Work directly on active branch `feat/footage-sourcing-v2` (PR #147, currently at `4aad9cc9`). Do NOT open a separate PR; these commits ride onto PR #147 before re-testing live and merging.

**Preservation:** Zero DB migrations, zero `MainOcr` / `EditDocumentV2` / OpenAPI / dashboard / Remotion / golden changes, zero changes to `footage/adapters/context_model.py` (which already sends `"temperature": 0`), zero extra OCR calls or frame extractions per clip. All existing `incident` and `commentary` tests (`test_context.py`, `test_replay.py`, `test_reposts.py`, `test_service.py`) must remain green without weakening assertions.

**Tech Stack:** Python 3.12+ control plane (`uv`, `pytest`, `ruff` via WSL `make test T=<path>`, `make lint`).

---

## Task 1: Optional Per-Frame OCR Text Capture (`assembly/ocr.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/ocr.py`
- Test: `python/tests/assembly/test_ocr.py`

- [ ] **Step 1: Write failing tests in `python/tests/assembly/test_ocr.py`**

Add unit tests covering Spec §3.1:
1. Calling `analyze_main_ocr(..., collected_frames=frames_out)` populates `frames_out` with one `list[str]` per non-empty sampled frame (stripped `box.text` in box order, preserving per-frame adjacency even across multiple frames) while making the exact same number of `text.read` calls (zero extra OCR compute).
2. Calling `analyze_main_ocr(...)` without `collected_frames` behaves identically and returns the same `MainOcr` object.

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/assembly/test_ocr.py"
```

- [ ] **Step 3: Implement `collected_frames` in `python/src/thoth_control_plane/assembly/ocr.py`**

Add keyword-only `collected_frames: list[list[str]] | None = None` to `analyze_main_ocr()` (line 151). Right after coverage check (line 173, before `classify_ocr_frames` at line 175):
```python
if collected_frames is not None:
    for frame in read:
        lines = [stripped for box in frame.boxes if (stripped := box.text.strip())]
        if lines:
            collected_frames.append(lines)
```

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/assembly/test_ocr.py tests/assembly/test_ocr_replay.py"
make lint
```

- [ ] **Step 5: Commit Task 1**

```bash
git add python/src/thoth_control_plane/assembly/ocr.py python/tests/assembly/test_ocr.py
git commit -m "feat(ocr): optionally collect per-frame text boxes during main ocr"
```

---

## Task 2: Parse Burned-In Frame Credits (`footage/reposts.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/reposts.py`
- Test: `python/tests/footage/test_reposts.py`

- [ ] **Step 1: Write failing tests in `python/tests/footage/test_reposts.py`**

Add unit tests covering Spec §3.2:
1. Guarded `dok` / `dok.` in `NAMED_CREDIT`:
   - `"Dok: YouTube/Festival Film Indonesia"` → `CreditRef("festivalfilmindonesia", "Festival Film Indonesia", "youtube")`
   - `"Dok. YouTube Festival Film Indonesia"` → `CreditRef("festivalfilmindonesia", "Festival Film Indonesia", "youtube")`
   - `"Dok. @festivalfilm_id"` → `CreditRef("festivalfilm_id", "festivalfilm_id", None)`
   - `"Dokter memeriksa pasien"` / `"Dokumen resmi negara"` / `"Film dokumenter FFI"` → `None`
   - `"Dok. Pribadi"` / `"Dok. Istimewa"` → `None`
2. `frame_credited_source(frames)`:
   - Single-line credit: `[["Breaking News", "Sumber: YouTube / Festival Film Indonesia"]]` → `CreditRef("festivalfilmindonesia", "Festival Film Indonesia", "youtube")`.
   - Split two-box credit with colon: `[["Sumber:", "YouTube Festival Film Indonesia"]]` → `CreditRef("festivalfilmindonesia", "Festival Film Indonesia", "youtube")`.
   - Split two-box credit WITHOUT colon: `[["Sumber", "YouTube Festival Film Indonesia"]]` and `[["YouTube", "Festival Film Indonesia"]]` → `CreditRef("festivalfilmindonesia", "Festival Film Indonesia", "youtube")`.
   - Prefers a YouTube credit in frame 2 over a non-YouTube credit in frame 1 (`[["Cr: @newsacct"], ["Sumber: YT/KompasTV"]]` → `kompastv`, `"youtube"`).
   - **Never** treats bare uploader `@handle` watermarks as credits (`[["@jawaposofficial", "Pidato FFI 2026"]]` → `None`).
   - Rejects non-account Indonesian labels (`[["Sumber: Istimewa"]]`, `[["Dok: Pribadi"]]`, `[["Sumber: Dokumentasi"]]`, `[["Sumber: Arsip"]]`, `[["Sumber: Internet"]]`, `[["Sumber: https://example.com"]]` → `None`).
   - Preserves frame-local adjacency (frame 1 `["Sumber:", "blur"]`, frame 2 `["Sumber:", "YouTube/FFI"]` → matches `ffi`, `"youtube"`).

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/footage/test_reposts.py"
```

- [ ] **Step 3: Implement `_explicit_credit`, guarded `dok`/`dok.`, and `frame_credited_source` in `footage/reposts.py`**

Implement per Spec §3.2:
- Extend `NAMED_CREDIT` with colon `dok\.?` and guarded `\bdok\.\s+(?=@|(?:{_PLATFORM})\b)`.
- Extract `_explicit_credit(text: str) -> CreditRef | None` (running ONLY `text_rule_credit` + `NAMED_CREDIT`, never `text_handles`).
- Define `FRAME_PLACEHOLDERS = PLACEHOLDERS | frozenset({"istimewa", "pribadi", "dokumentasi", "arsip", "net", "internet", "repro", "dokpribadi", "dokistimewa"})`.
- Implement `frame_credited_source(frames: Sequence[Sequence[str]]) -> CreditRef | None` scanning each frame's single lines and prefix-adjacent pairs (inserting `:` when prefix lacks trailing `:`/`/`), filtering `FRAME_PLACEHOLDERS`, preferring the first `platform == "youtube"` match across frames.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/test_reposts.py"
make lint
```

- [ ] **Step 5: Commit Task 2**

```bash
git add python/src/thoth_control_plane/footage/reposts.py python/tests/footage/test_reposts.py
git commit -m "feat(footage): parse burned-in video credits from ocr frames"
```

---

## Task 3: Commentary Card Prompts, Real Scene `visual` & Generic Vlog Guard (`footage/context.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/context.py`
- Test: `python/tests/footage/test_context.py`
- Test: `python/tests/footage/test_replay.py`

- [ ] **Step 1: Write failing tests in `test_context.py` and `test_replay.py`**

Add tests covering Spec §3.4:
1. Prompt assertions: `CARD_PROMPT` explicitly instructs reading the entire `transcript` for every discussed public figure and controversy/gesture; `REFINE_PROMPT` instructs absorbing newly surfacing figures/films/gestures from `results` titles into `people` and `related`.
2. `context_objects()` on a `commentary` card:
   - Event/discussed-figure query (`"Irini Dewi Wanti FFI 2026"` or `"Pernyataan Fadli Zon FFI 2026"`): keeps `person=True` AND sets `visual = strip_names(card.event, card)` (NOT `PERSON_VISUAL = "a person on camera"`!).
   - Commentator-only query (`"Ernest Prakasa standup"`): still sets `person=True` and `visual = PERSON_VISUAL`.
   - `incident` card (`mutant_card`): unchanged (`person=True` and `visual = PERSON_VISUAL`).
3. `context_reason()` generic vlog guard on `commentary` card:
   - Using `wf_aea765e4`'s real card (`main_kind="commentary"`, `people=[Ernest Prakasa, Irini Dewi Wanti]`, `event="Kritik terhadap pernyataan Irini Dewi Wanti terkait penggunaan panggung FFI 2026 untuk kritik pemerintah"`, `queries=["Irini Dewi Wanti FFI 2026", "Ernest Prakasa kritik Kemenbud FFI"]`, `related=[{"event": "Polemik penggunaan panggung FFI 2026 untuk kritik pemerintah", "query": "FFI 2026 kritik pemerintah"}]`, `spoken=["kritik", "protes", "panggung"]`):
     - Rejects (`"story"`) `@wulanguritno81` (*"Semalam menghadiri Festival Film Indonesia 2026. Sebuah ajang yang selalu punya tempat istimewa bagi kita semua, insan perfilman..."*).
     - Rejects (`"story"`) `@theidnpageant` (*"Damai di hati damai di bumi Peraih penghargaan pemeran utama perempuan terbaik Festival Film Indonesia 2026 #ffi2026"*).
     - Passes (`None`) `@tribunnews` (*"Sejumlah Sineas Gunakan Panggung FFI 2026 untuk Suarakan Protes, Ini Tanggapan Kemenbud"*).
     - Passes (`None`) `"Sineas acungkan 3 jari di panggung FFI 2026"` when card has `"FFI 2026 3 jari"` in `related.query` (matching `test_service.py`'s `STAGE`!).
   - All 9 `FFI_ON_STORY` captions in `test_replay.py` (`ffi_candidates.json`) still pass, and adding `@wulanguritno81` + `@theidnpageant` assertions in `test_replay.py` confirms both are rejected `"story"`.

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/footage/test_context.py tests/footage/test_replay.py"
```

- [ ] **Step 3: Implement changes in `python/src/thoth_control_plane/footage/context.py`**

Implement per Spec §3.4:
- Update `CARD_PROMPT` and `REFINE_PROMPT` (preserving all existing contract phrases checked by tests).
- Add pure helper `_is_commentator_only(query: str, card: ContextCard) -> bool`: `q = norm(query)`; returns `names_subject(q, card) and not any(mentions(q, n) for n in discussed_names(card)) and not has_event_term(q, card)`.
- In `context_objects()`: for `event is None` and `person`:
  - If `card.main_kind == "commentary"` and not `_is_commentator_only(query, card)`: `visual = strip_names(card.event, card) or DEFAULT_VISUAL`.
  - Otherwise: `visual = PERSON_VISUAL`.
- Add pure helper `_topic_signals(card: ContextCard) -> set[str]`:
  `named = _named_words(card)`, `ev = set(event_terms(card))`, `qwords = {w for text in (*card.queries, *(r.query for r in card.related)) for w in content_words(text)} - named - ev - {"indonesia", "indonesian"}`, return `set(card.spoken) | qwords`.
- Add helper `_commentary_event_ok(said: str, matched: set[str], signals: set[str]) -> bool`:
  `if not signals: return True`
  `non_year = {t for t in matched if not _YEAR.fullmatch(t)}`
  `return (len(matched) >= 3 and len(non_year) >= 2) or any(_says(said, w) for w in signals)`
- Apply `_commentary_event_ok` in `context_reason()` ONLY on `card.main_kind == "commentary"` for personless `card.event` / `related.event` matches (never affecting `names_subject`, `names_discussed_with_context`, or `main_kind == "incident"`).

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/test_context.py tests/footage/test_replay.py tests/footage/test_service.py"
make lint
```
Verify **zero** regressions in `test_service.py` (especially `test_commentary_event_clips_skip_the_commentators_face` and `test_a_commentary_run_reuses_library_clips_without_the_commentators_face`)!

- [ ] **Step 5: Commit Task 3**

```bash
git add python/src/thoth_control_plane/footage/context.py python/tests/footage/test_context.py python/tests/footage/test_replay.py
git commit -m "fix(footage): block generic event vlogs and tighten commentary card prompts"
```

---

## Task 4: Live OCR-Credit Tracing (`OCR_TRACED` Queue) & 3-Minute Re-Entrant `_sections()` (`footage/service.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py`
- Test: `python/tests/footage/test_service.py`

- [ ] **Step 1: Write failing tests in `python/tests/footage/test_service.py`**

Add tests covering Spec §3.3 & §3.5:
1. **Live OCR-credit tracing end-to-end inside `_check_all()`:**
   - Candidate TikTok repost (`source="search"`, `query="q1"`) fails OCR as `"subtitle"`, with mocked `text.read` returning frame boxes `["Sumber:", "YouTube Festival Film Indonesia"]`.
   - Even when `repost.query` (`"q1"`) AND `SECTIONS` are already at `PER_QUERY = 2` (or `admitted`), `_trace_ocr_credits()` traces `Festival Film Indonesia` on YouTube (via `_trace_listing` / cached `_trace_search`), runs `_sections()` on a long traced YouTube ceremony video, injects the clean section into `queues[OCR_TRACED]`, and admits it in the same run!
   - Enforces `MAX_OCR_TRACES = 3` cap across multiple subtitled clips.
   - Shares `state.traced_keys` with pre-check `_trace()`: an account already traced from captions is NOT traced again from OCR.
   - Bare `@handle` watermark in OCR (`["@jawaposofficial"]`) does NOT trigger OCR tracing.
   - `progress.step("footage.screen_clips", ...)` never reports `n > total` when OCR-traced candidates are injected mid-loop.
2. **3-minute `_sections()` threshold & safe re-entrancy:**
   - A 260 s (`> 180 s`, `<= 900 s`) YouTube video with matching discussion captions is cut into `source="section"` candidates and the parent is rejected `"duration"`.
   - A 260 s YouTube video with 0 matching sections stays `status == "pending"` (NOT rejected `"duration"`), AND a second `_sections(workflow, card, sectioned)` call does NOT call `hints()` on it again.
   - A `> 900 s` ceremony video is still rejected `"duration"` even when 0 sections match, AND inside `MAX_LONG_VIDEOS = 6`, `> 900 s` videos are prioritized ahead of `180–900 s` videos at equal `story_score`.

- [ ] **Step 2: Run targeted tests to verify RED**

```bash
make test T="tests/footage/test_service.py"
```

- [ ] **Step 3: Implement changes in `python/src/thoth_control_plane/footage/service.py`**

Implement per Spec §3.3 & §3.5:
- Add constants `LONG_SECTION_SECONDS = 180.0`, `MAX_OCR_TRACES = 3`, `OCR_TRACED = "ocr_trace"`.
- Update `quota_key(candidate)`:
  - `if candidate.source == "section": return OCR_TRACED if candidate.query == OCR_TRACED else SECTIONS`
  - `if candidate.source == "ocr_trace": return OCR_TRACED`
  - `return candidate.query`
- Add `traced_keys`, `ocr_credits`, `ocr_traced_count`, `sectioned` fields to `_Build`.
- In `_trace()`: record every traced `(platform, normalize(ref.account))` into `state.traced_keys` (passing `state` into `_trace`).
- In `_sections(self, workflow, card, sectioned=None)`:
  - Use `LONG_SECTION_SECONDS` (`180.0`), skip URLs already in `already`, sort by `(-(c.story_score or 0.0), (c.source_duration or 0.0) <= MAX_SECONDS)`.
  - Mark `already.add(c.url)` once inspected; preserve `query=OCR_TRACED` when parent has `c.query == OCR_TRACED` (or `c.source == "ocr_trace"`).
  - Reject parent `"duration"` iff `rows` is non-empty OR `(c.source_duration or 0.0) > MAX_SECONDS`.
- In `_check()`: pass `collected_frames=ocr_frames` into `analyze_main_ocr(...)` when `state.card is not None and candidate.source != "carousel"`; on `ocr.outcome in ("subtitle", "overlay")`, extract `frame_credited_source(ocr_frames)` and append `(candidate, ref)` to `state.ocr_credits` before rejecting `"subtitle"`.
- In `_check_all()`: accept `identity: MainIdentity | None = None`, include `OCR_TRACED` in `queues`, track `total_pending = len(pending)` and `queued_urls: set[str]`, and call `_trace_ocr_credits()` between batches (incrementing `total_pending` and prepending newly discovered clean originals/sections to `queues`).

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/ tests/assembly/test_ocr.py"
make lint
```

- [ ] **Step 5: Commit Task 4**

```bash
git add python/src/thoth_control_plane/footage/service.py python/tests/footage/test_service.py
git commit -m "feat(footage): trace ocr video credits into live screening and cut 3-min youtube"
```

---

## Task 5: Full Verification, Graphify Update, Checkpoint & `CHANGELOG.md`

**Files:**
- Track spec & plan (force-add since `docs/superpowers/` is gitignored):
  - `docs/superpowers/specs/2026-11-27-ocr-video-credit-and-ffi-precision-design.md`
  - `docs/superpowers/plans/2026-11-27-ocr-video-credit-and-ffi-precision.md`
- Update: `CHANGELOG.md`
- Update: `.superpowers/sdd/2026-11-27-footage-sourcing-v2/progress.md` (gitignored; do not commit)

- [ ] **Step 1: Run full verification suite**

```bash
make lint
make test
make dashboard-test
make dashboard-build
```
Verify every exit code is `0`; fix any failure test-first before proceeding.

- [ ] **Step 2: Refresh local code index**

Run `graphify update .` (never stage `graphify-out/`, `.codegraph/`, or `.superpowers/`).

- [ ] **Step 3: Record completion in `CHANGELOG.md` and `.superpowers/sdd/2026-11-27-footage-sourcing-v2/progress.md`**

Include exact verification counts, commit list, and a **Next steps** section listing pending operator gates (push PR #147 update, CI green & stage1 branch-image deploy, live FFI re-run verifying OCR video credit tracing + Siera/3-jari stage clips + zero generic FFI vlogs with cost shown first, merge PR #147).

- [ ] **Step 4: Commit docs & spec/plan**

```bash
git add -f docs/superpowers/specs/2026-11-27-ocr-video-credit-and-ffi-precision-design.md docs/superpowers/plans/2026-11-27-ocr-video-credit-and-ffi-precision.md
git add CHANGELOG.md
git commit -m "docs: record ocr video credit tracing and commentary precision fixes"
```

- [ ] **Step 5: Hard stop & report back for review**

Do NOT push, merge, deploy, or run live/paid calls.
