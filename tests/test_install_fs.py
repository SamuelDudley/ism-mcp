"""Filesystem operations for the install command."""

from __future__ import annotations

import json

import pytest

from ism_mcp import install


def test_merge_creates_file_when_absent(tmp_path):
    path = tmp_path / ".mcp.json"
    action = install.merge_mcp_json(path, "ism", {"command": "uvx"})
    data = json.loads(path.read_text())
    assert data["mcpServers"]["ism"] == {"command": "uvx"}
    assert "create" in action


def test_merge_preserves_other_servers(tmp_path):
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    install.merge_mcp_json(path, "ism", {"command": "uvx"})
    data = json.loads(path.read_text())
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["ism"] == {"command": "uvx"}


def test_merge_replaces_existing_entry_of_same_name(tmp_path):
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {"ism": {"command": "old"}}}))
    action = install.merge_mcp_json(path, "ism", {"command": "uvx"})
    data = json.loads(path.read_text())
    assert data["mcpServers"]["ism"] == {"command": "uvx"}
    assert "update" in action


def test_merge_dry_run_does_not_write(tmp_path):
    path = tmp_path / ".mcp.json"
    install.merge_mcp_json(path, "ism", {"command": "uvx"}, dry_run=True)
    assert not path.exists()


def test_merge_rejects_non_object_json(tmp_path):
    path = tmp_path / ".mcp.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        install.merge_mcp_json(path, "ism", {"command": "uvx"})


def test_managed_block_creates_file_when_absent(tmp_path):
    path = tmp_path / "CLAUDE.md"
    action = install.write_managed_block(path, install.claude_md_block())
    assert install.MARKER_BEGIN in path.read_text()
    assert "create" in action


def test_managed_block_appends_and_keeps_existing_prose(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("# House rules\n\nExisting guidance.\n")
    action = install.write_managed_block(path, install.claude_md_block())
    text = path.read_text()
    assert "Existing guidance." in text
    assert text.count(install.MARKER_BEGIN) == 1
    assert "append" in action


def test_managed_block_replaces_in_place_and_stays_single(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("intro\n\n" + install.claude_md_block() + "\noutro\n")
    install.write_managed_block(path, install.claude_md_block())
    text = path.read_text()
    assert text.count(install.MARKER_BEGIN) == 1
    assert "intro" in text
    assert "outro" in text


def test_managed_block_dry_run_does_not_write(tmp_path):
    path = tmp_path / "CLAUDE.md"
    install.write_managed_block(path, install.claude_md_block(), dry_run=True)
    assert not path.exists()


def test_scaffold_writes_template_when_absent(tmp_path):
    path = tmp_path / ".ism-coverage.toml"
    action = install.scaffold_manifest(path, "schema_version = 1\n")
    assert path.read_text() == "schema_version = 1\n"
    assert "create" in action


def test_scaffold_keeps_existing_manifest(tmp_path):
    path = tmp_path / ".ism-coverage.toml"
    path.write_text("# my real evidence\n")
    action = install.scaffold_manifest(path, "schema_version = 1\n")
    assert path.read_text() == "# my real evidence\n"
    assert "keep" in action


def test_manifest_template_has_scope_section():
    text = install._manifest_template()
    assert "[scope]" in text


def test_manifest_template_omits_maturity_default():
    # maturity narrows scope to the Essential Eight subset, so the scaffold must not preset it.
    assert "maturity" not in install._manifest_template()


def test_copy_database_copies_and_creates_parent(tmp_path):
    src = tmp_path / "ism.db"
    src.write_bytes(b"SQLite format 3\x00")
    dst = tmp_path / "repo" / ".ism" / "ism.db"
    install.copy_database(src, dst)
    assert dst.read_bytes() == b"SQLite format 3\x00"


def test_copy_database_errors_when_source_missing(tmp_path):
    src = tmp_path / "missing.db"
    dst = tmp_path / "repo" / ".ism" / "ism.db"
    with pytest.raises(FileNotFoundError):
        install.copy_database(src, dst)


def test_copy_database_dry_run_does_not_write(tmp_path):
    src = tmp_path / "ism.db"
    src.write_bytes(b"x")
    dst = tmp_path / "repo" / ".ism" / "ism.db"
    install.copy_database(src, dst, dry_run=True)
    assert not dst.exists()
