"""End-to-end MCP tool tests for the coverage manifest tools."""

from __future__ import annotations

import json

import pytest

from ism_mcp import server, store

V = "2026.03.24"

SEED_TOML = """\
schema_version = 1

[scope]
classification = "S"
sections = ["Encryption", "Audit"]
baseline_version = "2026.03.24"

[project]
name = "demo"

[controls."ism-9001"]
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
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "none")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_coverage_read_returns_parsed_manifest(project_with_manifest, project_with_ism_db):
    result = json.loads(server.ism_coverage_read())
    assert result["scope"]["classification"] == "S"
    assert result["scope"]["sections"] == ["Encryption", "Audit"]
    assert result["project"]["name"] == "demo"
    assert "ism-9001" in result["controls"]
    assert result["controls"]["ism-9001"]["status"] == "covered"
    assert result["controls"]["ism-9001"]["last_reviewed"] == "2026-05-28"
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
    assert list(result["controls"].keys()) == ["ism-9001"]
    result = json.loads(server.ism_coverage_read(status_filter="partial"))
    assert result["controls"] == {}


def test_coverage_read_warns_about_identifier_not_in_ism(
    tmp_path, monkeypatch, project_with_ism_db
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ism-coverage.toml").write_text(
        SEED_TOML
        + '\n[controls."ism-7777"]\nstatus = "covered"\nhow_met = "x"\nlast_reviewed = 2026-05-28\n'
    )
    result = json.loads(server.ism_coverage_read())
    assert any("ism-7777" in w for w in result["warnings"])


def test_coverage_upsert_creates_entry(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ism-9002",
            status="covered",
            how_met="Sessions terminate after 14 min.",
            files=["src/auth.py:1-20"],
        )
    )
    assert result["ok"] is True
    assert result["action"] == "created"
    parsed = json.loads(server.ism_coverage_read())
    assert "ism-9002" in parsed["controls"]


def test_coverage_upsert_updates_existing_entry(project_with_manifest, project_with_ism_db):
    server.ism_coverage_upsert(
        identifier="ism-9001",
        status="partial",
        how_met="Now partial.",
    )
    parsed = json.loads(server.ism_coverage_read())
    assert parsed["controls"]["ism-9001"]["status"] == "partial"


def test_coverage_upsert_rejects_unknown_identifier(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ism-9999",
            status="covered",
            how_met="x",
        )
    )
    assert "error" in result
    assert "no such control" in result["error"].lower()


def test_coverage_upsert_rejects_invalid_status(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ism-9002",
            status="bogus",
            how_met="x",
        )
    )
    assert "error" in result
    assert "status" in result["error"].lower()


def test_coverage_upsert_rejects_missing_attachment(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ism-9002",
            status="covered",
            how_met="x",
            attachments=[{"path": "nope.png", "description": "x"}],
        )
    )
    assert "error" in result
    assert "nope.png" in result["error"]


def test_coverage_upsert_defaults_last_reviewed_to_today(
    project_with_manifest, project_with_ism_db
):
    from datetime import date as _date

    server.ism_coverage_upsert(
        identifier="ism-9002",
        status="covered",
        how_met="x",
    )
    parsed = json.loads(server.ism_coverage_read())
    assert parsed["controls"]["ism-9002"]["last_reviewed"] == _date.today().isoformat()


def test_coverage_upsert_warns_out_of_scope(project_with_manifest, project_with_ism_db):
    # ism-9002 is section 'Authentication' which is not in scope.sections = ["Encryption", "Audit"].
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ism-9002",
            status="covered",
            how_met="x",
        )
    )
    assert result["ok"] is True
    assert any("scope" in w.lower() for w in result["warnings"])


def test_coverage_gaps_without_work_lists_outstanding_in_scope(
    project_with_manifest, project_with_ism_db
):
    result = json.loads(server.ism_coverage_gaps())
    ids = [g["identifier"] for g in result["gaps"]]
    assert "ism-9003" in ids
    assert "ism-9001" not in ids  # covered
    assert "ism-9002" not in ids  # out of scope


def test_coverage_gaps_with_work_intersects_with_applicable(
    project_with_manifest, project_with_ism_db
):
    result = json.loads(server.ism_coverage_gaps(work="event logging"))
    ids = [g["identifier"] for g in result["gaps"]]
    assert "ism-9003" in ids
    g = next(g for g in result["gaps"] if g["identifier"] == "ism-9003")
    assert "score" in g
    assert "why" in g


def test_coverage_gaps_returns_error_when_manifest_missing(
    tmp_path, monkeypatch, project_with_ism_db
):
    monkeypatch.chdir(tmp_path)
    result = json.loads(server.ism_coverage_gaps())
    assert "error" in result


def test_coverage_gaps_limit_truncates(project_with_manifest, project_with_ism_db):
    result = json.loads(server.ism_coverage_gaps(limit=1))
    assert len(result["gaps"]) <= 1


def test_coverage_upsert_surfaces_sibling_attachment_warning(
    tmp_path, monkeypatch, project_with_ism_db
):
    (tmp_path / ".ism-coverage.toml").write_text(
        SEED_TOML + '\n[[controls."ism-9001".attachments]]\n'
        'path = ".ism-coverage/evidence/missing.png"\n'
        'description = "screenshot"\n'
    )
    monkeypatch.chdir(tmp_path)
    result = json.loads(
        server.ism_coverage_upsert(identifier="ism-9002", status="covered", how_met="x")
    )
    assert result["ok"] is True
    assert any("missing.png" in w for w in result["warnings"]), result["warnings"]


def test_upsert_stamps_reviewed_against_active_version(project_with_manifest, project_with_ism_db):
    out = json.loads(server.ism_coverage_upsert("ism-9002", "covered", "done"))
    assert out["ok"] is True
    read = json.loads(server.ism_coverage_read())
    assert read["controls"]["ism-9002"]["reviewed_against"] == V


def test_coverage_impact_reports_new_uncovered(project_with_manifest, project_with_ism_db):
    out = json.loads(server.ism_coverage_impact())
    assert out["target_version"] == V
    assert "summary" in out
    assert "ism-9003" in {e["identifier"] for e in out["new_uncovered"]}


UPPER_SEED = """\
schema_version = 1

[scope]
classification = "S"
sections = ["Encryption", "Audit"]
baseline_version = "2026.03.24"

[controls."ISM-9001"]
status = "covered"
how_met = "Network is encrypted."
last_reviewed = 2026-05-28
"""


def test_gaps_handles_uppercase_manifest_keys(tmp_path, monkeypatch, project_with_ism_db):
    # XLSX-era manifest keys (ISM-9001) must still register as covered against lowercase ids.
    (tmp_path / ".ism-coverage.toml").write_text(UPPER_SEED)
    monkeypatch.chdir(tmp_path)
    result = json.loads(server.ism_coverage_gaps())
    ids = [g["identifier"] for g in result["gaps"]]
    assert "ism-9001" not in ids
    assert "ism-9003" in ids


def test_impact_handles_uppercase_manifest_keys(tmp_path, monkeypatch, project_with_ism_db):
    (tmp_path / ".ism-coverage.toml").write_text(UPPER_SEED)
    monkeypatch.chdir(tmp_path)
    out = json.loads(server.ism_coverage_impact())
    assert "ism-9001" not in {e["identifier"] for e in out["new_uncovered"]}
