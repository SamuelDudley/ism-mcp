"""End-to-end ingest with the deterministic hash embedder."""

from __future__ import annotations

import sqlite3

import numpy as np

from ism_mcp import ingest, store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.oscal import VersionMeta


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def test_embed_controls_yields_identifier_keyed_unit_vectors(sample_controls):
    embedder = DeterministicHashEmbedder(dim=384)
    rows = list(ingest.embed_controls(sample_controls, embedder))
    assert [ident for ident, _ in rows] == [c.identifier for c in sample_controls]
    vec = np.frombuffer(rows[0][1], dtype=np.float32)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5


def test_embedding_text_includes_hierarchy_and_description(sample_controls):
    text = ingest.embedding_text(sample_controls[0])
    assert "Network encryption" in text
    assert "encrypted" in text


def test_ingest_version_with_embedder_populates_matrix(sample_controls):
    db = _db()
    vmeta = VersionMeta(
        version="2026.03.24",
        title="ISM",
        published=None,
        last_modified=None,
        oscal_version="1.1.2",
    )
    ingest.ingest_version(db, vmeta, sample_controls, embedder=DeterministicHashEmbedder(dim=384))
    matrix, ids = store.load_embedding_matrix(db, dim=384, version="2026.03.24")
    assert matrix.shape == (3, 384)
    assert set(ids) == {c.identifier for c in sample_controls}
    db.close()
