"""End-to-end MCP tool tests for the coverage manifest tools."""

from __future__ import annotations

import json

import pytest

from ism_mcp import server, store

SEED_TOML = """\
schema_version = 1

[scope]
classification = "P"
maturity = "ML2"
sections = ["Encryption", "Audit"]

[project]
name = "demo"

[controls."ISM-9001"]
status = "covered"
how_met = "Network is encrypted."
last_reviewed = 2026-05-28
files = ["src/net.py:1-20"]
"""


@pytest.fixture
def project_with_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / ".ism-coverage.toml"
    manifest.write_text(SEED_TOML)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def project_with_ism_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "none")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_coverage_read_returns_parsed_manifest(project_with_manifest, project_with_ism_db):
    result = json.loads(server.ism_coverage_read())
    assert result["scope"]["classification"] == "P"
    assert result["scope"]["maturity"] == "ML2"
    assert result["project"]["name"] == "demo"
    assert "ISM-9001" in result["controls"]
    assert result["controls"]["ISM-9001"]["status"] == "covered"
    assert result["controls"]["ISM-9001"]["last_reviewed"] == "2026-05-28"
    assert result["summary"] == {
        "total_curated": 1,
        "covered": 1,
        "partial": 0,
        "not_applicable": 0,
        "deferred": 0,
    }


def test_coverage_read_returns_error_when_missing(tmp_path, monkeypatch, project_with_ism_db):
    monkeypatch.chdir(tmp_path)
    result = json.loads(server.ism_coverage_read())
    assert "error" in result
    assert "no manifest" in result["error"].lower()


def test_coverage_read_status_filter(project_with_manifest, project_with_ism_db):
    result = json.loads(server.ism_coverage_read(status_filter="covered"))
    assert list(result["controls"].keys()) == ["ISM-9001"]
    result = json.loads(server.ism_coverage_read(status_filter="partial"))
    assert result["controls"] == {}


def test_coverage_read_warns_about_identifier_not_in_ism(
    tmp_path, monkeypatch, project_with_ism_db
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ism-coverage.toml").write_text(
        SEED_TOML
        + '\n[controls."ISM-7777"]\nstatus = "covered"\nhow_met = "x"\nlast_reviewed = 2026-05-28\n'
    )
    result = json.loads(server.ism_coverage_read())
    assert any("ISM-7777" in w for w in result["warnings"])
