"""Write Claude Code config, guidance, manifest, and database into a consumer repo."""

from __future__ import annotations

DB_ENV_VALUE = "${CLAUDE_PROJECT_DIR:-.}/.ism/ism.db"
DB_REPO_PATH = ".ism/ism.db"


def mcp_entry(
    mode: str,
    *,
    repo: str | None = None,
    rev: str | None = None,
    image: str | None = None,
) -> dict:
    """Return the .mcp.json server entry for the given distribution mode."""
    if mode == "uvx":
        if not repo or not rev:
            raise ValueError("uvx mode needs repo and rev")
        return {
            "type": "stdio",
            "command": "uvx",
            "args": ["--from", f"git+{repo}@{rev}", "ism-mcp", "serve"],
            "env": {"ISM_MCP_DB": DB_ENV_VALUE},
        }
    if mode == "docker":
        if not image:
            raise ValueError("docker mode needs image")
        return {
            "type": "stdio",
            "command": "docker",
            "args": [
                "run",
                "--rm",
                "-i",
                "-v",
                "${CLAUDE_PROJECT_DIR:-.}/.ism:/data:ro",
                "-e",
                "ISM_MCP_DB=/data/ism.db",
                image,
            ],
        }
    raise ValueError(f"unknown mode: {mode}")
