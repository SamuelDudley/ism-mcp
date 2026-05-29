"""Write Claude Code config, guidance, manifest, and database into a consumer repo."""

from __future__ import annotations

import json
from pathlib import Path

DB_ENV_VALUE = "${CLAUDE_PROJECT_DIR:-.}/.ism/ism.db"
DB_REPO_PATH = ".ism/ism.db"
MARKER_BEGIN = "<!-- ism-mcp:begin -->"
MARKER_END = "<!-- ism-mcp:end -->"


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


def claude_md_block() -> str:
    """Return the managed CLAUDE.md guidance block, markers included."""
    return f"""{MARKER_BEGIN}
## ISM controls (ism-mcp)

This repo has the ASD Information Security Manual available through the `ism` MCP server.

Consult it when the work touches Australian Government security, ASD or ACSC guidance,
the Essential Eight, or classifications (OFFICIAL, OFFICIAL:Sensitive, PROTECTED, SECRET,
TOP_SECRET), and during security review, threat modelling, or compliance writing.

- `ism_applicable(work, ...)` finds controls relevant to what you are doing.
- `ism_get(identifier)` returns the full text of one control.

Track coverage in `.ism-coverage.toml`:

- `ism_coverage_read()` shows what is recorded.
- `ism_coverage_gaps(work)` lists in-scope controls not yet addressed.
- `ism_coverage_upsert(...)` records how a control is met, with evidence.
{MARKER_END}
"""


def merge_mcp_json(path: Path, name: str, entry: dict, *, dry_run: bool = False) -> str:
    """Merge one server entry into .mcp.json, preserving other servers."""
    existed = path.is_file()
    text = path.read_text() if existed else ""
    data = json.loads(text) if text.strip() else {}
    servers = data.setdefault("mcpServers", {})
    if not existed:
        action = f"create {path.name} with server '{name}'"
    elif name in servers:
        action = f"update server '{name}' in {path.name}"
    else:
        action = f"add server '{name}' to {path.name}"
    if not dry_run:
        servers[name] = entry
        path.write_text(json.dumps(data, indent=2) + "\n")
    return action


def write_managed_block(path: Path, block: str, *, dry_run: bool = False) -> str:
    """Append or replace the marked block in CLAUDE.md, leaving other text intact."""
    if not path.is_file():
        if not dry_run:
            path.write_text(block)
        return f"create {path.name} with ism-mcp block"
    text = path.read_text()
    if MARKER_BEGIN in text and MARKER_END in text:
        start = text.index(MARKER_BEGIN)
        end = text.index(MARKER_END, start) + len(MARKER_END)
        new = text[:start] + block.strip("\n") + text[end:]
        action = f"replace ism-mcp block in {path.name}"
    else:
        new = text.rstrip("\n") + "\n\n" + block
        action = f"append ism-mcp block to {path.name}"
    if not dry_run:
        path.write_text(new)
    return action
