"""Embedder protocol and implementations."""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


def l2_normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms < 1e-9, 1.0, norms)


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class DeterministicHashEmbedder:
    """Stable per-text vector derived from SHA-256 of the input. Test-only."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:8], "big", signed=False)
            rng = np.random.default_rng(seed)
            out[i] = rng.standard_normal(self.dim, dtype=np.float32)
        return l2_normalise(out)


class FastEmbedEmbedder:
    """Default. Wraps BAAI/bge-small-en-v1.5 via fastembed."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self.dim = 384

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array(list(self._model.embed(texts)), dtype=np.float32)
        return l2_normalise(vectors)
