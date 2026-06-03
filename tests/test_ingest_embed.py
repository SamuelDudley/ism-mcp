"""End-to-end ingest with the deterministic hash embedder."""

from __future__ import annotations

import numpy as np
import openpyxl

from ism_mcp import store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls, parse_xlsx


def _write_workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Controls - January 2026"
    ws.append(["ISM Controls"] + [""] * 24)
    ws.append(
        [
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
            "x",
            "x",
            "x",
            "x",
            "x",
            "x",
            "x",
            "x",
            "x",
            "x",
        ]
    )
    ws.append(
        [
            "Guidelines for testing",
            "Encryption",
            "Network encryption",
            "ISM-9001",
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
            "All data communicated over network infrastructure is encrypted.",
            "",
            "",
            "",
            "",
            "Not Assessed",
            "",
            "",
            "Not Assessed",
            "Not Assessed",
            "",
        ]
    )
    wb.save(path)


def test_embed_controls_yields_normalised_blobs(tmp_path):
    workbook = tmp_path / "ccm.xlsx"
    _write_workbook(workbook)
    controls = list(parse_xlsx(workbook))
    embedder = DeterministicHashEmbedder(dim=384)
    rows = list(embed_controls(controls, embedder))
    assert len(rows) == 1
    rowid, blob = rows[0]
    assert rowid == 1
    assert len(blob) == 384 * 4


def test_ingest_round_trip_persists_embeddings(tmp_path):
    workbook = tmp_path / "ccm.xlsx"
    _write_workbook(workbook)
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, list(parse_xlsx(workbook)))
    controls_after = [c for c in [store.get_control(conn, "ISM-9001")] if c is not None]
    embedder = DeterministicHashEmbedder(dim=384)
    rows = list(embed_controls(controls_after, embedder))
    store.insert_embeddings(conn, rows)
    matrix, ids = store.load_embedding_matrix(conn, dim=384)
    assert matrix.shape == (1, 384)
    assert ids == [1]


def test_embed_controls_rowid_aligns_with_control_text(db, sample_controls):
    store.insert_controls(db, sample_controls)
    fetched = [c for c in (store.get_control(db, c.identifier) for c in sample_controls) if c]
    embedder = DeterministicHashEmbedder(dim=384)
    store.insert_embeddings(db, list(embed_controls(fetched, embedder)))
    matrix, ids = store.load_embedding_matrix(db, dim=384)
    rowid_by_id = {
        r["identifier"]: r["rowid"] for r in db.execute("SELECT rowid, identifier FROM controls")
    }
    # The embedding stored at a control's rowid must be that control's own text vector,
    # so a positional misalignment between embed order and rowid would fail here.
    target = store.get_control(db, "ISM-9002")
    assert target is not None
    text = (
        f"{target.topic}. {target.section}. {target.description} {(target.pdf_excerpt or '')[:500]}"
    )
    expected = embedder.embed([text])[0]
    pos = ids.index(rowid_by_id["ISM-9002"])
    np.testing.assert_allclose(matrix[pos], expected, atol=1e-6)
