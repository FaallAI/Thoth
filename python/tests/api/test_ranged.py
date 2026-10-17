"""One Range implementation for every streamed object (spec 2026-10-17, render storage)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from thoth_control_plane.api.ranged import ranged_response

DATA = b"0123456789"


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/object")
    def serve(request: Request):
        def read(start: int, end: int | None):
            yield DATA[start : None if end is None else end + 1]

        return ranged_response(
            size=len(DATA),
            read=read,
            media_type="video/mp4",
            range_header=request.headers.get("range"),
            headers={"X-Extra": "1"},
        )

    return TestClient(app)


def test_a_request_without_range_gets_the_whole_object() -> None:
    response = _client().get("/object")
    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["content-length"] == "10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["x-extra"] == "1"


def test_a_closed_range_is_partial_content() -> None:
    response = _client().get("/object", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"


def test_an_open_and_a_suffix_range_are_partial_content() -> None:
    assert _client().get("/object", headers={"Range": "bytes=7-"}).content == b"789"
    suffix = _client().get("/object", headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206 and suffix.content == b"789"
    assert suffix.headers["content-range"] == "bytes 7-9/10"


def test_ranged_response_handles_malformed_and_unsatisfiable_ranges() -> None:
    malformed = _client().get("/object", headers={"Range": "pages=1-2"})
    assert malformed.status_code == 200 and malformed.content == DATA
    beyond = _client().get("/object", headers={"Range": "bytes=10-"})
    assert beyond.status_code == 416
    assert beyond.headers["content-range"] == "bytes */10"
    clamped = _client().get("/object", headers={"Range": "bytes=8-99"})
    assert clamped.status_code == 206 and clamped.content == b"89"


def test_the_object_is_read_off_the_event_loop_thread() -> None:
    import threading

    app = FastAPI()
    seen: dict[str, int] = {}

    @app.get("/object")
    async def serve(request: Request):
        seen["loop"] = threading.get_ident()

        def read(start: int, end: int | None):
            # An S3 read opens its connection when called, so the call itself must be off-loop.
            seen["read"] = threading.get_ident()
            return iter([DATA])

        return ranged_response(size=len(DATA), read=read, media_type="video/mp4", range_header=None)

    assert TestClient(app).get("/object").content == DATA
    assert seen["read"] != seen["loop"]
