"""Faces of a video (spec 2026-11-15, 10.12): YuNet finds them at 1 fps, each is aligned to the
ArcFace 112 px template and embedded with ArcFace r50 (InsightFace buffalo_l). Both models are
baked into the worker image; a missing file is an explicit error."""

from __future__ import annotations

import functools
import threading
from pathlib import Path

import numpy as np

from thoth_control_plane.footage.faces import DETECT_SCORE, FACE_FPS, MIN_FACE, Face

FACE_FILES = ("yunet.onnx", "arcface.onnx")
CROP_SIZE = 112
THUMB_SIZE = 96
# Where ArcFace expects the eyes, nose and mouth corners in its 112 px crop (InsightFace).
ARCFACE_POINTS = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def similarity(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """The 2x3 rotation, scale and shift that best maps `source` points onto `target` (Umeyama,
    least squares), as InsightFace's alignment estimates it."""
    mean_s, mean_t = source.mean(axis=0), target.mean(axis=0)
    centred_s, centred_t = source - mean_s, target - mean_t
    u, singular, vt = np.linalg.svd(centred_t.T @ centred_s / len(source))
    sign = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[1, 1] = -1
    rotation = u @ sign @ vt
    scale = float((singular * np.diag(sign)).sum() / centred_s.var(axis=0).sum())
    shift = mean_t - scale * rotation @ mean_s
    return np.hstack([scale * rotation, shift[:, None]]).astype(np.float32)


@functools.cache
def shared_reader(models_dir: Path) -> FaceReader:
    """One reader per worker: the subject stage and the screening share its ArcFace session
    (final review, 5: two sessions held two copies of the model)."""
    return FaceReader(models_dir)


class FaceReader:
    def __init__(self, models_dir: Path) -> None:
        import cv2
        import onnxruntime

        missing = [name for name in FACE_FILES if not (models_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"face models missing: {', '.join(missing)}")
        self._detector = cv2.FaceDetectorYN.create(
            str(models_dir / "yunet.onnx"), "", (320, 320), DETECT_SCORE
        )
        self._session = onnxruntime.InferenceSession(
            str(models_dir / "arcface.onnx"), providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name
        # The detector keeps its input size between calls: one video at a time.
        self._lock = threading.Lock()

    def faces(self, path: Path, start: float = 0.0, duration: float | None = None) -> list[Face]:
        """Every face of at least MIN_FACE px, one frame a second from `start`; blocking."""
        import cv2

        with self._lock:
            capture = cv2.VideoCapture(str(path))
            try:
                rate = capture.get(cv2.CAP_PROP_FPS) or 25.0
                step = max(1, round(rate / FACE_FPS))
                if start:
                    capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
                found: list[Face] = []
                index = 0
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    at = index / rate
                    if duration is not None and at > duration:
                        break
                    if index % step == 0:
                        found += self._frame_faces(frame, int(start + at))
                    index += 1
                return found
            finally:
                capture.release()

    def _frame_faces(self, frame: np.ndarray, second: int) -> list[Face]:
        import cv2

        height, width = frame.shape[:2]
        self._detector.setInputSize((width, height))
        _, detected = self._detector.detect(frame)
        crops = []
        for row in detected if detected is not None else []:
            if min(row[2], row[3]) < MIN_FACE:
                continue
            matrix = similarity(row[4:14].reshape(5, 2).astype(np.float32), ARCFACE_POINTS)
            crops.append(cv2.warpAffine(frame, matrix, (CROP_SIZE, CROP_SIZE)))
        if not crops:
            return []
        faces = []
        for crop in crops:
            # The buffalo_l export fixes its batch at one face.
            blob = cv2.dnn.blobFromImage(
                crop, 1 / 127.5, (CROP_SIZE, CROP_SIZE), (127.5, 127.5, 127.5), swapRB=True
            )
            vector = self._session.run(None, {self._input: blob})[0][0]
            vector = vector / max(float(np.linalg.norm(vector)), 1e-9)
            thumb = cv2.imencode(".jpg", cv2.resize(crop, (THUMB_SIZE, THUMB_SIZE)))[1].tobytes()
            faces.append(Face(second=second, embedding=vector.astype(np.float32), crop=thumb))
        return faces
