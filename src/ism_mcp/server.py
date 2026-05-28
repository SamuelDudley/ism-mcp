"""MCP server exposing ISM lookup tools."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import store

DEFAULT_DB = Path(os.environ.get("ISM_MCP_DB", Path.home() / ".local/share/ism-mcp/ism.db"))


mcp = FastMCP("ism-mcp")


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


def run() -> None:
    mcp.run()
