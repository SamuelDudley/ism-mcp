"""Gaps and impact must canonicalize manifest identifiers before comparing.

XLSX-era manifests key entries as uppercase ISM-NNNN while OSCAL canonical ids are
lowercase ism-nnnn. Without canonicalization the covered set never matches the in-scope
set, so covered controls are mis-reported as gaps.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ism_mcp import coverage, diff
from ism_mcp.store import Control


def _ctl(identifier, section="s") -> Control:
    return Control(
        version="2026.03.24",
        identifier=identifier,
        label=identifier,
        title="t",
        control_class="ISM-control",
        guideline="g",
        section=section,
        topic="tp",
        description="d",
        control_revision=None,
        updated=None,
        sort_id=identifier,
        applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity={"ML1": False, "ML2": False, "ML3": False},
    )


def _entry(identifier, status="covered") -> coverage.ManifestEntry:
    return coverage.ManifestEntry(
        identifier=identifier, status=status, how_met="x", last_reviewed=date(2025, 12, 15)
    )


def _manifest(entries, scope=None) -> coverage.Manifest:
    return coverage.Manifest(
        path=Path("/tmp/.ism-coverage.toml"),
        schema_version=1,
        scope=scope or {"classification": "P"},
        project={},
        controls={e.identifier: e for e in entries},
        warnings=[],
    )


def _lower(x: str) -> str:
    return x.lower()


def test_gaps_canonicalizes_uppercase_covered_keys():
    manifest = _manifest([_entry("ISM-0428", "covered")])
    in_scope = [_ctl("ism-0428"), _ctl("ism-9999")]
    out = coverage.compute_gaps(manifest, in_scope, canonical=_lower)
    ids = [g["identifier"] for g in out["gaps"]]
    assert "ism-0428" not in ids
    assert "ism-9999" in ids


def test_gaps_status_reported_via_canonical_key():
    manifest = _manifest([_entry("ISM-0428", "partial")])
    out = coverage.compute_gaps(manifest, [_ctl("ism-0428")], canonical=_lower)
    g = next(g for g in out["gaps"] if g["identifier"] == "ism-0428")
    assert g["current_status"] == "partial"


def test_gaps_without_canonical_is_unchanged():
    manifest = _manifest([_entry("ism-0428", "covered")])
    out = coverage.compute_gaps(manifest, [_ctl("ism-0428"), _ctl("ism-9999")])
    assert [g["identifier"] for g in out["gaps"]] == ["ism-9999"]


def test_impact_canonicalizes_curated_set():
    manifest = _manifest(
        [_entry("ISM-0428", "covered")],
        scope={"classification": "P", "baseline_version": "2026.03.24"},
    )
    target = {"ism-0428": _ctl("ism-0428")}

    def lookup(version, identifier):
        return target.get(identifier.lower())

    in_scope_target = [_ctl("ism-0428"), _ctl("ism-9999")]
    out = coverage.compute_impact(
        manifest=manifest,
        target_version="2026.03.24",
        lookup=lookup,
        in_scope_target=in_scope_target,
        changed_fields=diff.changed_fields,
        diff_text=diff.unified_diff,
        canonical=_lower,
    )
    nu = {e["identifier"] for e in out["new_uncovered"]}
    assert "ism-0428" not in nu
    assert "ism-9999" in nu
    assert out["summary"]["still_valid"] == 1
