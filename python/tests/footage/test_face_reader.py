"""The face reader on the real models (spec 2026-11-15, 10.12); a missing model fails the test.

Fixtures, cut at 1 fps from spike 3's public clips: the Mutant main's subject (Saiful), Saiful in
another event ("Mutant Belajar Akting"), and another person (Tretan Muslim on a podcast). The
operator confirmed who is who (brainstorm item 76).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from thoth_control_plane.footage.adapters.faces import FaceReader, similarity
from thoth_control_plane.footage.faces import (
    EMBEDDING_DIM,
    clear_subject,
    group_faces,
    shows_subject,
    template,
)

FACES = Path(__file__).resolve().parents[1] / "fixtures" / "footage" / "faces"


def _models() -> Path:
    # Operator, 2026-10-11/13: a missing tool or model fails the test, never a skip.
    value = os.environ.get("THOTH_TEST_FACE_MODELS_DIR")
    if not value or not Path(value).is_dir():
        pytest.fail("THOTH_TEST_FACE_MODELS_DIR must point to the fetched face models")
    return Path(value)


def test_the_alignment_maps_points_onto_themselves() -> None:
    points = np.array([[10, 10], [30, 10], [20, 20], [12, 30], [28, 30]], dtype=np.float32)
    matrix = similarity(points, points * 2 + 5)
    moved = points @ matrix[:, :2].T + matrix[:, 2]
    assert np.allclose(moved, points * 2 + 5, atol=1e-3)


def test_a_missing_model_is_an_explicit_error(tmp_path: Path) -> None:
    (tmp_path / "yunet.onnx").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match=r"arcface\.onnx"):
        FaceReader(tmp_path)


def test_the_subject_is_found_in_another_event_and_another_person_is_not() -> None:
    reader = FaceReader(_models())
    main = reader.faces(FACES / "main_subject.mp4")
    assert main and all(f.embedding.shape == (EMBEDDING_DIM,) for f in main)
    assert all(abs(float(np.linalg.norm(f.embedding)) - 1.0) < 1e-3 for f in main)
    assert all(f.crop.startswith(b"\xff\xd8") for f in main)  # a JPEG thumbnail
    subject = clear_subject(group_faces(main))
    assert subject is not None
    kept = template(subject)
    assert shows_subject(kept, reader.faces(FACES / "same_person.mp4"))
    assert not shows_subject(kept, reader.faces(FACES / "other_person.mp4"))


def test_the_worker_shares_one_reader() -> None:  # final review, Minor 5 re-graded: memory
    from thoth_control_plane.footage.adapters.faces import shared_reader

    assert shared_reader(_models()) is shared_reader(_models())


def test_two_reads_at_once_match_one_at_a_time() -> None:  # final review, minor 4
    from concurrent.futures import ThreadPoolExecutor

    reader = FaceReader(_models())
    paths = [FACES / "main_subject.mp4", FACES / "same_person.mp4"]
    alone = [len(reader.faces(path)) for path in paths]
    with ThreadPoolExecutor(2) as pool:
        together = [len(found) for found in pool.map(reader.faces, paths)]
    assert together == alone
    assert not hasattr(reader, "_lock")  # each read has its own detector
