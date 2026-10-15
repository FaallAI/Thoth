"""The local multilingual embedder on the real model; a missing model fails the test."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.footage.adapters.embedder import OnnxEmbedder, cosine


def _required(variable: str) -> Path:
    # Operator, 2026-10-11/13: a missing tool or model fails the test, never a skip.
    value = os.environ.get(variable)
    if not value or not Path(value).is_dir():
        pytest.fail(f"{variable} must point to the fetched embedding model (plan Task 4)")
    return Path(value)


async def test_a_paraphrase_scores_above_an_unrelated_text() -> None:
    embedder = OnnxEmbedder(_required("THOTH_TEST_EMBEDDING_MODEL_DIR"))
    story, paraphrase, unrelated = await embedder.embed(
        [
            "banjir besar melanda jakarta, mobil terendam di jalan",
            "jalanan jakarta tergenang air setelah hujan deras",
            "resep nasi goreng kampung yang enak dan murah",
        ]
    )
    assert abs(cosine(story, story) - 1.0) < 1e-4
    assert cosine(story, paraphrase) > cosine(story, unrelated) + 0.1


async def test_a_missing_model_is_an_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(ToolMissing, match="embedding_model_missing"):
        await OnnxEmbedder(tmp_path).embed(["x"])


async def test_a_vector_does_not_depend_on_its_batch() -> None:
    embedder = OnnxEmbedder(_required("THOTH_TEST_EMBEDDING_MODEL_DIR"))
    text = "banjir besar melanda jakarta, mobil terendam di jalan"
    (alone,) = await embedder.embed([text])
    batch = await embedder.embed(
        ["resep nasi goreng kampung yang enak dan murah " * 8, text, "halo", "gempa di bandung"]
    )
    assert max(abs(x - y) for x, y in zip(alone, batch[1], strict=True)) < 1e-5
