"""Preview proxies (spec 2026-11-18): a light copy with a keyframe every second, for the Player."""

from __future__ import annotations

import asyncio
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.infrastructure.preview_proxy_builder import (
    ProxyBuildFailed,
    build_preview_proxy,
)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg is not installed"
)


def make(path: Path, *args: str) -> Path:
    subprocess.run([FFMPEG or "ffmpeg", "-v", "error", "-y", *args, str(path)], check=True)
    return path


def probe(path: Path, *args: str) -> str:
    return subprocess.run(
        [FFPROBE or "ffprobe", "-v", "error", *args, str(path)], capture_output=True, text=True
    ).stdout


def build(source: Path, proxy: Path) -> None:
    asyncio.run(build_preview_proxy(FFMPEG or "ffmpeg", str(source), "video/mp4", proxy))


@needs_ffmpeg
def test_a_proxy_has_a_keyframe_every_second_and_keeps_its_length(tmp_path: Path) -> None:
    # Like the stored sources: 60 fps, larger than the preview, one keyframe every 5 s.
    source = make(
        tmp_path / "source.mp4",
        *("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=60"),
        *("-f", "lavfi", "-i", "sine=frequency=440", "-t", "6"),
        *("-c:v", "libx264", "-g", "300", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"),
    )
    proxy = tmp_path / "proxy.mp4"
    build(source, proxy)

    info = json.loads(
        probe(
            proxy,
            *("-select_streams", "v:0", "-of", "json", "-show_entries"),
            "stream=codec_name,width,height,avg_frame_rate:format=duration",
        )
    )
    video = info["streams"][0]
    assert video["codec_name"] == "h264"
    assert (video["width"], video["height"]) == (960, 540)
    assert video["avg_frame_rate"] == "30/1"
    assert abs(float(info["format"]["duration"]) - 6.0) < 0.1
    keys = [
        float(t.strip(","))
        for t in probe(
            proxy,
            *("-select_streams", "v:0", "-skip_frame", "nokey"),
            *("-show_entries", "frame=pts_time", "-of", "csv=p=0"),
        ).split()
        if t.strip(",")
    ]
    assert max(b - a for a, b in itertools.pairwise(keys)) <= 1.05
    audio = probe(proxy, "-select_streams", "a:0", "-show_entries", "stream=codec_name")
    assert "codec_name=aac" in audio


@needs_ffmpeg
def test_a_small_silent_video_is_not_upscaled(tmp_path: Path) -> None:
    source = make(
        tmp_path / "source.mp4",
        *("-f", "lavfi", "-i", "testsrc2=size=360x640:rate=25", "-t", "2"),
        *("-c:v", "libx264", "-pix_fmt", "yuv420p"),
    )
    proxy = tmp_path / "proxy.mp4"
    build(source, proxy)
    size = probe(proxy, "-select_streams", "v:0", "-show_entries", "stream=width,height")
    assert "width=360" in size and "height=640" in size


@needs_ffmpeg
def test_a_file_ffmpeg_refuses_fails_the_build(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not a video")
    with pytest.raises(ProxyBuildFailed):
        build(source, tmp_path / "proxy.mp4")
    assert not (tmp_path / "proxy.mp4").exists()
