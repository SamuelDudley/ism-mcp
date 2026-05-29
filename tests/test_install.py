"""Install orchestration: the four writes, dry run, and idempotency."""

from __future__ import annotations

import json

import pytest

from ism_mcp import install

UVX = dict(mode="uvx", repo="https://example/ism-mcp", rev="abc1234")


def _repo_with_db(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    db_src = tmp_path / "ism.db"
    db_src.write_bytes(b"SQLite format 3\x00")
    return project, db_src


def test_install_writes_all_four_artifacts(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    install.install(project=project, db_src=db_src, **UVX)
    data = json.loads((project / ".mcp.json").read_text())
    assert data["mcpServers"]["ism"]["command"] == "uvx"
    assert (project / "CLAUDE.md").read_text().count(install.MARKER_BEGIN) == 1
    assert (project / ".ism-coverage.toml").is_file()
    assert (project / ".ism" / "ism.db").read_bytes() == b"SQLite format 3\x00"


def test_install_errors_when_source_db_missing(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    with pytest.raises(FileNotFoundError):
        install.install(project=project, db_src=tmp_path / "nope.db", **UVX)


def test_install_keeps_existing_manifest(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    (project / ".ism-coverage.toml").write_text("# my real evidence\n")
    install.install(project=project, db_src=db_src, **UVX)
    assert "# my real evidence" in (project / ".ism-coverage.toml").read_text()


def test_install_dry_run_writes_nothing(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    actions = install.install(project=project, db_src=db_src, dry_run=True, **UVX)
    assert not (project / ".mcp.json").exists()
    assert not (project / ".ism").exists()
    assert len(actions) == 4


def test_install_is_idempotent(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    install.install(project=project, db_src=db_src, **UVX)
    targets = [
        project / ".mcp.json",
        project / "CLAUDE.md",
        project / ".ism-coverage.toml",
        project / ".ism" / "ism.db",
    ]
    snapshot = {p: p.read_bytes() for p in targets}
    install.install(project=project, db_src=db_src, **UVX)
    for p, data in snapshot.items():
        assert p.read_bytes() == data
