"""Output schemas, enum parameters, and wire-level structured results."""

from __future__ import annotations

import asyncio

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from ism_mcp import server, store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls

V_OLD = "2025.12.9"
V_NEW = "2026.03.24"

SEED_TOML = """\
schema_version = 1

[scope]
classification = "S"
sections = ["Encryption", "Audit"]
baseline_version = "2026.03.24"

[controls."ism-9001"]
status = "covered"
how_met = "Network is encrypted."
last_reviewed = 2026-05-28
reviewed_against = "2025.12.9"
"""

TOOL_NAMES = [
    "ism_get",
    "ism_search",
    "ism_list_by_classification",
    "ism_list_topics",
    "ism_list_by_topic",
    "ism_stats",
    "ism_versions",
    "ism_list_sections",
    "ism_list_classifications",
    "ism_list_maturities",
    "ism_diff",
    "ism_history",
    "ism_applicable",
    "ism_coverage_read",
    "ism_coverage_upsert",
    "ism_coverage_gaps",
    "ism_coverage_impact",
]


@pytest.fixture
def two_version_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    old = []
    for c in sample_controls:
        if c.identifier == "ism-9003":
            continue
        fields = {**c.__dict__, "version": V_OLD}
        if c.identifier == "ism-9001":
            fields["title"] = "Old title: ism-9001"
        if c.identifier == "ism-9002":
            fields["section"] = "Legacy"
            fields["topic"] = "Old sessions"
            fields["guideline"] = "Old guidelines"
            fields["description"] = "Sessions are terminated after sixty minutes."
            fields["applies"] = {"NC": True, "OS": True, "P": True, "S": True, "TS": True}
            fields["maturity"] = {"ML1": False, "ML2": True, "ML3": True}
        old.append(store.Control(**fields))
    store.insert_controls(conn, old)
    store.insert_controls(conn, sample_controls)
    for version, count in ((V_OLD, len(old)), (V_NEW, len(sample_controls))):
        store.upsert_version(
            conn,
            version=version,
            label=None,
            published=None,
            last_modified=None,
            oscal_version="1.1.2",
            git_tag=None,
            git_commit=None,
            ingested_at="2026-06-04T00:00:00Z",
            control_count=count,
        )
    store.set_active_version(conn, V_NEW)
    embedder = DeterministicHashEmbedder(dim=384)
    rows = [(V_NEW, ident, blob) for ident, blob in embed_controls(sample_controls, embedder)]
    store.insert_embeddings(conn, rows)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "hash")
    server._reset_runtime_cache()
    yield tmp_path
    server._reset_runtime_cache()


@pytest.fixture
def project_dir(two_version_db, monkeypatch):
    manifest = two_version_db / ".ism-coverage.toml"
    manifest.write_text(SEED_TOML)
    monkeypatch.chdir(two_version_db)
    return two_version_db


def _list_tools() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def _wire_call(name: str, arguments: dict):
    async def go():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as session:
            return await session.call_tool(name, arguments)

    return asyncio.run(go())


def _sc(res) -> dict:
    assert res.structuredContent is not None
    return res.structuredContent


def _text(res) -> str:
    block = res.content[0]
    assert isinstance(block, TextContent)
    return block.text


def test_every_tool_publishes_an_object_schema():
    tools = _list_tools()
    assert set(tools) == set(TOOL_NAMES)
    for name, tool in tools.items():
        schema = tool.outputSchema
        assert schema is not None, name
        assert schema.get("type") == "object", name
        assert list(schema.get("properties", {})) != ["result"], name


def test_enum_parameters_render_in_input_schema():
    tools = _list_tools()
    classification = tools["ism_list_by_classification"].inputSchema["properties"]["classification"]
    assert classification["enum"] == ["NC", "OS", "P", "S", "TS"]
    status = tools["ism_coverage_upsert"].inputSchema["properties"]["status"]
    assert status["enum"] == ["covered", "partial", "not-applicable", "deferred"]
    change_types = tools["ism_diff"].inputSchema["properties"]["change_types"]
    enum_items = change_types["anyOf"][0]["items"]["enum"]
    assert "applicability_changed" in enum_items


def test_diff_schema_carries_keyword_keys():
    tools = _list_tools()
    schema = tools["ism_diff"].outputSchema
    assert schema is not None
    assert "from" in schema["properties"]
    assert "to" in schema["properties"]
    assert "from" in schema["$defs"]["RetitledEntry"]["properties"]
    assert "from" in schema["$defs"]["MovedEntry"]["properties"]


def test_wire_lookup_family_round_trips(two_version_db):
    res = _wire_call("ism_get", {"identifier": "ISM-9001"})
    assert res.isError is False
    assert res.structuredContent == server.ism_get("ISM-9001")
    res = _wire_call("ism_stats", {})
    assert res.isError is False
    assert res.structuredContent == server.ism_stats()
    res = _wire_call("ism_versions", {})
    assert res.isError is False
    assert res.structuredContent == server.ism_versions()


def test_wire_diff_and_history_round_trip(two_version_db):
    res = _wire_call("ism_diff", {})
    assert res.isError is False
    assert res.structuredContent == server.ism_diff()
    assert _sc(res)["from"] == V_OLD
    changes = _sc(res)["changes"]
    assert changes["retitled"][0]["from"] == "Old title: ism-9001"
    assert changes["moved"][0]["from"]["section"] == "Legacy"
    assert changes["reworded"][0]["diff"]
    assert set(changes["applicability_changed"][0]["removed"]) == {"S", "TS"}
    assert changes["maturity_changed"][0]["added"] == ["ML1"]
    filtered = _wire_call("ism_diff", {"change_types": ["added"]})
    assert filtered.isError is False
    assert _sc(filtered)["changes"]["reworded"] is None
    res = _wire_call("ism_history", {"identifier": "ism-9001"})
    assert res.isError is False
    assert res.structuredContent == server.ism_history("ism-9001")


def test_wire_applicable_round_trips_with_null_conditionals(two_version_db):
    res = _wire_call("ism_applicable", {"work": "network encryption", "limit": 5})
    assert res.isError is False
    assert res.structuredContent == server.ism_applicable("network encryption", limit=5)
    sc = _sc(res)
    assert sc["hint"] is None
    assert all(r["guideline"] is None for r in sc["results"])


def test_wire_coverage_family_round_trips(project_dir):
    res = _wire_call("ism_coverage_read", {})
    assert res.isError is False
    assert res.structuredContent == server.ism_coverage_read()
    res = _wire_call("ism_coverage_gaps", {})
    assert res.isError is False
    gaps = _sc(res)
    assert gaps == server.ism_coverage_gaps()
    assert gaps["gaps"][0]["identifier"] == "ism-9003"
    assert gaps["gaps"][0]["current_entry"] is None
    assert gaps["gaps"][0]["score"] is None
    res = _wire_call("ism_coverage_impact", {})
    assert res.isError is False
    assert res.structuredContent == server.ism_coverage_impact()
    impact = _sc(res)
    assert impact["re_review"][0]["changes"] == ["retitled"]
    assert impact["re_review"][0]["diff"] is None
    res = _wire_call(
        "ism_coverage_upsert",
        {"identifier": "ism-9002", "status": "covered", "how_met": "done"},
    )
    assert res.isError is False
    assert _sc(res)["action"] == "created"


def test_wire_out_of_enum_input_is_rejected(two_version_db):
    res = _wire_call("ism_applicable", {"work": "x", "classification": "official sensitive"})
    assert res.isError is True
    res = _wire_call("ism_list_by_classification", {"classification": "nc"})
    assert res.isError is True
    res = _wire_call(
        "ism_coverage_upsert",
        {"identifier": "ism-9001", "status": "bogus", "how_met": "x"},
    )
    assert res.isError is True
    res = _wire_call("ism_applicable", {"work": "x", "maturity": "2"})
    assert res.isError is True
    assert "unknown maturity" not in _text(res)
    res = _wire_call("ism_diff", {"change_types": ["renamed"]})
    assert res.isError is True
    assert "no such version" not in _text(res)


def test_wire_tool_error_reaches_client_as_is_error(two_version_db):
    res = _wire_call("ism_get", {"identifier": "ism-0000"})
    assert res.isError is True
    assert "no such control" in _text(res)


def test_gaps_propagates_applicable_error_with_prefix(two_version_db, monkeypatch):
    manifest = two_version_db / ".ism-coverage.toml"
    manifest.write_text(SEED_TOML.replace('sections = ["Encryption", "Audit"]', ""))
    monkeypatch.chdir(two_version_db)

    def boom(*args, **kwargs):
        raise server.ToolError("classification: synthetic failure")

    monkeypatch.setattr(server, "_applicable_result", boom)
    res = _wire_call("ism_coverage_gaps", {"work": "anything"})
    assert res.isError is True
    assert "ism_applicable: classification: synthetic failure" in _text(res)
