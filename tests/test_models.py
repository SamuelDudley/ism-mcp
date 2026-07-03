"""The response models mirror the payloads the tools build."""

from __future__ import annotations

import typing

from ism_mcp import coverage, models, store


def test_status_is_shared_with_coverage():
    assert coverage.Status is models.Status


def test_diff_result_uses_keyword_keys():
    assert set(models.DiffResult.__annotations__) == {"from", "to", "summary", "changes"}
    assert set(models.RetitledEntry.__annotations__) == {
        "identifier",
        "label",
        "title",
        "from",
        "to",
    }


def test_control_record_matches_store_as_dict_keys():
    c = store.Control(
        version="v",
        identifier="ism-0001",
        label="1",
        title="t",
        control_class="c",
        guideline="g",
        section="s",
        topic="p",
        control_revision=None,
        updated=None,
        sort_id=None,
        description="d",
        applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity={"ML1": False, "ML2": False, "ML3": False},
    )
    assert set(c.as_dict()) == set(models.ControlRecord.__annotations__)


def test_no_notrequired_keys_anywhere():
    for name in dir(models):
        obj = getattr(models, name)
        if typing.is_typeddict(obj):
            assert obj.__required_keys__ == frozenset(obj.__annotations__), name
