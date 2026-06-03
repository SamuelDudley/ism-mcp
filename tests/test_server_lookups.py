"""Server-level tests for the lookup tools and the missing-database error path."""

from __future__ import annotations

import json

import pytest

from ism_mcp import server, store


@pytest.fixture
def populated_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_ism_get_returns_record(populated_db):
    result = json.loads(server.ism_get("ISM-9001"))
    assert result["identifier"] == "ISM-9001"
    assert result["applies"]["S"] is True


def test_ism_get_unknown_returns_error(populated_db):
    result = json.loads(server.ism_get("ISM-0000"))
    assert "error" in result
    assert "no such control" in result["error"].lower()


def test_ism_search_returns_matches(populated_db):
    result = json.loads(server.ism_search("encryption"))
    assert result["count"] >= 1
    assert any(r["identifier"] == "ISM-9001" for r in result["results"])


def test_ism_list_by_classification_filters(populated_db):
    result = json.loads(server.ism_list_by_classification("S"))
    assert result["classification"] == "S"
    assert "ISM-9003" in result["identifiers"]


def test_ism_list_by_classification_unknown_returns_error(populated_db):
    result = json.loads(server.ism_list_by_classification("XX"))
    assert "error" in result


def test_ism_list_topics(populated_db):
    result = json.loads(server.ism_list_topics())
    assert "Network encryption" in result["topics"]


def test_ism_list_by_topic(populated_db):
    result = json.loads(server.ism_list_by_topic("Network encryption"))
    assert result["identifiers"] == ["ISM-9001"]


def test_ism_stats_reports_counts_and_active_path(populated_db):
    result = json.loads(server.ism_stats())
    assert result["controls"] == 3
    assert result["db_path"] == str(populated_db)


def test_missing_database_raises_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEFAULT_DB", tmp_path / "nope.db")
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    server._reset_runtime_cache()
    with pytest.raises(RuntimeError, match="database not found"):
        server.ism_get("ISM-9001")
    server._reset_runtime_cache()
