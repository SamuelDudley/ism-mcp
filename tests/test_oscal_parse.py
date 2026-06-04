"""Tests for parsing an OSCAL ISM catalog into VersionMeta and Control rows."""

from __future__ import annotations

import json
from pathlib import Path

from ism_mcp import oscal

FIXTURE = Path(__file__).parent / "fixtures" / "oscal" / "ISM_catalog.json"


def _catalog() -> dict:
    return json.loads(FIXTURE.read_text())["catalog"]


def test_parse_metadata():
    meta = oscal.parse_metadata(_catalog())
    assert meta.version == "2025.12.9"
    assert meta.oscal_version == "1.1.2"
    assert meta.published is not None
    assert meta.published.startswith("2025-12-09")


def test_parse_controls_yields_all_with_hierarchy():
    controls = list(oscal.parse_controls(_catalog(), maturity_sets={}))
    by_id = {c.identifier: c for c in controls}
    assert set(by_id) == {"ism-0714", "ism-1997", "ism-principle-gov-01"}

    c = by_id["ism-0714"]
    assert c.version == "2025.12.9"
    assert c.guideline == "Guidelines for cyber security roles"
    assert c.section == "Chief information security officer"
    assert c.topic == "Providing cyber security leadership"
    assert c.description.startswith("A chief information security officer")
    assert c.control_class == "ISM-control"
    assert c.control_revision == "3"
    assert c.updated == "Dec-25"
    assert c.applies == {"NC": True, "OS": True, "P": True, "S": True, "TS": True}
    assert c.label == "714"


def test_restricted_applicability():
    by_id = {c.identifier: c for c in oscal.parse_controls(_catalog(), maturity_sets={})}
    c = by_id["ism-1997"]
    assert c.applies == {"NC": False, "OS": False, "P": False, "S": False, "TS": True}
    assert c.control_revision is None


def test_principle_uses_label_prop():
    by_id = {c.identifier: c for c in oscal.parse_controls(_catalog(), maturity_sets={})}
    p = by_id["ism-principle-gov-01"]
    assert p.label == "GOV-01"
    assert p.control_class == "ISM-principle"
    assert p.title == "Executive cyber security accountability"


def test_maturity_from_sets():
    sets = {"ML1": {"ism-0714"}, "ML2": {"ism-0714"}, "ML3": {"ism-1997"}}
    by_id = {c.identifier: c for c in oscal.parse_controls(_catalog(), maturity_sets=sets)}
    assert by_id["ism-0714"].maturity == {"ML1": True, "ML2": True, "ML3": False}
    assert by_id["ism-1997"].maturity == {"ML1": False, "ML2": False, "ML3": True}
    assert by_id["ism-principle-gov-01"].maturity == {"ML1": False, "ML2": False, "ML3": False}
