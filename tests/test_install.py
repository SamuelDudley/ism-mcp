"""Install orchestration: the four writes, dry run, and idempotency."""

from __future__ import annotations

import argparse
import json
from typing import TypedDict

import pytest

from ism_mcp import __main__ as cli
from ism_mcp import install


class _Uvx(TypedDict):
    mode: str
    repo: str
    rev: str


UVX: _Uvx = {"mode": "uvx", "repo": "https://example/ism-mcp", "rev": "abc1234"}


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


def _args(**kw):
    base = dict(
        project=None,
        mode="uvx",
        repo="https://example/ism-mcp",
        rev="abc1234",
        image=None,
        db=None,
        name="ism",
        dry_run=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_cmd_install_returns_zero_and_writes(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    rc = cli.cmd_install(_args(project=str(project), db=str(db_src)))
    assert rc == 0
    assert (project / ".mcp.json").is_file()


def test_cmd_install_rejects_missing_project(tmp_path):
    rc = cli.cmd_install(_args(project=str(tmp_path / "absent"), db="x"))
    assert rc == 1


def test_cmd_install_uvx_without_repo_errors(tmp_path, monkeypatch):
    project, db_src = _repo_with_db(tmp_path)
    monkeypatch.setattr(cli, "_git_in_package", lambda *a: None)
    rc = cli.cmd_install(_args(project=str(project), db=str(db_src), repo=None))
    assert rc == 1


def test_cmd_install_docker_without_image_errors(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    rc = cli.cmd_install(_args(project=str(project), db=str(db_src), mode="docker", image=None))
    assert rc == 1
