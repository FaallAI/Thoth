"""YouTube single-video acquisition: yt-dlp (a library) for metadata, first-page comments,
and the merged MP4, then best-effort headless cards (comments on the watch page, the channel
header).

YouTube serves only DASH streams with signed, scrambled URLs, so a plain page request yields
no playable media; yt-dlp's JavaScript challenge solver (on `bun`) does. There is no post
card: every YouTube post is a video.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from thoth_control_plane.acquisition.adapters.youtube import (
    FormatChoice,
    YouTubeIdentity,
    YouTubeParse,
    YouTubeUrlError,
    canonicalize_youtube_url,
    parse_info,
    select_formats,
)
from thoth_control_plane.acquisition.browser import _default_session_factory
from thoth_control_plane.acquisition.card_browser import (
    CardBrowser,
    CardLayout,
    comment_targets,
    log_outcome,
    persist_cards,
)
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    MaterializedMedia,
    ReportSource,
    SourceReport,
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)

logger = logging.getLogger(__name__)

CONTENT_METHOD = "yt_dlp"
EXTRACT_TIMEOUT_SECONDS = 90.0
DOWNLOAD_TIMEOUT_SECONDS = 600.0
COMMENT_PAGE = "50"
YTDLP_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "socket_timeout": 30,
    "retries": 2,
    # yt-dlp solves YouTube's JavaScript challenges with an external runtime.
    "js_runtimes": {"bun": {}},
}
BOT_CHECK = ("sign in to confirm",)
GONE = (
    "private video",
    "video unavailable",
    "has been removed",
    "is not available",
    "members-only",
    "account associated with this video has been terminated",
)
STALE = (
    "signature",
    "nsig",
    "n challenge",
    "requested format is not available",
    "unable to extract",
)
PROFILE_CARD_SELECTOR = "#page-header"
LOGIN_PATHS = ("/signin",)
# Tags each matched comment; targets arrive as the evaluate argument, never interpolated.
# Comments load as the page scrolls. A thread linking to the comment's own `lc=` id is exact;
# the author's `@handle` plus the text prefix is the fallback. The comment itself is tagged,
# not its whole thread of replies.
TAG_COMMENTS_JS = """
async (targets) => {
  const threads = () => Array.from(document.querySelectorAll("ytd-comment-thread-renderer"));
  for (let step = 0; step < 8 && threads().length < targets.length; step++) {
    window.scrollBy(0, 1500);
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  const head = (thread) => thread.querySelector("ytd-comment-view-model, #comment") || thread;
  const free = (thread) => !head(thread).hasAttribute("data-thoth-comment");
  // `@ann` must not match inside `@anna` (handles also allow `.` and `-`).
  const mentions = (text, handle) => {
    for (let at = text.indexOf(handle); at !== -1; at = text.indexOf(handle, at + 1)) {
      if (!/[a-z0-9_.-]/.test(text.charAt(at + handle.length))) return true;
    }
    return false;
  };
  const tagged = [];
  for (const target of targets) {
    const id = target.comment_id;
    const linked = threads().find((thread) => free(thread)
      && thread.querySelector('a[href$="lc=' + id + '"], a[href*="lc=' + id + '&"]'));
    const handle = "@" + target.author.toLowerCase();
    const row = linked || threads().find((thread) => {
      const text = head(thread).innerText || "";
      return free(thread) && mentions(text.toLowerCase(), handle) && text.includes(target.prefix);
    });
    if (!row) continue;
    head(row).setAttribute("data-thoth-comment", id);
    tagged.push(id);
  }
  return tagged;
}
"""
YOUTUBE_LAYOUT = CardLayout(
    # Unused: a YouTube post is always a video, so no post card is asked for.
    post_selector="ytd-watch-metadata",
    profile_selector=PROFILE_CARD_SELECTOR,
    tag_js=TAG_COMMENTS_JS,
    login_paths=LOGIN_PATHS,
)


class YtDlpError(Exception):
    """An extraction failure, already mapped to its acquisition reason."""

    def __init__(self, reason: AcquisitionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def classify(error: BaseException) -> AcquisitionReason:
    """Map a yt-dlp failure to a reason by message class; the message never leaves here."""
    text = str(error).lower()
    if isinstance(error, TimeoutError) or "timed out" in text:
        return AcquisitionReason.REQUEST_TIMEOUT
    if any(phrase in text for phrase in BOT_CHECK):
        return AcquisitionReason.REQUEST_BLOCKED
    if any(phrase in text for phrase in STALE):
        logger.warning("youtube extraction failed in a way that suggests yt-dlp needs an update")
        return AcquisitionReason.REQUEST_BLOCKED
    if any(phrase in text for phrase in GONE):
        return AcquisitionReason.REQUEST_INCOMPLETE
    return AcquisitionReason.REQUEST_BLOCKED


class _Silent:
    """yt-dlp's logger: its messages can carry URLs, so none are kept."""

    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


def _default_factory(options: dict[str, Any]) -> Any:
    import yt_dlp

    return yt_dlp.YoutubeDL(options)


class YtDlpClient:
    """yt-dlp as a library, run in a worker thread under a timeout."""

    def __init__(self, factory: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self._factory = factory or _default_factory

    async def _run(
        self, options: dict[str, Any], call: Callable[[Any], Any], timeout: float
    ) -> Any:
        def work() -> Any:
            with self._factory({**YTDLP_OPTIONS, "logger": _Silent(), **options}) as ydl:
                return call(ydl)

        # ponytail: a timed-out thread finishes in the background (socket_timeout bounds it);
        # yt-dlp offers no cancellation.
        return await asyncio.wait_for(asyncio.to_thread(work), timeout)

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        options: dict[str, Any] = {"skip_download": True}
        if comments:
            options["getcomments"] = True
            options["extractor_args"] = {
                "youtube": {"max_comments": [COMMENT_PAGE, COMMENT_PAGE, "0", "0"]}
            }
        return await self._info(url, options)

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        """A channel tab's newest entries, flat: ids and views, no per-video extraction."""
        options = {"skip_download": True, "extract_flat": "in_playlist", "playlistend": limit}
        return await self._info(url, options)

    async def _info(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
        try:
            info = await self._run(
                options, lambda ydl: ydl.extract_info(url, download=False), EXTRACT_TIMEOUT_SECONDS
            )
        except Exception as error:
            raise YtDlpError(classify(error)) from None
        if not isinstance(info, dict):
            raise YtDlpError(AcquisitionReason.REQUEST_INCOMPLETE)
        return info

    async def download(self, url: str, choice: FormatChoice, directory: Path) -> Path:
        """Download the chosen video and audio and merge them into `directory/merged.mp4`."""
        options = {
            "format": f"{choice.video_format}+{choice.audio_format}",
            "merge_output_format": "mp4",
            "outtmpl": {"default": str(directory / "merged.%(ext)s")},
            "overwrites": True,
        }
        try:
            await self._run(options, lambda ydl: ydl.download([url]), DOWNLOAD_TIMEOUT_SECONDS)
        except Exception:
            raise MediaMaterializationError() from None
        merged = directory / "merged.mp4"
        if not merged.is_file():
            raise MediaMaterializationError()
        return merged


class YouTubeHeadlessBrowser(CardBrowser):
    """The YouTube card session: comment cards on the watch page, the channel header."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        super().__init__(YOUTUBE_LAYOUT, session_factory)


class YouTubeAcquirer:
    """One YouTube video: yt-dlp metadata and comments, the merged MP4, and cards."""

    def __init__(
        self,
        client: YtDlpClient,
        headless: YouTubeHeadlessBrowser,
        materializer: MediaMaterializer,
    ) -> None:
        self._client = client
        self._headless = headless
        self._materializer = materializer

    async def _media(
        self,
        identity: YouTubeIdentity,
        choice: FormatChoice,
        parsed: YouTubeParse,
        workflow_id: str,
        artifact_root: Path,
    ) -> MaterializedMedia:
        name = f"youtube-{identity.video_id}-1"
        location = PurePosixPath("reports") / workflow_id / "media" / name
        # On the artifact filesystem, so `adopt` places the file with an atomic rename.
        work = artifact_root / location.parent / f".youtube-{identity.video_id}.download"
        try:
            work.mkdir(parents=True, exist_ok=True)
            merged = await self._client.download(str(identity.canonical_url), choice, work)
            return await self._materializer.adopt(
                merged,
                artifact_root / location,
                location,
                AcquisitionStrategy.YT_DLP,
                duration_seconds=parsed.duration_seconds,
            )
        except OSError:
            raise MediaMaterializationError() from None
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        strategy = AcquisitionStrategy.YT_DLP
        try:
            try:
                identity = canonicalize_youtube_url(source_url)
            except YouTubeUrlError:
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
                )
            start = time.monotonic()
            reason: AcquisitionReason | None = None
            info: dict[str, Any] | None = None
            try:
                info = await self._client.extract(str(identity.canonical_url), comments=True)
            except YtDlpError as error:
                reason = error.reason
            parsed = parse_info(info, identity) if info is not None else None
            if parsed is None and reason is None:
                # Another video, a live or upcoming stream, or no valid owner.
                reason = AcquisitionReason.REQUEST_INCOMPLETE
            media: list[MaterializedMedia] = []
            if parsed is not None and info is not None:
                choice = select_formats(info.get("formats"), parsed.duration_seconds)
                if choice is None:
                    reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
                else:
                    try:
                        media = [
                            await self._media(identity, choice, parsed, workflow_id, artifact_root)
                        ]
                    except MediaMaterializationError:
                        reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
            attempt = _make_attempt(strategy, reason, _elapsed_ms(start))
            if reason is not None or parsed is None:
                code = (reason or AcquisitionReason.REQUEST_INCOMPLETE).value
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=code, retryable=code in RETRYABLE_FAILURES, attempts=[attempt]
                    )
                )
            cards = await self._headless.cards(
                str(identity.canonical_url),
                parsed.channel_url,
                want_post=False,
                targets=comment_targets(parsed.comments),
            )
            _, comments, profile_card = await asyncio.to_thread(
                persist_cards, cards, parsed.comments, workflow_id, artifact_root
            )
            log_outcome(
                "youtube",
                CONTENT_METHOD,
                len(media),
                comments,
                None,
                profile_card,
                want_post=False,
                problems=cards.problems,
                dropped=parsed.dropped_comments,
            )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(platform="youtube", canonical_url=identity.canonical_url),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    comments=comments,
                    profile_card=profile_card,
                )
            )
        finally:
            # Same shielded close as the other acquirers: a second cancellation must not
            # interrupt browser cleanup partway through.
            await asyncio.shield(self._headless.close())
