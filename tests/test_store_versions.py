"""Tests for the versions registry and active-version pointer in store.py."""

from __future__ import annotations

import sqlite3

import pytest

from ism_mcp import store


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    yield conn
    conn.close()


def test_schema_has_versions_table(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(versions)")}
    assert {"version", "label", "published", "oscal_version", "git_tag", "control_count"} <= cols


def test_controls_primary_key_is_version_and_identifier(db):
    pk = [r["name"] for r in db.execute("PRAGMA table_info(controls)") if r["pk"]]
    assert pk == ["version", "identifier"]


def test_upsert_and_list_versions(db):
    store.upsert_version(
        db,
        version="2025.12.9",
        label="December 2025",
        published="2025-12-09",
        last_modified="2025-12-09",
        oscal_version="1.1.2",
        git_tag="v2025.12.9",
        git_commit="abc",
        ingested_at="2026-06-04T00:00:00Z",
        control_count=2,
    )
    store.upsert_version(
        db,
        version="2026.03.24",
        label="March 2026",
        published="2026-03-24",
        last_modified="2026-03-24",
        oscal_version="1.1.2",
        git_tag="v2026.03.24",
        git_commit="def",
        ingested_at="2026-06-04T00:00:00Z",
        control_count=3,
    )
    versions = store.list_versions(db)
    assert [v["version"] for v in versions] == ["2026.03.24", "2025.12.9"]
    dec = store.get_version(db, "2025.12.9")
    assert dec is not None and dec["control_count"] == 2


def test_upsert_version_replaces_existing(db):
    for count in (2, 5):
        store.upsert_version(
            db,
            version="2025.12.9",
            label="December 2025",
            published="2025-12-09",
            last_modified="2025-12-09",
            oscal_version="1.1.2",
            git_tag=None,
            git_commit=None,
            ingested_at="2026-06-04T00:00:00Z",
            control_count=count,
        )
    updated = store.get_version(db, "2025.12.9")
    assert updated is not None and updated["control_count"] == 5
    assert len(store.list_versions(db)) == 1


def test_active_version_round_trip(db):
    assert store.get_active_version(db) is None
    store.set_active_version(db, "2026.03.24")
    assert store.get_active_version(db) == "2026.03.24"
