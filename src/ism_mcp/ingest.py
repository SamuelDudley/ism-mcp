"""Orchestrate OSCAL ingest: parse a catalog directory or a git tag into the store."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import fetch, oscal, store
from .embed import Embedder, l2_normalise
from .oscal import VersionMeta
from .store import Control

CATALOG_FILE = "ISM_catalog.json"
E8_FILES = {
    "ML1": "ISM_E8_ML1-baseline-resolved-profile_catalog.json",
    "ML2": "ISM_E8_ML2-baseline-resolved-profile_catalog.json",
    "ML3": "ISM_E8_ML3-baseline-resolved-profile_catalog.json",
}
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def version_label(version: str) -> str:
    """Humanise a version like 2026.03.24 to 'March 2026'. Falls back to the input."""
    parts = version.split(".")
    try:
        year, month = int(parts[0]), int(parts[1])
        return f"{_MONTHS[month - 1]} {year}"
    except IndexError, ValueError:
        return version


def _maturity_sets_from_dir(oscal_dir: Path) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for ml, fname in E8_FILES.items():
        path = oscal_dir / fname
        sets[ml] = oscal.collect_control_ids(oscal.load_catalog(path)) if path.is_file() else set()
    return sets


def load_version_from_dir(oscal_dir: Path) -> tuple[VersionMeta, list[Control]]:
    catalog = oscal.load_catalog(Path(oscal_dir) / CATALOG_FILE)
    sets = _maturity_sets_from_dir(Path(oscal_dir))
    return oscal.parse_metadata(catalog), list(oscal.parse_controls(catalog, sets))


def load_version_from_tag(repo_dir: Path, tag: str) -> tuple[VersionMeta, list[Control]]:
    catalog = json.loads(fetch.read_file_at_tag(repo_dir, tag, CATALOG_FILE))["catalog"]
    sets: dict[str, set[str]] = {}
    for ml, fname in E8_FILES.items():
        try:
            sub = json.loads(fetch.read_file_at_tag(repo_dir, tag, fname))["catalog"]
            sets[ml] = oscal.collect_control_ids(sub)
        except fetch.GitError:
            sets[ml] = set()
    return oscal.parse_metadata(catalog), list(oscal.parse_controls(catalog, sets))


def embedding_text(c: Control) -> str:
    return f"{c.guideline}. {c.section}. {c.topic}. {c.title}. {c.description}"


def embed_controls(controls: Iterable[Control], embedder: Embedder) -> Iterator[tuple[str, bytes]]:
    controls = list(controls)
    vectors = l2_normalise(embedder.embed([embedding_text(c) for c in controls]))
    for c, vec in zip(controls, vectors, strict=True):
        yield c.identifier, vec.astype(np.float32).tobytes()


def ingest_version(
    conn,
    vmeta: VersionMeta,
    controls: list[Control],
    embedder: Embedder | None = None,
    git_tag: str | None = None,
    git_commit: str | None = None,
    make_active: bool = True,
) -> dict:
    store.delete_version(conn, vmeta.version)
    store.insert_controls(conn, controls)
    store.upsert_version(
        conn,
        version=vmeta.version,
        label=version_label(vmeta.version),
        published=vmeta.published,
        last_modified=vmeta.last_modified,
        oscal_version=vmeta.oscal_version,
        git_tag=git_tag,
        git_commit=git_commit,
        ingested_at=datetime.now(UTC).isoformat(),
        control_count=len(controls),
    )
    embedded = 0
    if embedder is not None:
        rows = [(vmeta.version, ident, blob) for ident, blob in embed_controls(controls, embedder)]
        embedded = store.insert_embeddings(conn, rows)
    if make_active:
        store.set_active_version(conn, vmeta.version)
    return {"version": vmeta.version, "controls": len(controls), "embedded": embedded}
