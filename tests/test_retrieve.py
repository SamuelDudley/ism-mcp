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
    ids = ["ism-0010", "ism-0020", "ism-0030"]
    idx = VectorIndex(matrix, ids)
    query = np.array([1.0, 0.0], dtype=np.float32)
    query /= np.linalg.norm(query)
    results = idx.search(query, top_k=3)
    assert [rid for rid, _ in results] == ["ism-0010", "ism-0020", "ism-0030"]
    assert results[0][1] > results[1][1] > results[2][1]


def test_vector_index_respects_top_k():
    matrix = np.array([[1.0], [0.5], [0.1]], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    idx = VectorIndex(matrix, ["a", "b", "c"])
    query = np.array([1.0], dtype=np.float32)
    assert len(idx.search(query, top_k=2)) == 2


def test_vector_index_empty_returns_empty():
    idx = VectorIndex(np.empty((0, 4), dtype=np.float32), [])
    query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert idx.search(query, top_k=10) == []


def test_rrf_fuses_two_rankings():
    lex = [("ism-0010", 0.0), ("ism-0020", 0.0), ("ism-0030", 0.0)]
    sem = [("ism-0020", 0.0), ("ism-0010", 0.0), ("ism-0040", 0.0)]
    fused = rrf([lex, sem], k=60)
    ranked = [rid for rid, _ in fused]
    assert ranked[:2] == ["ism-0020", "ism-0010"] or ranked[:2] == ["ism-0010", "ism-0020"]
    assert "ism-0030" in ranked
    assert "ism-0040" in ranked


def test_rrf_top_in_both_outranks_top_in_one():
    lex = [("ism-0010", 0.0), ("ism-0099", 0.0)]
    sem = [("ism-0010", 0.0), ("ism-0088", 0.0)]
    fused = dict(rrf([lex, sem], k=60))
    assert fused["ism-0010"] > fused["ism-0099"]
    assert fused["ism-0010"] > fused["ism-0088"]


def test_rrf_normalised_score_is_in_unit_range():
    lex = [("ism-0010", 0.0)]
    sem = [("ism-0010", 0.0)]
    fused = rrf([lex, sem], k=60, normalised=True)
    assert fused[0][0] == "ism-0010"
    assert 0.99 <= fused[0][1] <= 1.0


def test_rrf_empty_inputs_returns_empty():
    assert rrf([], k=60) == []
    assert rrf([[]], k=60) == []


def test_vector_index_non_positive_top_k_returns_empty():
    matrix = np.array([[1.0], [0.5]], dtype=np.float32)
    idx = VectorIndex(matrix, ["a", "b"])
    query = np.array([1.0], dtype=np.float32)
    assert idx.search(query, top_k=0) == []
    assert idx.search(query, top_k=-1) == []


def test_vector_index_returns_string_ids():
    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    idx = VectorIndex(matrix, ["ism-0001", "ism-0002"])
    hits = idx.search(np.array([1.0, 0.0], dtype=np.float32), top_k=1)
    assert hits[0][0] == "ism-0001"


def test_rrf_fuses_string_ids():
    fused = rrf([[("a", 0.0), ("b", 0.0)], [("b", 0.0), ("a", 0.0)]])
    assert {rid for rid, _ in fused} == {"a", "b"}
