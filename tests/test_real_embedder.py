"""Slow integration test. Downloads the real bge-small-en-v1.5 model. Opt-in only."""

from __future__ import annotations

import json

import numpy as np
import pytest

from ism_mcp import server, store
from ism_mcp.embed import FastEmbedEmbedder
from ism_mcp.ingest import embed_controls


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


@pytest.mark.slow
def test_applicable_surfaces_a_lexically_disjoint_semantic_match(
    tmp_path, sample_controls, monkeypatch
):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    version = sample_controls[0].version
    store.set_active_version(conn, version)
    embedder = FastEmbedEmbedder()
    rows = [(version, ident, blob) for ident, blob in embed_controls(sample_controls, embedder)]
    store.insert_embeddings(conn, rows)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "fastembed")
    server._reset_runtime_cache()
    # "idle logout window" shares no words with the session control's text, so a hit
    # there can only come from semantic retrieval, and its why must say so.
    result = json.loads(server.ism_applicable("idle logout window", limit=3))
    server._reset_runtime_cache()
    nine2 = next((r for r in result["results"] if r["identifier"] == "ism-9002"), None)
    assert nine2 is not None, [r["identifier"] for r in result["results"]]
    assert "semantic" in nine2["why"]
    assert "lexical" not in nine2["why"]
