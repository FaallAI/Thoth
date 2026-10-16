"""The operator's 2026-10-15 footage labels, replayed on the real embedding model.

Calibration finding (six stories, 47 labeled candidates): between 0.27 and 0.33 relevant and
irrelevant clips overlap, so no threshold separates them there.

The calibration run used a dynamically quantized model whose scores depended on batch
composition (up to 0.047 off) and on the CPU's instruction set (AVX-512 machines up to 0.017
off). The embedder is now the fp32 export, whose scores agree across CPUs within 1e-6
(2026-10-16). `score` is the fp32 value; `recorded_story_score` is the calibration history.
On fp32 the irrelevant B5 (0.349) and the relevant #10 (0.381) bound a clean gap; the operator
chose 0.36, its middle (2026-10-16).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from thoth_control_plane.footage.adapters.embedder import OnnxEmbedder, cosine

THRESHOLD = 0.36
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


def _cpu() -> str:
    # The int8 kernels differ by instruction set, so a drift report names the CPU it ran on.
    info = Path("/proc/cpuinfo")
    if not info.exists():
        return "cpu unknown"
    text = info.read_text()
    model = next(
        (
            line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.startswith("model name")
        ),
        "cpu unknown",
    )
    flags = sorted({f for f in ("avx512_vnni", "avx_vnni", "avx512f") if f" {f}" in text})
    return f"{model} {flags}"


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
    drift = {c["ref"]: round(s - c["score"], 4) for c, s in scored if abs(s - c["score"]) > 1e-4}
    assert not drift, f"{_cpu()}: {drift}"
    for candidate, score in scored:
        admitted = score >= THRESHOLD
        assert admitted == (candidate["golden_decision"] == "admitted"), candidate["ref"]


async def test_relevant_and_irrelevant_overlap_near_the_threshold() -> None:
    scored = await _scores()
    assert any(c["label"] == "relevant" and s < THRESHOLD for c, s in scored)
    assert any(c["label"] == "irrelevant" and s > 0.30 for c, s in scored)
