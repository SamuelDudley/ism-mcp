"""Tests for store.py: insert, get, FTS search, classification filter, meta."""

from __future__ import annotations

import numpy as np
import pytest

from ism_mcp import store


def test_insert_and_get_round_trip(db, sample_controls):
    store.insert_controls(db, sample_controls)
    fetched = store.get_control(db, "ISM-9001")
    assert fetched is not None
    assert fetched.identifier == "ISM-9001"
    assert fetched.description == sample_controls[0].description
    assert fetched.applies == sample_controls[0].applies


def test_get_returns_none_for_missing(db):
    assert store.get_control(db, "ISM-0000") is None


def test_count_controls(db, sample_controls):
    assert store.count_controls(db) == 0
    store.insert_controls(db, sample_controls)
    assert store.count_controls(db) == 3


def test_fts_search_by_keyword(db, sample_controls):
    store.insert_controls(db, sample_controls)
    results = store.search(db, "encryption", limit=10)
    assert [c.identifier for c in results] == ["ISM-9001"]


def test_fts_search_returns_empty_for_no_match(db, sample_controls):
    store.insert_controls(db, sample_controls)
    assert store.search(db, "xyzzy", limit=10) == []


def test_list_by_classification_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    ts = store.list_by_classification(db, "TS")
    assert {c.identifier for c in ts} == {"ISM-9001", "ISM-9003"}
    nc = store.list_by_classification(db, "NC")
    assert {c.identifier for c in nc} == {"ISM-9001", "ISM-9002"}


def test_list_by_classification_rejects_unknown(db):
    with pytest.raises(ValueError, match="unknown classification"):
        store.list_by_classification(db, "XX")


def test_list_topics_and_by_topic(db, sample_controls):
    store.insert_controls(db, sample_controls)
    topics = store.list_topics(db)
    assert "Network encryption" in topics
    network = store.list_by_topic(db, "Network encryption")
    assert [c.identifier for c in network] == ["ISM-9001"]


def test_meta_set_and_get(db):
    store.set_meta(db, "ism_revision", "2026-03")
    assert store.get_meta(db, "ism_revision") == "2026-03"
    store.set_meta(db, "ism_revision", "2026-06")
    assert store.get_meta(db, "ism_revision") == "2026-06"
    assert store.get_meta(db, "missing_key") is None


def test_insert_and_fetch_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = list(db.execute("SELECT rowid, identifier FROM controls ORDER BY rowid"))
    rowid_for = {row["identifier"]: row["rowid"] for row in rows}
    vectors = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    store.insert_embeddings(
        db,
        [
            (rowid_for["ISM-9001"], vectors[0].tobytes()),
            (rowid_for["ISM-9002"], vectors[1].tobytes()),
            (rowid_for["ISM-9003"], vectors[2].tobytes()),
        ],
    )
    matrix, ids = store.load_embedding_matrix(db, dim=4)
    assert matrix.shape == (3, 4)
    assert matrix.dtype == np.float32
    assert set(ids) == set(rowid_for.values())


def test_load_embedding_matrix_returns_empty_when_table_empty(db):
    matrix, ids = store.load_embedding_matrix(db, dim=4)
    assert matrix.shape == (0, 4)
    assert ids == []


def test_reset_drops_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    row = db.execute("SELECT rowid FROM controls LIMIT 1").fetchone()
    store.insert_embeddings(db, [(row["rowid"], (b"\x00" * 16))])
    store.reset(db)
    _matrix, ids = store.load_embedding_matrix(db, dim=4)
    assert ids == []


def test_list_in_scope_filters_by_classification(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(db, classification="NC", maturity=None, sections=None)
    assert {c.identifier for c in rows} == {"ISM-9001", "ISM-9002"}


def test_list_in_scope_filters_by_maturity(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(db, classification="NC", maturity="ML1", sections=None)
    assert {c.identifier for c in rows} == {"ISM-9002"}


def test_list_in_scope_filters_by_sections(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(
        db, classification=None, maturity=None, sections=["Encryption", "Audit"]
    )
    assert {c.identifier for c in rows} == {"ISM-9001", "ISM-9003"}


def test_list_in_scope_combines_all_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(db, classification="TS", maturity="ML3", sections=["Audit"])
    assert {c.identifier for c in rows} == {"ISM-9003"}


def test_list_in_scope_rejects_unknown_classification(db):
    with pytest.raises(ValueError, match="classification"):
        store.list_in_scope(db, classification="XX", maturity=None, sections=None)
