"""Server-level tests for the lookup tools and the missing-database error path."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from ism_mcp import server, store

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
        published="2026-03-24",
        last_modified=None,
        oscal_version="1.1.2",
        git_tag="v2026.03.24",
        git_commit="x",
        ingested_at="2026-06-04T00:00:00Z",
        control_count=len(sample_controls),
    )
    store.set_active_version(conn, V)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_ism_get_returns_record(populated_db):
    result = server.ism_get("ISM-9001")
    assert result["identifier"] == "ism-9001"
    assert result["applies"]["S"] is True


def test_ism_get_unknown_raises(populated_db):
    with pytest.raises(ToolError, match="no such control"):
        server.ism_get("ism-0000")


def test_ism_search_returns_matches(populated_db):
    result = server.ism_search("encryption")
    assert result["count"] >= 1
    assert any(r["identifier"] == "ism-9001" for r in result["results"])


def test_ism_list_by_classification_filters(populated_db):
    result = server.ism_list_by_classification("S")
    assert result["classification"] == "S"
    assert "ism-9003" in result["identifiers"]


def test_ism_list_by_classification_unknown_raises(populated_db):
    with pytest.raises(ToolError, match="unknown classification"):
        server.ism_list_by_classification("XX")


def test_ism_list_topics(populated_db):
    result = server.ism_list_topics()
    assert "Network encryption" in result["topics"]


def test_ism_list_by_topic(populated_db):
    result = server.ism_list_by_topic("Network encryption")
    assert result["identifiers"] == ["ism-9001"]


def test_ism_stats_reports_active_and_path(populated_db):
    result = server.ism_stats()
    assert result["controls"] == 3
    assert result["active_version"] == V
    assert result["db_path"] == str(populated_db)


def test_missing_database_raises_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEFAULT_DB", tmp_path / "nope.db")
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    server._reset_runtime_cache()
    with pytest.raises(RuntimeError, match="database not found"):
        server.ism_get("ism-9001")
    server._reset_runtime_cache()
