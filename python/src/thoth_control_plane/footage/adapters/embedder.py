"""Sentence embeddings on the local ONNX model: mean pooling over the attention mask, as the
model's `1_Pooling/config.json` says, then unit length. No network at run time."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.attribution.adapters.speech import missing

EMBEDDING_FILES = ("model.onnx", "tokenizer.json")
MAX_TOKENS = 128


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Vectors from `OnnxEmbedder` are unit length, so the dot product is the cosine."""
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


class OnnxEmbedder:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._session: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        if missing(self._dir, EMBEDDING_FILES):
            raise ToolMissing("embedding_model_missing")
        if self._session is None:
            import onnxruntime
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(self._dir / "tokenizer.json"))
            tokenizer.enable_truncation(MAX_TOKENS)
            tokenizer.enable_padding()
            self._tokenizer = tokenizer
            self._session = onnxruntime.InferenceSession(
                str(self._dir / "model.onnx"), providers=["CPUExecutionProvider"]
            )

    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        import numpy as np

        self._load()
        encodings = self._tokenizer.encode_batch([text or " " for text in texts])
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        names = {item.name for item in self._session.get_inputs()}
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]
        weights = mask[..., None].astype(hidden.dtype)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        vectors = pooled / np.clip(norms, 1e-12, None)
        return [[float(x) for x in row] for row in vectors]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self.embed_sync, texts)
