"""MCP server exposing ISM lookup tools."""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
from datetime import date as _date
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import classification as cls
from . import coverage, diff, retrieve, store
from . import paths as repo_paths
from .embed import DeterministicHashEmbedder, Embedder, FastEmbedEmbedder

DEFAULT_DB = Path(os.environ.get("ISM_MCP_DB", Path.home() / ".local/share/ism-mcp/ism.db"))

MAX_LIMIT = 200


mcp = FastMCP("ism-mcp")

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES_MANIFEST = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


_RUNTIME: dict[str, object] = {}


def _reset_runtime_cache() -> None:
    conn = _RUNTIME.get("conn")
    if conn is not None:
        with contextlib.suppress(Exception):
            conn.close()  # type: ignore[attr-defined]
    _RUNTIME.clear()


def _active_db() -> Path:
    """Resolve the database path at call time so a runtime ISM_MCP_DB takes effect."""
    return Path(os.environ.get("ISM_MCP_DB", str(DEFAULT_DB)))


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _embedder() -> Embedder | None:
    mode = os.environ.get("ISM_MCP_EMBEDDER", "fastembed").lower()
    if mode == "none":
        return None
    if "embedder" in _RUNTIME:
        return _RUNTIME["embedder"]  # type: ignore[return-value]
    e: Embedder = DeterministicHashEmbedder(dim=384) if mode == "hash" else FastEmbedEmbedder()
    _RUNTIME["embedder"] = e
    return e


def _vector_index(conn) -> retrieve.VectorIndex | None:
    if "vec_index" in _RUNTIME:
        return _RUNTIME["vec_index"]  # type: ignore[return-value]
    embedder = _embedder()
    if embedder is None:
        return None
    version = store.get_active_version(conn)
    if version is None:
        return None
    matrix, ids = store.load_embedding_matrix(conn, dim=embedder.dim, version=version)
    if len(ids) == 0:
        return None
    idx = retrieve.VectorIndex(matrix, ids)
    _RUNTIME["vec_index"] = idx
    return idx


def _conn() -> sqlite3.Connection:
    path = _active_db()
    if not path.exists():
        raise RuntimeError(
            f"ISM database not found at {path}. "
            "Run `ism-mcp ingest` or `ism-mcp ingest-history` first."
        )
    cached = _RUNTIME.get("conn")
    if cached is not None and _RUNTIME.get("conn_path") == path:
        return cached  # type: ignore[return-value]
    conn = store.open_db(path)
    _RUNTIME["conn"] = conn
    _RUNTIME["conn_path"] = path
    return conn


@mcp.tool(annotations=READ_ONLY)
def ism_get(identifier: str, version: str | None = None) -> str:
    """Get the full record for one ISM control by identifier (e.g. `ism-1781`).

    Identifier input is tolerant: `ISM-1781`, bare `1781`, and legacy labels resolve to
    the canonical OSCAL id. Returns the control as JSON, or `{"error": ...}` when no
    control matches. Use ism_search or ism_applicable first when the identifier is
    unknown. Defaults to the active ISM version. Pass `version` (see ism_versions)
    for a historical one.
    """
    conn = _conn()
    c = store.get_control(conn, identifier, version=version)
    if c is None:
        return json.dumps({"error": f"no such control: {identifier}"})
    return json.dumps(c.as_dict(), indent=2)


@mcp.tool(annotations=READ_ONLY)
def ism_search(query: str, limit: int = 10, version: str | None = None) -> str:
    """Full-text keyword search (FTS5 BM25) over ISM control text and topics.

    Best when you already know the terms, an exact phrase, or part of a control title.
    To rank controls against a free-text description of work, use ism_applicable instead.
    Defaults to the active ISM version.
    """
    conn = _conn()
    results = store.search(conn, query, limit=_clamp_limit(limit), version=version)
    return json.dumps(
        {"query": query, "count": len(results), "results": [c.as_dict() for c in results]},
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
def ism_list_by_classification(classification: str, version: str | None = None) -> str:
    """List controls that apply at a given classification level. Allowed values: NC, OS, P, S, TS."""
    conn = _conn()
    try:
        results = store.list_by_classification(conn, classification, version=version)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps(
        {
            "classification": classification.upper(),
            "count": len(results),
            "identifiers": [c.identifier for c in results],
        },
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
def ism_list_topics(version: str | None = None) -> str:
    """List all distinct topic strings present in the ISM.

    The vocabulary for the `topic` argument of ism_list_by_topic.
    """
    conn = _conn()
    topics = store.list_topics(conn, version=version)
    return json.dumps({"count": len(topics), "topics": topics}, indent=2)


@mcp.tool(annotations=READ_ONLY)
def ism_list_by_topic(topic: str, version: str | None = None) -> str:
    """List controls under a specific topic (exact match, use `ism_list_topics` to enumerate)."""
    conn = _conn()
    results = store.list_by_topic(conn, topic, version=version)
    return json.dumps(
        {"topic": topic, "count": len(results), "identifiers": [c.identifier for c in results]},
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
def ism_stats() -> str:
    """Report database statistics: active version, total versions, and control count."""
    conn = _conn()
    active = store.get_active_version(conn)
    row = store.get_version(conn, active) if active else None
    return json.dumps(
        {
            "active_version": active,
            "versions": len(store.list_versions(conn)),
            "controls": store.count_controls(conn) if active else 0,
            "oscal_version": row["oscal_version"] if row else None,
            "git_tag": row["git_tag"] if row else None,
            "db_path": str(_active_db()),
        },
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
def ism_versions() -> str:
    """List loaded ISM versions, newest first. The vocabulary for version/from/to arguments."""
    conn = _conn()
    active = store.get_active_version(conn)
    versions = store.list_versions(conn)
    return json.dumps(
        {
            "active": active,
            "count": len(versions),
            "versions": [
                {
                    "version": v["version"],
                    "label": v["label"],
                    "published": v["published"],
                    "control_count": v["control_count"],
                    "git_tag": v["git_tag"],
                    "is_active": v["version"] == active,
                }
                for v in versions
            ],
        },
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
def ism_list_sections(version: str | None = None) -> str:
    """List the distinct ISM Section values, the vocabulary for the `tags` filter on `ism_applicable`."""
    conn = _conn()
    sections = store.list_sections(conn, version=version)
    return json.dumps({"count": len(sections), "sections": sections}, indent=2)


@mcp.tool(annotations=READ_ONLY)
def ism_list_classifications() -> str:
    """Return the classification enum (canonical abbreviations and friendly aliases)."""
    return json.dumps(
        {
            "canonical": ["NC", "OS", "P", "S", "TS"],
            "friendly": [
                "OFFICIAL",
                "OFFICIAL:Sensitive",
                "PROTECTED",
                "SECRET",
                "TOP_SECRET",
            ],
        },
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
def ism_list_maturities() -> str:
    """Return the Essential Eight maturity levels."""
    return json.dumps({"maturities": ["ML1", "ML2", "ML3"]}, indent=2)


@mcp.tool(annotations=READ_ONLY)
def ism_diff(
    from_version: str | None = None,
    to_version: str | None = None,
    change_types: list[str] | None = None,
) -> str:
    """Catalog delta between two ISM versions.

    Defaults compare the version before active (from) to the active version (to), so a
    bare call answers 'what changed in the latest release'. `change_types` narrows the
    buckets (added, removed, reworded, retitled, moved, applicability_changed,
    maturity_changed). Use ism_versions to see loadable versions.
    """
    conn = _conn()
    versions = [v["version"] for v in store.list_versions(conn)]  # newest first
    if len(versions) < 2 and (from_version is None or to_version is None):
        return json.dumps(
            {"error": "need two versions to diff", "hint": "load history with ingest-history"}
        )
    to_v = to_version or store.get_active_version(conn) or versions[0]
    if from_version is not None:
        from_v = from_version
    else:
        later = [v for v in versions if v < to_v]
        from_v = later[0] if later else None
    if from_v is None:
        return json.dumps({"error": "no earlier version to compare against to_version"})
    for v in (from_v, to_v):
        if store.get_version(conn, v) is None:
            return json.dumps({"error": f"no such version: {v}", "hint": "call ism_versions"})

    result = diff.diff_controls(store.list_controls(conn, from_v), store.list_controls(conn, to_v))
    if change_types:
        result = {
            "summary": {k: v for k, v in result["summary"].items() if k in change_types},
            "changes": {k: v for k, v in result["changes"].items() if k in change_types},
        }
    return json.dumps({"from": from_v, "to": to_v, **result}, indent=2)


@mcp.tool(annotations=READ_ONLY)
def ism_history(identifier: str) -> str:
    """Show one control's evolution across every loaded ISM version.

    Returns a chronological timeline of changes to that single control. For the
    whole-catalog delta between two versions, use ism_diff instead.
    """
    conn = _conn()
    versions = [v["version"] for v in store.list_versions(conn)]
    order = sorted(versions)  # chronological, ascending
    canon = None
    for v in reversed(order):
        canon = store.normalise_identifier(conn, identifier, version=v)
        if canon is not None:
            break
    if canon is None:
        return json.dumps(
            {
                "identifier": identifier,
                "timeline": [],
                "hint": "no control with that id in any version",
            }
        )
    by_version = {v: store.get_control(conn, canon, version=v) for v in order}
    return json.dumps(diff.build_history(canon, order, by_version), indent=2)


@mcp.tool(annotations=READ_ONLY)
def ism_applicable(
    work: str,
    classification: str | None = None,
    maturity: str | None = None,
    tags: list[str] | None = None,
    paths: list[str] | None = None,
    limit: int = 20,
    verbose: bool = False,
) -> str:
    """Rank ISM controls relevant to a free-text description of planned or current work.

    The primary discovery tool. Describe the work in a sentence or two and it returns
    the most relevant controls. For exact keyword or phrase lookup, use ism_search.
    Uses hybrid retrieval (semantic embeddings + FTS5 BM25) fused with Reciprocal Rank Fusion.
    Optional filters: classification (NC|OS|P|S|TS or OFFICIAL|...|TOP_SECRET),
    maturity (ML1|ML2|ML3, Essential Eight only: only ~126 of 1081 controls carry a maturity rating,
    so passing maturity drops every other control; leave it unset unless scoping to the Essential Eight),
    tags (validated against ism_list_sections), paths (repo paths whose tokens expand the lexical query).
    `score` in each result is a normalised RRF score in [0.0, 1.0], not a probability.
    """
    conn = _conn()

    try:
        norm_classification = (
            cls.normalise_classification(classification) if classification else None
        )
    except ValueError as e:
        return json.dumps({"error": f"classification: {e}"})

    try:
        norm_maturity = cls.normalise_maturity(maturity) if maturity else None
    except ValueError as e:
        return json.dumps({"error": f"maturity: {e}"})

    valid_sections = set(store.list_sections(conn))
    if tags:
        unknown = [t for t in tags if t not in valid_sections]
        if unknown:
            return json.dumps(
                {"error": f"unknown tags: {unknown}. Use ism_list_sections() to discover."}
            )

    expanded_terms, matched_path_tokens = repo_paths.expand_paths(paths or [])
    lexical_query = " ".join([work, *sorted(expanded_terms)]) if expanded_terms else work

    lex_results = store.search(conn, lexical_query, limit=50)
    lex_ranking = [(c.identifier, 0.0) for c in lex_results]

    sem_ranking: list[tuple[str, float]] = []
    semantic_used = False
    idx = _vector_index(conn)
    embedder = _embedder()
    if idx is not None and embedder is not None:
        q_vec = embedder.embed([work])[0]
        sem_ranking = idx.search(q_vec, top_k=50)
        semantic_used = True

    fused = retrieve.rrf([lex_ranking, sem_ranking] if semantic_used else [lex_ranking], k=60)
    candidates_before_filter = len(fused)

    lex_ids = {rid for rid, _ in lex_ranking}
    sem_ids = {rid for rid, _ in sem_ranking}
    path_keywords = repo_paths.token_keywords(matched_path_tokens)
    matches = _materialise(conn, fused, lex_ids, sem_ids, path_keywords, semantic_used)
    matches = _apply_filters(matches, norm_classification, norm_maturity, tags)
    matches = matches[: _clamp_limit(limit)]

    response: dict = {
        "query": work,
        "filters": {
            "classification": norm_classification,
            "maturity": norm_maturity,
            "tags": tags or [],
            "paths": paths or [],
        },
        "count": len(matches),
        "candidates_before_filter": candidates_before_filter,
        "results": [_render_result(m, verbose) for m in matches],
    }
    if not matches and candidates_before_filter > 0:
        response["hint"] = (
            f"filters eliminated {candidates_before_filter} candidates. "
            "Relax classification, maturity, or tags."
        )
    return json.dumps(response, indent=2)


_WORD_RE = re.compile(r"\w+")
_TEXT_FIELDS = ("description", "topic", "section", "guideline")


def _materialise(
    conn,
    fused: list[tuple[str, float]],
    lex_ids: set[str],
    sem_ids: set[str],
    path_keywords: dict[str, set[str]],
    semantic_used: bool,
) -> list[dict]:
    version = store.get_active_version(conn)
    out: list[dict] = []
    for identifier, score in fused:
        row = conn.execute(
            "SELECT * FROM controls WHERE version = ? AND identifier = ?",
            (version, identifier),
        ).fetchone()
        if row is None:
            continue
        why: list[str] = []
        if semantic_used and identifier in sem_ids:
            why.append("semantic")
        if identifier in lex_ids:
            why.append("lexical")
        if path_keywords:
            words = {w for f in _TEXT_FIELDS for w in _WORD_RE.findall(str(row[f]).lower())}
            for token in sorted(path_keywords):
                if path_keywords[token] & words:
                    why.append(f"path:{token}")
        out.append({"row": row, "score": float(score), "why": why})
    return out


def _apply_filters(
    matches: list[dict],
    classification: str | None,
    maturity: str | None,
    tags: list[str] | None,
) -> list[dict]:
    filtered: list[dict] = []
    for m in matches:
        r = m["row"]
        if classification and not r[f"applies_{classification.lower()}"]:
            continue
        if maturity and not r[f"maturity_{maturity.lower()}"]:
            continue
        if tags and r["section"] not in tags:
            continue
        filtered.append(m)
    return filtered


def _render_result(m: dict, verbose: bool) -> dict:
    r = m["row"]
    base = {
        "identifier": r["identifier"],
        "label": r["label"],
        "title": r["title"],
        "topic": r["topic"],
        "section": r["section"],
        "description": r["description"],
        "applies": {c: bool(r[f"applies_{c.lower()}"]) for c in store.CLASSIFICATIONS},
        "maturity": {ml: bool(r[f"maturity_{ml.lower()}"]) for ml in store.MATURITIES},
        "score": round(m["score"], 4),
        "why": m["why"],
    }
    if verbose:
        base["guideline"] = r["guideline"]
    return base


def _find_manifest_or_error(project_path: str | None) -> tuple[Path | None, dict | None]:
    start = Path(project_path) if project_path else Path.cwd()
    found = coverage.find_manifest(start)
    if found is None:
        return None, {
            "error": "no manifest found",
            "hint": (
                "create .ism-coverage.toml at the project root with at minimum a [scope] section"
            ),
        }
    return found, None


def _manifest_to_json(manifest: coverage.Manifest, status_filter: str | None) -> dict:
    controls = {}
    summary = {
        "total_curated": len(manifest.controls),
        "covered": 0,
        "partial": 0,
        "not_applicable": 0,
        "deferred": 0,
    }
    for ident, entry in manifest.controls.items():
        key = entry.status.replace("-", "_")
        summary[key] = summary.get(key, 0) + 1
        if status_filter is not None and entry.status != status_filter:
            continue
        controls[ident] = {
            "status": entry.status,
            "how_met": entry.how_met,
            "last_reviewed": entry.last_reviewed.isoformat(),
            "reviewed_against": entry.reviewed_against,
            "reviewed_by": entry.reviewed_by,
            "next_review": entry.next_review.isoformat() if entry.next_review else None,
            "files": entry.files,
            "commits": entry.commits,
            "urls": entry.urls,
            "attachments": entry.attachments,
        }
    return {
        "manifest_path": str(manifest.path),
        "scope": manifest.scope,
        "project": manifest.project,
        "summary": summary,
        "controls": controls,
        "warnings": manifest.warnings,
    }


@mcp.tool(annotations=READ_ONLY)
def ism_coverage_read(project_path: str | None = None, status_filter: str | None = None) -> str:
    """Read the project's coverage manifest (`.ism-coverage.toml`). Never writes.

    Returns scope, summary counts, and curated entries. Walks up from cwd to find the
    manifest if `project_path` is omitted. `status_filter` narrows the controls map to a
    single status (`covered|partial|not-applicable|deferred`) while summary stays unfiltered.
    """
    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None
    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    conn = _conn()
    extra_warnings: list[str] = list(manifest.warnings)
    for ident in manifest.controls:
        if store.get_control(conn, ident) is None:
            extra_warnings.append(f"{ident}: not present in the current ISM revision")
    manifest = coverage.Manifest(
        path=manifest.path,
        schema_version=manifest.schema_version,
        scope=manifest.scope,
        project=manifest.project,
        controls=manifest.controls,
        warnings=extra_warnings,
    )

    return json.dumps(_manifest_to_json(manifest, status_filter), indent=2)


def _is_in_scope(scope: dict, control) -> bool:
    sections = scope.get("sections")
    if sections and control.section not in sections:
        return False
    classification = scope.get("classification")
    if classification:
        try:
            normalised = cls.normalise_classification(classification)
        except ValueError:
            return True  # malformed scope shouldn't prevent inserts
        if not control.applies.get(normalised, False):
            return False
    maturity = scope.get("maturity")
    if maturity:
        try:
            normalised_m = cls.normalise_maturity(maturity)
        except ValueError:
            return True
        if not control.maturity.get(normalised_m, False):
            return False
    return True


@mcp.tool(annotations=WRITES_MANIFEST)
def ism_coverage_upsert(
    identifier: str,
    status: str,
    how_met: str,
    last_reviewed: str | None = None,
    reviewed_by: str | None = None,
    next_review: str | None = None,
    reviewed_against: str | None = None,
    files: list[str] | None = None,
    commits: list[str] | None = None,
    urls: list[dict] | None = None,
    attachments: list[dict] | None = None,
    project_path: str | None = None,
) -> str:
    """Create or update one entry in the coverage manifest (`.ism-coverage.toml`).

    The only tool that writes to disk. It rewrites the manifest file atomically and an
    existing entry for the identifier is replaced whole. Validates identifier against
    the ISM DB, validates status enum, validates that every attachment path resolves on
    disk and that every url and attachment carries a description. `last_reviewed`
    defaults to today.
    """
    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None

    conn = _conn()
    control = store.get_control(conn, identifier)
    if control is None:
        return json.dumps(
            {
                "error": (
                    f"no such control: {identifier}. "
                    "Use ism_search or ism_list_topics to find the right id."
                )
            }
        )

    try:
        last_reviewed_date = _date.fromisoformat(last_reviewed) if last_reviewed else _date.today()
        next_review_date = _date.fromisoformat(next_review) if next_review else None
    except ValueError as e:
        return json.dumps({"error": f"date format: {e}"})

    entry = coverage.ManifestEntry(
        identifier=identifier,
        status=status,  # type: ignore[arg-type]
        how_met=how_met,
        last_reviewed=last_reviewed_date,
        reviewed_by=reviewed_by,
        next_review=next_review_date,
        reviewed_against=reviewed_against or store.get_active_version(conn),
        files=list(files or []),
        commits=list(commits or []),
        urls=list(urls or []),
        attachments=list(attachments or []),
    )

    try:
        result = coverage.upsert_entry(path, entry)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)})

    manifest = coverage.read_manifest(path)
    result["warnings"].extend(manifest.warnings)
    if not _is_in_scope(manifest.scope, control):
        result["warnings"].append(f"{identifier}: identifier is outside declared scope")

    return json.dumps(result, indent=2)


@mcp.tool(annotations=READ_ONLY)
def ism_coverage_gaps(
    work: str | None = None,
    project_path: str | None = None,
    limit: int = 50,
) -> str:
    """Return outstanding in-scope controls (uncurated, partial, deferred). Never writes.

    The complement of ism_coverage_read: read reports what is curated, gaps reports
    what is missing. Reads the manifest (`.ism-coverage.toml`), walking up from cwd
    when `project_path` is omitted. If `work` is supplied, runs `ism_applicable` with
    the project's scope as filters and intersects with the manifest to return
    work-relevant gaps ranked by relevance score. Without `work`, returns the full
    outstanding set ordered uncurated > partial > deferred.
    """
    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None

    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    conn = _conn()
    try:
        in_scope = store.list_in_scope(
            conn,
            classification=manifest.scope.get("classification"),
            maturity=manifest.scope.get("maturity"),
            sections=manifest.scope.get("sections"),
        )
    except ValueError as e:
        return json.dumps({"error": f"scope: {e}"})

    applicable: list[dict] | None = None
    if work is not None:
        raw = json.loads(
            ism_applicable(
                work,
                classification=manifest.scope.get("classification"),
                maturity=manifest.scope.get("maturity"),
                tags=manifest.scope.get("sections"),
                limit=200,
            )
        )
        if "error" in raw:
            return json.dumps({"error": f"ism_applicable: {raw['error']}"})
        applicable = raw.get("results") or []

    result = coverage.compute_gaps(
        manifest,
        in_scope,
        applicable=applicable,
        limit=_clamp_limit(limit),
        canonical=lambda i: store.normalise_identifier(conn, i) or i,
    )
    return json.dumps(
        {
            "scope": manifest.scope,
            "work": work,
            **result,
        },
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
def ism_coverage_impact(
    project_path: str | None = None,
    target_version: str | None = None,
    limit: int = 50,
) -> str:
    """Report what a newer ISM version means for the project's coverage. Never writes.

    Buckets covered/partial entries into re_review (control changed since it was assessed),
    removed_upstream (control gone at target), and new_uncovered (now in scope, no entry).
    `target_version` defaults to scope.baseline_version or the active version.
    """
    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None
    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    conn = _conn()
    target = (
        target_version or manifest.scope.get("baseline_version") or store.get_active_version(conn)
    )
    if target is None or store.get_version(conn, target) is None:
        return json.dumps(
            {"error": f"no such target version: {target}", "hint": "call ism_versions"}
        )

    try:
        in_scope_target = store.list_in_scope(
            conn,
            classification=manifest.scope.get("classification"),
            maturity=manifest.scope.get("maturity"),
            sections=manifest.scope.get("sections"),
            version=target,
        )
    except ValueError as e:
        return json.dumps({"error": f"scope: {e}"})

    def lookup(version: str, identifier: str):
        return store.get_control(conn, identifier, version=version)

    result = coverage.compute_impact(
        manifest=manifest,
        target_version=target,
        lookup=lookup,
        in_scope_target=in_scope_target,
        changed_fields=diff.changed_fields,
        diff_text=diff.unified_diff,
        limit=_clamp_limit(limit),
        canonical=lambda i: store.normalise_identifier(conn, i) or i,
    )
    return json.dumps({"manifest_path": str(path), **result}, indent=2)


def run() -> None:
    mcp.run()
