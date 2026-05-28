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

    return Manifest(
        path=manifest_path,
        schema_version=int(raw.get("schema_version", 1)),
        scope=dict(raw.get("scope") or {}),
        project=dict(raw.get("project") or {}),
        controls=controls,
        warnings=[],
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
