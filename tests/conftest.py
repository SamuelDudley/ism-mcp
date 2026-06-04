"""Shared pytest fixtures for ism-mcp tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from ism_mcp import store


@pytest.fixture
def db() -> Generator[sqlite3.Connection]:
    """An empty in-memory SQLite database with the ism-mcp schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def sample_controls() -> list[store.Control]:
    """A small set of synthetic controls covering the schema's optional fields."""
    v = "2026.03.24"
    return [
        store.Control(
            version=v,
            identifier="ism-9001",
            label="9001",
            title="Control: ism-9001",
            control_class="ISM-control",
            guideline="Guidelines for testing",
            section="Encryption",
            topic="Network encryption",
            control_revision="1",
            updated="May-26",
            sort_id="catalog[1].group[01].control[1]",
            description="All data communicated over network infrastructure is encrypted.",
            applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": False},
        ),
        store.Control(
            version=v,
            identifier="ism-9002",
            label="9002",
            title="Control: ism-9002",
            control_class="ISM-control",
            guideline="Guidelines for testing",
            section="Authentication",
            topic="Session management",
            control_revision="2",
            updated="Jun-26",
            sort_id="catalog[1].group[02].control[1]",
            description="Sessions are terminated after fifteen minutes of inactivity.",
            applies={"NC": True, "OS": True, "P": True, "S": False, "TS": False},
            maturity={"ML1": True, "ML2": True, "ML3": True},
        ),
        store.Control(
            version=v,
            identifier="ism-9003",
            label="9003",
            title="Control: ism-9003",
            control_class="ISM-control",
            guideline="Guidelines for testing",
            section="Audit",
            topic="Event logging",
            control_revision="1",
            updated="May-26",
            sort_id="catalog[1].group[03].control[1]",
            description="Events are logged to a centralised facility.",
            applies={"NC": False, "OS": False, "P": False, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": True},
        ),
    ]
