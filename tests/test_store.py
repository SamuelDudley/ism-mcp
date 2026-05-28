"""Tests for store.py: insert, get, FTS search, classification filter, meta."""

from __future__ import annotations

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
