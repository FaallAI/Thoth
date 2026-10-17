"""Sentence embeddings on the local ONNX model: mean pooling over the attention mask, as the
model's `1_Pooling/config.json` says, then unit length. No network at run time."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.attribution.adapters.ocr import ORT_THREADS
from thoth_control_plane.attribution.adapters.speech import missing

EMBEDDING_FILES = ("model.onnx", "tokenizer.json")
MAX_TOKENS = 128


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Vectors from `OnnxEmbedder` are unit length, so the dot product is the cosine."""
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


@functools.cache
def load_model(directory: Path) -> tuple[Any, Any]:
    """The tokenizer and ONNX session, built once per process: building the session holds the GIL
    for about 2 s, past Temporal's deadlock limit, so the worker builds it before it polls."""
    import onnxruntime
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
    tokenizer.enable_truncation(MAX_TOKENS)
    tokenizer.enable_padding()
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = ORT_THREADS
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    session = onnxruntime.InferenceSession(
        str(directory / "model.onnx"), options, providers=["CPUExecutionProvider"]
    )
    return tokenizer, session


class OnnxEmbedder:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._session: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        if missing(self._dir, EMBEDDING_FILES):
            raise ToolMissing("embedding_model_missing")
        if self._session is None:
            self._tokenizer, self._session = load_model(self._dir)

    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        # One text per run: no padding, so a vector never depends on its neighbours in a batch.
        return [self._embed_one(text or " ") for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        import numpy as np

        self._load()
        encoding = self._tokenizer.encode(text)
        ids = np.array([encoding.ids], dtype=np.int64)
        mask = np.array([encoding.attention_mask], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        names = {item.name for item in self._session.get_inputs()}
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]
        weights = mask[..., None].astype(hidden.dtype)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        vector = pooled[0] / max(float(np.linalg.norm(pooled[0])), 1e-12)
        return [float(x) for x in vector]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self.embed_sync, texts)
