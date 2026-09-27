# Direct full migration of Scout to Python; Stage 1 closed by operator decision

**Status:** accepted — operator decision, 2026-09-27

Until now the [Python Scout migration](../python-scout-migration-roadmap.md) moved one capability
at a time through its own operational gates: activation parity, controlled fallback, an
accelerated acceptance window with in-window parity samples, restart recovery, a rollback drill,
and a human cutover decision. The TypeScript Scout runtime is no longer used for daily work, so
those per-capability gates mostly measure Scout's availability rather than Python's correctness.
Stage 1 showed this directly: its last parity reference failed because this host was rate-limited
by TikTok oEmbed (HTTP 429), a dependency that only the Scout path has. The operator therefore
closed Stage 1 and chose to migrate the remaining stages directly to Python, with parity checked
offline and one end-to-end acceptance at the end.

## Stage 1 closure

The operator closed Stage 1 (TikTok single-post acquisition) on this evidence, all on image
digest `56fa84e6…` / commit `478b06f`:

- activation parity sample `p9` passed, 9 of 9 fields matching, with all 12 artifact checks passing;
- controlled fallback exercise `f4` passed;
- acceptance window `56fa84e6` recorded 226 valid completed runs, all on the Python route with no
  legacy fallback and no terminal failure.

The closure is an operator waiver, not an evaluator `ready` verdict. The evaluator would still
report two blockers:

- `INSUFFICIENT_WINDOW`: the window spans 20.08 hours, from the first valid run at
  2026-09-26T05:38Z. The policy requires 24 hours.
- `INSUFFICIENT_PARITY_SAMPLES`: no in-window parity sample was recorded. `p10` was
  `evidence_incomparable` because the Scout reference could not read oEmbed metadata. `p11` was
  never run.

Stage 1 did not run restart recovery or the rollback drill. Both move to the final end-to-end
acceptance described below. The worker keeps its deployed activity mode until a later deployment
changes it.

## Strategy for Stages 2–10

Each remaining stage gets its own specification and plan, and is ported directly to Python.
Every stage requires:

- golden fixtures recorded once from Scout, or from captured real inputs where Scout cannot
  produce them;
- deterministic offline parity tests against those fixtures;
- a small review of the stage's diff;
- one controlled live smoke.

Individual stages no longer require:

- acceptance or soak windows;
- activation parity gates or in-window parity samples;
- controlled fallback exercises;
- a walk through the `shadow` → `python_preferred` → `python_only` operating states.

After the last port, one final acceptance comes before Stage 10 retires Scout:

- one end-to-end soak of the complete Python path;
- a full review;
- restart recovery;
- a rollback test at the deployment level;
- the operator's approval.

## Consequences

- Each capability now has less production evidence of equivalence to Scout. A behavioral
  regression can surface only in the final end-to-end soak, where it is more expensive to
  localize. The offline golden fixtures are the main defense.
- The legacy fallback shares the oEmbed dependency that failed `p10`, so it is not a reliable
  safety net under load. Deployment rollback, not fallback, is the recovery mechanism.
- Stage 1 soak, parity, and fallback tooling stays in the repository as history, but new stages
  must not depend on it.
