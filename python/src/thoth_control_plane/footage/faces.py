"""The story's subject by face (footage library spec 2026-11-15, 10.12): pure rules over ArcFace
embeddings. The main's faces are grouped and ranked by screen time; a clip shows the subject when
its faces match the subject's group in two distinct seconds.

Spike 3 (2026-11-16, operator ground truth): the same person scored 0.54-0.57 against their own
group across events, different people at most 0.30.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

FACE_FPS = 1.0
MIN_FACE = 40  # px, the face box's short side
DETECT_SCORE = 0.8
GROUP_LINK = 0.25  # average-linkage merge
MIN_SECONDS = 3  # a group counts from three distinct seconds on screen
CLEAR_RATIO = 1.5
MAX_CHOICES = 4
TEMPLATE_SIZE = 16
TOP_K = 5
MATCH = 0.42
MATCH_SECONDS = 2
EMBEDDING_DIM = 512


@dataclass(frozen=True)
class Face:
    second: int
    embedding: np.ndarray  # L2-normalised, EMBEDDING_DIM floats
    crop: bytes = b""  # a small JPEG, shown when the operator chooses the subject


@dataclass(frozen=True)
class FaceGroup:
    members: list[Face]
    seconds: int


def group_faces(faces: Sequence[Face]) -> list[FaceGroup]:
    """Average-linkage groups of one person each, with at least MIN_SECONDS distinct seconds,
    longest on screen first."""
    if not faces:
        return []
    vectors = np.vstack([face.embedding for face in faces]).astype(np.float32)
    # ponytail: O(n^2) memory and O(n^3) merges; a 3-minute main holds a few hundred faces.
    sums = vectors @ vectors.T  # pairwise similarity sums between groups
    sizes = np.ones(len(faces))
    alive = np.ones(len(faces), dtype=bool)
    members: list[list[int]] = [[i] for i in range(len(faces))]
    np.fill_diagonal(sums, 0.0)
    while alive.sum() > 1:
        average = sums / np.outer(sizes, sizes)
        mask = np.outer(alive, alive)
        np.fill_diagonal(mask, False)
        average[~mask] = -np.inf
        a, b = np.unravel_index(int(np.argmax(average)), average.shape)
        if average[a, b] < GROUP_LINK:
            break
        sums[a, :] += sums[b, :]
        sums[:, a] += sums[:, b]
        sums[a, a] = 0.0
        sizes[a] += sizes[b]
        alive[b] = False
        members[a] += members[b]
    groups = []
    for index in np.flatnonzero(alive):
        kept = [faces[i] for i in members[index]]
        seconds = len({face.second for face in kept})
        if seconds >= MIN_SECONDS:
            groups.append(FaceGroup(members=kept, seconds=seconds))
    return sorted(groups, key=lambda group: -group.seconds)


def clear_subject(groups: Sequence[FaceGroup]) -> FaceGroup | None:
    """The top group when it alone counts or stays CLEAR_RATIO times longer than the next one;
    None when there is no group or the top is not clear (the operator chooses)."""
    if not groups:
        return None
    if len(groups) == 1 or groups[0].seconds >= CLEAR_RATIO * groups[1].seconds:
        return groups[0]
    return None


def template(group: FaceGroup) -> np.ndarray:
    """Up to TEMPLATE_SIZE member embeddings, evenly spaced over the group's time on screen."""
    ordered = sorted(group.members, key=lambda face: face.second)
    picks = np.unique(np.linspace(0, len(ordered) - 1, min(len(ordered), TEMPLATE_SIZE)).round())
    return np.vstack([ordered[int(i)].embedding for i in picks]).astype(np.float32)


def shows_subject(subject: np.ndarray, faces: Sequence[Face]) -> bool:
    """Faces in at least MATCH_SECONDS distinct seconds score MATCH or more: each face's score is
    the mean of its TOP_K best similarities to the subject's template."""
    if len(subject) == 0:
        return False
    k = min(TOP_K, len(subject))
    seconds = {
        face.second
        for face in faces
        if float(np.sort(subject @ face.embedding)[-k:].mean()) >= MATCH
    }
    return len(seconds) >= MATCH_SECONDS


def encode_template(array: np.ndarray) -> str:
    """The template as text for a workflow payload: float16, base64."""
    return base64.b64encode(np.asarray(array, dtype="<f2").tobytes()).decode("ascii")


def decode_template(text: str) -> np.ndarray:
    raw = np.frombuffer(base64.b64decode(text), dtype="<f2")
    return raw.reshape(-1, EMBEDDING_DIM).astype(np.float32)
