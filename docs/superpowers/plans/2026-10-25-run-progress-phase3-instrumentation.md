# Run progress, phase 3: instrumentation. Implementation plan

Date: 2026-10-25.

| | |
|---|---|
| Spec | `docs/superpowers/specs/2026-10-25-run-progress-contract-design.md`, §5 (step catalogue) and G2 (approved) |
| Design | `docs/DESIGN.md` §7.2 (steps per stage) and §7.5 (failures) |
| Roadmap | "Dashboard redesign track", step 4 |
| Checkpoint | `.superpowers/sdd/2026-10-25-run-progress-phase3/progress.md` |
| Branch | `feat/run-progress-instrumentation`, stacked on `feat/run-progress-steps` (`4f1aeea`, phase 2 reviewed GO, with the N1/N2/F2 follow-ups; pushed as a backup branch, not merged) |

The track shares one set of operator gates. Do not push, open a PR, merge or deploy.

## Goal

The real acquirers, attribution, footage and assembly emit the phase 2 catalogue codes at natural boundaries. A running dashboard can then show, for example, "Capture comment cards 4 of 10" or "Wait before the next page (30 s)".

Phase 3 also closes **F1**: a footage activity that failed shows the `footage` stage as `failed` while the run continues (DESIGN §7.5). Today it shows `completed`.

**Out of this phase:**
- estimates and the inbox (phase 4);
- render frames (phase 5);
- any API, schema, migration or dashboard change. The generated contract must not change.

## Ground truth (read before coding)

**The recorder.**
- `thoth_control_plane/progress.py` provides `await progress.step(code, *, n=None, total=None, wait_until=None, params=None)` and `progress.step_sync(...)` for threads.
- It drops a code outside the closed `CATALOGUE` or outside the scope's stage, and keeps `params` only for the keys `verdict`, `platform` and `count` with values `^[a-z0-9_.-]{1,40}$` or an int.
- It never raises.
- Progress updates of one code within 1 s are held and flushed later (N1), so emitting each item of a loop is fine. Still, emit **per item, never per frame or per byte**.

**The scope.** `activities/progress_scope.py` sets the stage from the activity type:

| Activity type | Stage |
|---|---|
| `inspect_source_candidates` | source |
| `attribute_source` | attribution |
| `build_footage` | footage |
| `assemble_content` | assembly |

Code outside a scope records nothing, which is why unit tests need `progress.scoped(...)` plus a fake sink, as in `tests/test_progress.py`.

**The browser loop.**
- `acquisition/browser_loop.py` runs every Scrapling session, and its `page_action` and `page_setup` callbacks, on a separate event loop in a separate thread (`run_coroutine_threadsafe`).
- `call_soon_threadsafe` copies the caller's context, so the ContextVar scope *should* reach callbacks such as `card_browser._on_post`. **Task 1 proves it before anything relies on it.**

**Source seams:**

| Seam | What it does |
|---|---|
| `activities/source_investigation.py` `_run` | Calls the acquisition runner and stores the report |
| `acquisition/card_browser.py` `CardBrowser.cards` | Post page visit, then `asyncio.sleep(PAGE_SPACING_SECONDS)`, then profile visit |
| `card_browser._on_post` | Post card crop; the tagged comment rows loop over `_crop_row`, which returns `None` for a covered row; `is_login_path` |
| `card_browser._on_profile` | Profile crop and profile page crop; `is_login_path` |
| `acquisition/x_service.py` `XHeadlessBrowser.cards` | The embed loop, with a `PAGE_SPACING_SECONDS` / `EMBED_SPACING_SECONDS` sleep before each embed |

- **Media downloads per platform:**
  - `MediaMaterializer.materialize` callers, at least `acquisition/service.py` (TikTok `_materialize`) and `acquisition/threads_service.py`;
  - Instagram, X and YouTube download through their own paths (`instagram_service.py`, `x_service.py`, `youtube_service.py`). Find each.
- **Post fetch per platform:** each service's `inspect`, at its first metadata request (FxEmbed for X, the page or API for the others).

**Attribution** (`attribution/service.py` `identify`):
- `_read` is OCR;
- `_credit` and `_reaction` are the vision and credit paths;
- candidate search;
- `_evaluate` / `_check` compare frames per finalist;
- the verdict is in `attribution/models.py` `Verdict = original | replaced | unresolved`.

**Footage** (`footage/service.py` `build` → `_build`):
- query planning;
- `_search` (per platform);
- `_check_all` / `_check` (screening);
- `_creator` (creator listing and profile page);
- `_result`.

**Assembly** (`assembly/service.py` `build`):
- subtitles OCR;
- `_comments` (the Jev judge);
- `_figures`;
- the content set save.

**F1.** `workflows/source_investigation.py` `_footage`: on `ActivityError` it appends a `stage.failed` source event, then records `STAGE_COMPLETED`.
- `StagePlan.fail` overrides `complete`, and `complete` ignores a `failed` stage.
- `_plan_fail` exists in the workflow.

## Design decisions (fixed; ask before changing)

**D1. Emission table.** Emit at these points. Use only catalogue codes, with no new codes. "≈" means the executor finds the exact line in the named function.

| Code | Where | Arguments |
|---|---|---|
| `source.read_link` | `_run`, before the runner | — |
| `source.fetch_post` | each platform service, ≈ its first metadata request | `params={"platform": <platform>}` |
| `source.download_media` | each platform's media loop, after each item | `n`, `total` |
| `source.capture_post_card` | `_on_post`, after the post crop | — |
| `source.capture_comment_cards` | `_on_post` row loop, after each row | `n`, `total` (tagged rows we sent) |
| `source.gate_covered` | `_on_post`, after the loop, when ≥ 1 row was covered | `params={"count": covered}` |
| `source.page_gap` | `CardBrowser.cards` and the X embed loop, right before each sleep | `wait_until = now + gap` |
| `source.capture_embed_cards` | X embed loop, after each embed | `n`, `total` |
| `source.capture_profile` | `_on_profile`, after the crops | — |
| `source.login_wall` | `_on_post` / `_on_profile`, when `is_login_path`; also each service's existing login-path checks | — |
| `source.save_report` | `_run`, after the report is stored | — |
| `attribution.read_text` | `identify`, before OCR of the frames | — |
| `attribution.ask_vision` | before each vision or credit model call | — |
| `attribution.search_candidates` | after the candidate search | `params={"count": found}` |
| `attribution.compare_frames` | per finalist checked | `n`, `total` |
| `attribution.verdict` | when the verdict is decided | `params={"verdict": verdict}` |
| `footage.plan_queries` | after the queries are planned | `params={"count": queries}` |
| `footage.search_platforms` | per platform searched | `n`, `total`, `params={"platform": name}` |
| `footage.screen_clips` | per candidate screened | `n`, `total` |
| `footage.creator_listing` | when the creator listing and profile page start | — |
| `footage.keep_clips` | at `_result` | `params={"count": kept}` |
| `assembly.read_subtitles` | before the subtitles OCR | — |
| `assembly.judge_comments` | after judging | `params={"count": kept}`, `total=candidates` |
| `assembly.find_figures` | after the figures | `params={"count": figures}` |
| `assembly.save_content_set` | after the content set is stored | — |

- **Code that runs in a thread** (`asyncio.to_thread`, an executor) uses `progress.step_sync`. Code on an event loop uses `await progress.step`.
- **No emission may change behavior,** ordering of side effects, timeouts or results. Steps are observability only.
- Every emission sits in its own line, never inside an expression a test already asserts on.

**D2. F1.**
- In `_footage`'s `except ActivityError` path, call `self._plan_fail("footage")` **before** the existing `STAGE_COMPLETED` event, so the stage reads `failed`.
- The run continues and can still succeed.
- It is a query-only state change: no new Temporal command, so no patch.

**D3. Tests prove sequences, not lines.** Each seam test runs the real code with the existing fakes inside `progress.scoped(StepScope(...))` with a fake sink. It asserts the ordered `(code, n, total, params)` list for one representative flow:
- the TikTok and X cards flows, including a covered row and a login path;
- one media loop per platform;
- attribution `original` and `replaced`;
- footage with two platforms;
- assembly.

## Tasks (test first; one commit per task; one-line English subjects)

1. **Guard: the scope reaches the browser loop.**
   - **Test:** inside `progress.scoped(scope)` with a fake sink, a coroutine run through `browser_loop.on_browser_loop(...)` calls `await progress.step("source.read_link")`, and the sink receives it with that scope.
   - **Test:** `progress.step_sync` from `asyncio.to_thread` inside the scope is recorded too.
   - **If the first test fails,** stop and ask (see Hard stops). Do not work around it.
2. **Source: the activity and the cards** (`_run`, `CardBrowser.cards`, `_on_post`, `_on_profile`, the X embed loop), per D1. Tests per D3.
3. **Source: fetch and media per platform** (TikTok, Instagram, X, YouTube, Threads), per D1. Tests per D3.
4. **Attribution,** per D1. Tests per D3, for `original` and `replaced`.
5. **Footage, plus F1 (D2).**
   - Tests per D3 for the footage service.
   - A workflow test: a `build_footage` `ActivityError` → `footage` is `failed`, assembly still runs, and the run succeeds.
   - The phase 1 fixture replays still pass.
6. **Assembly,** per D1. Tests per D3.
7. **Docs.** A `CHANGELOG.md` entry, and only the step 4 status cell of `docs/ROADMAP.md` "Dashboard redesign track".

## Verification (record the evidence in the checkpoint)

- **Python, from WSL in the worktree:**
  - while iterating, `bash scripts/dev/pytest-wsl.sh tests/test_progress.py tests/acquisition tests/activities tests/attribution tests/footage tests/assembly tests/workflows`.;
  - then the full `bash scripts/dev/pytest-wsl.sh` and `make lint`.
- **Replay:**
  - the phase 1 fixture replays and the older replay tests pass;
  - `git diff 4f1aeea -- python/src/thoth_control_plane/workflows/` shows only the D2 lines.
- **No contract change:** `python python/scripts/export_openapi.py` then `git diff --exit-code python/openapi.json` (empty).
- **No dashboard change:** `git diff 4f1aeea --stat -- dashboard/` is empty, so the dashboard suite is not required.
  - If you do run it: with Bun 1.4.4 on Windows, 1 to 3 random UI tests are known to flake. Rerun a failing file alone and report it by name.
- **Steps never carry URLs or secrets:** `rg -n "progress\.step" python/src` lists every emission. Check that every `params` value is one of: a platform name, a verdict, or a count.

## Constraints

- **Offline only:** no live requests to any platform or provider, and no deploy.
- **Rust is frozen:** no `cargo update`, no `build_cuda.bat`.
- **Commits:** one-line English subjects through a single `git commit -m`. No body, no trailer, no `Co-Authored-By`.
- **Never stage** `.superpowers/`, `graphify-out/`, `.serena/` or `design/`. Use `git add -f` only for `docs/superpowers/...`.
- **Line endings:** keep LF; edit through the editor tools.

## Hard stops

- Stop and ask if:
  - Task 1 shows the scope does not reach the browser loop;
  - a seam needs a code outside the catalogue;
  - an emission would need a behavior change;
  - F1 needs a Temporal command.
- Stop after Task 7 with local commits.
- Do not start phases 4-5.
