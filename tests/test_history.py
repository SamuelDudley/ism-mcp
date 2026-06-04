"""Tests for the per-control history timeline."""

from __future__ import annotations

from ism_mcp import diff
from ism_mcp.store import Control


def _ctl(version, description="d", applies=None) -> Control:
    return Control(
        version=version,
        identifier="ism-0001",
        label="1",
        title="t",
        control_class="ISM-control",
        guideline="g",
        section="s",
        topic="tp",
        description=description,
        control_revision=None,
        updated=None,
        sort_id="1",
        applies=applies or {"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity={"ML1": False, "ML2": False, "ML3": False},
    )


def test_history_marks_changed_fields_and_bounds():
    order = ["2025.09.10", "2025.12.9", "2026.03.24"]
    by_version: dict[str, Control | None] = {
        "2025.09.10": _ctl("2025.09.10", description="a"),
        "2025.12.9": _ctl("2025.12.9", description="a"),
        "2026.03.24": _ctl("2026.03.24", description="b"),
    }
    out = diff.build_history("ism-0001", order, by_version)
    assert out["first_seen"] == "2025.09.10"
    assert out["last_seen"] is None
    timeline = {t["version"]: t for t in out["timeline"]}
    assert timeline["2025.09.10"]["changed"] == []
    assert timeline["2025.12.9"]["changed"] == []
    assert "reworded" in timeline["2026.03.24"]["changed"]


def test_history_records_removal():
    order = ["2025.12.9", "2026.03.24"]
    by_version: dict[str, Control | None] = {"2025.12.9": _ctl("2025.12.9"), "2026.03.24": None}
    out = diff.build_history("ism-0001", order, by_version)
    assert out["last_seen"] == "2025.12.9"
    assert [t["version"] for t in out["timeline"]] == ["2025.12.9"]
