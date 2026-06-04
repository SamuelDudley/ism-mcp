"""Guard against opening a database written by an older, incompatible schema."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from ism_mcp import __main__ as cli
from ism_mcp import store

FX = Path(__file__).parent / "fixtures" / "oscal"


def _write_old_schema_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE controls (identifier TEXT PRIMARY KEY, description TEXT NOT NULL);"
    )
    conn.execute("INSERT INTO controls VALUES ('ISM-0001', 'legacy row')")
    conn.commit()
    conn.close()


def test_open_db_rejects_incompatible_old_schema(tmp_path):
    db = tmp_path / "old.db"
    _write_old_schema_db(db)
    with pytest.raises(store.IncompatibleSchemaError, match="incompatible older schema"):
        store.open_db(db)


def test_open_db_accepts_fresh_database(tmp_path):
    db = tmp_path / "new.db"
    conn = store.open_db(db)
    assert "version" in {r["name"] for r in conn.execute("PRAGMA table_info(controls)")}
    conn.close()


def test_ingest_fresh_rebuilds_over_old_schema(tmp_path):
    db = tmp_path / "ism.db"
    _write_old_schema_db(db)
    oscal_dir = tmp_path / "oscal"
    oscal_dir.mkdir()
    for f in FX.glob("*.json"):
        shutil.copy(f, oscal_dir / f.name)

    rc = cli.main(
        ["ingest", "--oscal", str(oscal_dir), "--db", str(db), "--fresh", "--no-embeddings"]
    )
    assert rc == 0
    conn = store.open_db(db)
    assert store.get_active_version(conn) == "2025.12.9"
    assert store.count_controls(conn) == 3
    conn.close()
