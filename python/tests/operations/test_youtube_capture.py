"""The YouTube capture CLI refuses bad input before any network access and never echoes a URL."""

from __future__ import annotations

from pathlib import Path

import pytest

from thoth_control_plane.operations.youtube_capture import _bucket, main

SECRET = "secret_person"


@pytest.mark.parametrize(
    "line",
    [
        f"bogus https://www.youtube.com/@{SECRET}",
        f"video https://www.youtube.com/@{SECRET}",
        f"short http://www.youtube.com/watch?v={SECRET}x",
        "channel https://www.youtube.com/watch?v=abcDEF123_-",
        "video",
    ],
)
def test_bad_lines_stop_before_any_fetch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    urls = tmp_path / "urls.txt"
    urls.write_text(line + "\n", encoding="utf-8")
    assert main(["--urls", str(urls), "--out", str(tmp_path / "raw")]) == 2
    out = capsys.readouterr().out
    assert SECRET not in out and "youtube.com" not in out
    assert "error" in out
    assert list((tmp_path / "raw").glob("*.json")) == []


@pytest.mark.parametrize(
    ("size", "bucket"),
    [(1, "<10MB"), (60 * 1024 * 1024, "<100MB"), (500 * 1024 * 1024, ">=450MB")],
)
def test_sizes_are_reported_as_buckets(size: int, bucket: str) -> None:
    assert _bucket(size) == bucket
