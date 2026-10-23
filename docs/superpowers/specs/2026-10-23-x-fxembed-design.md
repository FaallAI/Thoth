# X via FxEmbed — Design

**Date:** 2026-10-23. **Status:** approved in chat by the operator (2026-10-23).
**Origin:** follow-up research `D:/thoth-tmp/research/followups-2026-10-23/report.md`, items A1
and A2. The operator chose the permanent fix.

## Why

Sometime between 2026-10-16 and 2026-10-22, X's signed-out pages stopped embedding tweet JSON.
Every part of Thoth that read that JSON now gets nothing back, and no error is raised:

- **The main.** An X post with two or more videos loses all of them. Syndication carries
  renditions of one video only, and the page parse that named each video is empty. The main
  falls back to the post card.
- **Comment cards.** X mains have none: the replies came from the page JSON.
- **Engagement.** X mains lose `play` (views) and `share` (reposts), and lose the full text of
  long tweets.
- **Creator material and attribution.** `x_discovery.parse_profile` returns `no_data` on every
  call. That kills X creator footage, X creator photos and X attribution discovery.

The operator needs all of these. The most important are, in order: the multi-video main,
comment cards, and footage.

## Goals

- **G1 Every video of an X post.** The acquisition report lists every video of the post, in
  post order, each as its best MP4.
- **G2 Replies and comment cards.** The post's first-page replies come back as report comments
  with author, text and likes. Each one gets a real card cropped from the X post page, as
  before; a synthetic card is never drawn.
- **G3 Engagement and text.** `play` (views) and `share` (reposts) come back. A long tweet
  gets its full text.
- **G4 Profile media listing.** The profile's recent media posts come back for:
  - attribution discovery (videos);
  - creator footage (videos);
  - creator photos (photo posts).

  The video/photo split, the repost and other-author filters, and the ranking stay as today.
- **G5 Card crops that survive X's DOM.** The profile card and the profile page are found by
  shape instead of `main > div:nth-child(4)`, and both are captured on the live check.
- **G6 Multi-video footage rule.** An X post with two or more videos follows Stage 5b rule F2,
  which already applies to Instagram carousels:
  - the first video is the main;
  - the other videos are footage (at most six), and nothing is searched;
  - each video still passes the footage checks.

## Non-goals

- **No new main rules.** The main is still chosen as Stage 5a A2 decided: the original when
  attribution replaced the input, otherwise the input post. Within a post, the first video is
  the main.
- **X keyword search for footage is unchanged.** It runs signed in and reads the captured
  `SearchTimeline` response, not the page, so it is not broken.
- **No X account use** for any of the goals above.
- **No self-hosted FxEmbed instance yet.** It stays one setting away (see Decisions).
- **No other platforms.** FxEmbed also serves Bluesky, but nothing here touches it.

## Anti-goals

- **No silent loss.** Every fallback logs a warning with a reason. A dead source must never
  again look like an empty answer.
- **No drawn or synthetic cards.** Every card is a crop of the real X page.
- **No full-body or credential logging.** Never log full FxEmbed response bodies or any
  credential.

## Decisions

Operator decisions (2026-10-23):

- **D1** The permanent fix: FxEmbed (the FxTwitter API, MIT, `https://api.fxtwitter.com`).
- **D2** Every listed component is required. The order of importance is the multi-video main,
  comment cards, then footage.
- **D3** The main follows the existing rules (5a A2). A multi-video post follows 5b F2.

Executor's calls, which the operator can overrule:

- **D4 Public API first; the base URL is a setting.** Add
  `THOTH_X_FXEMBED_URL = "https://api.fxtwitter.com"` to the settings. Moving to a self-hosted
  instance then means changing that one value.
- **D5 Syndication stays the core.** `cdn.syndication.twimg.com` stays the source of a post's
  identity, author, text, photos and the single-video fallback. FxEmbed replaces only the dead
  page enrichment (`XAcquirer._page`), which returns the same `XPageParse`.
  - If FxEmbed is down or refuses, the acquisition still succeeds with today's
    syndication-only result and a warning. The main then has one video and no comments.
- **D6 FxEmbed replaces the profile page parse.** `XProfileDiscovery` reads
  `/2/profile/{handle}/media` instead of the profile HTML. On failure it keeps today's typed
  empty result (`DiscoveryReason`) and logs a warning.
- **D7 Comment cards stay page crops.** The reply IDs from FxEmbed become the crop targets on
  the X post page; the targeting is today's `comment_targets` / `TAG_REPLIES_JS`. The page
  renders only some replies signed out (the recorded page had the post and two replies).
  - A reply the page does not render gets no card. It stays in the report as a text comment
    (`card` is None, as `card_browser.persist_cards` already allows), and Studio already places
    such comments as the `comment` role.
  - The log counts replies listed against cards cropped, so the gap stays visible.
- **D8 Remove the dead page-JSON readers for X posts and profiles**, along with their tests and
  fixtures:
  - `parse_page`, the profile path of `parse_profile`, and the page fetch in `XAcquirer._page`
    and `XProfileDiscovery._collect`.
  - Keep `page_tweets` and whatever `footage/adapters/x_search.py` still imports.
  - Keep `operations/x_fixture.py` working, or move it to the new parser.

## FxEmbed facts this design relies on

Verified live on 2026-10-23 with three anonymous requests, 30 s apart. The raw JSON is kept in
`D:/thoth-tmp/research/x-fxembed/`; the OpenAPI document is `openapi.json` there.

| Endpoint | What came back for `InFebriyan128/status/2110509448032862621` |
|---|---|
| `GET /2/status/{id}` | `code` 200 and `status`: two separate `media.videos[]` (11.1 s and 20.1 s), each with `url` plus three `formats[]` (container, codec, bitrate, url, size). Also `likes`, `reposts`, `replies`, `views`, `quotes`, `bookmarks`, `author.screen_name`, `text`/`raw_text`, `created_at` and `created_timestamp` |
| `GET /2/conversation/{id}` | `code` 200, `replies[]` (34; each with `id`, `text`, `author`, `likes`, `replies` and the other counts) and a `cursor` |
| `GET /2/profile/{handle}/media?count=20` | `code` 200, `results[]` (15 posts: 9 with videos, 6 with photos, each a full status) and `cursor` |

- **Rate limit:** documented at 1000 requests per minute per IP for API v2.
- **Authentication:** none.
- **Terms:** none stated; the code is MIT and self-hostable.
- **Response shape:** every response carries `code`, which mirrors the HTTP status.

## Design

### FxEmbed client

Add a small client in `acquisition/` beside the X modules: `x_fxembed.py`, or a section of
`x_service.py` if that file stays readable. It uses the existing request stack
(`XRequestFetcher` / the Scrapling GET helper) and the same timeout. It has three reads:

- `status(post_id)`: the post's status object.
- `replies(post_id)`: the first page of replies only. No paging; the card crops cap the useful
  count anyway (`MAX_COMMENTS`).
- `profile_media(handle, count)`: one page of media posts. `count` is the discovery request's
  limit, capped at FxEmbed's maximum.

Errors map to the reasons the callers already understand:

| Response | Reason |
|---|---|
| HTTP 429 | rate limited |
| 5xx, timeout, connection error | unavailable |
| `code` 404, or no status | not found / no data |
| Unreadable JSON | unreadable |

The client never raises past its caller's existing `except` boundary. The User-Agent names
Thoth.

### Post enrichment (G1-G3)

`XAcquirer._page` becomes an FxEmbed enrichment that fills `XPageParse`:

- **`videos`:** the best MP4 of each `media.videos[]` entry, in order. Pick from `formats[]`
  with the same "best MP4" rule `_best_mp4` uses today (container mp4, highest bitrate). Use
  `url` when there are no formats.
  - `_syndication_media` already assigns page videos to the syndication's video entries in
    order. Check that the multi-video post then yields every video, and fix that function if it
    does not.
- **`engagement`:**
  - `views` → `play`;
  - `reposts` → `share`;
  - `likes` → `like`;
  - `replies` → `comment`.

  These are the same keys `tweet_engagement` produced. `with_page` keeps merging only `play`
  and `share` over the syndication counts, as today.
- **`text`:** `raw_text.text`, or `text`, used when the syndication marks the post as long
  (`note_tweet`). Same rule as today.
- **`comments`:** from `replies`. Keep only replies to this post, by its own conversation, that
  have an author, text and a numeric ID. Take at most `MAX_COMMENTS`, in FxEmbed's order. Carry
  over today's `_comment` rules: text cut to `MAX_COMMENT_TEXT`, likes defaulting to 0.
  `dropped_comments` counts the rest.

A failed FxEmbed read gives an empty `XPageParse` and a warning, which is exactly today's
failure shape.

### Profile listing (G4)

`XProfileDiscovery._collect` reads `profile_media`. A new parser maps `results[]` to the
existing `DiscoveredVideo` / `DiscoveredPhoto` with the existing rules:

- **Dropped:**
  - another author's post (`author.screen_name` ≠ handle, case-insensitive);
  - a repost (`reposted_by` present).
- **Video post:** at least one video, becoming a `DiscoveredVideo` with caption, `published_at`
  and engagement (same keys as above).
- **Photo post:** photos and no video, becoming a `DiscoveredPhoto` with up to 20 image URLs.
- **Ranking:** `rank_videos`, unchanged.

Attribution discovery and the creator listing pick this up through `DEFAULT_FACTORIES` and
`CREATOR_PLATFORMS` without any further change.

### Multi-video footage (G6)

`footage/service.py` `_carousel` today accepts only an Instagram `/p/` main. Widen it to an X
main whose report holds two or more videos. Everything after that (source `carousel`, at most
six, the checks, owned files never deleted) stays the same. Its docstring and the 5b spec
reference get updated.

### Card anchors (G5)

- **Profile card.** Replace `PROFILE_CARD_SELECTOR = 'main > div:nth-child(4):has-text(...)'`
  with a shape rule measured in the page, in the spirit of `MEDIA_BOX_JS`/`PROFILE_PAGE_JS`.
  - The header is the block of the primary column from its top (the banner) down to the top of
    the first `article`.
  - It must contain the `@{owner}` text, so a wrong page never yields a card.
- **Profile page.** `PROFILE_PAGE_ITEMS = "main article"` with one row has never produced a
  profile page live. The builder finds out why on the Task 0 recon and fixes it. If the
  signed-out profile renders no posts at all, the profile page is reported as not captured,
  and the reason is logged.
- **Post card and `media_box`** work today and are left alone.

## Observability

One info line per X acquisition and per X profile listing gives the FxEmbed outcome:

- for a post: `videos=`, `replies=`, `cards=`;
- for a listing: `videos=`, `photos=`, `dropped=`;
- plus `reason=` on failure.

Every fallback is a warning.

## Tests (offline, test first)

- **Fixtures** from the recorded JSON (`status.json`, `conv.json`, `media.json`), trimmed to the
  fields used, with no URLs beyond what the parsers need:
  - status → two videos in order, the engagement keys, long text;
  - replies → comments, drop rules, cap;
  - media listing → split, other-author and repost drops, photos;
  - error shapes → each reason;
  - a 404 `code`.
- **Acquisition:**
  - a multi-video post yields every video in order;
  - an FxEmbed outage yields today's syndication-only report plus a warning;
  - comment targets come from FxEmbed IDs.
- **Footage:** an X main with two videos takes the F2 path; one video does not.
- **Card anchors:** the recorded X profile page in `tests/acquisition/pages/` gets a
  profile-card box from the shape rule. These browser tests run in CI with Chromium, as today.
- **Removed:** the tests for the deleted page-JSON readers. Keep the tests for `page_tweets` as
  `x_search` uses it.

## Live gates (operator authorisation, each its own)

- **Task 0 recon:**
  - one anonymous visit each to an X post page and an X profile page (headless, as the
    acquisition does), to settle the G5 anchors and the profile page;
  - FxEmbed calls for two more posts (a single-video post and a text-only post).
- **Final live check:**
  - one acquisition of the multi-video post above;
  - one X profile listing;
  - one footage run on an X main with two or more videos, if one is at hand.

  Requests are anonymous and at least 30 s apart, and every request is recorded.

## Left to the builder

- The module layout.
- The exact JSON field fallbacks (`raw_text` vs `text`).
- The FxEmbed `count` maximum.
- Whether `operations/x_fixture.py` is ported or retired.
- How the profile-page fix works, once the recon shows the cause.
