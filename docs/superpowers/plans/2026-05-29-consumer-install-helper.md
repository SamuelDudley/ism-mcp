# Consumer install helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ism-mcp install --project PATH` so one command writes the Claude Code MCP entry, a CLAUDE.md guidance block, a scaffolded coverage manifest, and the committed ISM database into a consumer repo.

**Architecture:** A new `install.py` module splits pure builders (the `.mcp.json` entry dict, the CLAUDE.md block text) from filesystem operations (JSON merge, managed-block write, manifest scaffold, database copy). An orchestrator runs the four writes and supports a dry run. A new `install` subcommand in `__main__.py` resolves `--repo` and `--rev` defaults from the package's own git checkout, then calls the orchestrator.

**Tech Stack:** Python 3.14, standard library only (`json`, `shutil`, `subprocess`, `pathlib`, `importlib.resources`), pytest, ruff, pyright, uv.

---

## Background the engineer needs

- The server reads the database location from the `ISM_MCP_DB` environment variable (`server.py:16`). No server change is needed.
- Claude Code does not guarantee a project-scoped server's working directory. The portable way to point at a repo-relative file is the documented `${CLAUDE_PROJECT_DIR:-.}` expansion, which Claude Code substitutes with the clone's project root when it loads `.mcp.json`. The `:-.` default is required because the variable is set in the server's environment, not Claude Code's own, when expanding a project-scoped config. So the database env value is always the literal string `${CLAUDE_PROJECT_DIR:-.}/.ism/ism.db`.
- Data files are loaded with `from importlib.resources import files` then `files("ism_mcp.data").joinpath("NAME").read_text()`. See `paths.py:14`. The coverage template is `coverage_template.toml` under `src/ism_mcp/data/`.
- Tests are hermetic and use the `tmp_path` fixture. They start with `from __future__ import annotations` and a one-line module docstring. No real ISM files are required.
- Run a single test with `uv run pytest tests/PATH::NAME -v`. Run the whole gate with `./scripts/ci.sh`, which must end with `==> CI OK`.
- Modes are `uvx` (default) and `docker`. Semantic search is always on. There is no `lexical` or `local` mode.

## File structure

- Create `src/ism_mcp/install.py`. Holds module constants, builders (`mcp_entry`, `claude_md_block`), filesystem operations (`merge_mcp_json`, `write_managed_block`, `scaffold_manifest`, `copy_database`), the template loader (`_manifest_template`), and the orchestrator (`install`).
- Modify `src/ism_mcp/__main__.py`. Adds the `install` subcommand, its argument parser, and git default resolution.
- Create `tests/test_install_builders.py`. Covers `mcp_entry` and `claude_md_block`.
- Create `tests/test_install_fs.py`. Covers the four filesystem operations.
- Create `tests/test_install.py`. Covers the orchestrator, dry run, idempotency, and the CLI command.
- Modify `README.md` and `HANDOVER.md` in the final task.

The constants and signatures defined in Task 1 are used unchanged by every later task.

---

## Task 1: Builder for the .mcp.json entry

**Files:**
- Create: `src/ism_mcp/install.py`
- Test: `tests/test_install_builders.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install_builders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ism_mcp.install'`

- [ ] **Step 3: Write minimal implementation**

Create `src/ism_mcp/install.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install_builders.py -v`
Expected: PASS (5 tests, but `claude_md_block` tests come in Task 2, so only these 5 exist now)

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/install.py tests/test_install_builders.py
git commit -m "feat: build the mcp.json server entry for install modes"
```

---

## Task 2: Builder for the CLAUDE.md guidance block

**Files:**
- Modify: `src/ism_mcp/install.py`
- Test: `tests/test_install_builders.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install_builders.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install_builders.py -v`
Expected: FAIL with `AttributeError: module 'ism_mcp.install' has no attribute 'MARKER_BEGIN'`

- [ ] **Step 3: Write minimal implementation**

Add the markers next to the existing constants in `src/ism_mcp/install.py`:

```python
MARKER_BEGIN = "<!-- ism-mcp:begin -->"
MARKER_END = "<!-- ism-mcp:end -->"
```

Add the builder function:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install_builders.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/install.py tests/test_install_builders.py
git commit -m "feat: build the claude.md guidance block for install"
```

---

## Task 3: Merge the entry into .mcp.json

**Files:**
- Modify: `src/ism_mcp/install.py`
- Test: `tests/test_install_fs.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install_fs.py -v`
Expected: FAIL with `AttributeError: module 'ism_mcp.install' has no attribute 'merge_mcp_json'`

- [ ] **Step 3: Write minimal implementation**

Add `import json` and `from pathlib import Path` to the top of `src/ism_mcp/install.py`, then add:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install_fs.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/install.py tests/test_install_fs.py
git commit -m "feat: merge the install entry into mcp.json"
```

---

## Task 4: Write the managed block into CLAUDE.md

**Files:**
- Modify: `src/ism_mcp/install.py`
- Test: `tests/test_install_fs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install_fs.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install_fs.py -v`
Expected: FAIL with `AttributeError: module 'ism_mcp.install' has no attribute 'write_managed_block'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/ism_mcp/install.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install_fs.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/install.py tests/test_install_fs.py
git commit -m "feat: write the managed guidance block into claude.md"
```

---

## Task 5: Scaffold the manifest and copy the database

**Files:**
- Modify: `src/ism_mcp/install.py`
- Test: `tests/test_install_fs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install_fs.py`:

```python
import pytest


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install_fs.py -v`
Expected: FAIL with `AttributeError: module 'ism_mcp.install' has no attribute 'scaffold_manifest'`

- [ ] **Step 3: Write minimal implementation**

Add `import shutil` and `from importlib.resources import files` to the top of `src/ism_mcp/install.py`, then add:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install_fs.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/install.py tests/test_install_fs.py
git commit -m "feat: scaffold the manifest and copy the database for install"
```

---

## Task 6: Orchestrate the four writes

**Files:**
- Modify: `src/ism_mcp/install.py`
- Test: `tests/test_install.py`

- [ ] **Step 1: Write the failing test**

```python
"""Install orchestration: the four writes, dry run, and idempotency."""

from __future__ import annotations

import json

import pytest

from ism_mcp import install

UVX = dict(mode="uvx", repo="https://example/ism-mcp", rev="abc1234")


def _repo_with_db(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    db_src = tmp_path / "ism.db"
    db_src.write_bytes(b"SQLite format 3\x00")
    return project, db_src


def test_install_writes_all_four_artifacts(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    install.install(project=project, db_src=db_src, **UVX)
    data = json.loads((project / ".mcp.json").read_text())
    assert data["mcpServers"]["ism"]["command"] == "uvx"
    assert (project / "CLAUDE.md").read_text().count(install.MARKER_BEGIN) == 1
    assert (project / ".ism-coverage.toml").is_file()
    assert (project / ".ism" / "ism.db").read_bytes() == b"SQLite format 3\x00"


def test_install_errors_when_source_db_missing(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    with pytest.raises(FileNotFoundError):
        install.install(project=project, db_src=tmp_path / "nope.db", **UVX)


def test_install_keeps_existing_manifest(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    (project / ".ism-coverage.toml").write_text("# my real evidence\n")
    install.install(project=project, db_src=db_src, **UVX)
    assert "# my real evidence" in (project / ".ism-coverage.toml").read_text()


def test_install_dry_run_writes_nothing(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    actions = install.install(project=project, db_src=db_src, dry_run=True, **UVX)
    assert not (project / ".mcp.json").exists()
    assert not (project / ".ism").exists()
    assert len(actions) == 4


def test_install_is_idempotent(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    install.install(project=project, db_src=db_src, **UVX)
    targets = [
        project / ".mcp.json",
        project / "CLAUDE.md",
        project / ".ism-coverage.toml",
        project / ".ism" / "ism.db",
    ]
    snapshot = {p: p.read_bytes() for p in targets}
    install.install(project=project, db_src=db_src, **UVX)
    for p, data in snapshot.items():
        assert p.read_bytes() == data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install.py -v`
Expected: FAIL with `AttributeError: module 'ism_mcp.install' has no attribute 'install'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/ism_mcp/install.py`:

```python
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
        raise FileNotFoundError(f"source database not found at {db_src}. Run 'ism-mcp ingest' first.")
    return [
        merge_mcp_json(project / ".mcp.json", name, entry, dry_run=dry_run),
        write_managed_block(project / "CLAUDE.md", claude_md_block(), dry_run=dry_run),
        scaffold_manifest(project / ".ism-coverage.toml", _manifest_template(), dry_run=dry_run),
        copy_database(db_src, project / DB_REPO_PATH, dry_run=dry_run),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/install.py tests/test_install.py
git commit -m "feat: orchestrate the four install writes with a dry run"
```

---

## Task 7: The install subcommand

**Files:**
- Modify: `src/ism_mcp/__main__.py`
- Test: `tests/test_install.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install.py`:

```python
import argparse

from ism_mcp import __main__ as cli


def _args(**kw):
    base = dict(
        project=None, mode="uvx", repo="https://example/ism-mcp", rev="abc1234",
        image=None, db=None, name="ism", dry_run=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_cmd_install_returns_zero_and_writes(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    rc = cli.cmd_install(_args(project=str(project), db=str(db_src)))
    assert rc == 0
    assert (project / ".mcp.json").is_file()


def test_cmd_install_rejects_missing_project(tmp_path):
    rc = cli.cmd_install(_args(project=str(tmp_path / "absent"), db="x"))
    assert rc == 1


def test_cmd_install_uvx_without_repo_errors(tmp_path, monkeypatch):
    project, db_src = _repo_with_db(tmp_path)
    monkeypatch.setattr(cli, "_git_in_package", lambda *a: None)
    rc = cli.cmd_install(_args(project=str(project), db=str(db_src), repo=None))
    assert rc == 1


def test_cmd_install_docker_without_image_errors(tmp_path):
    project, db_src = _repo_with_db(tmp_path)
    rc = cli.cmd_install(_args(project=str(project), db=str(db_src), mode="docker", image=None))
    assert rc == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install.py -v`
Expected: FAIL with `AttributeError: module 'ism_mcp.__main__' has no attribute 'cmd_install'`

- [ ] **Step 3: Write minimal implementation**

In `src/ism_mcp/__main__.py`, add `subprocess` to the imports and add `install` to the package import line so it reads:

```python
import subprocess
```

```python
from . import ingest, install, server, store
```

Add the git helper and the command before `def main`:

```python
def _git_in_package(*git_args: str) -> str | None:
    pkg_dir = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "-C", str(pkg_dir), *git_args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip() or None


def cmd_install(args: argparse.Namespace) -> int:
    project = Path(args.project)
    if not project.is_dir():
        print(f"error: --project {project} is not a directory", file=sys.stderr)
        return 1
    repo = args.repo or _git_in_package("remote", "get-url", "origin")
    rev = args.rev or _git_in_package("rev-parse", "--short", "HEAD")
    if args.mode == "uvx" and not repo:
        print(
            "error: uvx mode needs --repo. No git origin detected. "
            "Publish ism-mcp and set origin, or pass --repo.",
            file=sys.stderr,
        )
        return 1
    if args.mode == "docker" and not args.image:
        print("error: docker mode needs --image.", file=sys.stderr)
        return 1
    db_src = Path(args.db or server.DEFAULT_DB)
    try:
        actions = install.install(
            project=project,
            db_src=db_src,
            mode=args.mode,
            repo=repo,
            rev=rev,
            image=args.image,
            name=args.name,
            dry_run=args.dry_run,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    prefix = "would " if args.dry_run else ""
    for a in actions:
        print(f"  {prefix}{a}", file=sys.stderr)
    print(f"{'dry run, ' if args.dry_run else ''}done. {project}", file=sys.stderr)
    return 0
```

Register the parser inside `main`, after the `serve` parser:

```python
    p_install = sub.add_parser(
        "install",
        help="Write Claude Code config, guidance, manifest, and database into a repo.",
    )
    p_install.add_argument("--project", required=True, help="Target repo root.")
    p_install.add_argument(
        "--mode",
        choices=["uvx", "docker"],
        default="uvx",
        help="Distribution mode (default: uvx).",
    )
    p_install.add_argument(
        "--repo", help="Source git URL. Defaults to this checkout's origin remote."
    )
    p_install.add_argument(
        "--rev", help="Git revision to pin. Defaults to this checkout's short HEAD."
    )
    p_install.add_argument("--image", help="Docker image reference (docker mode).")
    p_install.add_argument("--db", help=f"Source database to copy (default: {server.DEFAULT_DB}).")
    p_install.add_argument("--name", default="ism", help="MCP server key name (default: ism).")
    p_install.add_argument(
        "--dry-run", action="store_true", help="Report planned writes without changing anything."
    )
    p_install.set_defaults(func=cmd_install)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/__main__.py tests/test_install.py
git commit -m "feat: add the install subcommand with git default resolution"
```

---

## Task 8: Full gate and documentation

**Files:**
- Modify: `README.md`
- Modify: `HANDOVER.md`

- [ ] **Step 1: Run the full gate**

Run: `./scripts/ci.sh`
Expected: ends with `==> CI OK`. If ruff or pyright flags `install.py` or `__main__.py`, fix and re-run before continuing.

- [ ] **Step 2: Add an "Adopt in a project" section to README.md**

Insert after the "Use as a Claude Code MCP server" section:

````markdown
## Adopt in a project

`ism-mcp install` writes everything a teammate needs into a consumer repo. The
database is committed into the repo, so a clone has data without a local ingest.

```bash
uv run ism-mcp install --project /path/to/consumer-repo
```

This writes, all idempotent on re-run:

- `.mcp.json` with the `ism` server entry. Other servers in the file are kept.
- A managed block in `CLAUDE.md` between `<!-- ism-mcp:begin -->` and
  `<!-- ism-mcp:end -->`, telling agents when to consult the server.
- `.ism-coverage.toml` scaffolded from the template, only if absent. An existing
  manifest is never overwritten.
- `.ism/ism.db`, the database, refreshed on each run.

The default `uvx` mode launches the server with
`uvx --from git+<repo>@<rev> ism-mcp serve`. `--repo` defaults to this checkout's
`origin` remote and `--rev` to its short HEAD, so the entry pins a reproducible
build. A teammate needs only `uv`. The first semantic query downloads the
embedding model once, then runs offline.

For air-gapped or locked-down environments, `--mode docker --image <ref>` emits a
`docker run` entry that mounts the committed database. Building and hosting the
image is left to you.

The database path uses Claude Code's `${CLAUDE_PROJECT_DIR:-.}` expansion, so it
resolves to each teammate's project root. Claude Code prompts once per repo to
trust a project-scoped server. `claude mcp reset-project-choices` clears the
approval.

Use `--dry-run` to see the planned writes without changing anything.

### Prerequisite: publish the server

`uvx` and `docker` both fetch a pinned source, so ism-mcp must reach a git remote
before any teammate can run it. Push this repo to a remote and set `origin`. Then
migrate your own user-scope registration to the same launch command:

```bash
claude mcp add ism -s user -- uvx --from git+<origin>@<rev> ism-mcp serve
```

The user-scope server keeps the default database at
`~/.local/share/ism-mcp/ism.db`, which you ingest locally. It carries no
`ISM_MCP_DB` override, since that path is only for project installs where the
database travels with the repo.
````

- [ ] **Step 3: Add the install tooling note to the CLI table or commands in README.md**

In the development or usage commands, confirm the three subcommands are listed: `ingest`, `serve`, `install`. Add a line for `install` if a command list exists. If no such list exists, skip this step.

- [ ] **Step 4: Update HANDOVER.md**

Make these edits:

- In the roadmap table, change the `E: Consumer install helper` row from `next` to `done` with scope `ism-mcp install --project PATH, uvx and docker modes`.
- Under "Where we are", add `ism install --project PATH` to the tool and command summary.
- Under "Next action", set the next sub-project to `C: Graph and curated cuts` and point at the vision doc, since E is the last of the two `next` items.
- Add a known limitation: uvx and docker modes require ism-mcp to be published to a git remote. Note whether the remote has been created yet.
- Update the branch state line to name `feature/consumer-install-helper`.

- [ ] **Step 5: Run the full gate again**

Run: `./scripts/ci.sh`
Expected: ends with `==> CI OK`.

- [ ] **Step 6: Commit**

```bash
git add README.md HANDOVER.md
git commit -m "docs: document the install command and publish prerequisite"
```

---

## Manual prerequisite for the operator

uvx and docker modes cannot work for any teammate until ism-mcp is pushed to a
reachable git remote, which this repo does not have yet. Creating that remote and
pushing is an outward-facing action for the repo owner to take. The install
command resolves `--repo` from `origin` once it is set. Until then, `install`
errors with a clear hint, and `--dry-run` works for inspecting output.

## Self-review notes

- Spec coverage: two modes, `${CLAUDE_PROJECT_DIR:-.}` DB path, four artifacts with their idempotency rules, `--repo` from origin, builder and filesystem split, publish prerequisite and personal migration, hermetic tests. Each maps to a task above.
- The `install` function keyword signature, the `mcp_entry` signature, and the constants `DB_ENV_VALUE`, `DB_REPO_PATH`, `MARKER_BEGIN`, `MARKER_END` are defined once in Task 1 and Task 2 and used unchanged afterwards.
- Database write is guarded up front in the orchestrator, so a missing source database raises before any file is written.
