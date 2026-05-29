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
