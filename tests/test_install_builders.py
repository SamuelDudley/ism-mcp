"""Builders for the install command: .mcp.json entry and CLAUDE.md block."""

from __future__ import annotations

import pytest

from ism_mcp import install


def test_uvx_entry_pins_repo_and_rev_and_sets_db_env():
    entry = install.mcp_entry("uvx", repo="https://example/ism-mcp", rev="abc1234")
    assert entry["command"] == "uvx"
    assert entry["args"] == ["--from", "git+https://example/ism-mcp@abc1234", "ism-mcp", "serve"]
    assert entry["env"]["ISM_MCP_DB"] == "${CLAUDE_PROJECT_DIR:-.}/.ism/ism.db"
    assert entry["type"] == "stdio"


def test_docker_entry_mounts_committed_db():
    entry = install.mcp_entry("docker", image="ghcr.io/acme/ism-mcp:1")
    assert entry["command"] == "docker"
    assert "ghcr.io/acme/ism-mcp:1" in entry["args"]
    assert "${CLAUDE_PROJECT_DIR:-.}/.ism:/data:ro" in entry["args"]
    assert "ISM_MCP_DB=/data/ism.db" in entry["args"]


def test_uvx_entry_requires_repo_and_rev():
    with pytest.raises(ValueError):
        install.mcp_entry("uvx", repo=None, rev="abc1234")


def test_docker_entry_requires_image():
    with pytest.raises(ValueError):
        install.mcp_entry("docker", image=None)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        install.mcp_entry("local")


def test_claude_md_block_is_delimited_by_markers():
    block = install.claude_md_block()
    assert block.startswith(install.MARKER_BEGIN)
    assert block.rstrip().endswith(install.MARKER_END)
    assert block.count(install.MARKER_BEGIN) == 1
    assert block.count(install.MARKER_END) == 1


def test_claude_md_block_names_the_key_tools():
    block = install.claude_md_block()
    assert "ism_applicable" in block
    assert "ism_coverage_gaps" in block
    assert ".ism-coverage.toml" in block


def test_claude_md_block_uses_invocation_prefix():
    block = install.claude_md_block()
    # Tool names must carry the mcp__<name>__ prefix Claude Code invokes them by.
    assert "mcp__ism__ism_applicable" in block
    assert "mcp__ism__ism_coverage_impact" in block
    # A bare, unprefixed tool bullet would not be callable.
    assert "- `ism_applicable(" not in block


def test_claude_md_block_honours_server_name():
    block = install.claude_md_block(name=" sm_custom".strip())
    assert "mcp__sm_custom__ism_applicable" in block
    assert "mcp__ism__" not in block
