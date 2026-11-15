"""The planner's view of the sources (spec 2026-11-13, 5.2 and 5.4): shots, keyframes, sheets.

Shots come from ffmpeg's scene score; very short ones merge and long ones split, so every shot is a
picture a phrase can use. The model reads numbered contact sheets: 3x3 tiles of one source each,
and the cards stacked at a width where their text stays readable. CPU only.
"""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCENE_THRESHOLD = 0.3
MIN_SHOT = 0.8
MAX_SHOT = 4.0
SPLIT_TO = 3.0
TILE = 384
GRID = 3
CARD_WIDTH = 900
_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_LABEL = (255, 220, 0)


@dataclass(frozen=True)
class Sheet:
    source: str
    shot_ids: list[str]
    jpeg: bytes


async def _run(*command: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await process.communicate()
    except asyncio.CancelledError:
        # The planner's deadline passed: the command must not keep the CPU busy after it.
        process.kill()
        await process.wait()
        raise
    return process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _duration(video: Path, ffprobe: str) -> float:
    code, out, _ = await _run(
        ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)
    )
    if code != 0:
        raise RuntimeError("ffprobe could not read the video's duration")
    return float(out.strip())


async def detect_shots(video: Path, ffmpeg: str, ffprobe: str) -> list[tuple[float, float]]:
    """The video's shots in seconds: cuts where the scene score passes 0.3, shots under 0.8 s
    merged into the one before, shots over 4 s split into pieces of about 3 s."""
    total = await _duration(video, ffprobe)
    code, _, err = await _run(
        ffmpeg, "-hide_banner", "-i", str(video),
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo", "-an", "-f", "null", "-",
    )  # fmt: skip
    if code != 0:
        raise RuntimeError("ffmpeg could not read the video's scenes")
    cuts = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", err) if 0 < float(t) < total]
    edges = [0.0, *cuts, total]
    spans: list[tuple[float, float]] = []
    for start, end in pairwise(edges):
        if spans and end - start < MIN_SHOT:
            spans[-1] = (spans[-1][0], end)
            continue
        spans.append((start, end))
    if len(spans) > 1 and spans[0][1] - spans[0][0] < MIN_SHOT:
        spans[1] = (spans[0][0], spans[1][1])
        spans.pop(0)
    shots: list[tuple[float, float]] = []
    for start, end in spans:
        pieces = max(1, round((end - start) / SPLIT_TO)) if end - start > MAX_SHOT else 1
        step = (end - start) / pieces
        shots += [(start + i * step, start + (i + 1) * step) for i in range(pieces)]
    return shots


async def keyframes(
    video: Path, spans: Sequence[tuple[float, float]], ffmpeg: str, directory: Path
) -> list[Path]:
    """One JPEG per span, from its middle, scaled to fit a 384 px tile."""
    frames = []
    for index, (start, end) in enumerate(spans):
        target = directory / f"{video.stem}_{index:04d}.jpg"
        code, _, _ = await _run(
            ffmpeg, "-y", "-v", "error", "-ss", f"{(start + end) / 2:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={TILE}:{TILE}:force_original_aspect_ratio=decrease",
            str(target),
        )  # fmt: skip
        if code != 0 or not target.exists():
            raise RuntimeError("ffmpeg could not take a keyframe")
        frames.append(target)
    return frames


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(_FONT, size)
    except OSError:
        return ImageFont.load_default()


def _jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def contact_sheets(source: str, tiles: Sequence[tuple[str, Path]]) -> list[Sheet]:
    """3x3 sheets of one source's keyframes, each tile labelled with its shot id in yellow."""
    per = GRID * GRID
    font = _font(40)
    sheets = []
    for first in range(0, len(tiles), per):
        group = tiles[first : first + per]
        canvas = Image.new("RGB", (TILE * GRID, TILE * GRID), (20, 20, 20))
        draw = ImageDraw.Draw(canvas)
        for index, (shot_id, frame) in enumerate(group):
            x, y = (index % GRID) * TILE, (index // GRID) * TILE
            with Image.open(frame) as picture:
                tile = picture.convert("RGB")
                tile.thumbnail((TILE, TILE))
                canvas.paste(tile, (x + (TILE - tile.width) // 2, y + (TILE - tile.height) // 2))
            draw.rectangle([x, y, x + 110, y + 50], fill=_LABEL)
            draw.text((x + 6, y + 3), shot_id, fill=(0, 0, 0), font=font)
            draw.rectangle([x, y, x + TILE - 1, y + TILE - 1], outline=(90, 90, 90), width=2)
        sheets.append(Sheet(source, [shot_id for shot_id, _ in group], _jpeg(canvas, 85)))
    return sheets


def card_sheet(cards: Sequence[tuple[str, Path]]) -> bytes | None:
    """The cards stacked 900 px wide: on a comment card the text is the point."""
    if not cards:
        return None
    gap = 16
    scaled = []
    for card_id, path in cards:
        with Image.open(path) as picture:
            image = picture.convert("RGB")
        scale = min((CARD_WIDTH - 40) / image.width, 520 / image.height)
        size = (int(image.width * scale), int(image.height * scale))
        scaled.append((card_id, image.resize(size)))
    height = sum(image.height + 50 + gap for _, image in scaled) + gap
    canvas = Image.new("RGB", (CARD_WIDTH, height), (20, 20, 20))
    draw = ImageDraw.Draw(canvas)
    font = _font(36)
    y = gap
    for card_id, image in scaled:
        draw.rectangle([20, y, 130, y + 44], fill=_LABEL)
        draw.text((26, y + 2), card_id, fill=(0, 0, 0), font=font)
        canvas.paste(image, (20, y + 50))
        y += image.height + 50 + gap
    return _jpeg(canvas, 88)
