"""Server tests for ism_versions, ism_stats, version params, ism_diff, ism_history."""

from __future__ import annotations

import json

import pytest

from ism_mcp import server, store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls


def _point_server_at(monkeypatch, db_path):
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "hash")
    server._reset_runtime_cache()


@pytest.fixture
def two_version_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    new = sample_controls
    old = [store.Control(**{**c.as_dict(), "version": "2025.12.9"}) for c in sample_controls[:2]]
    store.insert_controls(conn, old)
    store.insert_controls(conn, new)
    for ver, label, count in [("2025.12.9", "December 2025", 2), ("2026.03.24", "March 2026", 3)]:
        store.upsert_version(
            conn,
            version=ver,
            label=label,
            published=ver.replace(".", "-"),
            last_modified=None,
            oscal_version="1.1.2",
            git_tag=f"v{ver}",
            git_commit="x",
            ingested_at="2026-06-04T00:00:00Z",
            control_count=count,
        )
    store.set_active_version(conn, "2026.03.24")
    rows = [
        ("2026.03.24", i, b) for i, b in embed_controls(new, DeterministicHashEmbedder(dim=384))
    ]
    store.insert_embeddings(conn, rows)
    conn.close()
    _point_server_at(monkeypatch, db_path)
    yield db_path
    server._reset_runtime_cache()


@pytest.fixture
def single_version_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    store.upsert_version(
        conn,
        version="2026.03.24",
        label="March 2026",
        published=None,
        last_modified=None,
        oscal_version="1.1.2",
        git_tag=None,
        git_commit=None,
        ingested_at="2026-06-04T00:00:00Z",
        control_count=len(sample_controls),
    )
    store.set_active_version(conn, "2026.03.24")
    conn.close()
    _point_server_at(monkeypatch, db_path)
    yield db_path
    server._reset_runtime_cache()


def test_ism_versions_lists_active_first(two_version_db):
    out = json.loads(server.ism_versions())
    assert out["active"] == "2026.03.24"
    assert out["count"] == 2
    assert out["versions"][0]["version"] == "2026.03.24"
    assert out["versions"][0]["is_active"] is True


def test_ism_stats_reports_active_version(two_version_db):
    out = json.loads(server.ism_stats())
    assert out["active_version"] == "2026.03.24"
    assert out["versions"] == 2
    assert out["controls"] == 3


def test_ism_get_defaults_to_active_and_accepts_version(two_version_db):
    active = json.loads(server.ism_get("ism-9003"))
    assert active["version"] == "2026.03.24"
    missing = json.loads(server.ism_get("ism-9003", version="2025.12.9"))
    assert "error" in missing


def test_ism_get_tolerant_identifier(two_version_db):
    out = json.loads(server.ism_get("ISM-9001"))
    assert out["identifier"] == "ism-9001"


def test_ism_diff_defaults_to_latest_vs_previous(two_version_db):
    out = json.loads(server.ism_diff())
    assert out["from"] == "2025.12.9"
    assert out["to"] == "2026.03.24"
    # ism-9003 exists only in the active (new) version per the fixture:
    assert "ism-9003" in {c["identifier"] for c in out["changes"]["added"]}


def test_ism_diff_explicit_versions_and_unknown(two_version_db):
    bad = json.loads(server.ism_diff(from_version="9999.99.99", to_version="2026.03.24"))
    assert "error" in bad


def test_ism_history_timeline(two_version_db):
    out = json.loads(server.ism_history("ism-9001"))
    assert out["identifier"] == "ism-9001"
    assert [t["version"] for t in out["timeline"]] == ["2025.12.9", "2026.03.24"]


def test_ism_diff_single_version_errors(single_version_db):
    out = json.loads(server.ism_diff())
    assert "error" in out
