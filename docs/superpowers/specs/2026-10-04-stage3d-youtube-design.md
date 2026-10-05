# Stage 3d: YouTube Acquisition on the Platform Kernel

Status: written spec approved by the operator on 2026-10-04; implemented on branch
`feat/stage3d-youtube` (see `docs/superpowers/plans/2026-10-04-stage3d-youtube.md`).

## 1. Context and scope

Stage 3a built the platform-neutral kernel and ported Threads. Stage 3b ported Instagram, and
Stage 3c ported X. Stage 3d ports YouTube, the last Stage 3 platform. Afterwards no post URL
routes to legacy Scout for acquisition.

Today Scout reads YouTube in four ways:
- **Inspect:** oEmbed metadata.
- **Media:** yt-dlp downloads it directly from the canonical URL.
- **Comments:** scraped from the watch page DOM.
- **Social card:** the oEmbed thumbnail.

Scout has no YouTube discovery.

The operator chose:

- **Anonymous only.** The multi-account rotating login feature, integrated with the UI,
  follows this stage.
- **Approach A.** yt-dlp is used as a Python library for metadata, media, and first-page
  comments. Scrapling headless is used for cards only.
  - YouTube stream URLs are signed and scrambled (signature and `n` parameter).
  - A plain page request yields no playable URL, so yt-dlp's JavaScript challenge solver
    (run on `bun`) is required.
- **Media policy A.**
  - Take the highest of 1080p, 720p, then 480p whose estimated video plus audio size stays
    under 450 MB.
  - Otherwise the media fails validation.
- **yt-dlp update mechanism A.**
  - A daily workflow bumps the pin, runs the offline tests in its own job, opens a pull
    request, and merges it automatically when it is green.
  - It then dispatches the image build.
  - The worker warns at startup when its yt-dlp is behind PyPI.
  - The worker never updates itself.
- **Full Scout parity where YouTube allows anonymous access:** metadata, media, first-page
  comments with real cards, a profile (channel) card, and channel discovery.

These stay as they are:
- TikTok, Threads, Instagram, and X behavior.
- Facebook and Reddit stay `unsupported`.
- No new failure codes; `RETRYABLE_FAILURES` and `LEGACY_FALLBACK_ELIGIBLE_CODES` are
  unchanged.
- No live test in the suite.
- A card is never synthetic.

## 2. Access probe evidence (2026-10-04, anonymous, read-only)

These are counts, keys, and enums only. The probe covered one video, one Short, and one
channel, run in the capture image (yt-dlp 2026.08.19, ffmpeg 5.1, bun).

- **yt-dlp metadata (video and Short).** Every probed key was present, with no warnings:
  `id`, `title`, `description`, `uploader`, `uploader_id`, `channel`, `channel_id`,
  `channel_url`, `duration`, `view_count`, `like_count`, `comment_count`, `upload_date`,
  `timestamp`, `availability`, `live_status`, `age_limit`, `thumbnails`, `tags`.
- **Formats.** There are **no progressive formats**. All formats are DASH:
  - video-only MP4 up to 2160p (video) and 1920p (Short);
  - ten audio-only formats (`m4a` and `webm`);
  - 22 of the video formats carry `filesize` or `filesize_approx`.
- **Comments through yt-dlp.** 20 top-level comments, with the keys `id`, `author`,
  `author_id`, `text`, `like_count`, `timestamp`, `is_pinned`, `parent`.
- **Watch page (request).** Status 200, no consent redirect. It holds both
  `ytInitialPlayerResponse` and `ytInitialData`.
- **Watch page (headless).**
  - It renders with no consent wall.
  - After scrolling, 60 comment threads render (`ytd-comment-thread-renderer`).
  - `ytd-watch-metadata` measures 1344×192.
- **Shorts page (headless).** It renders, but the comments stay in a closed panel, so none
  are in the DOM. The `/watch?v=<id>` page serves a Short's comments.
- **Channel through yt-dlp, flat.**
  - `/videos`: 12 entries, all with `view_count` and `duration`.
  - `/shorts`: 12 entries, with `view_count` only.
  - Neither tab carries upload dates or likes.
- **Channel page (headless).** `#page-header` measures about 1680×216.

## 3. Components

### 3.1 Routing and models (`platforms.py`, `models.py`)

- `PYTHON_PLATFORM_HOSTS["youtube"] = frozenset({"youtube.com", "youtu.be"})`.
  `bare_host` already strips `www.` and `m.`.
- `ReportSource.platform` accepts `"youtube"`.
- `AcquisitionStrategy.YT_DLP = "yt_dlp"`: a method label in the report, not a failure code.
- `ReportComment.comment_id` widens from numeric-only to `^[A-Za-z0-9_-]{5,64}$`.
  - YouTube comment ids are strings like `Ugz…`.
  - Numeric TikTok, Instagram, and X ids still validate.
  - The value stays safe in card file names and selectors.

### 3.2 URL identity and parsers (`acquisition/adapters/youtube.py`)

**Accepted URLs**
- Shapes: `/watch?v=<id>`, `/shorts/<id>`, `/embed/<id>`, `/live/<id>`, and
  `youtu.be/<id>`. The id is `[A-Za-z0-9_-]{11}`.
- `si`, `t`, and any other parameter are dropped.
- Https only, through the shared `_match_safe_path` checks.
- The canonical URL is `https://www.youtube.com/watch?v=<id>`, Shorts included.
- Channel URLs (`/@handle`, `/channel/UC…`) are not posts and fail as
  `invalid_source_url`.

**`parse_info(info, identity) -> YouTubeParse | None`** (pure)
- `post_id` = `id`, which must equal the identity's.
- `owner_handle` = `uploader_id` without `@`. If that is missing or invalid, `channel_id`.
- `text` = the title, then a blank line, then the description, cut to `MAX_POST_TEXT`.
- `published_at` from `timestamp`.
- `engagement`: `play` = `view_count`, `like` = `like_count`, `comment` = `comment_count`.
- Comments:
  - Take the top-level `comments` (`parent == "root"`), up to 50.
  - Each has an `id`, an `author` without `@`, a `text`, and `likes` = `like_count`.
  - The first copy of a repeated id wins. An invalid entry is dropped and counted.
- `live_status` of `is_live` or `is_upcoming` gives `None`. The caller maps that to
  `request_incomplete`, because no final video exists yet.

**`select_formats(formats, duration) -> FormatChoice | None`** (pure)
- It tries the heights 1080, 720, and 480 in turn.
- At each height it takes the best MP4 video-only format with an https URL, plus the best
  `m4a` audio. Here "best" means the largest bitrate at or under that height.
- The pair is kept when the estimated size is under 450 MB.
  - The estimate uses `filesize`, else `filesize_approx`, else `tbr × duration / 8`.
- When no pair fits, the result is `None`.

**Channel helper:** `parse_channel(entries) -> list[candidate]`, for discovery.

### 3.3 Service and acquirer (`acquisition/youtube_service.py`)

**`YtDlpClient`** wraps yt-dlp as a library. It runs in a worker thread with a timeout and
uses the `bun` JavaScript runtime. Logs stay quiet: no URLs.
- `extract(url, *, comments: bool) -> dict`. It asks for the first-page comments only.
- `download(video_id, choice, destination) -> Path`. yt-dlp downloads both formats and
  ffmpeg merges them into MP4.
- yt-dlp errors map to failure reasons by message class:
  - "Sign in to confirm" is `request_blocked`.
  - Private, removed, and unavailable are `request_incomplete`.
  - A timeout is `request_timeout`.
  - Signature and format extraction errors are `request_blocked`, plus a `warn` saying
    yt-dlp may need an update.

**`MediaMaterializer.adopt(path, ...)`** applies the existing validation to a local file:
the byte bounds, the magic-byte sniff, the SHA-256 checksum, and atomic placement. It then
returns `MaterializedMedia`.

**`YouTubeHeadlessBrowser`** is a `CardBrowser` with the YouTube layout.
- **Post card:** none, because every YouTube post is a video.
- **Comment cards** come from the `/watch?v=<id>` page.
  - The page is scrolled until comments render.
  - A thread is tagged by the link to its own comment (`a[href*="lc=<comment_id>"]`).
  - Text matching is the fallback.
- **Profile card:** `#page-header` on the channel page, fixed by the capture survey.

**`YouTubeAcquirer.inspect`** runs these steps:
1. Identity.
2. `extract`, then `parse_info`.
3. `select_formats`.
4. `download`, then `adopt`.
5. Cards.
6. A v3 report with `platform="youtube"` and strategy `yt_dlp`.

The download goes to a temporary path under the artifact root. A failure removes what it
wrote.

`registry.py` gains a YouTube branch. yt-dlp joins the `acquisition` extra, with the same
pin as `scout-runtime`.

### 3.4 Channel discovery (`acquisition/youtube_discovery.py`)

1. A flat yt-dlp listing of the channel's `/videos` and `/shorts` tabs, up to 12 each.
2. The 12 candidates with the most views are kept.
3. Each candidate gets a detail `extract` without comments, for its likes and timestamp.
4. The candidates are ranked with the shared `rank_videos`, which uses likes, views, and
   recency.
5. The result is cut to `limit`.

That is two listing requests plus up to 12 detail requests per discovery. A detail failure
returns the candidates gathered so far, ranked, with the failure's reason. Like Stage 3b,
that is a valid partial result. Discovery never raises.

### 3.5 yt-dlp freshness (`operations/yt_dlp_version.py`, workflow)

- **The module (pure core):**
  - `latest_from_pypi(fetch) -> str | None`;
  - `is_behind(installed, latest) -> bool`, which compares date versions.
- **Worker startup:**
  - One PyPI check with a 5-second timeout.
  - When the worker is behind, a `warn` log names both versions.
  - The worker never installs anything.
  - The API health route is unchanged, because a health check must not call PyPI.
- **`.github/workflows/yt-dlp-update.yml`** runs daily and on demand:
  1. Compare the pin with PyPI.
  2. If PyPI is newer, bump the pin in both extras and run `uv lock --upgrade-package
     yt-dlp`.
  3. Run the offline suite in the same job, because a pull request opened with the default
     token does not trigger other workflows.
  4. Open a pull request and merge it when the job is green.
  5. Dispatch `container-image.yml`. Of the events the default token fires, only
     `workflow_dispatch` and `repository_dispatch` start other workflows.
- **`container-image.yml`** gains a `workflow_dispatch` trigger.
- **Lint:** actionlint checks both workflows.

### 3.6 Operator tools (`operations/youtube_capture.py`, `operations/youtube_fixture.py`)

- **Capture.**
  - It reads the operator's URL file: `<kind> <url>`, with the kinds `video`, `short`, and
    `channel`.
  - It runs the real extract, download, and merge, then the card crops.
  - It writes only under `D:/thoth-tmp/bu/youtube/` and prints counts only: the chosen
    height, a size bucket, and validation pass or fail.
- **Fixtures.**
  - The fixture tool sanitizes the info JSON with the shared helpers: ids, handles, and
    text are pseudonymized, format URLs become synthetic, and counters are floored.
  - The leak check must find 0 leaks.

## 4. Error handling

| Condition | Code | Retryable / legacy fallback |
|---|---|---|
| Not a valid YouTube video URL | `invalid_source_url` | no / no |
| Bot check, or signature or format extraction error (yt-dlp may be outdated) | `request_blocked` | yes / yes |
| Timeout | `request_timeout` | yes / yes |
| Private, removed, unavailable, live, or upcoming | `request_incomplete` | yes / yes |
| No format pair fits, or the download or merge fails | `media_validation_failed` | existing rules |
| Card fails | none: `cards.problems` only; never in `outcome.attempts`; never synthetic | |

Logs never carry a URL, a raw handle, a title, a description, or comment text.

## 5. Testing (offline only)

- URL identity: every accepted and rejected shape.
- `parse_info`:
  - the field mapping;
  - string comment ids;
  - removing `@` from authors;
  - the 50-comment cap;
  - live and upcoming videos.
- `select_formats`:
  - stepping down from 1080 to 720 to 480;
  - estimating size from `tbr × duration`;
  - no pair fitting.
- yt-dlp error classification.
- Acquirer: a fake `YtDlpClient` covers every row of section 4.
- `adopt`: it rejects a file that is not MP4 and a file that is too large.
- Comment tagging: a browser test that skips without Playwright.
- Discovery: ranking, the partial result, and each reason.
- `yt_dlp_version`: version comparison and PyPI parsing with a fake fetch.

Verification: the full suite, plus Ruff check and format. actionlint for both workflows. No
Rust changes.

## 6. Live capture and golden fixtures

- **HARD STOP.** The capture needs operator authorization at capture time. It uses the
  operator's `D:/thoth-tmp/bu/youtube/urls.txt`.
- **Fixtures** go under `python/tests/fixtures/youtube/`, sanitized, with 0 leaks:
  - `video` and `short`: the info JSON;
  - `channel`: the flat entries, plus the details of the candidates.
- **The replay** runs `parse_info`, `select_formats`, and the discovery parse.
- **Download and merge** are proven by the capture's evidence, not by the suite.

## 7. Success criteria

1. A YouTube video or Short link gives a v3 report with:
   - a merged MP4 at the highest height that fits;
   - first-page comments with real cards;
   - a channel card.
2. Card failures never fail acquisition, and no card is synthetic.
3. Channel discovery ranks by likes, views, and recency.
4. The yt-dlp bump workflow opens and merges a pull request automatically. The worker warns
   when its yt-dlp is stale.
5. TikTok, Threads, Instagram, and X are unchanged. The full suite passes with no live test.

## 8. Gates outside this spec

- The live capture needs operator authorization at capture time.
- The workflow's automatic merge needs the repository setting "Allow GitHub Actions to
  create and approve pull requests". The operator enables it; no agent changes repository
  settings.
- Push, merge of this branch, and deploy are each a separate operator authorization.
- The multi-account login feature follows this stage.
