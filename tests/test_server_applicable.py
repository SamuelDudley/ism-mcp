"""End-to-end tests for ism_applicable with the deterministic hash embedder."""

from __future__ import annotations

import json

import pytest

from ism_mcp import server, store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls


@pytest.fixture
def populated_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    embedder = DeterministicHashEmbedder(dim=384)
    fetched = [
        c for c in (store.get_control(conn, c.identifier) for c in sample_controls) if c is not None
    ]
    store.insert_embeddings(conn, list(embed_controls(fetched, embedder)))
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "hash")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_applicable_returns_results(populated_db):
    result = json.loads(server.ism_applicable("network encryption", limit=5))
    assert result["count"] >= 1
    ids = [r["identifier"] for r in result["results"]]
    assert "ISM-9001" in ids


def test_applicable_includes_candidates_before_filter(populated_db):
    result = json.loads(server.ism_applicable("network encryption", limit=5))
    assert "candidates_before_filter" in result


def test_applicable_classification_filter(populated_db):
    result = json.loads(server.ism_applicable("audit logging", classification="SECRET", limit=5))
    ids = [r["identifier"] for r in result["results"]]
    assert "ISM-9003" in ids
    for r in result["results"]:
        assert r["applies"]["S"] is True


def test_applicable_empty_after_filter_includes_hint(populated_db):
    result = json.loads(
        server.ism_applicable(
            "anything",
            classification="NC",
            tags=["Audit"],
            limit=5,
        )
    )
    assert result["count"] == 0
    assert "hint" in result


def test_applicable_unknown_classification_returns_error(populated_db):
    result = json.loads(server.ism_applicable("anything", classification="HUSH"))
    assert "error" in result
    assert "classification" in result["error"].lower()


def test_applicable_unknown_tag_returns_error(populated_db):
    result = json.loads(server.ism_applicable("anything", tags=["No-Such-Section"]))
    assert "error" in result


def test_applicable_path_expansion_shows_in_why(populated_db):
    result = json.loads(
        server.ism_applicable("our auth flow", paths=["src/auth/session.py"], limit=5)
    )
    if result["count"] >= 1:
        whys = [w for r in result["results"] for w in r["why"]]
        assert any(w.startswith("path:") for w in whys)


def test_applicable_verbose_includes_excerpt(populated_db):
    result = json.loads(server.ism_applicable("logging events centrally", verbose=True, limit=5))
    found = [r for r in result["results"] if r["identifier"] == "ISM-9003"]
    assert found and "pdf_excerpt" in found[0]
