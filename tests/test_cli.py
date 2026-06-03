"""CLI orchestration: the ingest and serve subcommands."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import openpyxl

from ism_mcp import __main__ as cli
from ism_mcp import ingest, server, store
from tests.test_excerpt_extraction import _FakePage, _FakePdf

HEADERS = [
    "Guideline",
    "Section",
    "Topic",
    "Identifier",
    "Revision",
    "Updated",
    "NC",
    "OS",
    "P",
    "S",
    "TS",
    "ML1",
    "ML2",
    "ML3",
    "Description",
]


def _row(identifier: str, section: str, topic: str, description: str) -> list[str]:
    return [
        "Guidelines for testing",
        section,
        topic,
        identifier,
        "1",
        "Jan-26",
        "Yes",
        "Yes",
        "Yes",
        "No",
        "No",
        "Yes",
        "No",
        "No",
        description,
    ]


def _write_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Controls - January 2026"
    ws.append(["ISM Controls"])
    ws.append(HEADERS)
    ws.append(_row("ISM-9001", "Encryption", "Network encryption", "Data is encrypted in transit."))
    ws.append(_row("ISM-9002", "Authentication", "Session management", "Sessions terminate."))
    wb.save(path)


def _ingest_args(**kw) -> argparse.Namespace:
    base = dict(xlsx=None, pdf=None, db=None, revision=None, no_embeddings=True)
    base.update(kw)
    return argparse.Namespace(**base)


def test_cmd_ingest_no_embeddings_writes_db_and_meta(tmp_path):
    xlsx = tmp_path / "ccm.xlsx"
    _write_workbook(xlsx)
    db_path = tmp_path / "ism.db"
    rc = cli.cmd_ingest(_ingest_args(xlsx=str(xlsx), db=str(db_path), revision="2026-03"))
    assert rc == 0
    conn = store.open_db(db_path)
    assert store.count_controls(conn) == 2
    assert store.get_meta(conn, "ism_revision") == "2026-03"
    assert store.get_meta(conn, "xlsx_source") == str(xlsx)
    _matrix, ids = store.load_embedding_matrix(conn, dim=384)
    assert ids == []
    conn.close()


def test_cmd_ingest_attaches_pdf_excerpts(tmp_path, monkeypatch):
    xlsx = tmp_path / "ccm.xlsx"
    _write_workbook(xlsx)
    pages = [_FakePage("Data is encrypted in transit.\nControl: ISM-9001; Revision: 1")]
    monkeypatch.setattr(ingest.pdfplumber, "open", lambda _p: _FakePdf(pages))
    db_path = tmp_path / "ism.db"
    rc = cli.cmd_ingest(
        _ingest_args(xlsx=str(xlsx), pdf=str(tmp_path / "ism.pdf"), db=str(db_path))
    )
    assert rc == 0
    conn = store.open_db(db_path)
    c = store.get_control(conn, "ISM-9001")
    assert c is not None and c.pdf_excerpt is not None
    assert "encrypted in transit" in c.pdf_excerpt
    assert store.get_meta(conn, "pdf_source") == str(tmp_path / "ism.pdf")
    conn.close()


def test_cmd_serve_sets_runtime_db_and_runs(tmp_path, monkeypatch):
    # setenv (not delenv) so monkeypatch owns the key and restores it on teardown,
    # even though cmd_serve writes os.environ directly.
    monkeypatch.setenv("ISM_MCP_DB", str(tmp_path / "placeholder.db"))
    ran = {}
    monkeypatch.setattr(server, "run", lambda: ran.setdefault("ran", True))
    custom = tmp_path / "custom.db"
    rc = cli.cmd_serve(argparse.Namespace(db=str(custom)))
    assert rc == 0
    assert ran.get("ran") is True
    assert os.environ["ISM_MCP_DB"] == str(custom)
    assert server._active_db() == custom
