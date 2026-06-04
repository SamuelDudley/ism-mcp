"""Tests for OSCAL ingest orchestration over a directory."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from ism_mcp import ingest, store

FX = Path(__file__).parent / "fixtures" / "oscal"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def oscal_dir(tmp_path: Path) -> Path:
    d = tmp_path / "oscal"
    d.mkdir()
    for f in FX.glob("*.json"):
        shutil.copy(f, d / f.name)
    return d


def test_load_version_from_dir(oscal_dir: Path):
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    assert vmeta.version == "2025.12.9"
    by_id = {c.identifier: c for c in controls}
    assert by_id["ism-0714"].maturity == {"ML1": True, "ML2": True, "ML3": False}


def test_ingest_version_writes_controls_and_registry(db, oscal_dir: Path):
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    ingest.ingest_version(
        db, vmeta, controls, embedder=None, git_tag="v2025.12.9", git_commit="abc"
    )
    assert store.get_active_version(db) == "2025.12.9"
    assert store.count_controls(db) == 3
    version_row = store.get_version(db, "2025.12.9")
    assert version_row is not None
    assert version_row["git_tag"] == "v2025.12.9"


def test_ingest_version_is_idempotent(db, oscal_dir: Path):
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    ingest.ingest_version(db, vmeta, controls)
    ingest.ingest_version(db, vmeta, controls)
    assert store.count_controls(db) == 3
    assert len(store.list_versions(db)) == 1


def test_version_label_humanises():
    assert ingest.version_label("2026.03.24") == "March 2026"
    assert ingest.version_label("2025.12.9") == "December 2025"
