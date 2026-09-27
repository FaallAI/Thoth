"""Real TikTok card crops persisted as checksummed report artifacts."""

import asyncio
import hashlib
import json
import logging
from pathlib import PurePosixPath

import pytest

from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition import cards
from thoth_control_plane.acquisition.cards import (
    CardRejected,
    card_problem,
    persist_cards,
    png_size,
    write_card,
)
from thoth_control_plane.acquisition.models import MAX_CARD_BYTES, BrowserSnapshot, TikTokComment

SOURCE_URL = "https://www.tiktok.com/@creator/video/1234567890"
CARD_ROOT = PurePosixPath("reports/wf_cards_001/cards")
CARD_LOCATION = CARD_ROOT / "comment-12345.png"


def _snapshot(comments: list[TikTokComment], profile: bytes | None = None) -> BrowserSnapshot:
    return BrowserSnapshot(final_url=SOURCE_URL, comments=comments, profile_card_png=profile)


def test_png_size_reads_ihdr_dimensions() -> None:
    assert png_size(make_png(300, 80)) == (300, 80)


@pytest.mark.parametrize(
    "data",
    [b"", b"\x89PNG\r\n\x1a\n", b"GIF89a" + bytes(40), make_png(300, 80)[:20]],
    ids=["empty", "signature-only", "gif", "truncated-ihdr"],
)
def test_png_size_rejects_non_png_or_truncated(data: bytes) -> None:
    with pytest.raises(CardRejected):
        png_size(data)


@pytest.mark.parametrize(
    ("width", "height", "size", "problem"),
    [
        (300, 80, 6_000, None),
        (31, 13, 100, None),
        (300, 80, 0, "size"),
        (300, 80, MAX_CARD_BYTES + 1, "size"),
        (30, 80, 6_000, "dimensions"),
        (300, 12, 6_000, "dimensions"),
        (4_097, 80, 60_000, "dimensions"),
        (300, 4_097, 60_000, "dimensions"),
        (400, 100, 799, "flat"),
        (400, 100, 800, None),
    ],
)
def test_card_problem(width: int, height: int, size: int, problem: str | None) -> None:
    assert card_problem(width, height, size) == problem


def test_write_card_is_atomic_and_checksummed(tmp_path) -> None:
    data = make_png(300, 80)
    artifact = write_card(data, tmp_path, CARD_LOCATION)
    assert (tmp_path / CARD_LOCATION).read_bytes() == data
    assert artifact.location == CARD_LOCATION
    assert artifact.media_type == "image/png"
    assert artifact.bytes == len(data)
    assert artifact.checksum == "sha256:" + hashlib.sha256(data).hexdigest()
    assert (artifact.width, artifact.height) == (300, 80)
    assert list(tmp_path.rglob("*.part")) == []


def test_write_card_retry_overwrites_the_same_name(tmp_path) -> None:
    write_card(make_png(300, 80), tmp_path, CARD_LOCATION)
    second = make_png(320, 90)
    write_card(second, tmp_path, CARD_LOCATION)
    assert [path.name for path in (tmp_path / CARD_ROOT).iterdir()] == ["comment-12345.png"]
    assert (tmp_path / CARD_LOCATION).read_bytes() == second


def test_write_card_rejects_a_flat_crop_without_writing(tmp_path) -> None:
    with pytest.raises(CardRejected):
        write_card(make_png(400, 100, flat=True), tmp_path, CARD_LOCATION)
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    "error", [OSError("disk full"), asyncio.CancelledError()], ids=["oserror", "cancelled"]
)
def test_write_card_removes_part_file_when_replace_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    def failing_replace(*args, **kwargs):
        raise error

    monkeypatch.setattr(cards.os, "replace", failing_replace)
    with pytest.raises(type(error)):
        write_card(make_png(300, 80), tmp_path, CARD_LOCATION)
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_persist_cards_keeps_every_comment_and_drops_only_bad_cards(tmp_path, caplog) -> None:
    snapshot = _snapshot(
        [
            TikTokComment(
                comment_id="11111",
                author="alpha",
                text="first",
                likes=2,
                card_png=make_png(300, 80),
            ),
            TikTokComment(
                comment_id="22222",
                author="beta",
                text="second",
                card_png=make_png(400, 100, flat=True),
            ),
            TikTokComment(comment_id="33333", author="gamma", text="third", card_png=b"not a png"),
            TikTokComment(comment_id="44444", author="delta", text="fourth"),
        ],
        profile=make_png(500, 200),
    )
    with caplog.at_level(logging.WARNING, logger=cards.__name__):
        comments, profile = persist_cards(snapshot, "wf_cards_001", tmp_path)

    assert [comment.comment_id for comment in comments] == ["11111", "22222", "33333", "44444"]
    assert [comment.author for comment in comments] == ["alpha", "beta", "gamma", "delta"]
    assert comments[0].likes == 2
    assert comments[0].card is not None
    assert comments[0].card.location == CARD_ROOT / "comment-11111.png"
    assert [comment.card for comment in comments[1:]] == [None, None, None]
    assert profile is not None
    assert profile.location == CARD_ROOT / "profile.png"
    assert sorted(path.name for path in (tmp_path / CARD_ROOT).iterdir()) == [
        "comment-11111.png",
        "profile.png",
    ]
    assert [record.getMessage() for record in caplog.records] == [
        "tiktok card crops: written=2 rejected=2 failed=0"
    ]


def test_persist_cards_drops_a_card_whose_write_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    def failing_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cards.os, "replace", failing_replace)
    snapshot = _snapshot(
        [
            TikTokComment(
                comment_id="11111", author="alpha", text="first", card_png=make_png(300, 80)
            )
        ]
    )
    with caplog.at_level(logging.WARNING, logger=cards.__name__):
        comments, profile = persist_cards(snapshot, "wf_cards_001", tmp_path)

    assert [comment.comment_id for comment in comments] == ["11111"]
    assert comments[0].card is None
    assert profile is None
    assert [record.getMessage() for record in caplog.records] == [
        "tiktok card crops: written=0 rejected=0 failed=1"
    ]


def test_persist_cards_is_silent_when_every_card_is_written(tmp_path, caplog) -> None:
    snapshot = _snapshot(
        [
            TikTokComment(
                comment_id="11111", author="alpha", text="first", card_png=make_png(300, 80)
            )
        ],
        profile=make_png(500, 200),
    )
    with caplog.at_level(logging.WARNING, logger=cards.__name__):
        persist_cards(snapshot, "wf_cards_001", tmp_path)
    assert caplog.records == []


def test_persist_cards_without_a_snapshot_records_nothing(tmp_path) -> None:
    assert persist_cards(None, "wf_cards_001", tmp_path) == ([], None)
    assert list(tmp_path.iterdir()) == []


def test_persisted_comments_serialize_without_image_bytes(tmp_path) -> None:
    snapshot = _snapshot(
        [
            TikTokComment(
                comment_id="11111", author="alpha", text="first", card_png=make_png(300, 80)
            )
        ],
        profile=make_png(500, 200),
    )
    comments, profile = persist_cards(snapshot, "wf_cards_001", tmp_path)
    assert profile is not None
    dumped = json.dumps([comment.model_dump(mode="json") for comment in comments])
    dumped += profile.model_dump_json()
    assert "PNG" not in dumped
    assert "card_png" not in dumped
