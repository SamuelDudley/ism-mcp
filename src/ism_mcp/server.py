"""MCP server exposing ISM lookup tools."""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
from datetime import date as _date
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import classification as cls
from . import coverage, diff, models, retrieve, store
from . import paths as repo_paths
from .embed import DeterministicHashEmbedder, Embedder, FastEmbedEmbedder

DEFAULT_DB = Path(os.environ.get("ISM_MCP_DB", Path.home() / ".local/share/ism-mcp/ism.db"))

MAX_LIMIT = 200


mcp = FastMCP(
    "ism-mcp",
    instructions=(
        "Query layer over a local SQLite copy of the ASD Information Security Manual "
        "(ISM), including Essential Eight maturity data. Every tool returns a typed "
        "structured result matching its published output schema, and failures arrive "
        "as tool errors (isError) with a message, never as error payloads. Data is as "
        "fresh as the last ingested ISM release (check with ism_stats). Every tool is "
        "read-only except ism_coverage_upsert, which edits the project's "
        ".ism-coverage.toml. No network access, auth, or rate limits."
    ),
)

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
def ism_get(identifier: str, version: str | None = None) -> models.ControlRecord:
    """Get the full record for one ISM control by identifier (e.g. `ism-1781`).

    Identifier input is tolerant: `ISM-1781`, bare `1781`, and legacy labels resolve
    to the canonical OSCAL id. Returns the control record with title, control text,
    section, topic, classification applicability, and Essential Eight maturity flags.
    Fails when nothing matches. Use ism_search or ism_applicable first when the
    identifier is unknown. Defaults to the active ISM version. Pass `version` (see
    ism_versions) for a historical one.
    """
    conn = _conn()
    c = store.get_control(conn, identifier, version=version)
    if c is None:
        raise ToolError(f"no such control: {identifier}")
    return c.as_dict()


@mcp.tool(annotations=READ_ONLY)
def ism_search(query: str, limit: int = 10, version: str | None = None) -> models.SearchResult:
    """Full-text keyword search (FTS5 BM25) over ISM control text and topics.

    Best when you already know the terms, an exact phrase, or part of a control title.
    To rank controls against a free-text description of work, use ism_applicable
    instead. FTS operators in the query are neutralised, so input matches literally.
    Returns `{query, count, results}` with full control records. `limit` defaults to
    10 (capped at 200). Defaults to the active ISM version.
    """
    conn = _conn()
    results = store.search(conn, query, limit=_clamp_limit(limit), version=version)
    return {"query": query, "count": len(results), "results": [c.as_dict() for c in results]}


@mcp.tool(annotations=READ_ONLY)
def ism_list_by_classification(
    classification: models.Classification, version: str | None = None
) -> models.ClassificationControls:
    """List controls that apply at a given classification level.

    `classification` takes canonical abbreviations only: NC, OS, P, S, or TS (see
    ism_list_classifications for the OFFICIAL through TOP_SECRET mapping). Returns
    `{classification, count, identifiers}` with ids only. Fetch full records with
    ism_get. An unknown level fails.
    """
    conn = _conn()
    try:
        results = store.list_by_classification(conn, classification, version=version)
    except ValueError as e:
        raise ToolError(str(e)) from e
    return {
        "classification": classification,
        "count": len(results),
        "identifiers": [c.identifier for c in results],
    }


@mcp.tool(annotations=READ_ONLY)
def ism_list_topics(version: str | None = None) -> models.TopicsList:
    """List all distinct topic strings present in the ISM.

    The vocabulary for the `topic` argument of ism_list_by_topic. Returns
    `{count, topics}` for the active version unless `version` is passed.
    """
    conn = _conn()
    topics = store.list_topics(conn, version=version)
    return {"count": len(topics), "topics": topics}


@mcp.tool(annotations=READ_ONLY)
def ism_list_by_topic(topic: str, version: str | None = None) -> models.TopicControls:
    """List controls under a specific topic (exact match, use ism_list_topics to enumerate).

    Returns `{topic, count, identifiers}` with ids only. Fetch full records with
    ism_get. An unknown topic returns an empty list, not an error.
    """
    conn = _conn()
    results = store.list_by_topic(conn, topic, version=version)
    return {"topic": topic, "count": len(results), "identifiers": [c.identifier for c in results]}


@mcp.tool(annotations=READ_ONLY)
def ism_stats() -> models.Stats:
    """Report database state: active ISM version, version and control counts, db path.

    Takes no arguments. Useful as a first call to confirm data is ingested and see
    which ISM release the other tools will answer from. For the full version list
    use ism_versions.
    """
    conn = _conn()
    active = store.get_active_version(conn)
    row = store.get_version(conn, active) if active else None
    return {
        "active_version": active,
        "versions": len(store.list_versions(conn)),
        "controls": store.count_controls(conn) if active else 0,
        "oscal_version": row["oscal_version"] if row else None,
        "git_tag": row["git_tag"] if row else None,
        "db_path": str(_active_db()),
    }


@mcp.tool(annotations=READ_ONLY)
def ism_versions() -> models.VersionsResult:
    """List loaded ISM versions, newest first. The vocabulary for version/from/to arguments.

    Returns `{active, count, versions}` where each entry carries version, label,
    published date, control_count, and git_tag. Call this before passing `version`,
    `from_version`, or `to_version` to other tools.
    """
    conn = _conn()
    active = store.get_active_version(conn)
    versions = store.list_versions(conn)
    return {
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
    }


@mcp.tool(annotations=READ_ONLY)
def ism_list_sections(version: str | None = None) -> models.SectionsList:
    """List the distinct ISM Section values, the vocabulary for the `tags` filter on ism_applicable.

    Returns `{count, sections}` for the active version unless `version` is passed.
    """
    conn = _conn()
    sections = store.list_sections(conn, version=version)
    return {"count": len(sections), "sections": sections}


@mcp.tool(annotations=READ_ONLY)
def ism_list_classifications() -> models.ClassificationVocab:
    """Return the classification vocabulary as parallel lists.

    `canonical[i]` (NC, OS, P, S, TS) pairs with `friendly[i]` (OFFICIAL through
    TOP_SECRET). ism_applicable accepts either form. ism_list_by_classification
    accepts canonical only. Static data, no database read.
    """
    return {
        "canonical": ["NC", "OS", "P", "S", "TS"],
        "friendly": [
            "OFFICIAL",
            "OFFICIAL:Sensitive",
            "PROTECTED",
            "SECRET",
            "TOP_SECRET",
        ],
    }


@mcp.tool(annotations=READ_ONLY)
def ism_list_maturities() -> models.MaturityVocab:
    """Return the Essential Eight maturity levels: ML1, ML2, ML3.

    The Essential Eight is the ASD's baseline set of mitigation strategies, and only
    controls belonging to it carry a maturity rating. These levels are the vocabulary
    for the `maturity` filter on ism_applicable and for coverage manifest scope.
    Static data, no database read.
    """
    return {"maturities": ["ML1", "ML2", "ML3"]}


@mcp.tool(annotations=READ_ONLY)
def ism_diff(
    from_version: str | None = None,
    to_version: str | None = None,
    change_types: list[models.ChangeType] | None = None,
) -> models.DiffResult:
    """Catalog delta between two ISM versions.

    Defaults compare the version before active (from) to the active version (to), so a
    bare call answers 'what changed in the latest release'. `change_types` narrows the
    buckets (added, removed, reworded, retitled, moved, applicability_changed,
    maturity_changed) and sets unrequested buckets to null. Returns
    `{from, to, summary, changes}`. Fails on unknown versions. Use ism_versions to see
    loadable versions, and ism_history for one control's timeline instead of the
    whole catalog.
    """
    conn = _conn()
    versions = [v["version"] for v in store.list_versions(conn)]  # newest first
    if len(versions) < 2 and (from_version is None or to_version is None):
        raise ToolError("need two versions to diff. load history with ingest-history")
    to_v = to_version or store.get_active_version(conn) or versions[0]
    if from_version is not None:
        from_v = from_version
    else:
        later = [v for v in versions if v < to_v]
        from_v = later[0] if later else None
    if from_v is None:
        raise ToolError("no earlier version to compare against to_version")
    for v in (from_v, to_v):
        if store.get_version(conn, v) is None:
            raise ToolError(f"no such version: {v}. call ism_versions")

    result = diff.diff_controls(store.list_controls(conn, from_v), store.list_controls(conn, to_v))
    summary = dict(result["summary"])
    changes = dict(result["changes"])
    if change_types:
        keep = set(change_types)
        summary = {k: (v if k in keep else None) for k, v in summary.items()}
        changes = {k: (v if k in keep else None) for k, v in changes.items()}
    return {"from": from_v, "to": to_v, "summary": summary, "changes": changes}  # type: ignore[typeddict-item]


@mcp.tool(annotations=READ_ONLY)
def ism_history(identifier: str) -> models.HistoryResult:
    """Show one control's evolution across every loaded ISM version.

    Returns a chronological timeline of changes to that single control. Identifier
    input is tolerant like ism_get. An unknown id returns an empty timeline with a
    hint rather than an error. For the whole-catalog delta between two versions,
    use ism_diff instead.
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
        return {
            "identifier": identifier,
            "first_seen": None,
            "last_seen": None,
            "timeline": [],
            "hint": "no control with that id in any version",
        }
    by_version = {v: store.get_control(conn, canon, version=v) for v in order}
    history = diff.build_history(canon, order, by_version)
    return {**history, "hint": None}  # type: ignore[typeddict-item]


@mcp.tool(annotations=READ_ONLY)
def ism_applicable(
    work: str,
    classification: models.ClassificationInput | None = None,
    maturity: models.Maturity | None = None,
    tags: list[str] | None = None,
    paths: list[str] | None = None,
    limit: int = 20,
    verbose: bool = False,
) -> models.ApplicableResult:
    """Rank ISM controls relevant to a free-text description of planned or current work.

    The primary discovery tool. Describe the work in a sentence or two and it returns
    the most relevant controls. For exact keyword or phrase lookup, use ism_search.
    Uses hybrid retrieval (semantic embeddings + FTS5 BM25) fused with Reciprocal
    Rank Fusion. Optional filters: classification (NC|OS|P|S|TS or OFFICIAL through
    TOP_SECRET), maturity (ML1|ML2|ML3, Essential Eight controls only, so leave it
    unset unless scoping to the Essential Eight), tags (validated against
    ism_list_sections), paths (repo paths whose tokens expand the lexical query).
    Invalid filter values fail. `limit` defaults to 20 (capped at 200). `verbose`
    populates each control's guideline text, null otherwise. `score` is a normalised
    RRF score in [0.0, 1.0], not a probability.
    """
    return _applicable_result(work, classification, maturity, tags, paths, limit, verbose)


def _applicable_result(
    work: str,
    classification: str | None = None,
    maturity: str | None = None,
    tags: list[str] | None = None,
    paths: list[str] | None = None,
    limit: int = 20,
    verbose: bool = False,
) -> models.ApplicableResult:
    conn = _conn()

    try:
        norm_classification = (
            cls.normalise_classification(classification) if classification else None
        )
    except ValueError as e:
        raise ToolError(f"classification: {e}") from e

    try:
        norm_maturity = cls.normalise_maturity(maturity) if maturity else None
    except ValueError as e:
        raise ToolError(f"maturity: {e}") from e

    valid_sections = set(store.list_sections(conn))
    if tags:
        unknown = [t for t in tags if t not in valid_sections]
        if unknown:
            raise ToolError(f"unknown tags: {unknown}. Use ism_list_sections() to discover.")

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

    hint = None
    if not matches and candidates_before_filter > 0:
        hint = (
            f"filters eliminated {candidates_before_filter} candidates. "
            "Relax classification, maturity, or tags."
        )
    return {
        "query": work,
        "filters": {
            "classification": norm_classification,  # type: ignore[typeddict-item]
            "maturity": norm_maturity,  # type: ignore[typeddict-item]
            "tags": tags or [],
            "paths": paths or [],
        },
        "count": len(matches),
        "candidates_before_filter": candidates_before_filter,
        "results": [_render_result(m, verbose) for m in matches],
        "hint": hint,
    }


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


def _render_result(m: dict, verbose: bool) -> models.ApplicableEntry:
    r = m["row"]
    return {
        "identifier": r["identifier"],
        "label": r["label"],
        "title": r["title"],
        "topic": r["topic"],
        "section": r["section"],
        "description": r["description"],
        "applies": {c: bool(r[f"applies_{c.lower()}"]) for c in store.CLASSIFICATIONS},  # type: ignore[typeddict-item]
        "maturity": {ml: bool(r[f"maturity_{ml.lower()}"]) for ml in store.MATURITIES},  # type: ignore[typeddict-item]
        "score": round(m["score"], 4),
        "why": m["why"],
        "guideline": r["guideline"] if verbose else None,
    }


def _find_manifest(project_path: str | None) -> Path:
    start = Path(project_path) if project_path else Path.cwd()
    found = coverage.find_manifest(start)
    if found is None:
        raise ToolError(
            "no manifest found. "
            "create .ism-coverage.toml at the project root with at minimum a [scope] section"
        )
    return found


def _manifest_to_json(
    manifest: coverage.Manifest, status_filter: str | None
) -> models.CoverageReadResult:
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
def ism_coverage_read(
    project_path: str | None = None, status_filter: models.Status | None = None
) -> models.CoverageReadResult:
    """Read the project's coverage manifest (`.ism-coverage.toml`). Never writes.

    Returns scope, summary counts, and curated entries. Walks up from cwd to find the
    manifest if `project_path` is omitted and fails when none is found.
    `status_filter` narrows the controls map to a single status
    (`covered|partial|not-applicable|deferred`) while summary stays unfiltered. To
    see what is missing rather than what is curated, use ism_coverage_gaps.
    """
    path = _find_manifest(project_path)
    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

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

    return _manifest_to_json(manifest, status_filter)


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
    status: models.Status,
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
) -> models.UpsertResult:
    """Create or update one entry in the coverage manifest (`.ism-coverage.toml`).

    The only tool that writes to disk. It rewrites the manifest file atomically and an
    existing entry for the identifier is replaced whole. `status` must be one of
    covered, partial, not-applicable, or deferred. Validates identifier against the
    ISM DB, requires every attachment path to resolve on disk and every url and
    attachment to carry a description. `last_reviewed` defaults to today. Returns the
    action taken plus warnings and fails on validation errors.
    """
    path = _find_manifest(project_path)

    conn = _conn()
    control = store.get_control(conn, identifier)
    if control is None:
        raise ToolError(
            f"no such control: {identifier}. "
            "Use ism_search or ism_list_topics to find the right id."
        )

    try:
        last_reviewed_date = _date.fromisoformat(last_reviewed) if last_reviewed else _date.today()
        next_review_date = _date.fromisoformat(next_review) if next_review else None
    except ValueError as e:
        raise ToolError(f"date format: {e}") from e

    entry = coverage.ManifestEntry(
        identifier=identifier,
        status=status,
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
    except (ValueError, FileNotFoundError) as e:
        raise ToolError(str(e)) from e

    manifest = coverage.read_manifest(path)
    result["warnings"].extend(manifest.warnings)
    if not _is_in_scope(manifest.scope, control):
        result["warnings"].append(f"{identifier}: identifier is outside declared scope")

    return result  # type: ignore[return-value]


@mcp.tool(annotations=READ_ONLY)
def ism_coverage_gaps(
    work: str | None = None,
    project_path: str | None = None,
    limit: int = 50,
) -> models.GapsResult:
    """Return outstanding in-scope controls (uncurated, partial, deferred). Never writes.

    The complement of ism_coverage_read: read reports what is curated, gaps reports
    what is missing. Reads the manifest (`.ism-coverage.toml`), walking up from cwd
    when `project_path` is omitted. If `work` is supplied, runs `ism_applicable` with
    the project's scope as filters and intersects with the manifest to return
    work-relevant gaps ranked by relevance score. Without `work`, returns the full
    outstanding set ordered uncurated > partial > deferred.
    """
    path = _find_manifest(project_path)

    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

    conn = _conn()
    try:
        in_scope = store.list_in_scope(
            conn,
            classification=manifest.scope.get("classification"),
            maturity=manifest.scope.get("maturity"),
            sections=manifest.scope.get("sections"),
        )
    except ValueError as e:
        raise ToolError(f"scope: {e}") from e

    applicable: list[models.ApplicableEntry] | None = None
    if work is not None:
        try:
            raw = _applicable_result(
                work,
                classification=manifest.scope.get("classification"),
                maturity=manifest.scope.get("maturity"),
                tags=manifest.scope.get("sections"),
                limit=200,
            )
        except ToolError as e:
            raise ToolError(f"ism_applicable: {e}") from e
        applicable = list(raw["results"])

    result = coverage.compute_gaps(
        manifest,
        in_scope,
        applicable=applicable,
        limit=_clamp_limit(limit),
        canonical=lambda i: store.normalise_identifier(conn, i) or i,
    )
    return {"scope": manifest.scope, "work": work, **result}  # type: ignore[typeddict-item]


@mcp.tool(annotations=READ_ONLY)
def ism_coverage_impact(
    project_path: str | None = None,
    target_version: str | None = None,
    limit: int = 50,
) -> models.ImpactResult:
    """Report what a newer ISM version means for the project's coverage. Never writes.

    Buckets covered/partial entries into re_review (control changed since it was
    assessed), removed_upstream (control gone at target), and new_uncovered (now in
    scope, no entry). `target_version` defaults to scope.baseline_version or the
    active version. Reads the manifest like ism_coverage_read, walking up from cwd
    when `project_path` is omitted. Run this after ingesting a new ISM release, then
    curate the buckets with ism_coverage_upsert.
    """
    path = _find_manifest(project_path)
    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

    conn = _conn()
    target = (
        target_version or manifest.scope.get("baseline_version") or store.get_active_version(conn)
    )
    if target is None or store.get_version(conn, target) is None:
        raise ToolError(f"no such target version: {target}. call ism_versions")

    try:
        in_scope_target = store.list_in_scope(
            conn,
            classification=manifest.scope.get("classification"),
            maturity=manifest.scope.get("maturity"),
            sections=manifest.scope.get("sections"),
            version=target,
        )
    except ValueError as e:
        raise ToolError(f"scope: {e}") from e

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
    return {"manifest_path": str(path), **result}  # type: ignore[typeddict-item]


def run() -> None:
    mcp.run()
