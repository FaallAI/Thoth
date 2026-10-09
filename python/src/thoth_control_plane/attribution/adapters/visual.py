"""Find a candidate's footage inside repost frames: ORB features and a RANSAC homography.

A repost may cut, zoom, overlay, or shrink the original into a panel of a reaction video, so a
whole-frame hash misses it. Feature matching does not care where or how large the footage sits:
a candidate frame that a repost frame contains yields many geometrically consistent matches
(spike on real reposts, 2026-10-10: true pairs 124 to 418 inliers, unrelated pairs at most 12).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from thoth_control_plane.attribution.ports import Frame

FEATURES = 600
RATIO = 0.75  # Lowe's ratio test
RANSAC_PIXELS = 5.0
MIN_MATCHES = 8


class OrbMatcher:
    def __init__(self, step: int = 2) -> None:
        # Every `step`-th frame is compared: adjacent seconds look alike, and ORB costs CPU.
        self._step = step

    async def prepare(self, frames: Sequence[Frame]) -> list[Any]:
        return await asyncio.to_thread(self._prepare, list(frames[:: self._step]))

    async def compare(self, repost: list[Any], candidate: list[Any]) -> list[int]:
        return await asyncio.to_thread(self._compare, repost, candidate)

    def _prepare(self, frames: list[Frame]) -> list[Any]:
        import cv2
        import numpy as np

        orb = cv2.ORB_create(nfeatures=FEATURES)
        prepared = []
        for frame in frames:
            image = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            keypoints, descriptors = orb.detectAndCompute(image, None)
            if descriptors is None or len(keypoints) < MIN_MATCHES:
                continue  # a flat frame (a fade, a black card) has nothing to match
            points = np.float32([keypoint.pt for keypoint in keypoints])
            prepared.append((points, descriptors))
        return prepared

    def _compare(self, repost: list[Any], candidate: list[Any]) -> list[int]:
        import cv2

        if not repost or not candidate:
            return []
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        # ponytail: every repost frame against every candidate frame, a few thousand pairs at
        # 1 frame per 2 s; index candidates by a coarse hash if clips grow long.
        return [
            max(_inliers(cv2, matcher, frame, other) for other in candidate) for frame in repost
        ]


def _inliers(cv2: Any, matcher: Any, a: Any, b: Any) -> int:
    (points_a, descriptors_a), (points_b, descriptors_b) = a, b
    pairs = matcher.knnMatch(descriptors_a, descriptors_b, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < RATIO * n.distance]
    if len(good) < MIN_MATCHES:
        return 0
    source = points_a[[m.queryIdx for m in good]].reshape(-1, 1, 2)
    target = points_b[[m.trainIdx for m in good]].reshape(-1, 1, 2)
    _, mask = cv2.findHomography(source, target, cv2.RANSAC, RANSAC_PIXELS)
    return int(mask.sum()) if mask is not None else 0
