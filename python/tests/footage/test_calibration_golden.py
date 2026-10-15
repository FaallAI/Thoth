"""The operator's 2026-10-15 footage labels, replayed on the real embedding model.

Calibration finding (six stories, 47 labeled candidates): between 0.27 and 0.33 relevant and
irrelevant clips overlap, so no threshold separates them there; 0.33 stays because it still
rejects the clear misses without dropping clips the operator labeled relevant above it.

The calibration run embedded whole batches through a dynamically quantized model, so its scores
depended on batch composition (up to 0.047 off). The embedder now runs one text at a time; the
stored `score` is that batch-independent value and `recorded_story_score` is the calibration
history. Two candidates cross 0.33 versus the calibration run: #18 (relevant) falls to 0.317 and
is now rejected, B9 (irrelevant) rises to 0.332 and is now admitted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from thoth_control_plane.footage.adapters.embedder import OnnxEmbedder, cosine

THRESHOLD = 0.33
_STORIES = json.loads(
    (Path(__file__).parent.parent / "fixtures/footage/calibration_2026-10-15.json").read_text(
        encoding="utf-8"
    )
)


def _required(variable: str) -> Path:
    # Operator, 2026-10-11/13: a missing tool or model fails the test, never a skip.
    value = os.environ.get(variable)
    if not value or not Path(value).is_dir():
        pytest.fail(f"{variable} must point to the fetched embedding model (plan Task 4)")
    return Path(value)


async def _scores() -> list[tuple[dict, float]]:
    embedder = OnnxEmbedder(_required("THOTH_TEST_EMBEDDING_MODEL_DIR"))
    scored = []
    for story in _STORIES:
        text = story["text"]  # exactly FootageBuilder._story
        vectors = await embedder.embed(
            [f"{text[:120]}. {text}".strip(), *(c["caption"] for c in story["candidates"])]
        )
        for candidate, vector in zip(story["candidates"], vectors[1:], strict=True):
            score = 0.0
            if candidate["caption"].strip():
                score = max(0.0, min(1.0, cosine(vectors[0], vector)))
            scored.append((candidate, score))
    return scored


async def test_scores_and_threshold_decisions_reproduce() -> None:
    scored = await _scores()
    assert len(scored) == 47
    for candidate, score in scored:
        assert abs(score - candidate["score"]) <= 1e-4, candidate["ref"]
        admitted = score >= THRESHOLD
        assert admitted == (candidate["golden_decision"] == "admitted"), candidate["ref"]


async def test_relevant_and_irrelevant_overlap_near_the_threshold() -> None:
    scored = await _scores()
    assert any(c["label"] == "relevant" and s < THRESHOLD for c, s in scored)
    assert any(c["label"] == "irrelevant" and s > 0.30 for c, s in scored)
