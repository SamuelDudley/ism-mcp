"""Tests for the OSCAL git fetch helper against a local source repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ism_mcp import fetch


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "ISM_catalog.json").write_text('{"v": 1}')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "v1")
    _git(repo, "tag", "v2025.12.9")
    (repo / "ISM_catalog.json").write_text('{"v": 2}')
    _git(repo, "commit", "-aqm", "v2")
    _git(repo, "tag", "v2026.03.24")
    return repo


def test_ensure_clone_then_list_tags(source_repo: Path, tmp_path: Path):
    cache = tmp_path / "cache"
    repo_dir = fetch.ensure_clone(repo=str(source_repo), cache=cache)
    assert repo_dir.is_dir()
    tags = fetch.list_tags(repo_dir)
    assert tags == ["v2025.12.9", "v2026.03.24"]


def test_read_file_at_tag(source_repo: Path, tmp_path: Path):
    repo_dir = fetch.ensure_clone(repo=str(source_repo), cache=tmp_path / "cache")
    assert fetch.read_file_at_tag(repo_dir, "v2025.12.9", "ISM_catalog.json") == '{"v": 1}'
    assert fetch.read_file_at_tag(repo_dir, "v2026.03.24", "ISM_catalog.json") == '{"v": 2}'


def test_ensure_clone_is_idempotent(source_repo: Path, tmp_path: Path):
    cache = tmp_path / "cache"
    first = fetch.ensure_clone(repo=str(source_repo), cache=cache)
    second = fetch.ensure_clone(repo=str(source_repo), cache=cache)
    assert first == second
    assert fetch.list_tags(second) == ["v2025.12.9", "v2026.03.24"]


def test_missing_file_at_tag_raises(source_repo: Path, tmp_path: Path):
    repo_dir = fetch.ensure_clone(repo=str(source_repo), cache=tmp_path / "cache")
    with pytest.raises(fetch.GitError):
        fetch.read_file_at_tag(repo_dir, "v2025.12.9", "does_not_exist.json")
