"""CLI orchestration: fetch, ingest, ingest-history subcommands."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ism_mcp import __main__ as cli
from ism_mcp import store

FX = Path(__file__).parent / "fixtures" / "oscal"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def oscal_dir(tmp_path: Path) -> Path:
    d = tmp_path / "oscal"
    d.mkdir()
    for f in FX.glob("*.json"):
        shutil.copy(f, d / f.name)
    return d


@pytest.fixture
def history_repo(tmp_path: Path, oscal_dir: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(oscal_dir, repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "dec")
    _git(repo, "tag", "v2025.12.9")
    catalog = (repo / "ISM_catalog.json").read_text().replace("2025.12.9", "2026.03.24")
    (repo / "ISM_catalog.json").write_text(catalog)
    _git(repo, "commit", "-aqm", "mar")
    _git(repo, "tag", "v2026.03.24")
    return repo


def test_ingest_one_version(oscal_dir: Path, tmp_path: Path):
    db = tmp_path / "ism.db"
    rc = cli.main(["ingest", "--oscal", str(oscal_dir), "--db", str(db), "--no-embeddings"])
    assert rc == 0
    conn = store.open_db(db)
    assert store.get_active_version(conn) == "2025.12.9"
    assert store.count_controls(conn) == 3
    conn.close()


def test_ingest_history_walks_tags(history_repo: Path, tmp_path: Path):
    db = tmp_path / "ism.db"
    rc = cli.main(
        ["ingest-history", "--oscal-repo", str(history_repo), "--db", str(db), "--no-embeddings"]
    )
    assert rc == 0
    conn = store.open_db(db)
    assert {v["version"] for v in store.list_versions(conn)} == {"2025.12.9", "2026.03.24"}
    assert store.get_active_version(conn) == "2026.03.24"
    conn.close()
