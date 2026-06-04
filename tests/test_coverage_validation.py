"""Validation of manifest entries: status enum, evidence shape, required fields."""

from __future__ import annotations

from datetime import date

import pytest

from ism_mcp.coverage import ManifestEntry, validate_entry


def _entry(**overrides) -> ManifestEntry:
    base: dict = dict(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    base.update(overrides)
    return ManifestEntry(**base)


def test_valid_entry_passes(tmp_path):
    entry = _entry()
    validate_entry(entry, project_root=tmp_path)  # no exception


def test_invalid_status_raises(tmp_path):
    entry = _entry(status="bogus")
    with pytest.raises(ValueError, match="status"):
        validate_entry(entry, project_root=tmp_path)


def test_empty_how_met_raises(tmp_path):
    entry = _entry(how_met="")
    with pytest.raises(ValueError, match="how_met"):
        validate_entry(entry, project_root=tmp_path)


def test_url_without_description_raises(tmp_path):
    entry = _entry(urls=[{"url": "https://example.com"}])
    with pytest.raises(ValueError, match=r"url.*description"):
        validate_entry(entry, project_root=tmp_path)


def test_url_without_url_field_raises(tmp_path):
    entry = _entry(urls=[{"description": "x"}])
    with pytest.raises(ValueError, match="url"):
        validate_entry(entry, project_root=tmp_path)


def test_attachment_without_description_raises(tmp_path):
    attachment_file = tmp_path / "evidence.png"
    attachment_file.write_bytes(b"x")
    entry = _entry(attachments=[{"path": "evidence.png"}])
    with pytest.raises(ValueError, match=r"attachment.*description"):
        validate_entry(entry, project_root=tmp_path)


def test_attachment_path_must_exist(tmp_path):
    entry = _entry(
        attachments=[{"path": "missing.png", "description": "x"}],
    )
    with pytest.raises(FileNotFoundError, match=r"missing\.png"):
        validate_entry(entry, project_root=tmp_path)


def test_attachment_absolute_path_escaping_root_raises(tmp_path):
    entry = _entry(attachments=[{"path": "/etc/hostname", "description": "x"}])
    with pytest.raises(ValueError, match="escapes project root"):
        validate_entry(entry, project_root=tmp_path)


def test_attachment_traversal_escaping_root_raises(tmp_path):
    entry = _entry(attachments=[{"path": "../../etc/hostname", "description": "x"}])
    with pytest.raises(ValueError, match="escapes project root"):
        validate_entry(entry, project_root=tmp_path)


def test_attachment_path_resolves_relative_to_project_root(tmp_path):
    sub = tmp_path / ".ism-coverage" / "evidence" / "ISM-0428"
    sub.mkdir(parents=True)
    (sub / "lock-prompt.png").write_bytes(b"x")
    entry = _entry(
        attachments=[
            {
                "path": ".ism-coverage/evidence/ISM-0428/lock-prompt.png",
                "description": "Admin console at 14:01",
            }
        ],
    )
    validate_entry(entry, project_root=tmp_path)  # no exception
