"""Tests for the per-control PDF excerpt extractor."""

from __future__ import annotations

from pathlib import Path

from ism_mcp import ingest, store
from ism_mcp.ingest import extract_excerpts_from_lines, extract_excerpts_from_text


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdf:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakePdf:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_extracts_narrative_paragraph_preceding_control_label():
    text = """Some unrelated content here.

Encryption ensures confidentiality. All data on the wire is protected.
Control: ISM-9001; Revision: 1; Updated: May-26; Applicable: NC, OS, P, S, TS

Logging events centrally helps detection. Aggregated logs enable correlation.
Control: ISM-9003; Revision: 1; Updated: May-26; Applicable: S, TS

Trailing prose."""
    excerpts = extract_excerpts_from_text(text, page_no=42)
    assert "ISM-9001" in excerpts
    assert "ISM-9003" in excerpts
    assert "Encryption ensures confidentiality" in excerpts["ISM-9001"][0]
    assert "All data on the wire" in excerpts["ISM-9001"][0]
    assert "Control: ISM-9001" not in excerpts["ISM-9001"][0]
    assert excerpts["ISM-9001"][1] == 42
    assert "Logging events centrally" in excerpts["ISM-9003"][0]


def test_returns_empty_for_text_without_control_labels():
    assert extract_excerpts_from_text("just prose without any labels", page_no=1) == {}


def test_multiple_controls_in_one_label_block():
    text = """A shared paragraph that two controls reference.
Control: ISM-1000; Revision: 1; Updated: May-26; Applicable: NC
Control: ISM-1001; Revision: 1; Updated: May-26; Applicable: NC"""
    excerpts = extract_excerpts_from_text(text, page_no=5)
    assert "ISM-1000" in excerpts and "ISM-1001" in excerpts
    assert excerpts["ISM-1000"][0] == excerpts["ISM-1001"][0]
    assert "shared paragraph" in excerpts["ISM-1000"][0]


def test_narrative_can_cross_page_boundary():
    lines = [
        "End of one section discussing the topic in detail.",
        "More narrative on the same topic.",
        "",
        "Control: ISM-2002; Revision: 1; Updated: Dec-25; Applicable: NC, OS, P, S, TS",
        "The board maintains a sufficient level of cyber security literacy.",
    ]
    page_of_line = [17, 17, 17, 18, 18]
    excerpts = extract_excerpts_from_lines(lines, page_of_line)
    assert "ISM-2002" in excerpts
    excerpt, page = excerpts["ISM-2002"]
    assert "End of one section" in excerpt
    assert "More narrative" in excerpt
    assert "Control:" not in excerpt
    assert page == 18


def test_label_without_preceding_narrative_is_skipped():
    text = "Control: ISM-1234; Revision: 1; Updated: May-26; Applicable: NC"
    assert extract_excerpts_from_text(text, page_no=1) == {}


def _control(
    identifier: str, *, pdf_excerpt: str | None = None, pdf_page: int | None = None
) -> store.Control:
    return store.Control(
        identifier=identifier,
        guideline="Guidelines for testing",
        section="Encryption",
        topic="Network encryption",
        revision="1",
        updated="May-26",
        description="x",
        applies=dict.fromkeys(store.CLASSIFICATIONS, True),
        maturity=dict.fromkeys(store.MATURITIES, False),
        pdf_excerpt=pdf_excerpt,
        pdf_page=pdf_page,
    )


def test_attach_pdf_excerpts_attaches_by_identifier_and_leaves_others(monkeypatch):
    pages = [
        _FakePage("Network encryption protects data in transit.\nControl: ISM-9001; Revision: 1"),
        _FakePage("Sessions must terminate when a user goes idle.\nControl: ISM-9002; Revision: 1"),
    ]
    monkeypatch.setattr(ingest.pdfplumber, "open", lambda _path: _FakePdf(pages))
    controls = [
        _control("ISM-9001"),
        _control("ISM-9002"),
        _control("ISM-9003", pdf_excerpt="pre-existing", pdf_page=7),
    ]
    out = ingest.attach_pdf_excerpts(controls, Path("ignored.pdf"))
    by_id = {c.identifier: c for c in out}
    assert "Network encryption protects data in transit." in (by_id["ISM-9001"].pdf_excerpt or "")
    assert by_id["ISM-9001"].pdf_page == 1
    assert by_id["ISM-9002"].pdf_page == 2
    assert by_id["ISM-9003"].pdf_excerpt == "pre-existing"
    assert by_id["ISM-9003"].pdf_page == 7
