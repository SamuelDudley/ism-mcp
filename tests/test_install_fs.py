"""Filesystem operations for the install command."""

from __future__ import annotations

import json

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
