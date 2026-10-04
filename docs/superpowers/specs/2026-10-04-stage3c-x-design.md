# Stage 3c: X Acquisition on the Platform Kernel

Status: written spec approved by the operator on 2026-10-04; implemented on branch
`feat/stage3c-x` (see `docs/superpowers/plans/2026-10-04-stage3c-x.md`).

Amended the same day after a throwaway decoder ran over the probe pages. The changes cover
field paths, video variants, long-tweet text, and the shared card browser (sections 2, 3.1,
3.2, 3.4, and 3.5).

## 1. Context and scope

Stage 3a built the platform-neutral acquisition kernel and ported Threads. Stage 3b ported
Instagram. Stage 3c ports X onto the same kernel. Today every X URL routes to legacy Scout,
which reads X through a logged-in CDP tab.

The operator chose these terms:

- Anonymous only. The multi-account rotating login feature follows Stages 3c and 3d. That
  feature is integrated with the UI.
- Full Scout parity where X allows anonymous access. Work that needs a login waits for the
  login feature: replies past the first page, and a profile timeline past what the page
  serves.
- Approach A. The syndication JSON is the core of a post. The page's server-rendered data,
  serialized by seroval, is a best-effort enrichment: first-page replies, views, and
  reposts. A broken enrichment never fails an acquisition.

Unchanged:

- TikTok, Threads, and Instagram behavior.
- YouTube stays `legacy`. Facebook and Reddit stay `unsupported`.
- No new failure codes. `RETRYABLE_FAILURES` and `LEGACY_FALLBACK_ELIGIBLE_CODES` stay as
  they are.
- No live test in the suite.
- A card is never synthetic.

## 2. Access probe evidence (2026-10-04, anonymous, read-only)

These are counts, keys, and enums only. The probe covered a video, an image, a text-only
post, a reply-heavy post, and a profile.

- **Syndication** (`https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=<any>`):
  200 for all four posts.
  - Any token is accepted.
  - Keys: `__typename` (`Tweet`), `id_str`, `text`, `display_text_range`, `created_at`,
    `favorite_count`, `conversation_count`, `user`, `entities`, `mediaDetails`, `photos`,
    `video` (4 or 5 variants), `note_tweet` (long text), `parent`, and the
    `in_reply_to_*` fields.
  - Absent: retweet count, views, and replies.
- **Post page** (request): 200 with no login redirect. A TanStack Router stream carries the
  data as seroval-serialized JavaScript.
  - The syntax has bare keys and about 370 `$R[n]` assignments and references per page.
  - Each page holds 5 to 7 `Tweet` objects: the post, its parent when it is a reply, and
    about 4 to 6 replies.
  - Each tweet carries `full_text`, `favorite_count`, `reply_count`, `retweet_count`,
    `bookmark_count`, `views`, `screen_name`, and, for video, `video_info`.
- **Profile page** (request): 200. It serves about 6 timeline tweets, including a
  `TimelinePinEntry`, in the same format.
- **Syndication profile timeline**: 429.
- **Decoded page tweets**: a throwaway decoder ran over the probe pages.
  - It decoded every page: 4 to 6 tweets per page. It skipped only the router's runtime
    script.
  - Field paths:
    - `rest_id`;
    - `core.user_results.result.core.screen_name`;
    - `details.full_text` and `details.created_at_ms`;
    - for a long tweet, `note_tweet.note_tweet_results.result.text` (`full_text` is cut
      there);
    - `counts.{favorite,reply,retweet}_count`;
    - `views.count`, a decimal string;
    - `reply_to_results.rest_id`;
    - `media_entities2[]`, each with `type` and `video_info.variants[]` of
      `{content_type, url}`.
  - A tweet can appear twice.
- **Syndication media**: `mediaDetails[]` items carry no id and no video variants. The only
  variants are the top-level `video.variants[]` of `{type, src}`. They cover one video and
  carry no bitrate. `note_tweet` carries only an `id`, not the long text.
- **Headless**: the page renders with no login wall.
  - The logged-out layout has no `data-testid` attributes. It shows 3 `<article>`
    elements and one `<video>`.
  - No GraphQL traffic is captured, and `self.$R` is gone after hydration. Headless gives
    no content data, so it is used for cards only.

## 3. Components

### 3.1 Routing (`acquisition/platforms.py`, `acquisition/models.py`)

- `PYTHON_PLATFORM_HOSTS["x"] = frozenset({"x.com", "twitter.com", "mobile.x.com",
  "mobile.twitter.com"})`.
  - `bare_host` strips `www.` and `m.`, so the `mobile.` hosts are listed explicitly.
  - `t.co` is not an X host and stays legacy.
- `ReportSource.platform` accepts `"x"`.

### 3.2 URL identity and parsers (`acquisition/adapters/x.py`)

- **Accepted paths:**
  - `/<handle>/status/<id>`, `/<handle>/statuses/<id>`, `/i/web/status/<id>`,
    `/i/status/<id>`;
  - optionally followed by `/photo/<n>` or `/video/<n>`;
  - with or without a trailing slash.
- **Checks:** query and fragment are dropped. The URL must be https, on an allowlisted
  host, with no userinfo, on port 443 only. These go through the shared
  `_match_safe_path`. Handles match `[A-Za-z0-9_]{1,15}`, and ids are decimal.
- **Identity:** `canonicalize_x_post_url(url) -> XPostIdentity(post_id)`.
  - The canonical URL is rebuilt as `https://x.com/<author>/status/<id>`.
  - `<author>` comes from the tweet's `user.screen_name`, never from the URL.
  - Profile URLs are not posts and fail as `invalid_source_url`.
- **`parse_syndication(data, identity, page_videos) -> XParse | None`:**
  - `post_id` = `id_str`. The id must equal the identity's.
  - `text` is sliced by `display_text_range`. That drops the leading reply mentions and
    the trailing media `t.co` link.
  - A long tweet (`note_tweet` present) is truncated in syndication. When the page parse
    found the post, the page's text replaces it.
  - `owner_handle` = `user.screen_name`. A missing or invalid value gives `None`.
  - `published_at` comes from `created_at`.
  - `engagement`: `like` = `favorite_count`, `comment` = `conversation_count`.
  - Media keep the order of `mediaDetails`:
    - `video` and `animated_gif` take the largest-resolution https `video/mp4` variant.
      The size is the `<w>x<h>` path segment, and the first variant wins a tie.
    - The n-th video item takes the n-th video of the page's post. A single video falls
      back to the syndication `video.variants`. A video with neither is skipped.
    - `photo` takes `media_url_https` with `name=orig`.
    - An item with no https URL is skipped. A quote tweet's media are not the post's.
  - A text-only post is valid.
  - A `TweetTombstone`, or any other `__typename`, gives `None`.
- **`parse_page(roots, identity) -> XPageParse`.** The roots are the decoded seroval
  values.
  - For the post: `play` (`views.count`, a decimal string) and `share`
    (`retweet_count`).
  - Replies: distinct tweets whose `reply_to_results.rest_id` equals the post id.
    - Fields: `comment_id` = `rest_id`, `author` = `screen_name`, and
      `likes` = `favorite_count`.
    - `text` = the note text when present, else `full_text`. Either way, the leading
      `@mentions` and the trailing `t.co` links are removed, and the result is cut to 2,000
      characters. The post's own page text follows the same rule.
    - First seen wins on a duplicate. Invalid entries are dropped and counted. At most 50.
  - Nothing found gives an empty parse, never an error.

### 3.3 Seroval decoder (`acquisition/adapters/seroval.py`)

A pure decoder for the subset of seroval output X serves:

- object and array literals, with bare or quoted keys;
- strings with escapes;
- numbers, booleans, `null`, `undefined`, and `!0`/`!1`;
- `$R[n]=<value>` assignments and `$R[n]` references, including cycles;
- the stream wrapper `($R=>...)($R["..."])`.

`decode_scripts(html) -> list[object]` reads every script that carries `$R` and returns
the decoded values. Any construct outside the grammar makes that script decode to nothing.
The decoder never raises and never runs code.

### 3.4 Service and acquirer (`acquisition/x_service.py`)

- **`XRequestFetcher`** wraps the existing `_scrapling_get`:
  - `syndication(id) -> dict`;
  - `page(url) -> str`.
  - A login redirect or a non-200 status raises `RequestFetchError(REQUEST_BLOCKED)`.
    A timeout raises `REQUEST_TIMEOUT`.
- **Shared card browser.** Several pieces move from Instagram to
  `acquisition/card_browser.py`: the card session, crop, tagging, persistence, and outcome
  logging.
  - Each platform supplies a `CardLayout`: the post and profile selectors, the tagging
    script, the login paths, and an optional dialog to dismiss.
  - Instagram behavior is unchanged.
- **`XHeadlessBrowser`** is a `CardBrowser` with the X layout. It opens one lazily opened
  stealthy session and is used for cards only.
  - On the post page:
    - The post card comes from the post selector, and only when the post has no video.
    - The tagging script tags comment rows. A row is a top-level `<article>`, never a
      nested quoted one. It must not be tagged yet, and it must hold both `@<author>` and
      the reply's text prefix.
  - On the profile page: the profile card.
  - The post and profile selectors are provisional (`article` and `main`). The capture
    fixes them.
- **`XAcquirer.inspect`** runs these steps:
  1. Identity.
  2. Syndication, then `parse_syndication`.
  3. Page, then `decode_scripts`, then `parse_page`. Failures here are logged and
     ignored.
  4. Media through the shared `materialize_media`.
  5. Cards.
  6. A v3 report with `platform="x"`.
- **Method:** `CONTENT_METHOD = "request"`. Headless serves no content data on logged-out
  pages, as section 2 records, so the capture records both methods as evidence and
  headless never parses content.
- `registry.py` gains an X branch.

### 3.5 Profile discovery (`acquisition/x_discovery.py`)

- One request for `/<handle>`: decode the seroval scripts, then read the timeline tweets.
- Kept: video tweets (`video_info` present) authored by the handle (case-insensitive).
  - Reposts and other authors are dropped and counted.
  - A pinned tweet is kept like any other.
- Mapping to `DiscoveredVideo`:
  - `post_id` = `rest_id`.
  - `canonical_url` rebuilt.
  - `caption` = `full_text`.
  - `published_at` from `details.created_at_ms`.
  - `engagement` = `like`, `comment`, `share`, `play`.
- Ranked with the shared `rank_videos` (likes, views, recency), then cut to `limit`.
  - Anonymous pages serve about 6 tweets.
  - `pages=1`, `exhausted=False`.
- Failures never raise. A login redirect or a block is `blocked`. No timeline is
  `no_data`. A timeout is `timeout`.

### 3.6 Operator tools (`operations/x_capture.py`, `operations/x_fixture.py`)

- **`x_capture`** reads the operator's URL file (`<kind> <url>`, with kinds `video`,
  `image`, `text`, `replies`, `profile`). It writes raw captures and card PNGs only under
  `D:/thoth-tmp/bu/x/`. It prints counts only.
- **`x_fixture`** sanitizes with the Stage 2 and 3b helpers:
  - handles, ids, and text are pseudonymized;
  - media URLs are made synthetic;
  - counters are floored;
  - timestamps are synthetic.
  - It applies the shared `leak_count` and refuses to write a leaking fixture.

## 4. Data flow and load

- Per post: two requests (syndication and the page) and up to two headless visits (the
  post page and the profile page), spaced as in 3b.
- Per profile discovery: one request.

## 5. Error handling

| Condition | Code | Retryable / legacy fallback |
|---|---|---|
| Not a valid X post URL | `invalid_source_url` | no / no |
| Syndication blocked, non-200, or a login redirect | `request_blocked` | yes / yes |
| Request timeout | `request_timeout` | yes / yes |
| Tombstone, unknown typename, id mismatch, or invalid author | `request_incomplete` | yes / yes |
| No text and no media | `no_content` | no / no |
| Media fails validation | `media_validation_failed` | existing rules |
| Page fetch, decode, or parse fails | none: replies are empty, `warn` with counts only | |
| A card fails | none: `cards.problems`, never in `outcome.attempts`, never synthetic | |

Logs never carry a URL, a raw handle, or tweet or reply text.

## 6. Live capture and golden fixtures

- The capture is a HARD STOP. It needs operator authorization at capture time, with a URL
  file the operator writes and Claude never reads: `video`, `image`, `text`, `replies`,
  `profile`.
- Fixtures go under `python/tests/fixtures/x/`, all sanitized with 0 leaks:
  - `video`, `image`, `text`, `replies`: each holds the syndication JSON and the decoded
    page roots;
  - `profile`: the decoded timeline roots.
- What the golden replay covers:
  - The replay runs `parse_syndication`, `parse_page`, and the discovery parse.
  - The seroval decoder is covered by synthetic samples built from the observed grammar.
  - The decoder's success on real pages is recorded as capture evidence: decoded tweet
    counts per page.

## 7. Testing (offline only)

- **URL identity:** every accepted and rejected shape.
- **Seroval:**
  - references, nested and cyclic;
  - escapes and numbers;
  - the wrapper;
  - an unknown construct decodes to nothing.
- **Syndication:**
  - the highest-bitrate MP4, photo order, GIF;
  - `note_tweet` and `display_text_range`;
  - text-only posts, tombstones, an id mismatch, an invalid author.
- **Page:** direct replies only, duplicates, the 50 cap, `play` and `share`.
- **Acquirer:**
  - every row of section 5;
  - card isolation;
  - the browser closes on cancellation;
  - a page failure still yields a report.
- **Discovery:** own videos only, reposts dropped, ranking, the limit, each reason.
- **Comment tagging:** a browser test that skips without Playwright, as in 3b.

Verification: the WSL full suite, plus Ruff check and format. No Rust changes.

## 8. Success criteria

1. An X post link runs the Python acquirer and yields a v3 report. The report has media,
   first-page replies, and real cards where cropping succeeds.
2. A seroval or card failure never fails an acquisition. No card is synthetic.
3. Profile discovery returns the handle's own video tweets, ranked by likes, views, and
   recency.
4. TikTok, Threads, and Instagram are unchanged. The full suite passes with no live test.

## 9. Gates outside this spec

- The live capture needs operator authorization at capture time.
- Push, merge, and deploy are each a separate operator authorization.
- Replies past the first page and a longer timeline wait for the login feature.
- Anonymous profile pages serve about six tweets. In the probe, one of five was a video, so
  X discovery often yields 0 or 1 videos until the login feature lengthens the timeline.
  The operator chose to build it now regardless.
- The seroval format is X's front-end internals. Watch it at the live smoke; the
  syndication core keeps posts working if it changes.
