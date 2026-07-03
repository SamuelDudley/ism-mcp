"""Coverage manifest read, validate, serialise, gap-compute. No MCP dependency."""

from __future__ import annotations

import contextlib
import os
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .models import RankedControlRef, Status


@dataclass(frozen=True)
class ManifestEntry:
    identifier: str
    status: Status
    how_met: str
    last_reviewed: date
    reviewed_by: str | None = None
    next_review: date | None = None
    reviewed_against: str | None = None
    files: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    urls: list[dict[str, str]] = field(default_factory=list)
    attachments: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    path: Path
    schema_version: int
    scope: dict
    project: dict
    controls: dict[str, ManifestEntry]
    warnings: list[str]


MANIFEST_FILENAME = ".ism-coverage.toml"


def find_manifest(start: Path) -> Path | None:
    """Walk up from `start` looking for .ism-coverage.toml. Return None if not found."""
    current = start.resolve()
    while True:
        candidate = current / MANIFEST_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def read_manifest(path: Path) -> Manifest:
    """Read and parse the manifest at `path`. Raises FileNotFoundError or ValueError."""
    if not path.is_file():
        raise FileNotFoundError(path)
    return read_manifest_text(path.read_text(), path)


def read_manifest_text(text: str, manifest_path: Path) -> Manifest:
    """Parse the manifest TOML and return a Manifest. Warnings come from validation."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"manifest at {manifest_path} is not valid TOML: {e}") from e

    controls: dict[str, ManifestEntry] = {}
    for identifier, body in (raw.get("controls") or {}).items():
        controls[identifier] = _entry_from_dict(identifier, body)

    project_root = manifest_path.parent
    warnings: list[str] = []
    for ident, entry in controls.items():
        for a in entry.attachments:
            path_ref = a.get("path")
            if path_ref is None:
                continue
            resolved = (project_root / path_ref).resolve()
            if not _within(project_root, resolved):
                warnings.append(f"{ident}: attachment path escapes project root: {path_ref}")
                continue
            if not resolved.is_file():
                warnings.append(f"{ident}: attachment not found on disk: {path_ref}")

    return Manifest(
        path=manifest_path,
        schema_version=int(raw.get("schema_version", 1)),
        scope=dict(raw.get("scope") or {}),
        project=dict(raw.get("project") or {}),
        controls=controls,
        warnings=warnings,
    )


def _entry_from_dict(identifier: str, body: dict) -> ManifestEntry:
    for required in ("status", "how_met"):
        if required not in body:
            raise ValueError(f"{identifier}: missing required key {required!r}")
    for key in ("status", "how_met", "reviewed_against", "reviewed_by"):
        value = body.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{identifier}: {key} must be a string, got {value!r}")
    for key in ("files", "commits"):
        if any(not isinstance(item, str) for item in body.get(key) or []):
            raise ValueError(f"{identifier}: {key} entries must be strings")
    last_reviewed = body.get("last_reviewed")
    if not isinstance(last_reviewed, date):
        raise ValueError(f"{identifier}: last_reviewed must be a TOML date, got {last_reviewed!r}")
    next_review = body.get("next_review")
    if next_review is not None and not isinstance(next_review, date):
        raise ValueError(f"{identifier}: next_review must be a TOML date or omitted")
    return ManifestEntry(
        identifier=identifier,
        status=body["status"],
        how_met=body["how_met"],
        last_reviewed=last_reviewed,
        reviewed_by=body.get("reviewed_by"),
        next_review=next_review,
        reviewed_against=body.get("reviewed_against"),
        files=list(body.get("files") or []),
        commits=list(body.get("commits") or []),
        urls=[_as_table(identifier, "url", u) for u in (body.get("urls") or [])],
        attachments=[
            _as_table(identifier, "attachment", a) for a in (body.get("attachments") or [])
        ],
    )


def _as_table(identifier: str, kind: str, item: object) -> dict:
    if not isinstance(item, dict):
        raise ValueError(f"{identifier}: each {kind} entry must be a table")
    return dict(item)


def _within(project_root: Path, resolved: Path) -> bool:
    return resolved.is_relative_to(project_root.resolve())


VALID_STATUSES: frozenset[str] = frozenset(["covered", "partial", "not-applicable", "deferred"])


def validate_entry(entry: ManifestEntry, project_root: Path) -> None:
    """Raise ValueError or FileNotFoundError if the entry is invalid for this project."""
    if entry.status not in VALID_STATUSES:
        raise ValueError(
            f"{entry.identifier}: status {entry.status!r} not one of {sorted(VALID_STATUSES)}"
        )
    if not entry.how_met or not entry.how_met.strip():
        raise ValueError(f"{entry.identifier}: how_met is required and must be non-empty")
    for u in entry.urls:
        if "url" not in u:
            raise ValueError(f"{entry.identifier}: url entry missing 'url' key")
        if "description" not in u or not u["description"].strip():
            raise ValueError(f"{entry.identifier}: url {u['url']!r} missing description")
    for a in entry.attachments:
        if "path" not in a:
            raise ValueError(f"{entry.identifier}: attachment entry missing 'path' key")
        if "description" not in a or not a["description"].strip():
            raise ValueError(f"{entry.identifier}: attachment {a['path']!r} missing description")
        resolved = (project_root / a["path"]).resolve()
        if not _within(project_root, resolved):
            raise ValueError(
                f"{entry.identifier}: attachment path escapes project root: {a['path']}"
            )
        if not resolved.is_file():
            raise FileNotFoundError(f"{entry.identifier}: attachment not found: {a['path']}")


def serialise_manifest(manifest: Manifest) -> str:
    """Serialise a Manifest to TOML text. Subset of TOML matching the manifest schema."""
    lines: list[str] = [f"schema_version = {manifest.schema_version}", ""]

    if manifest.scope:
        lines.append("[scope]")
        for key, value in manifest.scope.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    if manifest.project:
        lines.append("[project]")
        for key, value in manifest.project.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    for identifier, entry in manifest.controls.items():
        lines.append(f'[controls."{identifier}"]')
        lines.append(f"status = {_toml_value(entry.status)}")
        lines.append(f"how_met = {_toml_multiline(entry.how_met)}")
        lines.append(f"last_reviewed = {entry.last_reviewed.isoformat()}")
        if entry.reviewed_against:
            lines.append(f"reviewed_against = {_toml_value(entry.reviewed_against)}")
        if entry.reviewed_by:
            lines.append(f"reviewed_by = {_toml_value(entry.reviewed_by)}")
        if entry.next_review:
            lines.append(f"next_review = {entry.next_review.isoformat()}")
        if entry.files:
            lines.append(f"files = {_toml_value(entry.files)}")
        if entry.commits:
            lines.append(f"commits = {_toml_value(entry.commits)}")
        for u in entry.urls:
            lines.append("")
            lines.append(f'[[controls."{identifier}".urls]]')
            lines.append(f"url = {_toml_value(u['url'])}")
            lines.append(f"description = {_toml_value(u['description'])}")
        for a in entry.attachments:
            lines.append("")
            lines.append(f'[[controls."{identifier}".attachments]]')
            lines.append(f"path = {_toml_value(a['path'])}")
            lines.append(f"description = {_toml_value(a['description'])}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return _toml_string(v)
    if isinstance(v, list):
        items = ", ".join(_toml_value(x) for x in v)
        return f"[{items}]"
    raise TypeError(f"unsupported TOML value type: {type(v).__name__}")


def _toml_string(s: str) -> str:
    if "\n" not in s and '"' not in s and "\\" not in s:
        return f'"{s}"'
    return _toml_multiline(s)


def _toml_multiline(s: str) -> str:
    safe = s.replace("\\", "\\\\").replace('"""', '\\"""')
    if "\n" not in safe and '"' not in safe:
        return f'"{safe}"'
    return f'"""\n{safe}"""'


def upsert_entry(manifest_path: Path, entry: ManifestEntry) -> dict:
    """Validate the entry, then write/update it in the manifest atomically.

    Returns a dict with `action` (`"created"` or `"updated"`), `identifier`, and `warnings`.
    Raises ValueError for invalid entries and FileNotFoundError for missing attachments.
    """
    validate_entry(entry, project_root=manifest_path.parent)

    manifest = read_manifest(manifest_path)
    action = "updated" if entry.identifier in manifest.controls else "created"
    new_controls = dict(manifest.controls)
    new_controls[entry.identifier] = entry
    updated = Manifest(
        path=manifest.path,
        schema_version=manifest.schema_version,
        scope=manifest.scope,
        project=manifest.project,
        controls=new_controls,
        warnings=[],
    )
    text = serialise_manifest(updated)
    _atomic_write(manifest_path, text)
    return {"ok": True, "identifier": entry.identifier, "action": action, "warnings": []}


def _atomic_write(target: Path, text: str) -> None:
    """Write `text` to `target` atomically via tempfile + os.replace in the same dir."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, target)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


_STATUS_PRIORITY = {"uncurated": 0, "partial": 1, "deferred": 2}


def compute_gaps(
    manifest: Manifest,
    in_scope: list,
    applicable: Sequence[RankedControlRef] | None = None,
    limit: int = 50,
    canonical: Callable[[str], str] | None = None,
) -> dict:
    """Compute outstanding controls relative to the manifest.

    `in_scope` is the list of Control-like objects (anything with `identifier`, `topic`,
    `section`, `description` attributes) in the project's declared scope.
    `applicable` is the optional output of `ism_applicable`: a list of dicts each
    containing at least `identifier`, `score`, `why`. When provided, gaps are
    intersected with this list and ordered by score descending.
    `canonical` maps a manifest identifier to the store's canonical form so XLSX-era
    `ISM-NNNN` keys match lowercase `ism-nnnn` in-scope identifiers. Defaults to identity.
    """
    canon = canonical or (lambda x: x)
    by_canonical = {canon(ident): e for ident, e in manifest.controls.items()}
    covered = {ck for ck, e in by_canonical.items() if e.status in ("covered", "not-applicable")}

    def _current_status(identifier: str) -> str:
        entry = by_canonical.get(identifier)
        return entry.status if entry else "uncurated"

    def _current_entry(identifier: str) -> dict | None:
        entry = by_canonical.get(identifier)
        if entry is None:
            return None
        return {
            "how_met": entry.how_met,
            "last_reviewed": entry.last_reviewed.isoformat(),
        }

    by_id = {c.identifier: c for c in in_scope}

    if applicable is None:
        candidates = [c for c in in_scope if c.identifier not in covered]
        candidates.sort(
            key=lambda c: (
                _STATUS_PRIORITY.get(_current_status(c.identifier), 99),
                c.identifier,
            )
        )
        gaps = []
        for c in candidates:
            gaps.append(
                {
                    "identifier": c.identifier,
                    "topic": c.topic,
                    "section": c.section,
                    "description": c.description,
                    "current_status": _current_status(c.identifier),
                    "current_entry": _current_entry(c.identifier),
                    "score": None,
                    "why": None,
                }
            )
        total = len(gaps)
        return {"gaps": gaps[:limit], "total_outstanding": total, "shown": min(limit, total)}

    # Work-aware: intersect with applicable, preserve applicable's score-descending order.
    gaps = []
    for entry in applicable:
        ident = entry["identifier"]
        if ident in covered:
            continue
        if ident not in by_id:
            continue  # outside scope
        c = by_id[ident]
        gaps.append(
            {
                "identifier": ident,
                "topic": c.topic,
                "section": c.section,
                "description": c.description,
                "current_status": _current_status(ident),
                "current_entry": _current_entry(ident),
                "score": entry.get("score"),
                "why": entry.get("why"),
            }
        )
    total = len(gaps)
    return {"gaps": gaps[:limit], "total_outstanding": total, "shown": min(limit, total)}


def compute_impact(
    manifest: Manifest,
    target_version: str,
    lookup: Callable[[str, str], Any],
    in_scope_target: list,
    changed_fields: Callable[[Any, Any], list[str]],
    diff_text: Callable[[str, str], str],
    limit: int = 50,
    canonical: Callable[[str], str] | None = None,
) -> dict:
    """Bucket coverage entries by what a move to `target_version` requires.

    `lookup(version, identifier)` returns a Control-like object or None.
    `changed_fields(old, new)` and `diff_text(old_text, new_text)` come from diff.py.
    `in_scope_target` is the list of in-scope controls at the target version.
    `canonical` maps a manifest identifier to the store's canonical form so curated
    entries match in-scope identifiers. Defaults to identity.
    """
    canon = canonical or (lambda x: x)
    baseline = manifest.scope.get("baseline_version")
    re_review: list[dict] = []
    removed: list[dict] = []
    still_valid = 0

    for ident, entry in manifest.controls.items():
        if entry.status not in ("covered", "partial"):
            continue
        against = entry.reviewed_against or baseline or target_version
        target = lookup(target_version, ident)
        if target is None:
            removed.append(
                {
                    "identifier": ident,
                    "status": entry.status,
                    "reviewed_against": against,
                    "hint": f"no longer in {target_version}; consider not-applicable or remove",
                }
            )
            continue
        old = lookup(against, ident)
        fields = changed_fields(old, target) if old is not None else []
        if fields:
            reworded_diff = None
            if old is not None and "reworded" in fields:
                reworded_diff = diff_text(old.description, target.description)
            re_review.append(
                {
                    "identifier": ident,
                    "status": entry.status,
                    "reviewed_against": against,
                    "changes": fields,
                    "how_met": entry.how_met,
                    "diff": reworded_diff,
                }
            )
        else:
            still_valid += 1

    curated = {canon(k) for k in manifest.controls}
    new_uncovered = [
        {
            "identifier": c.identifier,
            "label": c.label,
            "title": c.title,
            "section": c.section,
            "reason": "in scope at target, no manifest entry",
        }
        for c in in_scope_target
        if c.identifier not in curated
    ]

    re_review.sort(key=lambda e: e["identifier"])
    removed.sort(key=lambda e: e["identifier"])
    new_uncovered.sort(key=lambda e: e["identifier"])
    return {
        "baseline_version": baseline,
        "target_version": target_version,
        "summary": {
            "re_review": len(re_review),
            "removed_upstream": len(removed),
            "new_uncovered": len(new_uncovered),
            "still_valid": still_valid,
        },
        "re_review": re_review[:limit],
        "removed_upstream": removed[:limit],
        "new_uncovered": new_uncovered[:limit],
    }
