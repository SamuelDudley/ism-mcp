"""Tests for the pure diff engine over Control lists."""

from __future__ import annotations

from ism_mcp import diff
from ism_mcp.store import Control


def _ctl(
    identifier,
    *,
    version="v",
    description="d",
    title="t",
    section="s",
    topic="tp",
    guideline="g",
    applies=None,
    maturity=None,
) -> Control:
    return Control(
        version=version,
        identifier=identifier,
        label=identifier,
        title=title,
        control_class="ISM-control",
        guideline=guideline,
        section=section,
        topic=topic,
        description=description,
        control_revision=None,
        updated=None,
        sort_id=identifier,
        applies=applies or {"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity=maturity or {"ML1": False, "ML2": False, "ML3": False},
    )


def test_added_and_removed():
    old = [_ctl("ism-0001")]
    new = [_ctl("ism-0001"), _ctl("ism-0002")]
    result = diff.diff_controls(old, new)
    assert [c["identifier"] for c in result["changes"]["added"]] == ["ism-0002"]
    assert result["changes"]["removed"] == []
    assert result["summary"]["added"] == 1


def test_reworded_emits_unified_diff():
    old = [_ctl("ism-0001", description="old text")]
    new = [_ctl("ism-0001", description="new text")]
    result = diff.diff_controls(old, new)
    reworded = result["changes"]["reworded"]
    assert reworded[0]["identifier"] == "ism-0001"
    assert "old text" in reworded[0]["diff"]
    assert "new text" in reworded[0]["diff"]


def test_applicability_and_maturity_changes():
    old = [
        _ctl(
            "ism-0001",
            applies={"NC": False, "OS": True, "P": True, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": False},
        )
    ]
    new = [
        _ctl(
            "ism-0001",
            applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
            maturity={"ML1": True, "ML2": False, "ML3": False},
        )
    ]
    result = diff.diff_controls(old, new)
    appl = result["changes"]["applicability_changed"][0]
    assert appl["added"] == ["NC"] and appl["removed"] == []
    mat = result["changes"]["maturity_changed"][0]
    assert mat["added"] == ["ML1"]


def test_retitled_and_moved():
    old = [_ctl("ism-0001", title="A", topic="old topic")]
    new = [_ctl("ism-0001", title="B", topic="new topic")]
    result = diff.diff_controls(old, new)
    assert result["changes"]["retitled"][0]["identifier"] == "ism-0001"
    assert result["changes"]["moved"][0]["identifier"] == "ism-0001"


def test_changed_fields_helper():
    a = _ctl(
        "ism-0001",
        description="x",
        applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
    )
    b = _ctl(
        "ism-0001",
        description="y",
        applies={"NC": False, "OS": True, "P": True, "S": True, "TS": True},
    )
    assert set(diff.changed_fields(a, b)) == {"reworded", "applicability_changed"}
