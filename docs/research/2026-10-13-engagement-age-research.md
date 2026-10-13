# Engagement baseline against video age — research

Date: 2026-10-13. Raised during the Stage 4 reaction work. The rule compares a reaction's views
with the median views of its account's other videos. Those videos have collected views for days
or weeks, while Thoth processes a reaction hours after it is posted, so a fresh reaction loses
even while it is spreading.

## 1. How views accrue

| Platform | Accrual reported | Source |
|---|---|---|
| TikTok | most views in the first 1–5 days, then slow growth for 20–30 days | Socialinsider, 6 M posts (2025) |
| Instagram Reels | about 30% on day one, 65–70% within 72 hours, late spikes possible | Socialinsider, Upgrow, Kontentino |
| YouTube Shorts | spread out; spikes as late as 25–30 days | Socialinsider |
| Any (YouTube, Digg) | log views early and later correlate above 0.9; Digg settles in 2 hours, YouTube in about 10 days | Szabo & Huberman (2010) |

The aggregator numbers disagree in detail, but they agree on the shape. Views are front-loaded,
the curve differs by platform, and a video's early count predicts its later count (a roughly
constant ratio in log space).

Tools that rank a video against its channel compare it with the channel "within a similar
timeframe" (vidIQ's outlier score), not with lifetime totals.

## 2. Signals and their age bias

| Signal | Age bias | Note |
|---|---|---|
| Views / median lifetime views (today) | strong: young posts lose | the problem reported |
| Views per hour / channel's average views per hour | reversed: young posts win | old videos' rate has decayed |
| Comments per view | weak | but falls as a video grows (median 0.61% under 10 k views, 0.089% above 1 M), so a viral reaction looks *less* discussed |
| Views at the same age as the channel's videos | none | needs view history Thoth does not have yet |
| Views / (median × expected share at this age) | small, once the curve is right | Szabo–Huberman scaling with a per-platform curve |

## 3. Options

1. **Age-scaled baseline** (recommended). Each baseline video's lifetime views are scaled to the
   reaction's age: `expected = median(views_b × F(age) / F(age_b))`. Here `F` is the expected
   share of lifetime views at a given age for that platform; a video over 30 days old counts as
   `F = 1`.
   - `F` starts from the published curves, one per platform.
   - Thoth can recalibrate `F` later from its own snapshots: the same videos seen at two ages.
   - The ages come from `published_at`, which the report and the discovery listing both carry.
2. **Recent videos only**: the baseline holds only the account's videos from the last 7–14
   days. Simpler, but the bias only shrinks, and small accounts often have too few such videos.
3. **Comment rate instead of views**: biased against exactly the viral reactions.

Every option shares one limit: below a minimum age (proposed: 6 hours) the estimate is noise.
Such a reaction needs a policy:

- (a) **unknown, so a repost** (today's rule): a fresh reaction is never an original;
- (b) **decide on contribution and discussion alone** while it is too young to measure;
- (c) **re-check later**: a durable Temporal timer re-measures engagement at about 24 hours and
  updates the verdict. This is the most correct, but the verdict, and anything built on it,
  can change after the fact.

## 4. Recommendation

Option 1 with a 6-hour minimum age, and policy (b) for younger reactions. Snapshots for
recalibrating `F` are a follow-up. The live golden capture records `published_at` and the
discovery counts, so this can be calibrated offline whatever the operator chooses.

## Sources

- [Szabo & Huberman, Predicting the popularity of online content](https://arxiv.org/abs/0811.0405)
- [vidIQ Outliers](https://support.vidiq.com/en/articles/9660010-outliers)
- [Socialinsider: TikTok views over time](https://www.socialinsider.io/blog/tiktok-virality-insights/)
- [Socialinsider: Reels views over time](https://www.socialinsider.io/blog/how-long-does-it-take-for-reels-to-get-views/)
- [Socialinsider: YouTube Shorts views over time](https://www.socialinsider.io/blog/how-long-does-it-take-for-yt-shorts-to-get-views/)
- [Upgrow: Instagram vs TikTok content lifespan 2026](https://www.upgrow.com/blog/instagram-vs-tiktok-content-lifespan-data-2026)
- [Overseeros: comment-to-view ratio](https://www.overseeros.com/blog/good-comment-to-view-ratio-youtube)
