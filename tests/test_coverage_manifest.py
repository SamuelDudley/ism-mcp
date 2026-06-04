"""Dataclasses and basic schema for the coverage manifest."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from ism_mcp.coverage import Manifest, ManifestEntry


def test_manifest_entry_minimal_fields():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="Sessions terminate after 14 min.",
        last_reviewed=date(2026, 5, 28),
    )
    assert entry.identifier == "ISM-0428"
    assert entry.status == "covered"
    assert entry.files == []
    assert entry.commits == []
    assert entry.urls == []
    assert entry.attachments == []
    assert entry.reviewed_by is None
    assert entry.next_review is None


def test_manifest_entry_is_frozen():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    with pytest.raises(FrozenInstanceError):
        entry.status = "partial"  # type: ignore[misc]


def test_manifest_holds_controls_dict():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    m = Manifest(
        path=Path("/tmp/.ism-coverage.toml"),
        schema_version=1,
        scope={"classification": "P"},
        project={},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    assert m.controls["ISM-0428"].identifier == "ISM-0428"
    assert m.schema_version == 1
