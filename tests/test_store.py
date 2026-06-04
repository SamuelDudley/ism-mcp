"""Tests for store.py: insert, get, FTS search, classification filter, meta, versions."""

from __future__ import annotations

import numpy as np
import pytest

from ism_mcp import store

V = "2026.03.24"


def _activate(db):
    store.set_active_version(db, V)


def test_insert_and_get_round_trip(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    fetched = store.get_control(db, "ism-9001")
    assert fetched is not None
    assert fetched.identifier == "ism-9001"
    assert fetched.description == sample_controls[0].description
    assert fetched.applies == sample_controls[0].applies
    assert fetched.version == V


def test_get_returns_none_for_missing(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    assert store.get_control(db, "ism-0000") is None


def test_get_control_tolerant_identifier_forms(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    for raw in ("ISM-9001", "ism-9001", "9001"):
        c = store.get_control(db, raw)
        assert c is not None and c.identifier == "ism-9001"


def test_count_controls(db, sample_controls):
    _activate(db)
    assert store.count_controls(db) == 0
    store.insert_controls(db, sample_controls)
    assert store.count_controls(db) == 3


def test_fts_search_by_keyword(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    results = store.search(db, "encryption", limit=10)
    assert [c.identifier for c in results] == ["ism-9001"]


def test_search_tolerates_fts_metacharacters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    results = store.search(db, "network: encryption")
    assert [c.identifier for c in results] == ["ism-9001"]


def test_search_does_not_raise_on_operator_soup(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    for query in ["rate AND OR limit", "(unbalanced", "* prefix", "NEAR(x", "C:\\path"]:
        assert isinstance(store.search(db, query), list)


def test_list_by_classification_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    ts = store.list_by_classification(db, "TS")
    assert {c.identifier for c in ts} == {"ism-9001", "ism-9003"}
    nc = store.list_by_classification(db, "NC")
    assert {c.identifier for c in nc} == {"ism-9001", "ism-9002"}


def test_list_topics_and_by_topic(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    assert "Network encryption" in store.list_topics(db)
    network = store.list_by_topic(db, "Network encryption")
    assert [c.identifier for c in network] == ["ism-9001"]


def test_queries_scope_to_a_version(db, sample_controls):
    store.insert_controls(db, sample_controls)
    older = [store.Control(**{**c.as_dict(), "version": "2025.12.9"}) for c in sample_controls[:1]]
    store.insert_controls(db, older)
    store.set_active_version(db, V)
    assert store.count_controls(db) == 3
    assert store.count_controls(db, version="2025.12.9") == 1
    assert store.get_control(db, "ism-9002", version="2025.12.9") is None


def test_meta_set_and_get(db):
    store.set_meta(db, "active_version", "2026.03")
    assert store.get_meta(db, "active_version") == "2026.03"
    assert store.get_meta(db, "missing_key") is None


def test_insert_and_fetch_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    vectors = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]], dtype=np.float32)
    store.insert_embeddings(
        db,
        [
            (V, "ism-9001", vectors[0].tobytes()),
            (V, "ism-9002", vectors[1].tobytes()),
            (V, "ism-9003", vectors[2].tobytes()),
        ],
    )
    matrix, ids = store.load_embedding_matrix(db, dim=4, version=V)
    assert matrix.shape == (3, 4)
    assert matrix.dtype == np.float32
    assert ids == ["ism-9001", "ism-9002", "ism-9003"]


def test_load_embedding_matrix_empty(db):
    matrix, ids = store.load_embedding_matrix(db, dim=4, version=V)
    assert matrix.shape == (0, 4)
    assert ids == []


def test_delete_version_drops_controls_and_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    store.insert_embeddings(db, [(V, "ism-9001", (b"\x00" * 16))])
    store.upsert_version(
        db,
        version=V,
        label="March 2026",
        published=None,
        last_modified=None,
        oscal_version=None,
        git_tag=None,
        git_commit=None,
        ingested_at="2026-06-04T00:00:00Z",
        control_count=3,
    )
    store.delete_version(db, V)
    store.set_active_version(db, V)
    assert store.count_controls(db) == 0
    assert store.load_embedding_matrix(db, dim=4, version=V)[1] == []
    assert store.search(db, "encryption", limit=10) == []


def test_list_in_scope_combines_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    rows = store.list_in_scope(db, classification="TS", maturity="ML3", sections=["Audit"])
    assert {c.identifier for c in rows} == {"ism-9003"}


def test_list_in_scope_rejects_unknown_classification(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    with pytest.raises(ValueError, match="classification"):
        store.list_in_scope(db, classification="XX", maturity=None, sections=None)
