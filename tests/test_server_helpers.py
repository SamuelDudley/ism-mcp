"""Helper tools on the MCP server: list_sections, list_classifications, list_maturities."""

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
    return db_path


def test_list_sections_returns_distinct_sorted(populated_db):
    result = json.loads(server.ism_list_sections())
    assert result["sections"] == sorted({"Encryption", "Authentication", "Audit"})
    assert result["count"] == 3


def test_list_classifications_returns_canonical_and_friendly(populated_db):
    result = json.loads(server.ism_list_classifications())
    assert set(result["canonical"]) == {"NC", "OS", "P", "S", "TS"}
    assert "OFFICIAL" in result["friendly"]
    assert "PROTECTED" in result["friendly"]


def test_list_maturities_returns_ml1_through_ml3(populated_db):
    result = json.loads(server.ism_list_maturities())
    assert result["maturities"] == ["ML1", "ML2", "ML3"]
