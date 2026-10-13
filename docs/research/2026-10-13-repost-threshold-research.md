# The repost threshold for uncredited posts — research

Date: 2026-10-13. When no credit handle is found, Stage 4 calls a post `original` if Jev's
repost probability is below `repost_threshold`, and `unresolved` otherwise. The threshold went
from 0.5 to 0.6 the same day, so that kabinetketiduran (an operator-confirmed original) stayed
`original`.

## 1. The data

Only posts without a credit reach the threshold. Credited posts go straight to the search.

| Post | Truth | `is_repost` |
|---|---|---|
| tiktok koranjakarta …137 | repost of an X video | 0.40 |
| tiktok kabinetketiduran | original | 0.49 (first capture), 0.56 (recapture, same post) |
| tiktok detikcom | repost | 0.80 |
| tiktok koranjakarta …857 | repost of an X video | 0.95 |

- No threshold separates these: a true repost scored 0.40, below the original's 0.49.
- The same post moved 0.07 between captures, because the vision frames changed.
- Four points cannot place a threshold more finely than that noise.

## 2. What each error costs this tool

The verdict changes two things: whether Stage 5a may trim the intro (`unresolved` yes,
`original` no), and whether a later stage searches for the source. Replaying every Stage 5a
OCR golden both ways:

| Case | Trim not allowed | Trim allowed |
|---|---|---|
| kabinetketiduran (original, no headline) | clean | **clean** |
| DeLTY7YtLl4 (original, no headline) | clean | **clean** |
| detikjatim (repost with a headline) | subtitle, no trim | subtitle, **trims 6.5 s** |
| officialinews (repost with a headline) | subtitle, no trim | subtitle, **trims 9.5 s** |

- **An original wrongly `unresolved`** renders the same: the trim only removes a detected
  headline, and an original rarely carries one. The cost is a wasted source search later, and a
  verdict label that says "not sure".
- **A repost wrongly `original`** keeps the reposter's added headline in the render, and its
  source is never searched.

The second error costs more. With calibrated probabilities, the threshold that minimizes cost
is `C_u / (C_u + C_o)`, where `C_o` is the cost of a false original and `C_u` the cost of a
false unresolved. If a false original costs about three times as much, the threshold is about
0.25. If it costs twice as much, the threshold is 0.33. Jev returns probabilities meant for
thresholding, and the 0.40 repost shows it can under-score uncredited news reposts.

The kabinetketiduran case that motivated 0.6 gains nothing from it. Its render is `clean`
either way.

## 3. Options

1. **0.35** (recommended). Every repost in the data becomes `unresolved` (0.40 included).
   kabinetketiduran becomes `unresolved` at 0.49–0.56, its render unchanged. The golden records
   that the verdict is a coin flip, not that the post is a repost.
2. **0.5** (the old value). The 0.40 repost stays a false original; kabinetketiduran flips
   between `original` and `unresolved` from capture to capture.
3. **0.6** (current). Opens 0.5–0.6 to reposts, with no render benefit.

Under every option, the `repost probability` evidence lets the 0.3–0.6 band be monitored after
deployment. More uncredited examples, original and repost alike, are the way to narrow it.

## Sources

- Data: the Stage 4 golden fixtures across commits `4f46c56`, `7031296`, `4c9102f`, `HEAD`,
  and the pending captures of 2026-10-13.
- Stage 5a replay: `python/tests/fixtures/assembly/ocr/*.json` through
  `tests/assembly/ocr_replay.py`, with `trim_allowed` both ways.
- Jev returns calibrated probabilities for thresholding:
  [Jev on OpenRouter](https://openrouter.ai/docs/guides/community/jev).
