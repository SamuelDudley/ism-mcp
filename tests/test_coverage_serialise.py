"""Hand-rolled TOML serialiser for the manifest schema."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ism_mcp.coverage import Manifest, ManifestEntry, read_manifest_text, serialise_manifest


def test_round_trip_preserves_all_fields(tmp_path):
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="Sessions terminate after 14 min of idle.",
        last_reviewed=date(2026, 5, 28),
        reviewed_by="reviewer",
        next_review=date(2027, 5, 28),
        files=["src/auth/session.py:42-87", "tests/test_session_lock.py:15-60"],
        commits=["abc1234"],
        urls=[{"url": "https://example/policy", "description": "Authoritative session policy"}],
        attachments=[
            {"path": ".ism-coverage/evidence/ISM-0428/x.png", "description": "screenshot"}
        ],
    )
    original = Manifest(
        path=tmp_path / ".ism-coverage.toml",
        schema_version=1,
        scope={"classification": "P", "maturity": "ML2", "sections": ["Authentication hardening"]},
        project={"name": "demo", "description": "x"},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    text = serialise_manifest(original)
    parsed = read_manifest_text(text, original.path)
    assert parsed.schema_version == 1
    assert parsed.scope == original.scope
    assert parsed.project == original.project
    assert parsed.controls["ISM-0428"] == entry


def test_serialiser_quotes_strings_safely():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met='He said "hello" and left.\nSecond line.',
        last_reviewed=date(2026, 5, 28),
    )
    m = Manifest(
        path=Path("/x/.ism-coverage.toml"),
        schema_version=1,
        scope={"classification": "NC"},
        project={},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    text = serialise_manifest(m)
    # Multiline-with-quotes must survive a round-trip.
    parsed = read_manifest_text(text, m.path)
    assert parsed.controls["ISM-0428"].how_met == entry.how_met


def test_serialiser_omits_optional_empty_collections():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    m = Manifest(
        path=Path("/x/.ism-coverage.toml"),
        schema_version=1,
        scope={"classification": "NC"},
        project={},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    text = serialise_manifest(m)
    assert "files" not in text
    assert "commits" not in text
    assert "urls" not in text
    assert "attachments" not in text
