"""Vector cosine search and reciprocal-rank fusion."""

from __future__ import annotations

import numpy as np
from ism_mcp.retrieve import VectorIndex, rrf


def test_vector_index_returns_nearest_first():
    matrix = np.array(
        [[1.0, 0.0], [0.7, 0.7], [0.0, 1.0]],
        dtype=np.float32,
    )
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    ids = [10, 20, 30]
    idx = VectorIndex(matrix, ids)
    query = np.array([1.0, 0.0], dtype=np.float32)
    query /= np.linalg.norm(query)
    results = idx.search(query, top_k=3)
    assert [rid for rid, _ in results] == [10, 20, 30]
    assert results[0][1] > results[1][1] > results[2][1]


def test_vector_index_respects_top_k():
    matrix = np.array([[1.0], [0.5], [0.1]], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    idx = VectorIndex(matrix, [1, 2, 3])
    query = np.array([1.0], dtype=np.float32)
    assert len(idx.search(query, top_k=2)) == 2


def test_vector_index_empty_returns_empty():
    idx = VectorIndex(np.empty((0, 4), dtype=np.float32), [])
    query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert idx.search(query, top_k=10) == []


def test_rrf_fuses_two_rankings():
    lex = [(10, 0.0), (20, 0.0), (30, 0.0)]
    sem = [(20, 0.0), (10, 0.0), (40, 0.0)]
    fused = rrf([lex, sem], k=60)
    ranked = [rid for rid, _ in fused]
    assert ranked[:2] == [20, 10] or ranked[:2] == [10, 20]
    assert 30 in ranked
    assert 40 in ranked


def test_rrf_top_in_both_outranks_top_in_one():
    lex = [(10, 0.0), (99, 0.0)]
    sem = [(10, 0.0), (88, 0.0)]
    fused = dict(rrf([lex, sem], k=60))
    assert fused[10] > fused[99]
    assert fused[10] > fused[88]


def test_rrf_normalised_score_is_in_unit_range():
    lex = [(10, 0.0)]
    sem = [(10, 0.0)]
    fused = rrf([lex, sem], k=60, normalised=True)
    assert fused[0][0] == 10
    assert 0.99 <= fused[0][1] <= 1.0


def test_rrf_empty_inputs_returns_empty():
    assert rrf([], k=60) == []
    assert rrf([[]], k=60) == []
