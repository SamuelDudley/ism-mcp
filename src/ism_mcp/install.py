"""Write Claude Code config, guidance, manifest, and database into a consumer repo."""

from __future__ import annotations

import json
import shutil
from importlib.resources import files
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

Reach for `ism_applicable` first with a natural-language description of the work, then
surface the relevant controls before recommending mitigations.

- `ism_applicable(work, ...)` finds controls relevant to what you are doing.
- `ism_get(identifier)` returns the full text of one control. Identifiers are OSCAL ids
  like `ism-1781`; lookups also accept `ISM-1781`, a bare number, or a label.

The database holds the full ISM release history. When a newer ISM lands:

- `ism_versions()` lists the loaded releases.
- `ism_diff()` shows what changed in the latest release (added, removed, reworded, moved).
- `ism_history(identifier)` shows one control's evolution over time.

Track coverage in `.ism-coverage.toml`:

- `ism_coverage_read()` shows what is recorded.
- `ism_coverage_gaps(work)` lists in-scope controls not yet addressed.
- `ism_coverage_upsert(...)` records how a control is met, with evidence.
- `ism_coverage_impact()` flags covered controls to re-review after an ISM update.
{MARKER_END}
"""


def merge_mcp_json(path: Path, name: str, entry: dict, *, dry_run: bool = False) -> str:
    """Merge one server entry into .mcp.json, preserving other servers."""
    existed = path.is_file()
    text = path.read_text() if existed else ""
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
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


def scaffold_manifest(path: Path, template_text: str, *, dry_run: bool = False) -> str:
    """Write the manifest template only when no manifest exists."""
    if path.is_file():
        return f"keep existing {path.name}"
    if not dry_run:
        path.write_text(template_text)
    return f"create {path.name} from template"


def copy_database(src: Path, dst: Path, *, dry_run: bool = False) -> str:
    """Copy the database into the repo, creating the parent directory."""
    if not src.is_file():
        raise FileNotFoundError(f"source database not found at {src}. Run 'ism-mcp ingest' first.")
    action = f"overwrite {dst}" if dst.is_file() else f"copy database to {dst}"
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return action


def _manifest_template() -> str:
    return files("ism_mcp.data").joinpath("coverage_template.toml").read_text()


def install(
    *,
    project: Path,
    db_src: Path,
    mode: str = "uvx",
    repo: str | None = None,
    rev: str | None = None,
    image: str | None = None,
    name: str = "ism",
    dry_run: bool = False,
) -> list[str]:
    """Write the .mcp.json entry, CLAUDE.md block, manifest, and database. Return actions."""
    entry = mcp_entry(mode, repo=repo, rev=rev, image=image)
    if not db_src.is_file():
        raise FileNotFoundError(
            f"source database not found at {db_src}. Run 'ism-mcp ingest' first."
        )
    return [
        merge_mcp_json(project / ".mcp.json", name, entry, dry_run=dry_run),
        write_managed_block(project / "CLAUDE.md", claude_md_block(), dry_run=dry_run),
        scaffold_manifest(project / ".ism-coverage.toml", _manifest_template(), dry_run=dry_run),
        copy_database(db_src, project / DB_REPO_PATH, dry_run=dry_run),
    ]
