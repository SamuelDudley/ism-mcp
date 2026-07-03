"""Read a coverage manifest from disk and walk up to find it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ism_mcp.coverage import find_manifest, read_manifest, read_manifest_text

SAMPLE_TOML = """\
schema_version = 1

[scope]
classification = "P"
maturity = "ML2"
sections = ["Authentication hardening"]

[project]
name = "demo-admin"
description = "Demo admin console"

[controls."ISM-0428"]
status = "covered"
how_met = "Sessions terminate after 14 min."
last_reviewed = 2026-05-28
reviewed_by = "reviewer"
files = ["src/auth/session.py:42-87"]
commits = ["abc1234"]

[[controls."ISM-0428".urls]]
url = "https://confluence.example/IRAP/session-policy"
description = "Authoritative session policy doc"

[[controls."ISM-0428".attachments]]
path = ".ism-coverage/evidence/ISM-0428/lock-prompt.png"
description = "Admin console at 14:01 showing session-expired modal"
"""


def test_read_manifest_text_parses_all_fields():
    m = read_manifest_text(SAMPLE_TOML, Path("/x/.ism-coverage.toml"))
    assert m.schema_version == 1
    assert m.scope["classification"] == "P"
    assert m.scope["maturity"] == "ML2"
    assert m.scope["sections"] == ["Authentication hardening"]
    assert m.project["name"] == "demo-admin"
    assert "ISM-0428" in m.controls
    e = m.controls["ISM-0428"]
    assert e.status == "covered"
    assert e.last_reviewed == date(2026, 5, 28)
    assert e.files == ["src/auth/session.py:42-87"]
    assert e.commits == ["abc1234"]
    assert e.urls == [
        {
            "url": "https://confluence.example/IRAP/session-policy",
            "description": "Authoritative session policy doc",
        }
    ]
    assert len(e.attachments) == 1
    assert e.attachments[0]["path"].endswith("lock-prompt.png")


def test_read_manifest_from_disk(tmp_path):
    path = tmp_path / ".ism-coverage.toml"
    path.write_text(SAMPLE_TOML)
    m = read_manifest(path)
    assert m.path == path
    assert m.scope["classification"] == "P"


def test_read_manifest_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_manifest(tmp_path / "nope.toml")


def test_read_manifest_invalid_toml_raises(tmp_path):
    path = tmp_path / ".ism-coverage.toml"
    path.write_text("schema_version = not-a-number\n")
    with pytest.raises(ValueError, match="not valid TOML"):
        read_manifest(path)


def test_find_manifest_walks_up(tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "src" / "deeply" / "nested"
    nested.mkdir(parents=True)
    manifest = repo / ".ism-coverage.toml"
    manifest.write_text(SAMPLE_TOML)
    found = find_manifest(nested)
    assert found == manifest


def test_find_manifest_returns_none_if_none(tmp_path):
    nested = tmp_path / "nowhere" / "to" / "find"
    nested.mkdir(parents=True)
    assert find_manifest(nested) is None


def test_read_manifest_warns_about_missing_attachments(tmp_path):
    path = tmp_path / ".ism-coverage.toml"
    path.write_text(SAMPLE_TOML)
    # Attachment is referenced in SAMPLE_TOML but the file doesn't exist on disk.
    m = read_manifest(path)
    assert any("lock-prompt.png" in w for w in m.warnings), m.warnings


def test_read_manifest_no_warnings_when_attachments_exist(tmp_path):
    (tmp_path / ".ism-coverage" / "evidence" / "ISM-0428").mkdir(parents=True)
    (tmp_path / ".ism-coverage" / "evidence" / "ISM-0428" / "lock-prompt.png").write_bytes(b"x")
    path = tmp_path / ".ism-coverage.toml"
    path.write_text(SAMPLE_TOML)
    m = read_manifest(path)
    assert m.warnings == []


def test_read_manifest_missing_status_raises_valueerror():
    bad = 'schema_version = 1\n\n[controls."ISM-0428"]\nhow_met = "x"\nlast_reviewed = 2026-05-28\n'
    with pytest.raises(ValueError, match="status"):
        read_manifest_text(bad, Path("/x/.ism-coverage.toml"))


def test_read_manifest_warns_when_attachment_escapes_root(tmp_path):
    toml = (
        'schema_version = 1\n\n[controls."ISM-0428"]\n'
        'status = "covered"\nhow_met = "x"\nlast_reviewed = 2026-05-28\n\n'
        '[[controls."ISM-0428".attachments]]\n'
        'path = "../../../etc/hostname"\ndescription = "x"\n'
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / ".ism-coverage.toml"
    path.write_text(toml)
    m = read_manifest(path)
    assert any("escapes project root" in w for w in m.warnings), m.warnings


def test_read_manifest_non_string_scalar_raises_valueerror():
    bad = (
        'schema_version = 1\n\n[controls."ism-0428"]\nstatus = "covered"\n'
        'how_met = "x"\nlast_reviewed = 2026-05-28\nreviewed_against = 2025.12\n'
    )
    with pytest.raises(ValueError, match="reviewed_against must be a string"):
        read_manifest_text(bad, Path("/x/.ism-coverage.toml"))


def test_read_manifest_non_string_how_met_raises_valueerror():
    bad = (
        'schema_version = 1\n\n[controls."ism-0428"]\nstatus = "covered"\n'
        "how_met = 3\nlast_reviewed = 2026-05-28\n"
    )
    with pytest.raises(ValueError, match="how_met must be a string"):
        read_manifest_text(bad, Path("/x/.ism-coverage.toml"))


def test_read_manifest_non_string_file_entry_raises_valueerror():
    bad = (
        'schema_version = 1\n\n[controls."ism-0428"]\nstatus = "covered"\n'
        'how_met = "x"\nlast_reviewed = 2026-05-28\nfiles = [1]\n'
    )
    with pytest.raises(ValueError, match="files entries must be strings"):
        read_manifest_text(bad, Path("/x/.ism-coverage.toml"))
