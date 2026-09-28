# Stage 3b: Instagram Acquisition on the Platform Kernel

Status: design approved section by section by the operator on 2026-09-28; written spec
awaiting operator review.

## 1. Context and scope

Stage 3a (merged 2026-09-28) built the platform-neutral acquisition kernel: `SourceReport`
v3, the `platforms.py` routing table, the `registry.py` acquirer lookup, an image-capable
materializer, and Threads as the first ported platform. Stage 3b ports Instagram onto that
kernel with full Scout parity:

- post content, media, and the post card;
- first-page comments with real per-comment cards;
- the owner's profile card;
- profile discovery (a library with no caller until Stage 8, like TikTok discovery).

Out of scope:

- Any Instagram login or session cookie. Comment pagination, the grid beyond 12 posts,
  and view/play counts need one. Operator direction (2026-09-28): after 3b is implemented,
  a separate feature with its own spec adds login support for every platform, holding a
  pool of accounts per platform used in rotation; the login-only capabilities are tested
  then.
- `instagr.am` short links and profile URLs as acquisition input.
- Renaming the TikTok-named shared types (`TikTokNumericId`, `TikTokHandle`,
  `DiscoveredVideo`).
- Structured JSON logging. The operator wants it system-wide later; it is not part of 3b.
- Any live test in the suite, any Rust change, and the Stage 5 content-set mapping.

## 2. Operator decisions (2026-09-28)

1. Scope C: full Scout parity (post, media, post card, comments, profile card, profile
   discovery).
2. Method order: an anonymous Scrapling request pushed as far as it goes, then anonymous
   Scrapling headless, then report back before anything else. The feasibility probe found
   both sufficient for scope C except the items listed as out of scope above.
3. Comment cap C: accept the anonymous first comment page (6 to 14 comments per post in
   the probe). An optional IG session cookie is a later decision.
4. Link shapes C: plain post links and app share links are both supported.
5. Approach 1: an Instagram acquirer on the 3a kernel, following the Threads pattern.
6. Stage 3a rulings still apply: request wins when it matches or beats headless; the card
   method is decided per capability and headless opens only when a card is needed; no
   runtime request-to-headless fallback; Facebook and Reddit stay unsupported.

## 3. Architecture

### 3.1 URL identity (`acquisition/adapters/instagram.py`)

- Accepted post URL: `https://` only; host `instagram.com`, `www.instagram.com`, or
  `m.instagram.com`; path `/p/<code>/`, `/reel/<code>/`, `/reels/<code>/`, or
  `/tv/<code>/` with `code` matching `[A-Za-z0-9_-]{1,64}`. Query (including `?igsh=`),
  fragment, and a missing trailing slash are ignored.
- The canonical URL is always rebuilt as `https://www.instagram.com/p/<code>/`, never
  taken from Instagram.
- Share links: `/share/<token>/`, `/share/reel/<token>/`, `/share/p/<token>/`, with the
  token matching the same pattern. They are resolved before acquisition (section 3.4); the
  landing URL must itself parse as a post URL.
- Anything else, including profile URLs, fails as `invalid_source_url` (non-retryable,
  not fallback-eligible).
- `owner_handle` comes from the post's `user.username`, because an Instagram post URL
  carries no owner.

### 3.2 Routing and registry

- `PYTHON_PLATFORM_HOSTS["instagram"] = frozenset({"instagram.com"})`, so the default
  `python_tiktok_with_legacy_fallback` mode runs Instagram through Python and the
  existing fallback-eligible codes still fall back to legacy Scout.
- `registry.acquirer_for` gains an `instagram` branch returning `InstagramAcquirer`.
- Tests that used an Instagram URL as the "still legacy" example move to an X URL.

### 3.3 Model changes

- `ReportSource.platform` adds `"instagram"`. No other model changes.
- `SourcePost`: `post_id` = the post `code`; `text` = `caption.text` (empty when absent);
  `published_at` from `taken_at` (epoch seconds, UTC); `engagement` holds `like` and
  `comment` only, and is empty when `like_and_view_counts_disabled` is true.
- Comments use the existing `ReportComment`: `comment_id` = `pk` (numeric),
  `author` = `user.username`, `text`, `likes` = `comment_like_count`, and `card` = a real
  crop or `None`.

### 3.4 Instagram service (`acquisition/instagram_service.py`)

`InstagramAcquirer.inspect` runs, in order:

1. Share-link resolution when the input is a share link.
2. Request for content: one Scrapling `AsyncFetcher` GET of the canonical post URL with
   the Threads `REQUEST_OPTIONS`. The parser reads the `script[type="application/json"]`
   blobs and finds the `xig_polaris_media.if_not_gated_logged_out` node whose `code`
   matches.
3. Media materialization through the existing materializer:
   - carousel: `carousel_media` items in order; otherwise the post itself as one item;
   - an item with `video_versions` is a video (the widest version); otherwise an image
     (the widest `image_versions2` candidate);
   - at most `MAX_MEDIA_ITEMS` (20).
4. Comments from `xig_polaris_media.comments_connection.edges`, at most `MAX_COMMENTS`
   (50). A comment with empty text (for example a GIF-only comment) is dropped.
5. Cards through one anonymous `AsyncStealthySession` with two sequential navigations:
   - post page: dismiss the sign-up dialog through
     `div[role=dialog] svg[aria-label="Close"]`; crop the post card from
     `main > div > div` only when the post has no video media (the 3a rule); crop each
     first-page comment row, matched to a parsed comment by its author link
     (`/<username>/`) and the start of its text. The row selector is confirmed at the
     capture; an unmatched or unconfirmed row gets `card = None`;
   - profile page `/<owner>/`: dismiss the dialog, crop `header` as the profile card.
6. Build the v3 report. The browser is always closed in `finally` behind
   `asyncio.shield`, as in Threads.

Cards are written with `write_card` under `reports/<workflow_id>/cards/` as `post.png`,
`comment-<comment_id>.png`, and `profile.png`, and pass the existing card size and
density guard. A card is never synthetic.

Module constants record the decisions from section 6: `CONTENT_METHOD` (provisionally
`request`) and `SHARE_RESOLUTION_METHOD` (provisionally `request`: a Scrapling request with
safe redirects; the alternative is the Threads browser `wait_for_url` resolution). Both
parsers stay because the method-decision test replays them.

### 3.5 Profile discovery (`acquisition/instagram_discovery.py`)

- `InstagramProfileDiscovery.discover(ProfileDiscovery) -> DiscoveryResult`, request only:
  one Scrapling GET of `/<handle>/`, reading `xig_user_by_username` and the 12 nodes in
  `polaris_ordered_timeline_connection.edges`.
- Mapping to the existing `DiscoveredVideo`: `post_id` = `pk` (numeric);
  `canonical_url` rebuilt as `https://www.instagram.com/p/<code>/` after validating `code`;
  `caption`, `published_at`; `engagement` = `like` and `comment`; `duration_seconds` and
  `hashtags` left empty.
- Kept: video posts only (`media_type == 2`), matching legacy `igProfileReels`. Image and
  carousel posts count in `drops.photo_posts`; malformed nodes count in `drops.invalid`.
- Sorted by `like_count` descending (the legacy view sort is unavailable anonymously), then
  cut to `limit`. At most 12 results whatever the limit; `pages=1`, `exhausted=False`.
- Failures return an empty `DiscoveryResult` with a reason and never raise: login redirect
  is `blocked`; no user or timeline in the JSON (including private accounts) is `no_data`;
  timeout is `timeout`.

## 4. Data flow and progress

1. API intake and the workflow guard use `platform_support` unchanged; Instagram URLs
   become `python`.
2. The Python activity resolves `acquirer_for(url)` and calls `inspect`; the runner builds
   and closes the shared HTTP client and materializer as today.
3. Progress stage names follow `<platform>_<method>`: `instagram_request` and
   `instagram_headless`.
4. `legacy_scout` rollback mode still sends Instagram to legacy Scout.

## 5. Error handling

No new failure codes; `RETRYABLE_FAILURES` and `LEGACY_FALLBACK_ELIGIBLE_CODES` are
unchanged.

| Condition | Code | Retryable / fallback |
|---|---|---|
| Not a valid post or share URL | `invalid_source_url` | no / no |
| Share link lands on a non-post path | `invalid_source_url` | no / no |
| Request timeout (post or share resolution) | `request_timeout` | yes / yes |
| Login redirect, `require_login`, HTTP 403 or 429 | `request_blocked` | yes / yes |
| Post node missing (private, age-restricted, or deleted; indistinguishable anonymously) | `request_incomplete` | yes / yes |
| Empty caption and no media | `no_content` | no / no |
| CDN 429 / other CDN failure | `cdn_rate_limited` / `cdn_unavailable` | yes / yes |
| Magic bytes or size mismatch | `media_validation_failed` | yes / yes |

Never failures:

- A missing `comments_connection` (comments disabled) gives `comments == []`. Each comment
  failing validation (non-numeric `pk`, username outside the handle pattern, text empty
  or over 2000 characters) is dropped and counted at `debug`.
- Any card problem (headless cannot start, times out, dialog not dismissible, selector
  missing, crop rejected by the guard) leaves that card `None` with a `warning` naming the
  reason. Card failures are not added to `outcome.attempts`, which records only the
  content method, as in TikTok and Threads.

Logging: `info` for the final summary (method, media count, comment count, cards written),
`warning` for missing cards and degradation, `debug` for dropped comments. No URL, raw
handle, or caption text is logged. No raw diagnostic crosses into Temporal history.

## 6. Method comparison and golden fixtures

### 6.1 Live capture (operator authorization at capture time)

- One read-only anonymous session against public posts the operator supplies at capture
  time: one reel or video, one image, one carousel, one share link, plus one profile (the
  owner of one of those posts) for discovery.
- Each post is fetched once per method: the request post HTML, and the headless visit's
  page JSON plus the post card, comment card, and profile card crops. The share link
  records where the request and the headless resolution each land. The profile is fetched
  once by request. Hits are spaced a few seconds apart.
- A manual CLI `operations/instagram_capture.py` does the capture. It is outside the suite,
  writes only under `D:/thoth-tmp/`, and prints counts only. Raw captures are never
  committed or printed.

### 6.2 Comparison (offline)

Both content parsers replay the raw capture and count post fields present, media that pass
the materializer's validation rules, comments parsed, and blocked outcomes. The request
method wins when it matches or beats headless on every count and was not blocked. Share
resolution uses request when the request lands on a post path, otherwise the browser.
Cards are always headless. The result is recorded as restricted evidence (counts, keys,
enums only) in `CHANGELOG.md` and the checkpoint, and sets the section 3.4 constants.

### 6.3 Golden fixtures

- `operations/instagram_fixture.py` sanitizes the capture with the Stage 2 helpers:
  caption and comment text pseudonymized; handles, `pk`, and `code` replaced by stable
  pseudonyms (`pk` stays numeric); synthetic timestamps on a one-hour grid; counters kept
  to two significant digits; CDN URLs replaced by synthetic URLs.
- Committed under `python/tests/fixtures/instagram/`: `video`, `image`, `carousel`,
  `share`, and `profile`, each with the sanitized responses and the expected parser output,
  passing the leak check with 0 leaks. Card PNGs are not committed; tests use
  `png_fixtures.make_png`.

## 7. Testing (offline only)

The conftest `_offline_unless_live` guard is not changed. New or changed tests:

- URL identity: every accepted shape (`/p/`, `/reel/`, `/reels/`, `/tv/`, the three share
  forms, `?igsh=`, `www.`, `m.`, no trailing slash); rejected profile URLs, `instagr.am`,
  `http://`, and bad codes.
- Routing: Instagram is `python`; `acquirer_for` returns the Instagram acquirer; the moved
  legacy-example tests use X.
- Parser: golden replay matches exactly; carousel order and the 20-item cap; widest video
  version chosen; carousel video items become videos; disabled counts give empty
  engagement; the 50-comment cap and per-comment drops; a missing node is
  `request_incomplete`; a login redirect is `request_blocked`.
- Service: the post card only for non-video posts; unmatched comment rows get
  `card = None`; a failing headless still yields a report without cards; the browser is
  closed on cancellation.
- Discovery: video only, like-sorted, `limit` respected, at most 12; drop counts and each
  reason.
- Method decision: the chosen content and share methods still match or beat the other on
  the fixtures.
- `SourceReport` v3 accepts `platform="instagram"`.

Verification: WSL Python 3.12 full suite and ruff check and format. No Rust changes are
planned, so `build_cuda.bat` is not required. The pre-existing master failure
`tests/api/test_workflows.py::test_route_modules_do_not_depend_on_a_process_runner` is
reported as-is, not counted as a new failure.

## 8. Success criteria

1. Instagram post and share links run the Python acquirer in the default mode and produce
   a valid v3 report with media, first-page comments, and real cards where cropping
   succeeds.
2. Card failures never fail acquisition, and no card is synthetic.
3. Profile discovery returns like-sorted video posts from the anonymous 12-post grid.
4. The content and share-resolution method decisions are recorded with
   offline-reproducible evidence.
5. TikTok and Threads behavior is unchanged.
6. The full suite passes with no new failures and no live test.

## 9. Gates outside this spec

- The Instagram live capture needs operator authorization at capture time, with the posts,
  share link, and profile supplied by the operator.
- Login-only capabilities (comment pagination, grid beyond 12, view counts) wait for the
  separate multi-account, rotating login feature that follows 3b.
- About three Instagram hits per acquired post (post request, post page, profile page) is
  a rate risk to observe at the live smoke.
- Push, deployment, and any live smoke stay operator gates; live smokes wait for the final
  acceptance (ADR 0001).
