"""Embedder protocol and the deterministic hash implementation."""

from __future__ import annotations

import numpy as np

from ism_mcp.embed import DeterministicHashEmbedder, l2_normalise


def test_hash_embedder_shape_and_dtype():
    e = DeterministicHashEmbedder(dim=384)
    v = e.embed(["hello world", "another control"])
    assert v.shape == (2, 384)
    assert v.dtype == np.float32


def test_hash_embedder_is_deterministic():
    e = DeterministicHashEmbedder(dim=384)
    a = e.embed(["session timeout"])
    b = e.embed(["session timeout"])
    np.testing.assert_array_equal(a, b)


def test_hash_embedder_distinguishes_inputs():
    e = DeterministicHashEmbedder(dim=384)
    v = e.embed(["session timeout", "network encryption"])
    assert not np.allclose(v[0], v[1])


def test_hash_embedder_outputs_are_l2_normalised():
    e = DeterministicHashEmbedder(dim=384)
    v = e.embed(["foo", "bar", "baz"])
    norms = np.linalg.norm(v, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-6)


def test_l2_normalise_handles_zero_vector():
    v = np.zeros((1, 4), dtype=np.float32)
    out = l2_normalise(v)
    assert np.all(np.isfinite(out))
    assert out.shape == (1, 4)
