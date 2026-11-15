# Planner trial fixtures

Four held-out Style B drafts from the planner stage 1 trial (2026-11-13), exported by
`scripts/export_planner_fixtures.py`:

- `shots`: each source's shots (ffmpeg scene cuts at 0.3, merged under 0.8 s, split over 4 s), with
  the main video's speech per shot under the fixed rule (a sentence covering >= 1 s or half the shot);
- `cards`: the draft's comment and post cards;
- `phrases`: the narration split into phrases;
- `answer_v3`: `qwen/qwen3.7-flash` with prompt v3, run A (base shots and card overlay per phrase);
- `blind`: the operator's blind picks, made before seeing the model's answer (`own`), whether the
  model's round 2 pick was accepted after it was shown (`model_ok`, anchored, so counted apart), and
  that round 2 pick (`v2_pick`).

Limits: one story family (Rocky Gerung, Gibran), judged by one operator. The scores these fixtures give
are a regression guard, not the product's accuracy target (spec section 6).
