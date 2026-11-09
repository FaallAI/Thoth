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
    assert longest < 0.4  # the blocking version held the loop for 0.89 s here


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


def sleeping_ffmpeg(tmp_path: Path, seconds: int) -> tuple[Path, Path]:
    """A stand-in ffmpeg that records its pid and arguments, then sleeps."""
    pid, argv = tmp_path / "pid.txt", tmp_path / "argv.txt"
    fake = tmp_path / "ffmpeg"
    script = f'#!/bin/sh\necho $$ > {pid}\nprintf "%s\\n" "$@" >> {argv}\nexec sleep {seconds}\n'
    fake.write_text(script)
    fake.chmod(0o755)
    return fake, pid


def alive(pid_file: Path) -> bool:
    import os

    try:
        os.kill(int(pid_file.read_text()), 0)
    except ProcessLookupError:
        return False
    return True


async def test_a_cancelled_strip_build_stops_ffmpeg(tmp_path: Path) -> None:
    # Final review minor, fixed 2026-11-09: ffmpeg never outlives a cancelled request.
    import asyncio

    fake, pid = sleeping_ffmpeg(tmp_path, 30)
    build = asyncio.create_task(
        build_glance(str(fake), str(tmp_path / "x.mp4"), asset("video", 3, "video/mp4"))
    )
    for _ in range(100):
        if pid.exists() and pid.read_text().strip():
            break
        await asyncio.sleep(0.02)
    build.cancel()
    with pytest.raises(asyncio.CancelledError):
        await build
    await asyncio.sleep(0.1)
    assert not alive(pid)


async def test_a_timed_out_build_fails_and_stops_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    from thoth_control_plane.infrastructure import asset_glance_builder

    monkeypatch.setattr(asset_glance_builder, "GLANCE_TIMEOUT_SECONDS", 0.3)
    fake, pid = sleeping_ffmpeg(tmp_path, 30)
    with pytest.raises(GlanceBuildFailed):
        await build_glance(str(fake), str(tmp_path / "x.mp4"), asset("video", 3, "video/mp4"))
    assert not alive(pid)


def calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "argv.txt").read_text().split("\n")


async def test_a_short_video_is_decoded_in_full(tmp_path: Path) -> None:
    # 2026-11-09, measured: with keyframes 5 s apart, keyframes alone gave 3 different pictures
    # across 15 tiles of a 20 s video. A full decode of 5 minutes of 1080p took 7 s.
    fake, _ = sleeping_ffmpeg(tmp_path, 0)
    with pytest.raises(GlanceBuildFailed):
        await build_glance(str(fake), str(tmp_path / "x.mp4"), asset("video", 500, "video/mp4"))
    args = calls(tmp_path)
    assert args.count("-i") == 1 and "-skip_frame" not in args
    assert args[args.index("-threads") + 1] == "2"


async def test_a_short_video_that_times_out_falls_back_to_keyframes(
    tmp_path: Path, monkeypatch
) -> None:
    from thoth_control_plane.infrastructure import asset_glance_builder

    monkeypatch.setattr(asset_glance_builder, "GLANCE_TIMEOUT_SECONDS", 0.2)
    fake, _ = sleeping_ffmpeg(tmp_path, 30)
    with pytest.raises(GlanceBuildFailed):
        await build_glance(str(fake), str(tmp_path / "x.mp4"), asset("video", 500, "video/mp4"))
    args = calls(tmp_path)
    assert args.count("-i") == 2 and args.count("-skip_frame") == 1
    assert args.index("-skip_frame") > args.index("-i")


async def test_a_long_video_tries_keyframes_first(tmp_path: Path) -> None:
    # Tiles 10 s apart are further apart than a keyframe gap, so keyframes still differ.
    fake, _ = sleeping_ffmpeg(tmp_path, 0)
    with pytest.raises(GlanceBuildFailed):
        await build_glance(str(fake), str(tmp_path / "x.mp4"), asset("video", 600, "video/mp4"))
    args = calls(tmp_path)
    assert args[args.index("-skip_frame") + 1] == "nokey"
    assert args.index("-skip_frame") < args.index("-i")
    assert args.count("-i") == 2 and args.count("-skip_frame") == 1


async def test_a_long_video_that_times_out_is_not_tried_again(tmp_path: Path, monkeypatch) -> None:
    from thoth_control_plane.infrastructure import asset_glance_builder

    monkeypatch.setattr(asset_glance_builder, "GLANCE_TIMEOUT_SECONDS", 0.2)
    fake, _ = sleeping_ffmpeg(tmp_path, 30)
    with pytest.raises(GlanceBuildFailed):
        await build_glance(str(fake), str(tmp_path / "x.mp4"), asset("video", 600, "video/mp4"))
    assert calls(tmp_path).count("-i") == 1


async def test_a_track_that_ends_normally_is_not_killed(tmp_path: Path, monkeypatch) -> None:
    # CI, 2026-11-09: killing an ffmpeg that was already exiting made Python read its exit status
    # first, so asyncio reported 255 and a good track failed. Only an early stop may kill.
    import asyncio

    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\nhead -c 1600 /dev/zero\nexec 1>&-\nsleep 0.2\nexit 0\n")
    fake.chmod(0o755)
    killed: list[int] = []
    real_start = asyncio.create_subprocess_exec

    async def spying(*args, **kwargs):
        process = await real_start(*args, **kwargs)
        real_kill = process.kill

        def kill() -> None:
            killed.append(process.pid)
            real_kill()

        process.kill = kill  # type: ignore[method-assign]
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spying)
    glance = await build_glance(str(fake), str(tmp_path / "x.wav"), asset("audio", 1, "audio/wav"))
    assert glance.peaks is not None and glance.peaks.values == [0]
    assert killed == []


async def test_a_track_whose_ffmpeg_fails_partway_is_refused(tmp_path: Path) -> None:
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\nhead -c 1600 /dev/zero\nexec 1>&-\nsleep 0.2\nexit 1\n")
    fake.chmod(0o755)
    with pytest.raises(GlanceBuildFailed):
        await build_glance(str(fake), str(tmp_path / "x.wav"), asset("audio", 1, "audio/wav"))
