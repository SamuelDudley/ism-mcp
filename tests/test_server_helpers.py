"""Helper tools on the MCP server: list_sections, list_classifications, list_maturities."""

from __future__ import annotations

import pytest

from ism_mcp import server, store


@pytest.fixture
def populated_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    store.set_active_version(conn, sample_controls[0].version)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_list_sections_returns_distinct_sorted(populated_db):
    result = server.ism_list_sections()
    assert result["sections"] == sorted({"Encryption", "Authentication", "Audit"})
    assert result["count"] == 3


def test_list_classifications_returns_canonical_and_friendly(populated_db):
    result = server.ism_list_classifications()
    assert set(result["canonical"]) == {"NC", "OS", "P", "S", "TS"}
    assert "OFFICIAL" in result["friendly"]
    assert "PROTECTED" in result["friendly"]


def test_list_maturities_returns_ml1_through_ml3(populated_db):
    result = server.ism_list_maturities()
    assert result["maturities"] == ["ML1", "ML2", "ML3"]


def test_clamp_limit_bounds_range():
    assert server._clamp_limit(-5) == 1
    assert server._clamp_limit(0) == 1
    assert server._clamp_limit(5) == 5
    assert server._clamp_limit(10_000) == server.MAX_LIMIT


def test_active_db_reflects_runtime_env(tmp_path, monkeypatch):
    custom = tmp_path / "custom.db"
    monkeypatch.setenv("ISM_MCP_DB", str(custom))
    assert server._active_db() == custom


def test_conn_is_cached_and_reset_clears(populated_db):
    server._reset_runtime_cache()
    first = server._conn()
    assert server._conn() is first
    server._reset_runtime_cache()
    assert server._conn() is not first
