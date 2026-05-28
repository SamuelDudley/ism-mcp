"""Tests for the per-control PDF excerpt extractor."""

from __future__ import annotations

from ism_mcp.ingest import extract_excerpts_from_lines, extract_excerpts_from_text


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
