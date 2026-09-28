# Stage 2: TikTok Discovery Primitives and Engagement Normalization Design

**Status:** Design approved in conversation by the operator on 2026-09-27; written spec awaiting
operator review

## 1. Purpose and boundary

Stage 2 of the [Python Scout migration](../../python-scout-migration-roadmap.md) completes the
TikTok vertical slice. The single-post enrichment sub-stage (comments and real card artifacts) is
merged. This spec covers the remaining Stage 2 items:

- item 5, profile discovery;
- item 6, keyword and trending discovery;
- item 7, engagement and publication-time normalization.

The deliverable is a set of **acquisition primitives**: typed, strict, offline-tested functions
that turn a profile handle, a keyword, or "trending" into a list of discovered TikTok videos. No
production caller is added. Discovery orchestration (curated accounts, topic-to-URL, batch
scheduling, checkpoints, starting durable workflows from candidates) is Stage 8. Aggregating
hashtags into trending topics is Stage 8 as well.

Operator decisions that bind this design:

- Scout's approach is not ported. Scout scrapes DOM tiles, verifies each candidate caption through
  oEmbed (rate-limited to 429 in Stage 1, see ADR 0001), and reads trending from TikTok Studio,
  which needs a creator login.
- Captchas are avoided, never solved or blocked. Discovery uses only page routes that TikTok
  serves to an anonymous headless session. When TikTok still refuses, the primitive stops and
  reports a typed `captcha` reason. No captcha solver, no captcha-host blocking, no retry that
  re-triggers the challenge.
- No paid scraping service and no proxy is part of this design.
- Item 7 is delivered in the same sub-stage: the normalizer that discovery needs also fills the
  already-existing `TikTokPost.published_at` and `TikTokPost.engagement` fields on the single-post
  path.

## 2. Feasibility evidence

One read-only anonymous live probe was authorized by the operator on 2026-09-27. It recorded
counts, key names and enums only. Raw captures stay outside the repository.

Findings that shape the design:

- TikTok's JSON APIs carry signatures (`X-Bogus`, `X-Gnarly`, `msToken`) produced by the page's
  own SDK. Requests built outside that flow return HTTP 200 with an empty body. This held for an
  unsigned fetch, for an XHR auto-signed by the page, and for a replay of the page's own
  parameters. Building or signing requests is a dead end.
- The page's own requests succeed and their response bodies can be captured.

| Capability | Page | API captured | Headless result |
|---|---|---|---|
| Profile videos | `/@{handle}` | `/api/post/item_list/` | 16 items per page, `hasMore`, a scroll loads the next page, no captcha |
| Keyword videos | `/search?q=` | `/api/search/general/full/` | 12–13 entries per page after a warm-up visit, no captcha |
| Keyword videos | `/search/video?q=` | `/api/search/item/full/` | captcha, empty body: **not used** |
| Trending videos | `/explore` | `/api/explore/item_list/` | 6–8 items per page, `hasMore`, no captcha |

The following were also ruled out:

- **Creative Center** now requires a login and answers `invalid user`.
- **TikTok Studio** requires a creator login.
- **TikWM `feed/search`** answers 403 behind a Cloudflare challenge.
- **Blocking the captcha host.** A headless run with the verification host in Scrapling's
  `blocked_domains` still got a 0-byte `search/item/full` body and still rendered the captcha
  container. The refusal is server-side; the captcha is only its symptom.

All three captured APIs return the same item shape:

- `id` (string), `desc` (string), `createTime` (epoch seconds, number);
- `stats` (numbers) and `statsV2` (decimal strings), each with `playCount`, `diggCount`,
  `commentCount`, `shareCount` and `collectCount`;
- `video.duration` (seconds, number);
- `author` with `uniqueId`, `secUid` and `verified`;
- `challenges` (array; `title` is the hashtag);
- `imagePost` (present only on photo posts);
- `isAd` (boolean).

Search wraps each item as `data[] = {type, item, common}`. Only `type == 1` entries are videos.

## 3. Contracts

All new models live in `acquisition/models.py` and extend `StrictModel`. They reuse
`TikTokNumericId` and `TikTokHandle`.

```python
DiscoveryKind = Literal["profile", "keyword", "trending"]

class DiscoveryReason(StrEnum):
    CAPTCHA = "captcha"                  # empty/non-JSON API body or captcha container rendered
    BLOCKED = "blocked"                  # API JSON with a non-zero status code
    NO_DATA = "no_data"                  # no matching API response was captured
    TIMEOUT = "timeout"                  # navigation or the scroll deadline expired
    BROWSER_UNAVAILABLE = "browser_unavailable"  # the Scrapling stack could not start

class ProfileDiscovery(StrictModel):
    kind: Literal["profile"] = "profile"
    handle: TikTokHandle
    limit: Annotated[int, Field(ge=1, le=100)] = 30

class KeywordDiscovery(StrictModel):
    kind: Literal["keyword"] = "keyword"
    query: Annotated[str, Field(min_length=1, max_length=100)]  # stripped; no control characters
    limit: Annotated[int, Field(ge=1, le=100)] = 30

class TrendingDiscovery(StrictModel):
    kind: Literal["trending"] = "trending"
    limit: Annotated[int, Field(ge=1, le=100)] = 30

DiscoveryRequest = Annotated[
    ProfileDiscovery | KeywordDiscovery | TrendingDiscovery, Field(discriminator="kind")
]

class DiscoveredVideo(StrictModel):
    post_id: TikTokNumericId
    owner_handle: TikTokHandle
    canonical_url: HttpUrl               # rebuilt from handle and id, never taken from TikTok
    caption: Annotated[str, Field(max_length=10_000)] = ""
    published_at: str | None = None      # ISO 8601 UTC, "YYYY-MM-DDTHH:MM:SSZ"
    duration_seconds: Annotated[float, Field(ge=0)] | None = None
    engagement: dict[EngagementKey, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    hashtags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list)

class DiscoveryDrops(StrictModel):
    ads: int = 0
    photo_posts: int = 0
    invalid: int = 0                     # missing/invalid id or handle

class DiscoveryResult(StrictModel):
    kind: DiscoveryKind
    videos: list[DiscoveredVideo]        # deduplicated by post_id, first seen wins, at most limit
    pages: Annotated[int, Field(ge=0)]
    exhausted: bool                      # the last captured page reported no more results
    drops: DiscoveryDrops
    reason: DiscoveryReason | None = None
```

`EngagementKey = Literal["play", "like", "comment", "share", "collect"]`. The single-post
`TikTokPost.engagement` stays `dict[str, int]` for schema compatibility, but it only ever receives
keys produced by the same normalizer.

A result with `reason` set and non-empty `videos` is a valid partial result: the reason says why
collection stopped early. Retrying and checkpointing are Stage 8 decisions.

## 4. Components

### 4.1 Normalizer (`acquisition/normalize.py`)

These are pure functions shared by discovery, the headless single-post path, and the TikWM
adapter.

- `normalize_engagement(stats: object, stats_v2: object) -> dict[str, int]`
  - The key map is `playCount→play`, `diggCount→like`, `commentCount→comment`,
    `shareCount→share` and `collectCount→collect`.
  - `statsV2` is preferred because its decimal strings do not lose precision.
  - `stats` is the fallback per key.
  - A value that is not a non-negative integer (or a decimal string of one) is skipped, never
    guessed.
  - Booleans are rejected.
- `published_at_from_epoch(value: object) -> str | None`
  - A positive integer epoch-seconds value becomes a UTC ISO string.
  - Anything else, or a value outside the representable range, returns `None`.

### 4.2 Parser (`acquisition/discovery.py`)

`parse_discovery_page(kind, body: bytes) -> DiscoveryPage` is pure and is the offline test seam.

- `DiscoveryPage` is an internal dataclass, not a contract. It holds `videos`, `has_more` and
  `drops`, plus `reason` (`captcha` / `blocked` / `None`).
- Where each page type keeps its items:
  - profile and trending read `itemList`;
  - keyword reads `data[]` entries where `type == 1` and uses `entry.item`.
- The status code comes from `statusCode`, falling back to `status_code`.
- The "has more" flag comes from `hasMore` or `has_more`. The value is truthy when it is either
  `true` or `1`.
- An empty or non-JSON body is `captcha`.
- A non-zero status code is `blocked`.
- Each item is filtered in this order:
  1. `isAd` true → `drops.ads`;
  2. `imagePost` present → `drops.photo_posts`;
  3. an invalid id or handle, or a model validation failure → `drops.invalid`.
- The caption is `desc`, truncated to 10,000 characters.
- Hashtags come from `challenges[].title`, keeping only non-empty strings.
- `canonical_url` is `https://www.tiktok.com/@{handle}/video/{id}`.

### 4.3 Browser (`acquisition/discovery.py`)

`ScraplingDiscoveryBrowser.discover(request: DiscoveryRequest) -> DiscoveryResult`

**Session.** One `AsyncStealthySession` per call, closed afterwards. It reuses
`_default_session_factory` and the active-session counter from `browser.py`, with these settings:

- `headless=True`, `max_pages=1`, `network_idle=True`, `disable_resources=False`;
- `capture_xhr` matching only
  `/api/(post/item_list|search/general/full|explore/item_list)/`, so no other response body is
  held.

**Pages.** Each kind opens one page:

| Kind | Page |
|---|---|
| profile | `https://www.tiktok.com/@{handle}` |
| keyword | `https://www.tiktok.com/search?q={quote(query)}` (never `/search/video`) |
| trending | `https://www.tiktok.com/explore` |

**Warm-up.** Keyword discovery first visits `/explore` in the same session. That visit's
captured responses are discarded. Profile and trending need no warm-up.

**No routing.** Unlike the post session, this session does not reroute or empty any request:
`item_list` is exactly what is needed here.

**Pagination.** A `page_action` scrolls with `mouse.wheel` and waits for the next matching
response, up to 3 seconds per scroll. It stops on the first of:

- the unique-video count reaching `limit`;
- a page reporting no more results;
- two consecutive scrolls with no new page;
- the captcha container rendering;
- `MAX_SCROLLS = 10`;
- a 60-second deadline.

The count used for stopping is a cheap in-page tally. The authoritative parse happens after the
fetch, from `captured_xhr`, through `parse_discovery_page`.

**Assembly.** Pages are parsed in capture order and videos are deduplicated by `post_id`, first
seen wins. The list is truncated to `limit` and `drops` are summed. `exhausted` is true when the
last captured page reported no more results. The first page reason (`captcha` or `blocked`) stops
assembly: videos from earlier pages are kept, later pages are ignored.

**Result reason.** When no page reason was hit, `reason` is set as follows:

| Condition | `reason` |
|---|---|
| Captcha container rendered | `captcha` |
| No matching response captured | `no_data` |
| Playwright timeout | `timeout` |
| Session factory or browser start failed | `browser_unavailable` |

The primitive never raises for these conditions. It raises only for programmer errors, such as
an invalid request model.

**Logging.**

- `info`: kind, page count, video count, drop counts and reason.
- `warning`: when the reason is `captcha` or `blocked`.
- Handles, queries, captions, URLs and ids are never logged.

### 4.4 Single-post normalization (item 7)

These changes use the same normalizer:

- **`extract_browser_snapshot`.** When the item struct is available, fill
  `TikTokPost.published_at` from `createTime` and `engagement` from `stats`/`statsV2`.
- **`parse_tikwm_payload`.** Fill `published_at` from `data.create_time` and engagement from
  `data.play_count`, `digg_count`, `comment_count`, `share_count` and `collect_count`. These field
  names are an assumption: the committed TikWM fixture does not carry them. Missing fields leave
  the values empty and never raise.
- **`_merge_post`.** Merge per field. `published_at` comes from headless when present, else from
  the provider. `engagement` is the headless dict when it is non-empty, else the provider dict.
  Caption precedence and identity precedence are unchanged.

`TikTokSourceReport` needs no schema change: both fields already exist and are optional. Schema
v1 and v2 reports keep validating.

## 5. Fixtures and data hygiene

Sanitized golden fixtures go under `python/tests/fixtures/tiktok/discovery/`:
`profile.json`, `search.json` and `explore.json`. Each holds up to two captured pages.

- They are produced by a new operator tool, `operations/tiktok_discovery_fixture.py`, which
  reuses the comment fixture's pseudonym helpers:
  - ids become synthetic numeric ids;
  - handles become pseudonyms;
  - captions and hashtags become synthetic text of the same length;
  - media, cover, avatar and every other URL are dropped;
  - only the keys the parser reads are kept.
- Engagement numbers and `createTime` are de-identified, because exact values could still
  identify a post:
  - each counter is floored to two significant digits, keeping its type and digit count;
  - each distinct `createTime` becomes a synthetic epoch, starting at `1700000000` and adding
    one hour per value in order of first appearance, keeping its type;
  - a value the normalizer rejects is dropped, which replays the same.
- `expected` is the parser's replay of the sanitized pages. The tool refuses to write when the
  raw capture replays to a different shape: publication time present or absent, and counters
  at two significant digits.
- At generation time the tool checks that no original id, handle, caption or hashtag survives.
  Id and handle slots are checked by whole value, and other text by substring. Short words are
  checked where they stood. The counts are recorded in the SDD ledger; the originals are never
  committed.
- Raw captures stay under `D:/thoth-tmp/bu/out/` and are never committed or described publicly.
- The fixture capture is a separate read-only live run. It needs its own operator authorization
  at the plan execution gate. The feasibility probe does not cover it.

Synthetic in-test payloads cover every edge the captures do not contain. Examples: ads, photo
posts, `statsV2` absent, a non-numeric stat, `hasMore` as `1`, and non-zero status codes.

## 6. Testing

Every test is offline. The conftest network guard stays as it is.

**Normalizer**

- `statsV2` precedence and per-key fallback to `stats`;
- rejection of non-numeric, negative and boolean values;
- epoch to ISO UTC, and out-of-range or non-integer input to `None`.

**Parser**

- the golden shape of each page type;
- `type == 1` filtering for search;
- drop counts for ads, photo posts and invalid entries;
- `captcha` for an empty or non-JSON body;
- `blocked` for a non-zero status code;
- the canonical URL rebuilt from handle and id.

**Browser, with a fake session factory**

- the page URL for each kind, including an encoded query;
- warm-up for keyword only, with warm-up responses discarded;
- each stop condition;
- deduplication across pages and truncation to `limit`;
- partial results with a reason;
- `browser_unavailable` and `timeout`;
- the session always closed;
- logs containing no handle, query or caption.

**Single post**

- the snapshot fills `published_at` and `engagement`;
- TikWM fills them when the fields are present and leaves them empty without error when absent;
- `_merge_post` per-field precedence;
- v1 and v2 reports still validate.

**Verification**

- the full Python suite and ruff (`check` and `format --check`) are required;
- no live test: the final live smoke waits for the end of the migration;
- no Rust changes, so `build_cuda.bat` is not required.

## 7. Out of scope

- A production caller, a Temporal activity or an API route: all Stage 8.
- Trending topics derived from hashtags: Stage 8.
- Proxies, paid scraping services, captcha solving and captcha blocking.
- Logged-in sources (TikTok Studio, Creative Center).
- Photo-post discovery: the materializer accepts `video/mp4` only.
- Session pooling across discovery calls: add when Stage 8 measures a need.
