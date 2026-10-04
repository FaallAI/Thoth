"""The X capture CLI refuses bad input before any network access and never echoes a URL."""

from __future__ import annotations

from pathlib import Path

import pytest

from thoth_control_plane.operations.x_capture import main

SECRET_URL = "https://x.com/secret_person/status/1800000000000000001"


@pytest.mark.parametrize(
    "line",
    [
        f"bogus {SECRET_URL}",
        "video https://x.com/secret_person",
        "profile https://x.com/secret_person/status/1800000000000000001",
        "text http://x.com/secret_person/status/1800000000000000001",
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
    assert "secret_person" not in out
    assert "error" in out
    assert list((tmp_path / "raw").glob("*.json")) == []
