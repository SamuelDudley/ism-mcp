"""Ingest the ASD ISM Cloud Controls Matrix XLSX and (optionally) the ISM PDF."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import openpyxl
import pdfplumber

from .embed import Embedder
from .store import CLASSIFICATIONS, MATURITIES, Control

CONTROLS_SHEET = "Controls - March 2026"
HEADER_ROW = 2
DATA_START_ROW = 3


def parse_xlsx(xlsx_path: Path) -> Iterator[Control]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    # Sheet name embeds the revision date. Match by prefix so the parser
    # survives quarterly revisions without code changes.
    sheet_name = next(
        (sn for sn in wb.sheetnames if sn.startswith("Controls -")),
        None,
    )
    if sheet_name is None:
        raise ValueError(f"no 'Controls - ...' sheet found in {xlsx_path}")
    ws = wb[sheet_name]

    headers = [c.value for c in next(ws.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW))]
    col = {name: i for i, name in enumerate(headers) if name}

    required = {"Identifier", "Description", "Guideline", "Section", "Topic"}
    missing = required - set(col)
    if missing:
        raise ValueError(f"XLSX header missing required columns: {missing}")

    for row in ws.iter_rows(min_row=DATA_START_ROW, values_only=True):
        identifier = row[col["Identifier"]]
        if not identifier or not str(identifier).startswith("ISM-"):
            continue
        yield Control(
            identifier=str(identifier).strip(),
            guideline=str(row[col["Guideline"]] or "").strip(),
            section=str(row[col["Section"]] or "").strip(),
            topic=str(row[col["Topic"]] or "").strip(),
            revision=_str_or_none(row[col["Revision"]]) if "Revision" in col else None,
            updated=_str_or_none(row[col["Updated"]]) if "Updated" in col else None,
            description=str(row[col["Description"]] or "").strip(),
            applies={c: _yes(row[col[c]]) if c in col else False for c in CLASSIFICATIONS},
            maturity={m: _yes(row[col[m]]) if m in col else False for m in MATURITIES},
        )


def extract_excerpts_from_lines(
    lines: list[str], page_of_line: list[int]
) -> dict[str, tuple[str, int]]:
    """Return a mapping of identifier to (excerpt, page) for every Control: label.

    The excerpt is the narrative paragraph immediately preceding the control's label line.
    Looking back across page boundaries is allowed, so a label at the top of a page picks
    up the trailing narrative from the previous page. The reported page is always the page
    on which the label itself appears.
    Consecutive label lines, multiple controls sharing one narrative, all map to the same excerpt.
    """
    label_re = re.compile(r"^\s*Control:\s*(ISM-\d{3,4})\b")

    label_positions: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        m = label_re.match(line)
        if m:
            label_positions.append((idx, m.group(1)))

    excerpts: dict[str, tuple[str, int]] = {}
    i = 0
    while i < len(label_positions):
        run_start = i
        while (
            i + 1 < len(label_positions) and label_positions[i + 1][0] == label_positions[i][0] + 1
        ):
            i += 1
        narrative = _paragraph_before(lines, label_positions[run_start][0])
        label_page = page_of_line[label_positions[run_start][0]]
        for j in range(run_start, i + 1):
            excerpts[label_positions[j][1]] = (narrative, label_page)
        i += 1
    return excerpts


def extract_excerpts_from_text(text: str, page_no: int) -> dict[str, tuple[str, int]]:
    """Single-page wrapper around extract_excerpts_from_lines."""
    lines = text.splitlines()
    return extract_excerpts_from_lines(lines, [page_no] * len(lines))


def _paragraph_before(lines: list[str], label_line_idx: int) -> str:
    end = label_line_idx
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    start = end
    while (
        start > 0
        and lines[start - 1].strip()
        and not lines[start - 1].lstrip().startswith("Control:")
    ):
        start -= 1
    return " ".join(line.strip() for line in lines[start:end] if line.strip())


def attach_pdf_excerpts(controls: list[Control], pdf_path: Path) -> list[Control]:
    """Walk the PDF once, extract per-control excerpts, attach them to controls by identifier."""
    all_lines: list[str] = []
    page_of_line: list[int] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            page_lines = text.splitlines()
            all_lines.extend(page_lines)
            page_of_line.extend([page_no] * len(page_lines))
            all_lines.append("")
            page_of_line.append(page_no)
    excerpts = extract_excerpts_from_lines(all_lines, page_of_line)
    return [
        Control(
            **{
                **c.as_dict(),
                "pdf_excerpt": excerpts.get(c.identifier, (None, None))[0],
                "pdf_page": excerpts.get(c.identifier, (None, None))[1],
            }
        )
        if c.identifier in excerpts
        else c
        for c in controls
    ]


def _str_or_none(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _yes(v) -> bool:
    return str(v).strip().lower() == "yes"


def embed_controls(controls: list[Control], embedder: Embedder) -> Iterator[tuple[int, bytes]]:
    """Yield (rowid, normalised float32 BLOB) for each control."""
    texts = [
        f"{c.topic}. {c.section}. {c.description} {(c.pdf_excerpt or '')[:500]}" for c in controls
    ]
    vectors = embedder.embed(texts)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.where(norms < 1e-9, 1.0, norms)
    for rowid, vec in enumerate(vectors, start=1):
        yield rowid, vec.astype(np.float32).tobytes()
