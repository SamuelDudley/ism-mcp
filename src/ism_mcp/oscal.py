"""Parse an OSCAL ISM catalog dict into version metadata and Control rows."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .store import CLASSIFICATIONS, MATURITIES, Control

APPLICABILITY_VALUES = set(CLASSIFICATIONS)
_NUMERIC_ID = re.compile(r"^ism-0*(\d+)$")


@dataclass(frozen=True)
class VersionMeta:
    version: str
    title: str
    published: str | None
    last_modified: str | None
    oscal_version: str | None


def load_catalog(path: Path) -> dict:
    """Read an OSCAL file and return the dict under the top-level 'catalog' key."""
    return json.loads(Path(path).read_text())["catalog"]


def parse_metadata(catalog: dict) -> VersionMeta:
    md = catalog.get("metadata", {})
    return VersionMeta(
        version=md["version"],
        title=md.get("title", ""),
        published=md.get("published"),
        last_modified=md.get("last-modified"),
        oscal_version=md.get("oscal-version"),
    )


def walk_controls(catalog: dict) -> Iterator[tuple[dict, str, str, str]]:
    """Yield (control, guideline, section, topic) for every control in the catalog.

    All ISM controls sit at group depth three: the top group is the guideline, the
    first nested group is the section, the second nested group is the topic.
    """

    def walk(groups: list[dict], path: list[str]) -> Iterator[tuple[dict, str, str, str]]:
        for group in groups:
            new_path = [*path, group.get("title", "")]
            for control in group.get("controls", []):
                guideline = new_path[0] if len(new_path) > 0 else ""
                section = new_path[1] if len(new_path) > 1 else ""
                topic = new_path[2] if len(new_path) > 2 else ""
                yield control, guideline, section, topic
            yield from walk(group.get("groups", []), new_path)

    yield from walk(catalog.get("groups", []), [])


def prop_values(control: dict, name: str) -> list[str]:
    return [p["value"] for p in control.get("props", []) if p.get("name") == name]


def first_prop(control: dict, name: str) -> str | None:
    values = prop_values(control, name)
    return values[0] if values else None


def applicability(control: dict) -> dict[str, bool]:
    present = set(prop_values(control, "applicability")) & APPLICABILITY_VALUES
    return {c: c in present for c in CLASSIFICATIONS}


def maturity(identifier: str, maturity_sets: dict[str, set[str]]) -> dict[str, bool]:
    return {m: identifier in maturity_sets.get(m, set()) for m in MATURITIES}


def statement_prose(control: dict) -> str:
    parts = control.get("parts", [])
    for part in parts:
        if part.get("name") == "statement":
            return part.get("prose", "")
    return parts[0].get("prose", "") if parts else ""


def derive_label(control: dict) -> str:
    label = first_prop(control, "label")
    if label:
        return label
    match = _NUMERIC_ID.match(control["id"])
    return match.group(1) if match else control["id"]


def collect_control_ids(catalog: dict) -> set[str]:
    return {control["id"] for control, _g, _s, _t in walk_controls(catalog)}


def parse_controls(catalog: dict, maturity_sets: dict[str, set[str]]) -> Iterator[Control]:
    version = catalog.get("metadata", {})["version"]
    for control, guideline, section, topic in walk_controls(catalog):
        identifier = control["id"]
        yield Control(
            version=version,
            identifier=identifier,
            label=derive_label(control),
            title=control.get("title", ""),
            control_class=control.get("class", ""),
            guideline=guideline,
            section=section,
            topic=topic,
            description=statement_prose(control),
            control_revision=first_prop(control, "revision"),
            updated=first_prop(control, "updated"),
            sort_id=first_prop(control, "sort-id"),
            applies=applicability(control),
            maturity=maturity(identifier, maturity_sets),
        )
