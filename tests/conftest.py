"""Shared pytest fixtures for ism-mcp tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from ism_mcp import store


@pytest.fixture
def db() -> Generator[sqlite3.Connection, None, None]:
    """An empty in-memory SQLite database with the ism-mcp schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def sample_controls() -> list[store.Control]:
    """A small set of synthetic controls covering the schema's optional fields."""
    return [
        store.Control(
            identifier="ISM-9001",
            guideline="Guidelines for testing",
            section="Encryption",
            topic="Network encryption",
            revision="1",
            updated="May-26",
            description="All data communicated over network infrastructure is encrypted.",
            applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": False},
        ),
        store.Control(
            identifier="ISM-9002",
            guideline="Guidelines for testing",
            section="Authentication",
            topic="Session management",
            revision="2",
            updated="Jun-26",
            description="Sessions are terminated after fifteen minutes of inactivity.",
            applies={"NC": True, "OS": True, "P": True, "S": False, "TS": False},
            maturity={"ML1": True, "ML2": True, "ML3": True},
        ),
        store.Control(
            identifier="ISM-9003",
            guideline="Guidelines for testing",
            section="Audit",
            topic="Event logging",
            revision="1",
            updated="May-26",
            description="Events are logged to a centralised facility.",
            applies={"NC": False, "OS": False, "P": False, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": True},
            pdf_excerpt="Centralised event logging is required for all SECRET workloads.",
            pdf_page=42,
        ),
    ]
