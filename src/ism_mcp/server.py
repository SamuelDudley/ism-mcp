"""MCP server exposing ISM lookup tools."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import classification as cls
from . import paths as repo_paths
from . import retrieve, store
from .embed import DeterministicHashEmbedder, Embedder, FastEmbedEmbedder

DEFAULT_DB = Path(os.environ.get("ISM_MCP_DB", Path.home() / ".local/share/ism-mcp/ism.db"))


mcp = FastMCP("ism-mcp")


_RUNTIME: dict[str, object] = {}


def _reset_runtime_cache() -> None:
    _RUNTIME.clear()


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
    matrix, ids = store.load_embedding_matrix(conn, dim=embedder.dim)
    if len(ids) == 0:
        return None
    idx = retrieve.VectorIndex(matrix, ids)
    _RUNTIME["vec_index"] = idx
    return idx


def _conn():
    if not DEFAULT_DB.exists():
        raise RuntimeError(
            f"ISM database not found at {DEFAULT_DB}. "
            "Run `ism-mcp ingest --xlsx PATH [--pdf PATH]` first."
        )
    return store.open_db(DEFAULT_DB)


@mcp.tool()
def ism_get(identifier: str) -> str:
    """Get the full record for one ISM control by its identifier (e.g. `ISM-1781`)."""
    conn = _conn()
    c = store.get_control(conn, identifier)
    if c is None:
        return json.dumps({"error": f"no such control: {identifier}"})
    return json.dumps(c.as_dict(), indent=2)


@mcp.tool()
def ism_search(query: str, limit: int = 10) -> str:
    """Full-text search over ISM control descriptions and topics. Returns up to `limit` matches ranked by relevance."""
    conn = _conn()
    results = store.search(conn, query, limit=limit)
    return json.dumps(
        {"query": query, "count": len(results), "results": [c.as_dict() for c in results]},
        indent=2,
    )


@mcp.tool()
def ism_list_by_classification(classification: str) -> str:
    """List controls that apply at a given classification level. Allowed values: NC, OS, P, S, TS."""
    conn = _conn()
    try:
        results = store.list_by_classification(conn, classification)
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


@mcp.tool()
def ism_list_topics() -> str:
    """List all distinct topic strings present in the ISM."""
    conn = _conn()
    topics = store.list_topics(conn)
    return json.dumps({"count": len(topics), "topics": topics}, indent=2)


@mcp.tool()
def ism_list_by_topic(topic: str) -> str:
    """List controls under a specific topic (exact match, use `ism_list_topics` to enumerate)."""
    conn = _conn()
    results = store.list_by_topic(conn, topic)
    return json.dumps(
        {"topic": topic, "count": len(results), "identifiers": [c.identifier for c in results]},
        indent=2,
    )


@mcp.tool()
def ism_stats() -> str:
    """Report database statistics: total controls, ISM revision metadata, source paths."""
    conn = _conn()
    return json.dumps(
        {
            "controls": store.count_controls(conn),
            "ism_revision": store.get_meta(conn, "ism_revision"),
            "xlsx_source": store.get_meta(conn, "xlsx_source"),
            "pdf_source": store.get_meta(conn, "pdf_source"),
            "db_path": str(DEFAULT_DB),
        },
        indent=2,
    )


@mcp.tool()
def ism_list_sections() -> str:
    """List the distinct ISM Section values, the vocabulary for the `tags` filter on `ism_applicable`."""
    conn = _conn()
    sections = store.list_sections(conn)
    return json.dumps({"count": len(sections), "sections": sections}, indent=2)


@mcp.tool()
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


@mcp.tool()
def ism_list_maturities() -> str:
    """Return the Essential Eight maturity levels."""
    return json.dumps({"maturities": ["ML1", "ML2", "ML3"]}, indent=2)


@mcp.tool()
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

    Uses hybrid retrieval (semantic embeddings + FTS5 BM25) fused with Reciprocal Rank Fusion.
    Optional filters: classification (NC|OS|P|S|TS or OFFICIAL|...|TOP_SECRET), maturity (ML1|ML2|ML3),
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
    lex_ranking = [(_rowid_for(conn, c.identifier), 0.0) for c in lex_results]

    sem_ranking: list[tuple[int, float]] = []
    semantic_used = False
    idx = _vector_index(conn)
    embedder = _embedder()
    if idx is not None and embedder is not None:
        q_vec = embedder.embed([work])[0]
        sem_ranking = idx.search(q_vec, top_k=50)
        semantic_used = True

    fused = retrieve.rrf([lex_ranking, sem_ranking] if semantic_used else [lex_ranking], k=60)
    candidates_before_filter = len(fused)

    matches = _materialise(conn, fused, lex_results, matched_path_tokens, semantic_used)
    matches = _apply_filters(matches, norm_classification, norm_maturity, tags)
    matches = matches[:limit]

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


def _rowid_for(conn, identifier: str) -> int:
    row = conn.execute("SELECT rowid FROM controls WHERE identifier = ?", (identifier,)).fetchone()
    return int(row["rowid"]) if row else -1


def _materialise(
    conn,
    fused: list[tuple[int, float]],
    lex_results: list,
    matched_path_tokens: set[str],
    semantic_used: bool,
) -> list[dict]:
    lex_ids = {_rowid_for(conn, c.identifier) for c in lex_results}
    sem_ids_in_top = {rid for rid, _ in fused} - lex_ids if semantic_used else set()
    out: list[dict] = []
    for rowid, score in fused:
        row = conn.execute("SELECT * FROM controls WHERE rowid = ?", (rowid,)).fetchone()
        if row is None:
            continue
        why: list[str] = []
        if semantic_used and rowid in sem_ids_in_top | lex_ids:
            why.append("semantic")
        if rowid in lex_ids:
            why.append("lexical")
        for token in sorted(matched_path_tokens):
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
        "topic": r["topic"],
        "section": r["section"],
        "description": r["description"],
        "applies": {c: bool(r[f"applies_{c.lower()}"]) for c in store.CLASSIFICATIONS},
        "maturity": {ml: bool(r[f"maturity_{ml.lower()}"]) for ml in store.MATURITIES},
        "score": round(m["score"], 4),
        "why": m["why"],
    }
    if verbose:
        base["pdf_excerpt"] = r["pdf_excerpt"]
        base["pdf_page"] = r["pdf_page"]
    return base


def run() -> None:
    mcp.run()
