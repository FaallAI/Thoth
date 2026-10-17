"""Serve one stored object whole or by a single byte range (RFC 9110 section 14).

Only one `bytes=` range is honoured: a browser seeking in a video sends exactly one. A
header that is not a single bytes range is ignored and the whole object is served, which
the RFC allows; a range that starts past the end is 416.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping

from fastapi import Response
from fastapi.responses import StreamingResponse

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _lazily(
    read: Callable[[int, int | None], Iterator[bytes]], start: int, end: int | None
) -> Iterator[bytes]:
    """Defer the read itself into the stream: Starlette iterates a sync iterator in a
    threadpool, so an S3 read that connects when called never runs on the event loop."""
    yield from read(start, end)


def _bounds(header: str | None, size: int) -> tuple[int, int] | str | None:
    """(start, end inclusive), None for the whole object, or "unsatisfiable"."""
    match = _RANGE.fullmatch((header or "").strip())
    if size == 0 or match is None or (not match.group(1) and not match.group(2)):
        return None  # nothing to slice, or not one bytes range: the whole object
    first, last = match.group(1), match.group(2)
    if not first:  # a suffix: the last N bytes
        length = int(last)
        if length == 0:
            return "unsatisfiable"
        return max(0, size - length), size - 1
    start = int(first)
    if last and int(last) < start:
        return None  # a backwards range is invalid, so it is ignored (RFC 9110 section 14.1.1)
    end = size - 1 if not last else min(int(last), size - 1)
    if start >= size or end < start:
        return "unsatisfiable"
    return start, end


def ranged_response(
    *,
    size: int,
    read: Callable[[int, int | None], Iterator[bytes]],
    media_type: str,
    range_header: str | None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    common = {"Accept-Ranges": "bytes", **(headers or {})}
    bounds = _bounds(range_header, size)
    if bounds == "unsatisfiable":
        return Response(status_code=416, headers={**common, "Content-Range": f"bytes */{size}"})
    if bounds is None:
        return StreamingResponse(
            _lazily(read, 0, None),
            media_type=media_type,
            headers={**common, "Content-Length": str(size)},
        )
    start, end = bounds
    return StreamingResponse(
        _lazily(read, start, end),
        status_code=206,
        media_type=media_type,
        headers={
            **common,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
        },
    )
