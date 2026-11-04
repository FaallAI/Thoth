"""Worker-startup logging: one JSON line per record, and safety for the Scrapling provider stack.

Scrapling (and the Patchright browser it drives) logs signed CDN URLs, cookies,
and other provider-identifying detail at INFO level via the standard library
`logging` module. The control plane's own reports, Temporal history, and
events are already sanitized — this module exists solely to keep that
third-party library's stdout from ever reaching a configured handler unfiltered.

`configure_provider_logging()` must run before any capability probe or fetch
touches the `scrapling` namespace, must never raise (a broken logging
configuration must not prevent the worker from starting), and must be safe to
call more than once.
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime

REDACTED_PROVIDER_MESSAGE = "scrapling provider event redacted"
MAX_PROVIDER_TEXT = 1_000
# A URL keeps its scheme, host and path; userinfo (a proxy login), query and fragment go.
_URL = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)(?:[^\s/?#@]*@)?([^\s?#'\"<>]*)(?:[?#][^\s'\"<>]*)?"
)
# A cookie or authorization header: everything after it on the line.
_HEADER = re.compile(
    r"(?i)\b(set-cookie|cookie|proxy-authorization|authorization)\b(['\"]?\s*[:=]?\s*)[^\n]*"
)
_FIELD = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|access_token|auth_token|api_?key|sessionid|sid|"
    r"session|ct0|csrftoken|ds_user_id|mstoken|s_v_web_id|sid_tt|sid_guard|uid_tt|username)\b"
    r"(['\"]?\s*[:=]\s*['\"]?)([^\s'\",;&}]+)"
)
# A bare `user:password@host` (a proxy written without its scheme).
_USERINFO = re.compile(r"(?<![\w/])[^\s:/@'\"]+:[^\s:/@'\"]+@")
# Temporal fails an activation that does not finish within 2 s of event-loop time (TMPRL1101).
STALL_SECONDS = 1.0

logger = logging.getLogger(__name__)

_GUARD_MARKER = "_scrapling_redaction_guard"


def sanitize_provider_text(text: str) -> str:
    """The provider's text without the secrets it can carry: proxy logins, signed query strings,
    cookies, authorization, and token or session fields. Only these known shapes are removed."""
    text = _URL.sub(r"\1\2", text)
    text = _HEADER.sub(r"\1\2<redacted>", text)
    text = _FIELD.sub(r"\1\2<redacted>", text)
    text = _USERINFO.sub("<redacted>@", text)
    return text if len(text) <= MAX_PROVIDER_TEXT else text[:MAX_PROVIDER_TEXT] + "…"


UNREADABLE_BODY = "Error getting page content in async: Response.body:"


class ScraplingRedactionFilter(logging.Filter):
    """Drop DEBUG/INFO and sanitize WARNING/ERROR records in the `scrapling` namespace.

    Operator ruling 2026-10-24: a provider error stays readable (what failed, where, which
    exception); its secrets do not. The traceback and stack are dropped; the exception's type
    and sanitized text are appended. Anything that fails to sanitize is fully redacted.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("scrapling"):
            return True
        if record.levelno < logging.WARNING:
            return False
        # The browser already discarded that response's body (a navigation or a redirect);
        # the listing still succeeds, so the line is noise (stage1, 2026-10-30).
        if str(record.msg).startswith(UNREADABLE_BODY):
            return False
        try:
            text = record.getMessage()
            error = record.exc_info[1] if record.exc_info else None
            if error is not None:
                text = f"{text} | {type(error).__name__}: {error}"
            record.msg = sanitize_provider_text(text)
        except Exception:
            record.msg = REDACTED_PROVIDER_MESSAGE
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> None:
    """Write records to stdout as JSON: the control plane's INFO and up, others' WARNING and up.

    Third-party INFO stays out because it carries request URLs (httpx) and content. Without a
    root handler the worker printed only WARNING and up, through `logging.lastResort`. Never
    raises, and is idempotent, like `configure_provider_logging`.
    """
    try:
        root = logging.getLogger()
        if not any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JsonFormatter())
            root.addHandler(handler)
        root.setLevel(logging.WARNING)
        logging.getLogger("thoth_control_plane").setLevel(logging.INFO)
    except Exception:
        return


async def watch_event_loop(stall: float = STALL_SECONDS) -> None:
    """Catch what blocks the event loop or holds the GIL, while it still does.

    A synchronous call on the loop, or a thread that keeps the GIL, delays every Temporal
    activation; past 2 s the SDK reports a deadlock and a query answers 500. This coroutine
    re-arms faulthandler's watchdog every quarter `stall`; the watchdog is a C thread that needs
    neither the loop nor the GIL, so a missed beat dumps every thread's stack to stderr during
    the stall. The stall's length is logged once the loop runs again.
    """
    beat = stall / 4
    try:
        while True:
            faulthandler.dump_traceback_later(stall)
            before = time.monotonic()
            await asyncio.sleep(beat)
            late = time.monotonic() - before - beat
            if late > stall:
                logger.warning("event loop stalled seconds=%.1f", late + beat)
    finally:
        faulthandler.cancel_dump_traceback_later()


def _add_filter_once(target: logging.Filterer) -> None:
    if not any(isinstance(item, ScraplingRedactionFilter) for item in target.filters):
        target.addFilter(ScraplingRedactionFilter())


def _guard_future_handlers(logger: logging.Logger) -> None:
    """Attach the filter to every handler this logger will ever own.

    Applied to two logger objects, for two different late-arrival stories:

    - the `scrapling` logger, because Scrapling attaches its own
      `StreamHandler` to that exact logger at import time — lazily, inside
      `check_scrapling_capability()`, long after this module has already run
      at worker startup;
    - the **root** logger, because a record propagating up from a child such
      as `scrapling.fetchers` is never shown the `scrapling` Logger's own
      filters, so a root handler installed later (`logging.basicConfig()`,
      structured logging, a log shipper) would otherwise receive it raw.

    A one-time scan of `logger.handlers` at configure time cannot see a
    handler that does not exist yet, so instead this wraps `addHandler` on
    that one logger instance: whichever handler object is added, whenever
    that happens, gets the filter attached the moment it is added. The wrapper
    is set on the instance, not on `logging.Logger`, so no unrelated logger is
    affected; and the filter itself returns non-`scrapling` records untouched,
    so guarding the root handler chain does not alter application logging.
    """
    if getattr(logger.addHandler, _GUARD_MARKER, False):
        return
    original_add_handler = logger.addHandler

    def _guarded_add_handler(handler: logging.Handler) -> None:
        _add_filter_once(handler)
        original_add_handler(handler)

    setattr(_guarded_add_handler, _GUARD_MARKER, True)
    logger.addHandler = _guarded_add_handler


def configure_provider_logging() -> None:
    """Install the Scrapling redaction filter on every handler that could see it.

    Filters attached to a `Logger` object are only consulted for records
    originated on that exact logger — they are NOT consulted when a record
    merely propagates up from a child logger (e.g. `scrapling.fetchers`).
    Handler-level filters, by contrast, run for every record that reaches
    that handler regardless of which logger emitted it. So this installs the
    filter on:

    - the `scrapling` logger itself (covers exact-name records before they
      even reach a handler);
    - every handler already attached to the `scrapling` logger and to the
      root logger (covers records propagating up from child loggers such as
      `scrapling.fetchers`, given the handlers that exist right now);
    - via `_guard_future_handlers`, any handler added to the root logger
      *after* this function has already run (the same propagation path, for
      handlers that do not exist yet);
    - `logging.lastResort`, the stdlib's own fallback handler used when a
      record's propagation chain has no handler at all (covers child-logger
      WARNING/ERROR records in the "no handlers configured anywhere" state,
      which would otherwise print raw to stderr);
    - and, via `_guard_future_handlers`, any handler `scrapling` attaches to
      its own logger *after* this function has already run.

    Never raises: an unusual or broken logging configuration must not stop
    worker startup. Idempotent: safe to call more than once without
    installing duplicate filters or double-handling a record.
    """
    try:
        logger = logging.getLogger("scrapling")
        root_logger = logging.getLogger()
        logger.setLevel(logging.WARNING)

        targets: list[logging.Filterer] = [
            logger,
            *logger.handlers,
            *root_logger.handlers,
        ]
        if logging.lastResort is not None:
            targets.append(logging.lastResort)
        for target in targets:
            _add_filter_once(target)

        _guard_future_handlers(logger)
        _guard_future_handlers(root_logger)
    except Exception:
        return
