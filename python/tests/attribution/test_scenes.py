"""Shots from scene cuts, and the frames the vision call sees."""

from __future__ import annotations

from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.attribution.scenes import Shot, label, shots, vision_frames


def _frames(count: int) -> list[Frame]:
    return [Frame(float(n), f"r:{n}".encode()) for n in range(count)]


def test_cuts_split_the_video_and_short_shots_merge() -> None:
    assert shots([3.0, 3.4, 20.0], 30.0) == [Shot(0.0, 3.4), Shot(3.4, 20.0), Shot(20.0, 30.0)]
    assert shots([], 12.0) == [Shot(0.0, 12.0)]


def test_vision_sees_the_cover_and_the_middle_of_the_longest_shots() -> None:
    frames = _frames(70)
    cut = shots([3.0, 40.0, 41.5, 60.0], 70.0)

    seconds = [frame.second for frame in vision_frames(frames, cut)]

    # The cover seconds, then the middles of the shots from longest to shortest: 3-40 (21),
    # 41.5-60 (51), 60-70 (65), 0-3 (its middle is the cover second 1), 40-41.5 (41).
    assert seconds == [0.0, 1.0, 21.0, 41.0, 51.0, 65.0]


def test_a_clip_then_talk_reaction_is_seen_in_both_shots() -> None:
    frames = _frames(70)
    seconds = [f.second for f in vision_frames(frames, shots([3.0], 70.0))]

    assert any(s < 3.0 for s in seconds) and any(s > 30.0 for s in seconds)


def test_labels_follow_the_frame_inside_each_shot() -> None:
    cut = shots([3.0], 70.0)
    sent = [Frame(0.0, b""), Frame(1.0, b""), Frame(36.0, b"")]

    labelled = label(cut, sent, ["subject", "subject", "creator"])

    assert [shot.shows for shot in labelled] == ["subject", "creator"]


def test_a_short_shows_list_labels_nothing() -> None:
    cut = shots([3.0], 70.0)
    sent = [Frame(0.0, b""), Frame(36.0, b"")]

    assert [s.shows for s in label(cut, sent, ["creator"])] == ["other", "other"]
