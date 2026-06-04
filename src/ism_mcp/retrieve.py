"""In-memory cosine search and Reciprocal Rank Fusion."""

from __future__ import annotations

from collections import defaultdict

import numpy as np


class VectorIndex:
    """Dense matrix of L2-normalised embeddings, brute-force cosine search."""

    def __init__(self, matrix: np.ndarray, ids: list[str]) -> None:
        if matrix.shape[0] != len(ids):
            raise ValueError("matrix rows must match ids length")
        self._matrix = matrix
        self._ids = ids

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, query: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        k = max(0, min(top_k, self._matrix.shape[0]))
        if k == 0:
            return []
        scores = self._matrix @ query
        order = np.argpartition(-scores, k - 1)[:k]
        order = order[np.argsort(-scores[order])]
        return [(self._ids[int(i)], float(scores[int(i)])) for i in order]


def rrf(
    rankings: list[list[tuple[str, float]]],
    k: int = 60,
    normalised: bool = True,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. Returns fused [(id, score)] sorted by score desc."""
    accumulator: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (rid, _score) in enumerate(ranking, start=1):
            accumulator[rid] += 1.0 / (k + rank)
    if not accumulator:
        return []
    if normalised and rankings:
        max_score = len(rankings) / (k + 1)
        for rid in accumulator:
            accumulator[rid] = accumulator[rid] / max_score
    return sorted(accumulator.items(), key=lambda kv: (-kv[1], kv[0]))
