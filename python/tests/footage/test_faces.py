"""The face rules over embeddings (spec 2026-11-15, 10.12): groups, the clear subject, the match."""

from __future__ import annotations

import numpy as np

from thoth_control_plane.footage.faces import (
    MATCH,
    TEMPLATE_SIZE,
    Face,
    FaceGroup,
    clear_subject,
    decode_template,
    encode_template,
    group_faces,
    shows_subject,
    template,
)

DIM = 512


def _unit(seed: int) -> np.ndarray:
    vector = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
    return vector / np.linalg.norm(vector)


def _near(base: np.ndarray, seed: int, noise: float = 0.3) -> np.ndarray:
    vector = base + noise * _unit(seed)
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def _person(base: np.ndarray, seconds: range, seed: int) -> list[Face]:
    return [Face(second=s, embedding=_near(base, seed + s)) for s in seconds]


def test_group_faces_ranks_by_screen_time() -> None:
    saiful, densu, passer = _unit(1), _unit(2), _unit(3)
    faces = [
        *_person(saiful, range(0, 54), 100),
        *_person(densu, range(10, 41), 200),
        *_person(passer, range(5, 7), 300),  # two seconds: not a group that counts
    ]
    groups = group_faces(faces)
    assert [g.seconds for g in groups] == [54, 31]
    assert all(float(f.embedding @ saiful) > 0.8 for f in groups[0].members)


def test_a_face_twice_in_one_second_counts_one_second() -> None:
    saiful = _unit(1)
    faces = [Face(second=s // 2, embedding=_near(saiful, s)) for s in range(10)]
    assert [g.seconds for g in group_faces(faces)] == [5]


def _group(seconds: int) -> FaceGroup:
    return FaceGroup(members=[], seconds=seconds)


def test_clear_subject_needs_one_and_a_half_times_the_next() -> None:
    saiful, densu = _group(54), _group(31)
    assert clear_subject([saiful, densu]) is saiful  # the Mutant main: 54 s against 31 s
    assert clear_subject([_group(30), _group(25)]) is None
    alone = _group(9)
    assert clear_subject([alone]) is alone
    assert clear_subject([]) is None


def test_shows_subject_needs_two_seconds_at_the_match() -> None:
    saiful = _unit(1)
    kept = template(FaceGroup(members=_person(saiful, range(0, 40), 100), seconds=40))
    assert len(kept) == TEMPLATE_SIZE
    same = [Face(second=s, embedding=_near(saiful, 500 + s)) for s in (3, 4)]
    other = [Face(second=s, embedding=_unit(900 + s)) for s in (3, 4, 5)]
    assert shows_subject(kept, same)
    assert not shows_subject(kept, same[:1])  # one second is not enough
    assert not shows_subject(kept, [Face(second=3, embedding=same[0].embedding)] * 3)
    assert not shows_subject(kept, other)
    assert not shows_subject(kept, [])
    assert float(np.sort(kept @ other[0].embedding)[-5:].mean()) < MATCH


def test_template_round_trips_through_text() -> None:
    kept = np.vstack([_unit(n) for n in range(3)])
    back = decode_template(encode_template(kept))
    assert back.shape == (3, DIM)
    assert np.allclose(back, kept, atol=1e-3)
