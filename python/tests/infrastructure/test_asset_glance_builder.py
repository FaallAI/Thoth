"""Tier 3b: an asset's glance, built by the image's own ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.domain.editor_assets import EditorAsset
from thoth_control_plane.infrastructure.asset_glance_builder import (
    GlanceBuildFailed,
    GlanceToolMissing,
    build_glance,
    jpeg_size,
)

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


def make(path: Path, *args: str) -> Path:
    subprocess.run([FFMPEG or "ffmpeg", "-v", "error", "-y", *args, str(path)], check=True)
    return path


def asset(kind: str, seconds: float, media_type: str) -> EditorAsset:
    return EditorAsset(
        asset_id="asset_1",
        project_id="project_001",
        kind=kind,
        media_type=media_type,
        duration_in_frames=round(seconds * 30) if kind != "image" else None,
        width=160 if kind != "audio" else None,
        height=90 if kind != "audio" else None,
        fps=30.0 if kind == "video" else None,
        has_audio=kind == "audio",
        validation_state="ready",
    )


@needs_ffmpeg
def test_jpeg_size_reads_the_frame_header(tmp_path: Path) -> None:
    picture = make(tmp_path / "p.jpg", "-f", "lavfi", "-i", "color=c=red:s=64x48", "-frames:v", "1")
    assert jpeg_size(picture.read_bytes()) == (64, 48)


@needs_ffmpeg
async def test_a_video_glance_is_a_strip_of_frames_72_px_tall(tmp_path: Path) -> None:
    video = make(tmp_path / "v.mp4", "-f", "lavfi", "-i", "testsrc=d=3:s=160x90:r=30")
    glance = await build_glance(FFMPEG or "ffmpeg", str(video), asset("video", 3, "video/mp4"))
    assert glance.peaks is None and glance.strip is not None
    assert (glance.strip.frames, glance.strip.seconds_per_frame) == (3, 1)
    assert glance.strip.frame_height == 72 and glance.strip.frame_width == 128
    assert glance.strip.image.startswith("data:image/jpeg;base64,")


@needs_ffmpeg
async def test_an_image_glance_is_one_frame(tmp_path: Path) -> None:
    picture = make(
        tmp_path / "p.png", "-f", "lavfi", "-i", "color=c=blue:s=160x90", "-frames:v", "1"
    )
    glance = await build_glance(FFMPEG or "ffmpeg", str(picture), asset("image", 0, "image/png"))
    assert glance.strip is not None and glance.strip.frames == 1


@needs_ffmpeg
async def test_an_audio_glance_is_its_peaks(tmp_path: Path) -> None:
    tone = make(tmp_path / "a.wav", "-f", "lavfi", "-i", "sine=f=440:d=1", "-af", "volume=8")
    glance = await build_glance(FFMPEG or "ffmpeg", str(tone), asset("audio", 1, "audio/wav"))
    assert glance.strip is None and glance.peaks is not None
    assert glance.peaks.seconds_per_peak == 0.1
    assert len(glance.peaks.values) == 10 and min(glance.peaks.values) >= 90


@needs_ffmpeg
async def test_a_corrupt_file_fails_the_build(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video at all")
    with pytest.raises(GlanceBuildFailed):
        await build_glance(FFMPEG or "ffmpeg", str(broken), asset("video", 3, "video/mp4"))


async def test_a_missing_ffmpeg_says_so(tmp_path: Path) -> None:
    with pytest.raises(GlanceToolMissing):
        await build_glance(
            "/nonexistent/ffmpeg", str(tmp_path / "x.mp4"), asset("video", 3, "video/mp4")
        )


@needs_ffmpeg
async def test_a_60_fps_video_is_timed_on_the_canvas_clock(tmp_path: Path) -> None:
    # Final review 2026-11-09: durations count 30 fps canvas frames, whatever the media's own rate.
    video = make(tmp_path / "v60.mp4", "-f", "lavfi", "-i", "testsrc=d=4:s=160x90:r=60")
    sixty = asset("video", 4, "video/mp4").model_copy(update={"fps": 60.0})
    glance = await build_glance(FFMPEG or "ffmpeg", str(video), sixty)
    assert glance.strip is not None and glance.strip.frames == 4


@needs_ffmpeg
async def test_an_hour_long_track_never_stalls_the_event_loop(tmp_path: Path) -> None:
    # Final review 2026-11-09: peaks are folded as ffmpeg streams them, never all at once.
    import asyncio
    import time

    track = make(
        tmp_path / "long.wav", "-f", "lavfi", "-i", "sine=f=220:d=3600", "-ar", "8000", "-ac", "1"
    )
    longest = 0.0

    async def ticker() -> None:
        nonlocal longest
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            longest = max(longest, now - last)
            last = now

    beat = asyncio.create_task(ticker())
    glance = await build_glance(FFMPEG or "ffmpeg", str(track), asset("audio", 3600, "audio/wav"))
    await asyncio.sleep(0.05)  # let the ticker see a block that ended with the build
    beat.cancel()
    assert glance.peaks is not None and len(glance.peaks.values) == 2000
    assert longest < 0.15


@pytest.mark.parametrize(
    ("kind", "media_type", "formats"),
    [
        ("video", "video/mp4", "mov"),
        ("video", "video/webm", "matroska"),
        ("image", "image/png", "png_pipe"),
        ("audio", "audio/mpeg", "mp3"),
        ("audio", "audio/wav", "wav"),
    ],
)
async def test_ffmpeg_opens_only_the_format_the_asset_type_names(
    tmp_path: Path, kind: str, media_type: str, formats: str
) -> None:
    # Final review 2026-11-09: a crafted file (a playlist behind an ID3 header, say) cannot make an
    # older ffmpeg read another file or, from the store, another URL.
    argv = tmp_path / "argv.txt"
    fake = tmp_path / "ffmpeg"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {argv}\nexit 1\n')
    fake.chmod(0o755)
    with pytest.raises(GlanceBuildFailed):
        await build_glance(str(fake), str(tmp_path / "x"), asset(kind, 3, media_type))
    args = argv.read_text().split("\n")
    assert args[args.index("-format_whitelist") + 1] == formats
    assert args.index("-format_whitelist") < args.index("-i")


async def test_an_unknown_media_type_is_never_opened(tmp_path: Path) -> None:
    with pytest.raises(GlanceBuildFailed):
        await build_glance("ffmpeg", str(tmp_path / "x"), asset("video", 3, "video/quicktime"))
