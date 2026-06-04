"""Tests for deriving Essential Eight maturity from resolved E8 catalogs."""

from __future__ import annotations

import json
from pathlib import Path

from ism_mcp import oscal

FX = Path(__file__).parent / "fixtures" / "oscal"


def _load(name: str) -> dict:
    return json.loads((FX / name).read_text())["catalog"]


def test_collect_control_ids_from_e8():
    ids = oscal.collect_control_ids(_load("ISM_E8_ML2-baseline-resolved-profile_catalog.json"))
    assert ids == {"ism-0714", "ism-1997"}


def test_maturity_sets_feed_parse_controls():
    sets = {
        "ML1": oscal.collect_control_ids(
            _load("ISM_E8_ML1-baseline-resolved-profile_catalog.json")
        ),
        "ML2": oscal.collect_control_ids(
            _load("ISM_E8_ML2-baseline-resolved-profile_catalog.json")
        ),
        "ML3": oscal.collect_control_ids(
            _load("ISM_E8_ML3-baseline-resolved-profile_catalog.json")
        ),
    }
    catalog = _load("ISM_catalog.json")
    by_id = {c.identifier: c for c in oscal.parse_controls(catalog, sets)}
    assert by_id["ism-0714"].maturity == {"ML1": True, "ML2": True, "ML3": False}
    assert by_id["ism-1997"].maturity == {"ML1": False, "ML2": True, "ML3": True}
