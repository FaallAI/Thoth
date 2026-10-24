# `produce_video` runs attribution, footage and assembly: design and plan

Date: 2026-10-24. Status: approved by the operator 2026-10-24; implemented.
Research: `D:/thoth-tmp/research/produce-video-chain/report.md`, option a2.

## Problem

The dashboard wizard (`WorkflowWizard.tsx:54`) and the CLI (`cli.py:563`) start every workflow with `intent: "produce_video"`. `SourceInvestigationWorkflow` runs attribution, footage and content assembly only for `identify_original`. A `produce_video` run stops after the source stage at the `continue_to_acquisition` approval, then succeeds.

So dashboard and CLI runs never get:
- attribution;
- footage (with the carousel and, for a TikTok main, the profile page);
- a Content Set;
- the comment filter (D1 noise filter, D2 Jev judge).

The last Content Set was built on 2026-10-17.

## Operator rulings (2026-10-24)

1. `produce_video` also runs the chain.
2. The approval stays **before** the chain: source, then "Continue to acquisition?", then on approve attribution, footage and assembly. A reject stops before anything is spent. This matches the v1 design ("an approval request performs no side effect") and Stage 7's target flow ("request approval when required, then collect comments, then build footage").
3. The wizard's "No publish approval" toggle stays unwired until auto-draft (roadmap item 6).
4. The CLI follows automatically; no `--intent` option.

## Design

**D1. One chain, two intents.** The block that today runs only for `identify_original` (legacy guard; attribution when `attribute_source`; footage when `assemble_content and build_footage`; assembly when `assemble_content`; the cancel checks between steps; failure codes `source_attribution_failed` and `content_assembly_failed`) moves unchanged into `_production_chain(input_)`.
- It returns the terminal summary on failure or cancel, and None when the chain finished.
- `identify_original` calls it exactly where it does today.

**D2. `produce_video` after approve.**
- If `workflow.patched(PRODUCE_CHAIN_PATCH)` (`"produce-video-chain"`), the approved run calls `_production_chain` before it succeeds.
- Reject and cancel are unchanged: no chain, no spend.
- The flags gate each step exactly as for `identify_original`: with attribution or assembly off, the matching step is skipped.

**D3. Temporal safety.**
- The patch is evaluated only on the approve branch, so the code path is deterministic.
- A `produce_video` history recorded before the deploy has no patch marker. On replay `patched()` returns False and the old path (succeed at once) replays unchanged.
- No drain is needed, the same approach the metering patch (`COMPLETION_PATCH`) used.

**D4. No wizard, API or Studio change.**
- The monitor already renders the approval card and the stage events.
- "Open in Studio" and studio-import already work from the Content Set.

**D5. TikTok profile page.** It stays in the footage step (ruling of 2026-10-22). Once footage runs for `produce_video`, the gap closes.

## Cost per dashboard run, from the research

- **Before:** about 1 to 2.5 minutes and no provider calls.
- **After approval:** about 6 to 10 minutes, about 12 to 20 provider calls, and about 10 MB more storage.
- **Checked in implementation:** the research's "about one X account lease per run" is not right. X has no policy row, so it runs in the default `fallback` mode: an account is leased only when the anonymous attempt is blocked or hits a login wall. The only X lease on record is from 2026-10-22, during the login-wall episode. The normal case is 0 leases per run.

## Plan (test first, one branch, one commit)

1. **Tests in `tests/workflows/test_source_investigation.py`:**
   - a `produce_video` run with every flag on: approve runs attribution, footage and assembly once each, in order, and succeeds with the attribution and Content Set artifacts;
   - reject, and cancel while awaiting approval, call none of them;
   - a chain failure fails with the same codes as `identify_original`;
   - a replay test in the pattern of `test_a_history_recorded_before_metering_still_replays`. It records a `produce_video` run with the chain flags off, so the chain adds no activity; strips the patch marker and its search-attribute upsert; and replays the history with the new code.
   - The existing `identify_original` and `produce_video` tests stay green.
2. **Implement D1 and D2** in `workflows/source_investigation.py`.
3. **Verify:** full suite, `make lint`, and the CHANGELOG entry plus this spec and plan in the repository.
4. **Operator gates:** commit, push and PR; merge; deploy, with no workflow left awaiting approval or running at cutover as an extra safety.
5. **Live gate:** one `produce_video` run from the dashboard (a TikTok main), approved, up to a Content Set opened in Studio. Check:
   - the TikTok profile page;
   - the comment filter (D1 and D2) in the Content Set;
   - TikTok comment-card counts after the covered-row check.

## Not in scope

- Wiring "No publish approval".
- A CLI `--intent` option.
- Auto-draft.
