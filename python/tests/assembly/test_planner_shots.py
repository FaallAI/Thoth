"""Planner stage 1: source shots by ffmpeg scene cuts, and the contact sheets the model reads."""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from thoth_control_plane.assembly.planner_shots import (
    card_sheet,
    contact_sheets,
    detect_shots,
    keyframes,
)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _require(binary: str | None, name: str) -> str:
    # Operator, 2026-10-11: a missing ffmpeg is an error, never a skip.
    if binary is None:
        pytest.fail(f"{name} is required for this test and is not installed")
    return binary


def make_three_scene_clip(directory: Path) -> Path:
    """2 s red, 2 s blue, 6 s green: two hard cuts, then one long scene."""
    out = directory / "scenes.mp4"
    colors = [("red", 2), ("blue", 2), ("green", 6)]
    inputs: list[str] = []
    for color, seconds in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=10:d={seconds}"]
    subprocess.run(
        [
            _require(FFMPEG, "ffmpeg"),
            "-v",
            "error",
            *inputs,
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map",
            "[v]",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
    )
    return out


def solid_jpeg(directory: Path, index: int) -> Path:
    path = directory / f"tile{index}.jpg"
    Image.new("RGB", (200, 300), (index * 20 % 255, 40, 90)).save(path)
    return path


async def test_detect_shots_finds_the_cuts_of_a_three_scene_clip(tmp_path: Path) -> None:
    clip = make_three_scene_clip(tmp_path)
    spans = await detect_shots(clip, _require(FFMPEG, "ffmpeg"), _require(FFPROBE, "ffprobe"))
    assert len(spans) == 4, spans  # 2 s, 2 s, then the 6 s scene split into two 3 s pieces
    assert spans[0][0] == 0.0 and abs(spans[-1][1] - 10.0) < 0.2
    assert abs(spans[1][0] - 2.0) < 0.2 and abs(spans[2][0] - 4.0) < 0.2


async def test_keyframes_are_taken_inside_each_span(tmp_path: Path) -> None:
    clip = make_three_scene_clip(tmp_path)
    frames = await keyframes(clip, [(0.0, 2.0), (4.0, 10.0)], _require(FFMPEG, "ffmpeg"), tmp_path)
    assert len(frames) == 2
    green = Image.open(frames[1]).convert("RGB").getpixel((5, 5))
    assert green[1] > green[0] and max(Image.open(frames[0]).size) <= 384


def test_a_contact_sheet_holds_nine_tiles(tmp_path: Path) -> None:
    tiles = [(f"S{i}", solid_jpeg(tmp_path, i)) for i in range(1, 12)]
    sheets = contact_sheets("MAIN", tiles)
    assert [s.shot_ids[:1] for s in sheets] == [["S1"], ["S10"]]
    assert [len(s.shot_ids) for s in sheets] == [9, 2]
    assert Image.open(io.BytesIO(sheets[0].jpeg)).size == (1152, 1152)


def test_cards_stack_at_a_readable_width(tmp_path: Path) -> None:
    sheet = card_sheet([("C1", solid_jpeg(tmp_path, 1)), ("C2", solid_jpeg(tmp_path, 2))])
    assert sheet is not None and Image.open(io.BytesIO(sheet)).size[0] == 900


def test_no_cards_no_card_sheet() -> None:
    assert card_sheet([]) is None
