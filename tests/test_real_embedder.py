"""Slow integration test. Downloads the real bge-small-en-v1.5 model. Opt-in only."""

from __future__ import annotations

import numpy as np
import pytest

from ism_mcp.embed import FastEmbedEmbedder


@pytest.mark.slow
def test_fastembed_returns_normalised_384_vectors():
    e = FastEmbedEmbedder()
    v = e.embed(["session timeout"])
    assert v.shape == (1, 384)
    np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


@pytest.mark.slow
def test_fastembed_orders_session_query_above_unrelated():
    e = FastEmbedEmbedder()
    vectors = e.embed(
        [
            "Sessions are terminated after fifteen minutes of inactivity.",
            "All data communicated over network infrastructure is encrypted.",
            "Events are logged to a centralised facility.",
        ]
    )
    query = e.embed(["session timeout policy"])[0]
    sims = vectors @ query
    ranked = np.argsort(-sims)
    assert ranked[0] == 0
