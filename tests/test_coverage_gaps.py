"""Gap computation: in-scope minus covered/not-applicable, with optional work intersection."""

from __future__ import annotations

from datetime import date

from ism_mcp.coverage import Manifest, ManifestEntry, compute_gaps


class _Ctrl:
    """Minimal stand-in for store.Control sufficient for compute_gaps."""

    def __init__(self, identifier, topic, section, description):
        self.identifier = identifier
        self.topic = topic
        self.section = section
        self.description = description


def _manifest(tmp_path, controls):
    return Manifest(
        path=tmp_path / ".ism-coverage.toml",
        schema_version=1,
        scope={"classification": "P", "maturity": "ML2"},
        project={},
        controls=controls,
        warnings=[],
    )


def _entry(identifier, status, **kwargs):
    return ManifestEntry(
        identifier=identifier,
        status=status,
        how_met="x",
        last_reviewed=date(2026, 5, 28),
        **kwargs,
    )


def test_gaps_without_work_returns_all_outstanding(tmp_path):
    in_scope = [
        _Ctrl("ISM-0001", "Topic A", "Sec A", "desc A"),
        _Ctrl("ISM-0002", "Topic B", "Sec B", "desc B"),
        _Ctrl("ISM-0003", "Topic C", "Sec C", "desc C"),
        _Ctrl("ISM-0004", "Topic D", "Sec D", "desc D"),
    ]
    manifest = _manifest(
        tmp_path,
        {
            "ISM-0001": _entry("ISM-0001", "covered"),
            "ISM-0002": _entry("ISM-0002", "not-applicable"),
            "ISM-0003": _entry("ISM-0003", "partial"),
            # ISM-0004: uncurated
        },
    )
    result = compute_gaps(manifest, in_scope, applicable=None)
    ids = [g["identifier"] for g in result["gaps"]]
    assert ids == ["ISM-0004", "ISM-0003"]  # uncurated before partial
    assert result["total_outstanding"] == 2
    assert result["gaps"][0]["current_status"] == "uncurated"
    assert result["gaps"][1]["current_status"] == "partial"
    assert "current_entry" in result["gaps"][1]
    assert "current_entry" not in result["gaps"][0]


def test_gaps_ordering_uncurated_then_partial_then_deferred(tmp_path):
    in_scope = [
        _Ctrl("ISM-0010", "Topic", "Sec", "desc"),
        _Ctrl("ISM-0020", "Topic", "Sec", "desc"),
        _Ctrl("ISM-0030", "Topic", "Sec", "desc"),
    ]
    manifest = _manifest(
        tmp_path,
        {
            "ISM-0010": _entry("ISM-0010", "deferred"),
            "ISM-0020": _entry("ISM-0020", "partial"),
            # ISM-0030 uncurated
        },
    )
    result = compute_gaps(manifest, in_scope, applicable=None)
    statuses = [g["current_status"] for g in result["gaps"]]
    assert statuses == ["uncurated", "partial", "deferred"]


def test_gaps_with_work_intersects_applicable_results(tmp_path):
    in_scope = [
        _Ctrl("ISM-0001", "Topic A", "Sec A", "desc A"),
        _Ctrl("ISM-0002", "Topic B", "Sec B", "desc B"),
        _Ctrl("ISM-0003", "Topic C", "Sec C", "desc C"),
    ]
    manifest = _manifest(tmp_path, {})  # all uncurated
    applicable = [
        {"identifier": "ISM-0002", "score": 0.5, "why": ["semantic"]},
        {"identifier": "ISM-0001", "score": 0.3, "why": ["semantic", "lexical"]},
        # ISM-0003 isn't relevant to this work
    ]
    result = compute_gaps(manifest, in_scope, applicable=applicable)
    ids = [g["identifier"] for g in result["gaps"]]
    assert ids == ["ISM-0002", "ISM-0001"]
    assert result["gaps"][0]["score"] == 0.5
    assert result["gaps"][0]["why"] == ["semantic"]


def test_gaps_with_work_skips_covered(tmp_path):
    in_scope = [
        _Ctrl("ISM-0001", "Topic", "Sec", "desc"),
        _Ctrl("ISM-0002", "Topic", "Sec", "desc"),
    ]
    manifest = _manifest(tmp_path, {"ISM-0001": _entry("ISM-0001", "covered")})
    applicable = [
        {"identifier": "ISM-0001", "score": 0.9, "why": ["semantic"]},
        {"identifier": "ISM-0002", "score": 0.5, "why": ["semantic"]},
    ]
    result = compute_gaps(manifest, in_scope, applicable=applicable)
    ids = [g["identifier"] for g in result["gaps"]]
    assert ids == ["ISM-0002"]


def test_gaps_empty_when_everything_covered(tmp_path):
    in_scope = [_Ctrl("ISM-0001", "Topic", "Sec", "desc")]
    manifest = _manifest(tmp_path, {"ISM-0001": _entry("ISM-0001", "covered")})
    result = compute_gaps(manifest, in_scope, applicable=None)
    assert result["gaps"] == []
    assert result["total_outstanding"] == 0


def test_gaps_limit_truncates(tmp_path):
    in_scope = [_Ctrl(f"ISM-{i:04d}", "Topic", "Sec", "desc") for i in range(10)]
    manifest = _manifest(tmp_path, {})
    result = compute_gaps(manifest, in_scope, applicable=None, limit=3)
    assert len(result["gaps"]) == 3
    assert result["total_outstanding"] == 10
