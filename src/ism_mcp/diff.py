"""Pure comparison of Control sets across versions, plus per-control history."""

from __future__ import annotations

import difflib

from .store import CLASSIFICATIONS, MATURITIES, Control


def _applicability_list(c: Control) -> list[str]:
    return [k for k in CLASSIFICATIONS if c.applies.get(k)]


def _maturity_list(c: Control) -> list[str]:
    return [k for k in MATURITIES if c.maturity.get(k)]


def unified_diff(old_text: str, new_text: str) -> str:
    lines = difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=2)
    return "\n".join(lines)


def changed_fields(old: Control, new: Control) -> list[str]:
    """Which aspects of a same-identifier control changed from old to new."""
    fields: list[str] = []
    if old.description != new.description:
        fields.append("reworded")
    if old.title != new.title:
        fields.append("retitled")
    if (old.guideline, old.section, old.topic) != (new.guideline, new.section, new.topic):
        fields.append("moved")
    if old.applies != new.applies:
        fields.append("applicability_changed")
    if old.maturity != new.maturity:
        fields.append("maturity_changed")
    return fields


def _set_delta(old_keys: list[str], new_keys: list[str]) -> tuple[list[str], list[str]]:
    added = [k for k in new_keys if k not in old_keys]
    removed = [k for k in old_keys if k not in new_keys]
    return added, removed


def diff_controls(from_list: list[Control], to_list: list[Control]) -> dict:
    """Compare two versions' control lists into change buckets."""
    from_by = {c.identifier: c for c in from_list}
    to_by = {c.identifier: c for c in to_list}

    buckets: dict[str, list[dict]] = {
        "added": [],
        "removed": [],
        "reworded": [],
        "retitled": [],
        "moved": [],
        "applicability_changed": [],
        "maturity_changed": [],
    }

    for ident, c in to_by.items():
        if ident not in from_by:
            buckets["added"].append(
                {"identifier": ident, "label": c.label, "title": c.title, "section": c.section}
            )
    for ident, c in from_by.items():
        if ident not in to_by:
            buckets["removed"].append(
                {"identifier": ident, "label": c.label, "title": c.title, "section": c.section}
            )

    for ident in from_by.keys() & to_by.keys():
        old, new = from_by[ident], to_by[ident]
        for field in changed_fields(old, new):
            entry: dict = {"identifier": ident, "label": new.label, "title": new.title}
            if field == "reworded":
                entry["diff"] = unified_diff(old.description, new.description)
            elif field == "applicability_changed":
                a, r = _set_delta(_applicability_list(old), _applicability_list(new))
                entry["added"], entry["removed"] = a, r
            elif field == "maturity_changed":
                a, r = _set_delta(_maturity_list(old), _maturity_list(new))
                entry["added"], entry["removed"] = a, r
            elif field == "moved":
                entry["from"] = {
                    "guideline": old.guideline,
                    "section": old.section,
                    "topic": old.topic,
                }
                entry["to"] = {
                    "guideline": new.guideline,
                    "section": new.section,
                    "topic": new.topic,
                }
            elif field == "retitled":
                entry["from"], entry["to"] = old.title, new.title
            buckets[field].append(entry)

    for key in buckets:
        buckets[key].sort(key=lambda e: e["identifier"])
    summary = {key: len(value) for key, value in buckets.items()}
    return {"summary": summary, "changes": buckets}


def build_history(identifier: str, order: list[str], by_version: dict[str, Control | None]) -> dict:
    """Assemble one control's timeline across versions given in chronological order."""
    timeline: list[dict] = []
    first_seen: str | None = None
    last_present: str | None = None
    prev: Control | None = None
    for version in order:
        c = by_version.get(version)
        if c is None:
            continue
        if first_seen is None:
            first_seen = version
        last_present = version
        changed = changed_fields(prev, c) if prev is not None else []
        timeline.append(
            {
                "version": version,
                "title": c.title,
                "applicability": _applicability_list(c),
                "maturity": _maturity_list(c),
                "changed": changed,
            }
        )
        prev = c
    present_now = bool(order) and by_version.get(order[-1]) is not None
    return {
        "identifier": identifier,
        "first_seen": first_seen,
        "last_seen": None if present_now else last_present,
        "timeline": timeline,
    }
