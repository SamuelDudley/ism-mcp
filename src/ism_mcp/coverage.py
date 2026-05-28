"""Coverage manifest read, validate, serialise, gap-compute. No MCP dependency."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

Status = Literal["covered", "partial", "not-applicable", "deferred"]


@dataclass(frozen=True)
class ManifestEntry:
    identifier: str
    status: Status
    how_met: str
    last_reviewed: date
    reviewed_by: str | None = None
    next_review: date | None = None
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
        files=list(body.get("files") or []),
        commits=list(body.get("commits") or []),
        urls=[dict(u) for u in (body.get("urls") or [])],
        attachments=[dict(a) for a in (body.get("attachments") or [])],
    )


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
