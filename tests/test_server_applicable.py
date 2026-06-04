"""End-to-end tests for ism_applicable with the deterministic hash embedder."""

from __future__ import annotations

import json

import pytest

from ism_mcp import server, store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls

V = "2026.03.24"


@pytest.fixture
def populated_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    store.upsert_version(
        conn,
        version=V,
        label="March 2026",
        published=None,
        last_modified=None,
        oscal_version="1.1.2",
        git_tag=None,
        git_commit=None,
        ingested_at="2026-06-04T00:00:00Z",
        control_count=len(sample_controls),
    )
    store.set_active_version(conn, V)
    embedder = DeterministicHashEmbedder(dim=384)
    rows = [(V, ident, blob) for ident, blob in embed_controls(sample_controls, embedder)]
    store.insert_embeddings(conn, rows)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "hash")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_applicable_returns_results(populated_db):
    result = json.loads(server.ism_applicable("network encryption", limit=5))
    assert result["count"] >= 1
    ids = [r["identifier"] for r in result["results"]]
    assert "ism-9001" in ids


def test_applicable_includes_candidates_before_filter(populated_db):
    result = json.loads(server.ism_applicable("network encryption", limit=5))
    assert "candidates_before_filter" in result


def test_applicable_classification_filter(populated_db):
    result = json.loads(server.ism_applicable("audit logging", classification="SECRET", limit=5))
    ids = [r["identifier"] for r in result["results"]]
    assert "ism-9003" in ids
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
        server.ism_applicable("session inactivity", paths=["src/auth/session.py"], limit=5)
    )
    assert result["count"] >= 1
    whys = [w for r in result["results"] for w in r["why"]]
    assert any(w.startswith("path:") for w in whys)


def test_applicable_maturity_filter(populated_db):
    result = json.loads(server.ism_applicable("logging events", maturity="ML3", limit=5))
    ids = [r["identifier"] for r in result["results"]]
    assert "ism-9003" in ids
    for r in result["results"]:
        assert r["maturity"]["ML3"] is True


def test_materialise_semantic_tag_only_on_actual_semantic_ids(db, sample_controls):
    store.insert_controls(db, sample_controls)
    store.set_active_version(db, V)
    fused = [("ism-9001", 0.9), ("ism-9002", 0.5), ("ism-9003", 0.1)]
    out = server._materialise(
        db,
        fused,
        lex_ids={"ism-9001", "ism-9002"},
        sem_ids={"ism-9002", "ism-9003"},
        path_keywords={},
        semantic_used=True,
    )
    why = {m["row"]["identifier"]: m["why"] for m in out}
    assert why["ism-9001"] == ["lexical"]
    assert set(why["ism-9002"]) == {"semantic", "lexical"}
    assert why["ism-9003"] == ["semantic"]


def test_materialise_no_semantic_tag_when_semantic_unused(db, sample_controls):
    store.insert_controls(db, sample_controls)
    store.set_active_version(db, V)
    out = server._materialise(
        db,
        [("ism-9001", 0.9)],
        lex_ids={"ism-9001"},
        sem_ids=set(),
        path_keywords={},
        semantic_used=False,
    )
    assert out[0]["why"] == ["lexical"]


def test_materialise_path_token_only_when_text_matches(db, sample_controls):
    store.insert_controls(db, sample_controls)
    store.set_active_version(db, V)
    out = server._materialise(
        db,
        [("ism-9001", 0.9), ("ism-9002", 0.5)],
        lex_ids={"ism-9001", "ism-9002"},
        sem_ids=set(),
        path_keywords={"session": {"session", "timeout"}},
        semantic_used=False,
    )
    why = {m["row"]["identifier"]: m["why"] for m in out}
    assert "path:session" in why["ism-9002"]
    assert "path:session" not in why["ism-9001"]


def test_applicable_verbose_includes_guideline(populated_db):
    result = json.loads(server.ism_applicable("logging events centrally", verbose=True, limit=5))
    found = [r for r in result["results"] if r["identifier"] == "ism-9003"]
    assert found and "guideline" in found[0]
