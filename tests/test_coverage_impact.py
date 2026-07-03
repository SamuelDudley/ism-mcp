"""Tests for coverage drift computation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ism_mcp import coverage, diff
from ism_mcp.store import Control


def _ctl(version, identifier, description="d", applies=None) -> Control:
    return Control(
        version=version,
        identifier=identifier,
        label=identifier,
        title="t",
        control_class="ISM-control",
        guideline="g",
        section="s",
        topic="tp",
        description=description,
        control_revision=None,
        updated=None,
        sort_id=identifier,
        applies=applies or {"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity={"ML1": False, "ML2": False, "ML3": False},
    )


def _entry(
    identifier, status: coverage.Status = "covered", reviewed_against="2025.12.9"
) -> coverage.ManifestEntry:
    return coverage.ManifestEntry(
        identifier=identifier,
        status=status,
        how_met="x",
        last_reviewed=date(2025, 12, 15),
        reviewed_against=reviewed_against,
    )


def _manifest(entries) -> coverage.Manifest:
    return coverage.Manifest(
        path=Path("/tmp/.ism-coverage.toml"),
        schema_version=1,
        scope={"classification": "P", "baseline_version": "2026.03.24"},
        project={},
        controls={e.identifier: e for e in entries},
        warnings=[],
    )


def test_reviewed_against_round_trips_through_toml():
    text = coverage.serialise_manifest(_manifest([_entry("ism-0001")]))
    assert 'reviewed_against = "2025.12.9"' in text
    parsed = coverage.read_manifest_text(text, Path("/tmp/.ism-coverage.toml"))
    assert parsed.controls["ism-0001"].reviewed_against == "2025.12.9"


def test_compute_impact_buckets():
    manifest = _manifest([_entry("ism-0001"), _entry("ism-0002"), _entry("ism-0003")])

    target_controls = {
        "ism-0001": _ctl("2026.03.24", "ism-0001", description="CHANGED"),
        "ism-0002": _ctl("2026.03.24", "ism-0002", description="d"),
        "ism-0003": None,
    }
    reviewed_controls = {
        "ism-0001": _ctl("2025.12.9", "ism-0001", description="d"),
        "ism-0002": _ctl("2025.12.9", "ism-0002", description="d"),
        "ism-0003": _ctl("2025.12.9", "ism-0003", description="d"),
    }
    in_scope_target = [
        _ctl("2026.03.24", "ism-0001"),
        _ctl("2026.03.24", "ism-0002"),
        _ctl("2026.03.24", "ism-0009"),
    ]

    def lookup(version, identifier):
        return (target_controls if version == "2026.03.24" else reviewed_controls).get(identifier)

    out = coverage.compute_impact(
        manifest=manifest,
        target_version="2026.03.24",
        lookup=lookup,
        in_scope_target=in_scope_target,
        changed_fields=diff.changed_fields,
        diff_text=diff.unified_diff,
    )
    assert {e["identifier"] for e in out["re_review"]} == {"ism-0001"}
    assert out["re_review"][0]["changes"] == ["reworded"]
    assert out["re_review"][0]["diff"] is not None
    assert {e["identifier"] for e in out["removed_upstream"]} == {"ism-0003"}
    assert {e["identifier"] for e in out["new_uncovered"]} == {"ism-0009"}
    assert out["summary"]["still_valid"] == 1


def test_impact_non_reworded_change_has_null_diff():
    old = _ctl("2025.12.9", "ism-0001")
    new = _ctl(
        "2026.03.24",
        "ism-0001",
        applies={"NC": False, "OS": True, "P": True, "S": True, "TS": True},
    )

    def lookup(version, identifier):
        return {"2025.12.9": old, "2026.03.24": new}.get(version)

    out = coverage.compute_impact(
        manifest=_manifest([_entry("ism-0001")]),
        target_version="2026.03.24",
        lookup=lookup,
        in_scope_target=[new],
        changed_fields=diff.changed_fields,
        diff_text=diff.unified_diff,
    )
    assert out["re_review"][0]["changes"] == ["applicability_changed"]
    assert out["re_review"][0]["diff"] is None
