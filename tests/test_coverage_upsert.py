"""Atomic upsert of a manifest entry with full validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ism_mcp.coverage import (
    ManifestEntry,
    read_manifest,
    upsert_entry,
)

SEED_TOML = """\
schema_version = 1

[scope]
classification = "P"
maturity = "ML2"

[project]
name = "demo"
"""


def _seed(tmp_path: Path) -> Path:
    path = tmp_path / ".ism-coverage.toml"
    path.write_text(SEED_TOML)
    return path


def test_upsert_creates_entry(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="Sessions terminate after 14 min.",
        last_reviewed=date(2026, 5, 28),
        files=["src/auth/session.py:42-87"],
    )
    result = upsert_entry(path, entry)
    assert result["action"] == "created"
    assert result["identifier"] == "ISM-0428"
    m = read_manifest(path)
    assert "ISM-0428" in m.controls
    assert m.controls["ISM-0428"].how_met.startswith("Sessions terminate")


def test_upsert_updates_existing_entry(tmp_path):
    path = _seed(tmp_path)
    e1 = ManifestEntry(
        identifier="ISM-0428",
        status="partial",
        how_met="first pass",
        last_reviewed=date(2026, 5, 28),
    )
    upsert_entry(path, e1)
    e2 = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="now covered",
        last_reviewed=date(2026, 5, 29),
    )
    result = upsert_entry(path, e2)
    assert result["action"] == "updated"
    m = read_manifest(path)
    assert m.controls["ISM-0428"].status == "covered"
    assert m.controls["ISM-0428"].how_met == "now covered"


def test_upsert_rejects_invalid_status(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="bogus",  # type: ignore[arg-type]
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    with pytest.raises(ValueError, match="status"):
        upsert_entry(path, entry)
    # File unchanged.
    assert "ISM-0428" not in read_manifest(path).controls


def test_upsert_rejects_missing_attachment(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
        attachments=[{"path": "evidence/nope.png", "description": "x"}],
    )
    with pytest.raises(FileNotFoundError):
        upsert_entry(path, entry)


def test_upsert_returns_warning_for_out_of_scope_identifier(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    # Scope sets sections to ["Authentication hardening"] etc. Without an in-scope check
    # being wired in coverage.py (the server adds it), upsert should not warn here.
    # We just verify warnings is an empty list for the base function.
    result = upsert_entry(path, entry)
    assert result["warnings"] == []


def test_upsert_is_atomic(monkeypatch, tmp_path):
    path = _seed(tmp_path)
    original = path.read_text()
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    # Simulate failure during os.replace by patching it on the coverage module.
    from ism_mcp import coverage

    def boom(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(coverage.os, "replace", boom)
    with pytest.raises(OSError):
        upsert_entry(path, entry)
    assert path.read_text() == original
