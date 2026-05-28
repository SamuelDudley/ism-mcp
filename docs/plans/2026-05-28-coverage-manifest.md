# Coverage Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `.ism-coverage.toml` per-project manifest with three MCP tools (`ism_coverage_read`, `ism_coverage_upsert`, `ism_coverage_gaps`) that record IRAP-grade coverage evidence and report gaps.

**Architecture:** A new `coverage.py` module exposes plain Python functions (no MCP dependency) that read, validate, serialise, and gap-compute manifests. `server.py` registers three `@mcp.tool()` wrappers that walk up from cwd to find `.ism-coverage.toml`, call into `coverage.py`, and JSON-serialise the result. Gap detection reuses `ism_applicable` from sub-project B when a `work` description is supplied.

**Tech Stack:** Python 3.14, uv, sqlite3, `tomllib` (read), hand-rolled TOML writer for the schema subset, pytest, ruff, pyright. No new top-level dependencies.

**Prerequisite:** Sub-projects A (hardening) and B (hybrid discovery) merged. This plan assumes pytest, ruff, pyright, `scripts/ci.sh`, the `db` / `sample_controls` fixtures, the `ism_applicable` tool, and `controls_embeddings` are all in place.

**Reference spec:** `docs/superpowers/specs/2026-05-28-coverage-manifest-design.md`.

---

## Task 1: Module skeleton with dataclasses

**Files:**
- Create: `src/ism_mcp/coverage.py`
- Create: `tests/test_coverage_manifest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coverage_manifest.py`:

```python
"""Dataclasses and basic schema for the coverage manifest."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ism_mcp.coverage import Manifest, ManifestEntry


def test_manifest_entry_minimal_fields():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="Sessions terminate after 14 min.",
        last_reviewed=date(2026, 5, 28),
    )
    assert entry.identifier == "ISM-0428"
    assert entry.status == "covered"
    assert entry.files == []
    assert entry.commits == []
    assert entry.urls == []
    assert entry.attachments == []
    assert entry.reviewed_by is None
    assert entry.next_review is None


def test_manifest_entry_is_frozen():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        entry.status = "partial"  # type: ignore[misc]


def test_manifest_holds_controls_dict():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    m = Manifest(
        path=Path("/tmp/.ism-coverage.toml"),
        schema_version=1,
        scope={"classification": "P"},
        project={},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    assert m.controls["ISM-0428"].identifier == "ISM-0428"
    assert m.schema_version == 1
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_coverage_manifest.py -v
```

Expected: `ModuleNotFoundError: No module named 'ism_mcp.coverage'`.

- [ ] **Step 3: Create the module**

Create `src/ism_mcp/coverage.py`:

```python
"""Coverage manifest read, validate, serialise, gap-compute. No MCP dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

Status = Literal["covered", "partial", "not-applicable", "deferred"]


@dataclass(frozen=True)
class ManifestEntry:
    identifier: str
    status: Status
    how_met: str
    last_reviewed: date
    reviewed_by: str | None = None
    next_review: date | None = None
    files: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    urls: list[dict[str, str]] = field(default_factory=list)
    attachments: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    path: Path
    schema_version: int
    scope: dict
    project: dict
    controls: dict[str, ManifestEntry]
    warnings: list[str]
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_coverage_manifest.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/coverage.py tests/test_coverage_manifest.py
git commit -m "feat: add coverage manifest dataclasses"
```

---

## Task 2: Read manifest from text and disk, walk up from cwd

**Files:**
- Modify: `src/ism_mcp/coverage.py`
- Create: `tests/test_coverage_read.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coverage_read.py`:

```python
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
reviewed_by = "sam.dudley"
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
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_coverage_read.py -v
```

Expected: `ImportError: cannot import name 'find_manifest' from 'ism_mcp.coverage'`.

- [ ] **Step 3: Implement the read flow**

Append to `src/ism_mcp/coverage.py`:

```python
import tomllib


MANIFEST_FILENAME = ".ism-coverage.toml"


def find_manifest(start: Path) -> Path | None:
    """Walk up from `start` looking for .ism-coverage.toml. Return None if not found."""
    current = start.resolve()
    while True:
        candidate = current / MANIFEST_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def read_manifest(path: Path) -> Manifest:
    """Read and parse the manifest at `path`. Raises FileNotFoundError or ValueError."""
    if not path.is_file():
        raise FileNotFoundError(path)
    return read_manifest_text(path.read_text(), path)


def read_manifest_text(text: str, manifest_path: Path) -> Manifest:
    """Parse the manifest TOML and return a Manifest. Warnings come from validation."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"manifest at {manifest_path} is not valid TOML: {e}") from e

    controls: dict[str, ManifestEntry] = {}
    for identifier, body in (raw.get("controls") or {}).items():
        controls[identifier] = _entry_from_dict(identifier, body)

    return Manifest(
        path=manifest_path,
        schema_version=int(raw.get("schema_version", 1)),
        scope=dict(raw.get("scope") or {}),
        project=dict(raw.get("project") or {}),
        controls=controls,
        warnings=[],
    )


def _entry_from_dict(identifier: str, body: dict) -> ManifestEntry:
    last_reviewed = body.get("last_reviewed")
    if not isinstance(last_reviewed, date):
        raise ValueError(f"{identifier}: last_reviewed must be a TOML date, got {last_reviewed!r}")
    next_review = body.get("next_review")
    if next_review is not None and not isinstance(next_review, date):
        raise ValueError(f"{identifier}: next_review must be a TOML date or omitted")
    return ManifestEntry(
        identifier=identifier,
        status=body["status"],
        how_met=body["how_met"],
        last_reviewed=last_reviewed,
        reviewed_by=body.get("reviewed_by"),
        next_review=next_review,
        files=list(body.get("files") or []),
        commits=list(body.get("commits") or []),
        urls=[dict(u) for u in (body.get("urls") or [])],
        attachments=[dict(a) for a in (body.get("attachments") or [])],
    )
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_coverage_read.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/coverage.py tests/test_coverage_read.py
git commit -m "feat: add coverage manifest read and find-by-walk-up"
```

---

## Task 3: Schema validation

**Files:**
- Modify: `src/ism_mcp/coverage.py`
- Create: `tests/test_coverage_validation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coverage_validation.py`:

```python
"""Validation of manifest entries: status enum, evidence shape, required fields."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ism_mcp.coverage import ManifestEntry, validate_entry


def _entry(**overrides) -> ManifestEntry:
    base = dict(
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
    with pytest.raises(ValueError, match="url.*description"):
        validate_entry(entry, project_root=tmp_path)


def test_url_without_url_field_raises(tmp_path):
    entry = _entry(urls=[{"description": "x"}])
    with pytest.raises(ValueError, match="url"):
        validate_entry(entry, project_root=tmp_path)


def test_attachment_without_description_raises(tmp_path):
    attachment_file = tmp_path / "evidence.png"
    attachment_file.write_bytes(b"x")
    entry = _entry(attachments=[{"path": "evidence.png"}])
    with pytest.raises(ValueError, match="attachment.*description"):
        validate_entry(entry, project_root=tmp_path)


def test_attachment_path_must_exist(tmp_path):
    entry = _entry(
        attachments=[{"path": "missing.png", "description": "x"}],
    )
    with pytest.raises(FileNotFoundError, match="missing.png"):
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
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_coverage_validation.py -v
```

Expected: `ImportError: cannot import name 'validate_entry'`.

- [ ] **Step 3: Implement validation**

Append to `src/ism_mcp/coverage.py`:

```python
VALID_STATUSES: frozenset[str] = frozenset(
    ["covered", "partial", "not-applicable", "deferred"]
)


def validate_entry(entry: ManifestEntry, project_root: Path) -> None:
    """Raise ValueError or FileNotFoundError if the entry is invalid for this project."""
    if entry.status not in VALID_STATUSES:
        raise ValueError(
            f"{entry.identifier}: status {entry.status!r} not one of {sorted(VALID_STATUSES)}"
        )
    if not entry.how_met or not entry.how_met.strip():
        raise ValueError(f"{entry.identifier}: how_met is required and must be non-empty")
    for u in entry.urls:
        if "url" not in u:
            raise ValueError(f"{entry.identifier}: url entry missing 'url' key")
        if "description" not in u or not u["description"].strip():
            raise ValueError(f"{entry.identifier}: url {u['url']!r} missing description")
    for a in entry.attachments:
        if "path" not in a:
            raise ValueError(f"{entry.identifier}: attachment entry missing 'path' key")
        if "description" not in a or not a["description"].strip():
            raise ValueError(f"{entry.identifier}: attachment {a['path']!r} missing description")
        resolved = (project_root / a["path"]).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"{entry.identifier}: attachment not found: {a['path']}")
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_coverage_validation.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/coverage.py tests/test_coverage_validation.py
git commit -m "feat: add manifest entry validation"
```

---

## Task 4: Read-time warnings for dangling attachments

**Files:**
- Modify: `src/ism_mcp/coverage.py`
- Modify: `tests/test_coverage_read.py`

- [ ] **Step 1: Append the failing test**

Append to `tests/test_coverage_read.py`:

```python
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
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_coverage_read.py -v
```

Expected: 2 new test failures (warnings list is empty when it shouldn't be).

- [ ] **Step 3: Populate warnings in read**

Edit `read_manifest_text` in `src/ism_mcp/coverage.py`. Replace the final `return Manifest(...)` block with:

```python
    project_root = manifest_path.parent
    warnings: list[str] = []
    for ident, entry in controls.items():
        for a in entry.attachments:
            path_ref = a.get("path")
            if path_ref is None:
                continue
            resolved = (project_root / path_ref).resolve()
            if not resolved.is_file():
                warnings.append(f"{ident}: attachment not found on disk: {path_ref}")

    return Manifest(
        path=manifest_path,
        schema_version=int(raw.get("schema_version", 1)),
        scope=dict(raw.get("scope") or {}),
        project=dict(raw.get("project") or {}),
        controls=controls,
        warnings=warnings,
    )
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_coverage_read.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/coverage.py tests/test_coverage_read.py
git commit -m "feat: surface dangling attachment paths as read-time warnings"
```

---

## Task 5: Hand-rolled TOML serialiser with round-trip test

**Files:**
- Modify: `src/ism_mcp/coverage.py`
- Create: `tests/test_coverage_serialise.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coverage_serialise.py`:

```python
"""Hand-rolled TOML serialiser for the manifest schema."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ism_mcp.coverage import Manifest, ManifestEntry, read_manifest_text, serialise_manifest


def test_round_trip_preserves_all_fields(tmp_path):
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="Sessions terminate after 14 min of idle.",
        last_reviewed=date(2026, 5, 28),
        reviewed_by="sam.dudley",
        next_review=date(2027, 5, 28),
        files=["src/auth/session.py:42-87", "tests/test_session_lock.py:15-60"],
        commits=["abc1234"],
        urls=[{"url": "https://example/policy", "description": "Authoritative session policy"}],
        attachments=[
            {"path": ".ism-coverage/evidence/ISM-0428/x.png", "description": "screenshot"}
        ],
    )
    original = Manifest(
        path=tmp_path / ".ism-coverage.toml",
        schema_version=1,
        scope={"classification": "P", "maturity": "ML2", "sections": ["Authentication hardening"]},
        project={"name": "demo", "description": "x"},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    text = serialise_manifest(original)
    parsed = read_manifest_text(text, original.path)
    assert parsed.schema_version == 1
    assert parsed.scope == original.scope
    assert parsed.project == original.project
    assert parsed.controls["ISM-0428"] == entry


def test_serialiser_quotes_strings_safely():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met='He said "hello" and left.\nSecond line.',
        last_reviewed=date(2026, 5, 28),
    )
    m = Manifest(
        path=Path("/x/.ism-coverage.toml"),
        schema_version=1,
        scope={"classification": "NC"},
        project={},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    text = serialise_manifest(m)
    # Multiline-with-quotes must survive a round-trip.
    parsed = read_manifest_text(text, m.path)
    assert parsed.controls["ISM-0428"].how_met == entry.how_met


def test_serialiser_omits_optional_empty_collections():
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    m = Manifest(
        path=Path("/x/.ism-coverage.toml"),
        schema_version=1,
        scope={"classification": "NC"},
        project={},
        controls={"ISM-0428": entry},
        warnings=[],
    )
    text = serialise_manifest(m)
    assert "files" not in text
    assert "commits" not in text
    assert "urls" not in text
    assert "attachments" not in text
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_coverage_serialise.py -v
```

Expected: `ImportError: cannot import name 'serialise_manifest'`.

- [ ] **Step 3: Implement the serialiser**

Append to `src/ism_mcp/coverage.py`:

```python
def serialise_manifest(manifest: Manifest) -> str:
    """Serialise a Manifest to TOML text. Subset of TOML matching the manifest schema."""
    lines: list[str] = [f"schema_version = {manifest.schema_version}", ""]

    if manifest.scope:
        lines.append("[scope]")
        for key, value in manifest.scope.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    if manifest.project:
        lines.append("[project]")
        for key, value in manifest.project.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    for identifier, entry in manifest.controls.items():
        lines.append(f'[controls."{identifier}"]')
        lines.append(f"status = {_toml_value(entry.status)}")
        lines.append(f"how_met = {_toml_multiline(entry.how_met)}")
        lines.append(f"last_reviewed = {entry.last_reviewed.isoformat()}")
        if entry.reviewed_by:
            lines.append(f"reviewed_by = {_toml_value(entry.reviewed_by)}")
        if entry.next_review:
            lines.append(f"next_review = {entry.next_review.isoformat()}")
        if entry.files:
            lines.append(f"files = {_toml_value(entry.files)}")
        if entry.commits:
            lines.append(f"commits = {_toml_value(entry.commits)}")
        for u in entry.urls:
            lines.append("")
            lines.append(f'[[controls."{identifier}".urls]]')
            lines.append(f"url = {_toml_value(u['url'])}")
            lines.append(f"description = {_toml_value(u['description'])}")
        for a in entry.attachments:
            lines.append("")
            lines.append(f'[[controls."{identifier}".attachments]]')
            lines.append(f"path = {_toml_value(a['path'])}")
            lines.append(f"description = {_toml_value(a['description'])}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return _toml_string(v)
    if isinstance(v, list):
        items = ", ".join(_toml_value(x) for x in v)
        return f"[{items}]"
    raise TypeError(f"unsupported TOML value type: {type(v).__name__}")


def _toml_string(s: str) -> str:
    if "\n" not in s and '"' not in s and "\\" not in s:
        return f'"{s}"'
    return _toml_multiline(s)


def _toml_multiline(s: str) -> str:
    safe = s.replace("\\", "\\\\").replace('"""', '\\"""')
    if "\n" not in safe and '"' not in safe:
        return f'"{safe}"'
    return f'"""\n{safe}\n"""'
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_coverage_serialise.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/coverage.py tests/test_coverage_serialise.py
git commit -m "feat: add hand-rolled TOML serialiser for the manifest schema"
```

---

## Task 6: Atomic upsert with validation

**Files:**
- Modify: `src/ism_mcp/coverage.py`
- Create: `tests/test_coverage_upsert.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coverage_upsert.py`:

```python
"""Atomic upsert of a manifest entry with full validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ism_mcp.coverage import (
    ManifestEntry,
    read_manifest,
    upsert_entry,
)


SEED_TOML = """\
schema_version = 1

[scope]
classification = "P"
maturity = "ML2"

[project]
name = "demo"
"""


def _seed(tmp_path: Path) -> Path:
    path = tmp_path / ".ism-coverage.toml"
    path.write_text(SEED_TOML)
    return path


def test_upsert_creates_entry(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="Sessions terminate after 14 min.",
        last_reviewed=date(2026, 5, 28),
        files=["src/auth/session.py:42-87"],
    )
    result = upsert_entry(path, entry)
    assert result["action"] == "created"
    assert result["identifier"] == "ISM-0428"
    m = read_manifest(path)
    assert "ISM-0428" in m.controls
    assert m.controls["ISM-0428"].how_met.startswith("Sessions terminate")


def test_upsert_updates_existing_entry(tmp_path):
    path = _seed(tmp_path)
    e1 = ManifestEntry(
        identifier="ISM-0428",
        status="partial",
        how_met="first pass",
        last_reviewed=date(2026, 5, 28),
    )
    upsert_entry(path, e1)
    e2 = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="now covered",
        last_reviewed=date(2026, 5, 29),
    )
    result = upsert_entry(path, e2)
    assert result["action"] == "updated"
    m = read_manifest(path)
    assert m.controls["ISM-0428"].status == "covered"
    assert m.controls["ISM-0428"].how_met == "now covered"


def test_upsert_rejects_invalid_status(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="bogus",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    with pytest.raises(ValueError, match="status"):
        upsert_entry(path, entry)
    # File unchanged.
    assert "ISM-0428" not in read_manifest(path).controls


def test_upsert_rejects_missing_attachment(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
        attachments=[{"path": "evidence/nope.png", "description": "x"}],
    )
    with pytest.raises(FileNotFoundError):
        upsert_entry(path, entry)


def test_upsert_returns_warning_for_out_of_scope_identifier(tmp_path):
    path = _seed(tmp_path)
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    # Scope sets sections to ["Authentication hardening"] etc. Without an in-scope check
    # being wired in coverage.py (the server adds it), upsert should not warn here.
    # We just verify warnings is an empty list for the base function.
    result = upsert_entry(path, entry)
    assert result["warnings"] == []


def test_upsert_is_atomic(monkeypatch, tmp_path):
    path = _seed(tmp_path)
    original = path.read_text()
    entry = ManifestEntry(
        identifier="ISM-0428",
        status="covered",
        how_met="x",
        last_reviewed=date(2026, 5, 28),
    )
    # Simulate failure during os.replace by patching it on the coverage module.
    from ism_mcp import coverage

    def boom(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(coverage.os, "replace", boom)
    with pytest.raises(OSError):
        upsert_entry(path, entry)
    assert path.read_text() == original
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_coverage_upsert.py -v
```

Expected: `ImportError: cannot import name 'upsert_entry'`.

- [ ] **Step 3: Implement upsert**

Add to the top of `src/ism_mcp/coverage.py` (imports already present, augment):

```python
import os
import tempfile
```

Append to `src/ism_mcp/coverage.py`:

```python
def upsert_entry(manifest_path: Path, entry: ManifestEntry) -> dict:
    """Validate the entry, then write/update it in the manifest atomically.

    Returns a dict with `action` (`"created"` or `"updated"`), `identifier`, and `warnings`.
    Raises ValueError for invalid entries and FileNotFoundError for missing attachments.
    """
    validate_entry(entry, project_root=manifest_path.parent)

    manifest = read_manifest(manifest_path)
    action = "updated" if entry.identifier in manifest.controls else "created"
    new_controls = dict(manifest.controls)
    new_controls[entry.identifier] = entry
    updated = Manifest(
        path=manifest.path,
        schema_version=manifest.schema_version,
        scope=manifest.scope,
        project=manifest.project,
        controls=new_controls,
        warnings=[],
    )
    text = serialise_manifest(updated)
    _atomic_write(manifest_path, text)
    return {"ok": True, "identifier": entry.identifier, "action": action, "warnings": []}


def _atomic_write(target: Path, text: str) -> None:
    """Write `text` to `target` atomically via tempfile + os.replace in the same dir."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_coverage_upsert.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/coverage.py tests/test_coverage_upsert.py
git commit -m "feat: add atomic coverage manifest upsert"
```

---

## Task 7: Store helper for in-scope control listing

**Files:**
- Modify: `src/ism_mcp/store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_store.py`:

```python
def test_list_in_scope_filters_by_classification(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(db, classification="NC", maturity=None, sections=None)
    assert {c.identifier for c in rows} == {"ISM-9001", "ISM-9002"}


def test_list_in_scope_filters_by_maturity(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(db, classification="NC", maturity="ML1", sections=None)
    assert {c.identifier for c in rows} == {"ISM-9002"}


def test_list_in_scope_filters_by_sections(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(
        db, classification=None, maturity=None, sections=["Encryption", "Audit"]
    )
    assert {c.identifier for c in rows} == {"ISM-9001", "ISM-9003"}


def test_list_in_scope_combines_all_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = store.list_in_scope(
        db, classification="TS", maturity="ML3", sections=["Audit"]
    )
    assert {c.identifier for c in rows} == {"ISM-9003"}


def test_list_in_scope_rejects_unknown_classification(db):
    with pytest.raises(ValueError, match="classification"):
        store.list_in_scope(db, classification="XX", maturity=None, sections=None)
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_store.py -v -k in_scope
```

Expected: `AttributeError: module 'ism_mcp.store' has no attribute 'list_in_scope'`.

- [ ] **Step 3: Implement the helper**

Append to `src/ism_mcp/store.py`:

```python
def list_in_scope(
    conn: sqlite3.Connection,
    classification: str | None,
    maturity: str | None,
    sections: list[str] | None,
) -> list[Control]:
    """Controls matching all supplied filters. Each filter is optional."""
    where: list[str] = []
    params: list = []
    if classification is not None:
        cls = classification.upper()
        if cls not in CLASSIFICATIONS:
            raise ValueError(
                f"unknown classification {classification!r}, expected one of {CLASSIFICATIONS}"
            )
        where.append(f"applies_{cls.lower()} = 1")
    if maturity is not None:
        ml = maturity.upper()
        if ml not in MATURITIES:
            raise ValueError(f"unknown maturity {maturity!r}, expected one of {MATURITIES}")
        where.append(f"maturity_{ml.lower()} = 1")
    if sections:
        placeholders = ",".join(["?"] * len(sections))
        where.append(f"section IN ({placeholders})")
        params.extend(sections)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM controls {clause} ORDER BY identifier",
        params,
    ).fetchall()
    return [_row_to_control(r) for r in rows]
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_store.py -v -k in_scope
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/store.py tests/test_store.py
git commit -m "feat: add store.list_in_scope for scoped control listing"
```

---

## Task 8: Gap computation in coverage.py

**Files:**
- Modify: `src/ism_mcp/coverage.py`
- Create: `tests/test_coverage_gaps.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coverage_gaps.py`:

```python
"""Gap computation: in-scope minus covered/not-applicable, with optional work intersection."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ism_mcp.coverage import Manifest, ManifestEntry, compute_gaps


class _Ctrl:
    """Minimal stand-in for store.Control sufficient for compute_gaps."""

    def __init__(self, identifier, topic, section, description):
        self.identifier = identifier
        self.topic = topic
        self.section = section
        self.description = description


def _manifest(tmp_path, controls):
    return Manifest(
        path=tmp_path / ".ism-coverage.toml",
        schema_version=1,
        scope={"classification": "P", "maturity": "ML2"},
        project={},
        controls=controls,
        warnings=[],
    )


def _entry(identifier, status, **kwargs):
    return ManifestEntry(
        identifier=identifier,
        status=status,
        how_met="x",
        last_reviewed=date(2026, 5, 28),
        **kwargs,
    )


def test_gaps_without_work_returns_all_outstanding(tmp_path):
    in_scope = [
        _Ctrl("ISM-0001", "Topic A", "Sec A", "desc A"),
        _Ctrl("ISM-0002", "Topic B", "Sec B", "desc B"),
        _Ctrl("ISM-0003", "Topic C", "Sec C", "desc C"),
        _Ctrl("ISM-0004", "Topic D", "Sec D", "desc D"),
    ]
    manifest = _manifest(
        tmp_path,
        {
            "ISM-0001": _entry("ISM-0001", "covered"),
            "ISM-0002": _entry("ISM-0002", "not-applicable"),
            "ISM-0003": _entry("ISM-0003", "partial"),
            # ISM-0004: uncurated
        },
    )
    result = compute_gaps(manifest, in_scope, applicable=None)
    ids = [g["identifier"] for g in result["gaps"]]
    assert ids == ["ISM-0004", "ISM-0003"]  # uncurated before partial
    assert result["total_outstanding"] == 2
    assert result["gaps"][0]["current_status"] == "uncurated"
    assert result["gaps"][1]["current_status"] == "partial"
    assert "current_entry" in result["gaps"][1]
    assert "current_entry" not in result["gaps"][0]


def test_gaps_ordering_uncurated_then_partial_then_deferred(tmp_path):
    in_scope = [
        _Ctrl("ISM-0010", "Topic", "Sec", "desc"),
        _Ctrl("ISM-0020", "Topic", "Sec", "desc"),
        _Ctrl("ISM-0030", "Topic", "Sec", "desc"),
    ]
    manifest = _manifest(
        tmp_path,
        {
            "ISM-0010": _entry("ISM-0010", "deferred"),
            "ISM-0020": _entry("ISM-0020", "partial"),
            # ISM-0030 uncurated
        },
    )
    result = compute_gaps(manifest, in_scope, applicable=None)
    statuses = [g["current_status"] for g in result["gaps"]]
    assert statuses == ["uncurated", "partial", "deferred"]


def test_gaps_with_work_intersects_applicable_results(tmp_path):
    in_scope = [
        _Ctrl("ISM-0001", "Topic A", "Sec A", "desc A"),
        _Ctrl("ISM-0002", "Topic B", "Sec B", "desc B"),
        _Ctrl("ISM-0003", "Topic C", "Sec C", "desc C"),
    ]
    manifest = _manifest(tmp_path, {})  # all uncurated
    applicable = [
        {"identifier": "ISM-0002", "score": 0.5, "why": ["semantic"]},
        {"identifier": "ISM-0001", "score": 0.3, "why": ["semantic", "lexical"]},
        # ISM-0003 isn't relevant to this work
    ]
    result = compute_gaps(manifest, in_scope, applicable=applicable)
    ids = [g["identifier"] for g in result["gaps"]]
    assert ids == ["ISM-0002", "ISM-0001"]
    assert result["gaps"][0]["score"] == 0.5
    assert result["gaps"][0]["why"] == ["semantic"]


def test_gaps_with_work_skips_covered(tmp_path):
    in_scope = [
        _Ctrl("ISM-0001", "Topic", "Sec", "desc"),
        _Ctrl("ISM-0002", "Topic", "Sec", "desc"),
    ]
    manifest = _manifest(tmp_path, {"ISM-0001": _entry("ISM-0001", "covered")})
    applicable = [
        {"identifier": "ISM-0001", "score": 0.9, "why": ["semantic"]},
        {"identifier": "ISM-0002", "score": 0.5, "why": ["semantic"]},
    ]
    result = compute_gaps(manifest, in_scope, applicable=applicable)
    ids = [g["identifier"] for g in result["gaps"]]
    assert ids == ["ISM-0002"]


def test_gaps_empty_when_everything_covered(tmp_path):
    in_scope = [_Ctrl("ISM-0001", "Topic", "Sec", "desc")]
    manifest = _manifest(tmp_path, {"ISM-0001": _entry("ISM-0001", "covered")})
    result = compute_gaps(manifest, in_scope, applicable=None)
    assert result["gaps"] == []
    assert result["total_outstanding"] == 0


def test_gaps_limit_truncates(tmp_path):
    in_scope = [_Ctrl(f"ISM-{i:04d}", "Topic", "Sec", "desc") for i in range(10)]
    manifest = _manifest(tmp_path, {})
    result = compute_gaps(manifest, in_scope, applicable=None, limit=3)
    assert len(result["gaps"]) == 3
    assert result["total_outstanding"] == 10
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_coverage_gaps.py -v
```

Expected: `ImportError: cannot import name 'compute_gaps'`.

- [ ] **Step 3: Implement compute_gaps**

Append to `src/ism_mcp/coverage.py`:

```python
_STATUS_PRIORITY = {"uncurated": 0, "partial": 1, "deferred": 2}


def compute_gaps(
    manifest: Manifest,
    in_scope: list,
    applicable: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """Compute outstanding controls relative to the manifest.

    `in_scope` is the list of Control-like objects (anything with `identifier`, `topic`,
    `section`, `description` attributes) in the project's declared scope.
    `applicable` is the optional output of `ism_applicable`: a list of dicts each
    containing at least `identifier`, `score`, `why`. When provided, gaps are
    intersected with this list and ordered by score descending.
    """
    covered = {
        ident for ident, e in manifest.controls.items()
        if e.status in ("covered", "not-applicable")
    }

    def _current_status(identifier: str) -> str:
        entry = manifest.controls.get(identifier)
        return entry.status if entry else "uncurated"

    def _current_entry(identifier: str) -> dict | None:
        entry = manifest.controls.get(identifier)
        if entry is None:
            return None
        return {
            "how_met": entry.how_met,
            "last_reviewed": entry.last_reviewed.isoformat(),
        }

    by_id = {c.identifier: c for c in in_scope}

    if applicable is None:
        candidates = [c for c in in_scope if c.identifier not in covered]
        candidates.sort(
            key=lambda c: (
                _STATUS_PRIORITY.get(_current_status(c.identifier), 99),
                c.identifier,
            )
        )
        gaps = []
        for c in candidates:
            status = _current_status(c.identifier)
            gap: dict = {
                "identifier": c.identifier,
                "topic": c.topic,
                "section": c.section,
                "description": c.description,
                "current_status": status,
            }
            ce = _current_entry(c.identifier)
            if ce is not None:
                gap["current_entry"] = ce
            gaps.append(gap)
        total = len(gaps)
        return {"gaps": gaps[:limit], "total_outstanding": total, "shown": min(limit, total)}

    # Work-aware: intersect with applicable, preserve applicable's score-descending order.
    gaps = []
    for entry in applicable:
        ident = entry["identifier"]
        if ident in covered:
            continue
        if ident not in by_id:
            continue  # outside scope
        c = by_id[ident]
        status = _current_status(ident)
        gap = {
            "identifier": ident,
            "topic": c.topic,
            "section": c.section,
            "description": c.description,
            "current_status": status,
            "score": entry.get("score"),
            "why": entry.get("why"),
        }
        ce = _current_entry(ident)
        if ce is not None:
            gap["current_entry"] = ce
        gaps.append(gap)
    total = len(gaps)
    return {"gaps": gaps[:limit], "total_outstanding": total, "shown": min(limit, total)}
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_coverage_gaps.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/coverage.py tests/test_coverage_gaps.py
git commit -m "feat: add coverage gap computation"
```

---

## Task 9: Server tool `ism_coverage_read`

**Files:**
- Modify: `src/ism_mcp/server.py`
- Create: `tests/test_server_coverage.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_coverage.py`:

```python
"""End-to-end MCP tool tests for the coverage manifest tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ism_mcp import server, store


SEED_TOML = """\
schema_version = 1

[scope]
classification = "P"
maturity = "ML2"
sections = ["Encryption", "Audit"]

[project]
name = "demo"

[controls."ISM-9001"]
status = "covered"
how_met = "Network is encrypted."
last_reviewed = 2026-05-28
files = ["src/net.py:1-20"]
"""


@pytest.fixture
def project_with_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / ".ism-coverage.toml"
    manifest.write_text(SEED_TOML)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def project_with_ism_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "none")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_coverage_read_returns_parsed_manifest(project_with_manifest, project_with_ism_db):
    result = json.loads(server.ism_coverage_read())
    assert result["scope"]["classification"] == "P"
    assert result["scope"]["maturity"] == "ML2"
    assert result["project"]["name"] == "demo"
    assert "ISM-9001" in result["controls"]
    assert result["controls"]["ISM-9001"]["status"] == "covered"
    assert result["controls"]["ISM-9001"]["last_reviewed"] == "2026-05-28"
    assert result["summary"] == {
        "total_curated": 1,
        "covered": 1,
        "partial": 0,
        "not_applicable": 0,
        "deferred": 0,
    }


def test_coverage_read_returns_error_when_missing(tmp_path, monkeypatch, project_with_ism_db):
    monkeypatch.chdir(tmp_path)
    result = json.loads(server.ism_coverage_read())
    assert "error" in result
    assert "no manifest" in result["error"].lower()


def test_coverage_read_status_filter(project_with_manifest, project_with_ism_db):
    result = json.loads(server.ism_coverage_read(status_filter="covered"))
    assert list(result["controls"].keys()) == ["ISM-9001"]
    result = json.loads(server.ism_coverage_read(status_filter="partial"))
    assert result["controls"] == {}


def test_coverage_read_warns_about_identifier_not_in_ism(
    tmp_path, monkeypatch, project_with_ism_db
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ism-coverage.toml").write_text(
        SEED_TOML
        + '\n[controls."ISM-7777"]\nstatus = "covered"\nhow_met = "x"\nlast_reviewed = 2026-05-28\n'
    )
    result = json.loads(server.ism_coverage_read())
    assert any("ISM-7777" in w for w in result["warnings"])
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_server_coverage.py -v
```

Expected: `AttributeError: module 'ism_mcp.server' has no attribute 'ism_coverage_read'`.

- [ ] **Step 3: Implement the tool**

Add `from . import coverage` to the import block at the top of `src/ism_mcp/server.py`, alongside the other `from . import ...` lines. `Path` is already imported.

Append the function definitions below before `def run() -> None:`:

```python
def _find_manifest_or_error(project_path: str | None) -> tuple[Path | None, dict | None]:
    start = Path(project_path) if project_path else Path.cwd()
    found = coverage.find_manifest(start)
    if found is None:
        return None, {
            "error": "no manifest found",
            "hint": (
                "create .ism-coverage.toml at the project root with at minimum a [scope] section"
            ),
        }
    return found, None


def _manifest_to_json(manifest: coverage.Manifest, status_filter: str | None) -> dict:
    controls = {}
    summary = {
        "total_curated": len(manifest.controls),
        "covered": 0,
        "partial": 0,
        "not_applicable": 0,
        "deferred": 0,
    }
    for ident, entry in manifest.controls.items():
        key = entry.status.replace("-", "_")
        summary[key] = summary.get(key, 0) + 1
        if status_filter is not None and entry.status != status_filter:
            continue
        controls[ident] = {
            "status": entry.status,
            "how_met": entry.how_met,
            "last_reviewed": entry.last_reviewed.isoformat(),
            "reviewed_by": entry.reviewed_by,
            "next_review": entry.next_review.isoformat() if entry.next_review else None,
            "files": entry.files,
            "commits": entry.commits,
            "urls": entry.urls,
            "attachments": entry.attachments,
        }
    return {
        "manifest_path": str(manifest.path),
        "scope": manifest.scope,
        "project": manifest.project,
        "summary": summary,
        "controls": controls,
        "warnings": manifest.warnings,
    }


@mcp.tool()
def ism_coverage_read(project_path: str | None = None, status_filter: str | None = None) -> str:
    """Read the project's coverage manifest. Returns scope, summary counts, and curated entries.

    Walks up from cwd if `project_path` is omitted. `status_filter` narrows the controls map
    to a single status (`covered|partial|not-applicable|deferred`); summary is unfiltered.
    """
    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None
    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    conn = _conn()
    extra_warnings: list[str] = list(manifest.warnings)
    for ident in manifest.controls:
        if store.get_control(conn, ident) is None:
            extra_warnings.append(f"{ident}: not present in the current ISM revision")
    manifest = coverage.Manifest(
        path=manifest.path,
        schema_version=manifest.schema_version,
        scope=manifest.scope,
        project=manifest.project,
        controls=manifest.controls,
        warnings=extra_warnings,
    )

    return json.dumps(_manifest_to_json(manifest, status_filter), indent=2)
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_server_coverage.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_coverage.py
git commit -m "feat: add ism_coverage_read MCP tool"
```

---

## Task 10: Server tool `ism_coverage_upsert`

**Files:**
- Modify: `src/ism_mcp/server.py`
- Modify: `tests/test_server_coverage.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_server_coverage.py`:

```python
def test_coverage_upsert_creates_entry(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ISM-9002",
            status="covered",
            how_met="Sessions terminate after 14 min.",
            files=["src/auth.py:1-20"],
        )
    )
    assert result["ok"] is True
    assert result["action"] == "created"
    parsed = json.loads(server.ism_coverage_read())
    assert "ISM-9002" in parsed["controls"]


def test_coverage_upsert_updates_existing_entry(project_with_manifest, project_with_ism_db):
    server.ism_coverage_upsert(
        identifier="ISM-9001",
        status="partial",
        how_met="Now partial.",
    )
    parsed = json.loads(server.ism_coverage_read())
    assert parsed["controls"]["ISM-9001"]["status"] == "partial"


def test_coverage_upsert_rejects_unknown_identifier(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ISM-9999",
            status="covered",
            how_met="x",
        )
    )
    assert "error" in result
    assert "no such control" in result["error"].lower()


def test_coverage_upsert_rejects_invalid_status(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ISM-9002",
            status="bogus",
            how_met="x",
        )
    )
    assert "error" in result
    assert "status" in result["error"].lower()


def test_coverage_upsert_rejects_missing_attachment(project_with_manifest, project_with_ism_db):
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ISM-9002",
            status="covered",
            how_met="x",
            attachments=[{"path": "nope.png", "description": "x"}],
        )
    )
    assert "error" in result
    assert "nope.png" in result["error"]


def test_coverage_upsert_defaults_last_reviewed_to_today(
    project_with_manifest, project_with_ism_db
):
    from datetime import date as _date

    server.ism_coverage_upsert(
        identifier="ISM-9002",
        status="covered",
        how_met="x",
    )
    parsed = json.loads(server.ism_coverage_read())
    assert parsed["controls"]["ISM-9002"]["last_reviewed"] == _date.today().isoformat()


def test_coverage_upsert_warns_out_of_scope(project_with_manifest, project_with_ism_db):
    # ISM-9002 is section 'Authentication' which is not in scope.sections = ["Encryption", "Audit"].
    result = json.loads(
        server.ism_coverage_upsert(
            identifier="ISM-9002",
            status="covered",
            how_met="x",
        )
    )
    assert result["ok"] is True
    assert any("scope" in w.lower() for w in result["warnings"])
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_server_coverage.py -v -k upsert
```

Expected: `AttributeError: ism_coverage_upsert`.

- [ ] **Step 3: Implement the tool**

Add `from datetime import date as _date` to the imports at the top of `src/ism_mcp/server.py`.

Append the function definitions below before `def run() -> None:`:

```python
def _is_in_scope(scope: dict, control) -> bool:
    sections = scope.get("sections")
    if sections and control.section not in sections:
        return False
    classification = scope.get("classification")
    if classification:
        try:
            normalised = cls.normalise_classification(classification)
        except ValueError:
            return True  # malformed scope shouldn't prevent inserts
        if not control.applies.get(normalised, False):
            return False
    maturity = scope.get("maturity")
    if maturity:
        try:
            normalised_m = cls.normalise_maturity(maturity)
        except ValueError:
            return True
        if not control.maturity.get(normalised_m, False):
            return False
    return True


@mcp.tool()
def ism_coverage_upsert(
    identifier: str,
    status: str,
    how_met: str,
    last_reviewed: str | None = None,
    reviewed_by: str | None = None,
    next_review: str | None = None,
    files: list[str] | None = None,
    commits: list[str] | None = None,
    urls: list[dict] | None = None,
    attachments: list[dict] | None = None,
    project_path: str | None = None,
) -> str:
    """Create or update one entry in the coverage manifest.

    Validates identifier against the ISM DB, validates status enum, validates that
    every attachment path resolves on disk and that every url and attachment carries
    a description. `last_reviewed` defaults to today. Writes are atomic.
    """
    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None

    conn = _conn()
    control = store.get_control(conn, identifier)
    if control is None:
        return json.dumps(
            {
                "error": (
                    f"no such control: {identifier}. "
                    "Use ism_search or ism_list_topics to find the right id."
                )
            }
        )

    try:
        last_reviewed_date = _date.fromisoformat(last_reviewed) if last_reviewed else _date.today()
        next_review_date = _date.fromisoformat(next_review) if next_review else None
    except ValueError as e:
        return json.dumps({"error": f"date format: {e}"})

    entry = coverage.ManifestEntry(
        identifier=identifier,
        status=status,
        how_met=how_met,
        last_reviewed=last_reviewed_date,
        reviewed_by=reviewed_by,
        next_review=next_review_date,
        files=list(files or []),
        commits=list(commits or []),
        urls=list(urls or []),
        attachments=list(attachments or []),
    )

    try:
        result = coverage.upsert_entry(path, entry)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)})

    manifest = coverage.read_manifest(path)
    if not _is_in_scope(manifest.scope, control):
        result["warnings"].append(f"{identifier}: identifier is outside declared scope")

    return json.dumps(result, indent=2)
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_server_coverage.py -v
```

Expected: 11 tests pass (4 prior + 7 new).

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_coverage.py
git commit -m "feat: add ism_coverage_upsert MCP tool"
```

---

## Task 11: Server tool `ism_coverage_gaps`

**Files:**
- Modify: `src/ism_mcp/server.py`
- Modify: `tests/test_server_coverage.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_server_coverage.py`:

```python
def test_coverage_gaps_without_work_lists_outstanding_in_scope(
    project_with_manifest, project_with_ism_db
):
    # Seed manifest covers ISM-9001 (Encryption). ISM-9003 is in scope sections (Audit)
    # but uncurated. ISM-9002 is Authentication (out of scope sections).
    result = json.loads(server.ism_coverage_gaps())
    ids = [g["identifier"] for g in result["gaps"]]
    assert "ISM-9003" in ids
    assert "ISM-9001" not in ids  # covered
    assert "ISM-9002" not in ids  # out of scope


def test_coverage_gaps_with_work_intersects_with_applicable(
    project_with_manifest, project_with_ism_db
):
    result = json.loads(server.ism_coverage_gaps(work="event logging"))
    # ISM-9003 (Event logging) should surface for this work via lexical match on the topic.
    ids = [g["identifier"] for g in result["gaps"]]
    assert "ISM-9003" in ids
    # And each gap should carry score + why because work was supplied.
    g = next(g for g in result["gaps"] if g["identifier"] == "ISM-9003")
    assert "score" in g
    assert "why" in g


def test_coverage_gaps_returns_error_when_manifest_missing(
    tmp_path, monkeypatch, project_with_ism_db
):
    monkeypatch.chdir(tmp_path)
    result = json.loads(server.ism_coverage_gaps())
    assert "error" in result


def test_coverage_gaps_limit_truncates(project_with_manifest, project_with_ism_db):
    result = json.loads(server.ism_coverage_gaps(limit=1))
    assert len(result["gaps"]) <= 1
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/test_server_coverage.py -v -k gaps
```

Expected: `AttributeError: ism_coverage_gaps`.

- [ ] **Step 3: Implement the tool**

Append to `src/ism_mcp/server.py`:

```python
@mcp.tool()
def ism_coverage_gaps(
    work: str | None = None,
    project_path: str | None = None,
    limit: int = 50,
) -> str:
    """Return outstanding in-scope controls (uncurated, partial, deferred).

    If `work` is supplied, runs `ism_applicable` with the project's scope as filters
    and intersects with the manifest to return work-relevant gaps ranked by score.
    Without `work`, returns the full outstanding set ordered uncurated > partial > deferred.
    """
    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None

    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    conn = _conn()
    try:
        in_scope = store.list_in_scope(
            conn,
            classification=manifest.scope.get("classification"),
            maturity=manifest.scope.get("maturity"),
            sections=manifest.scope.get("sections"),
        )
    except ValueError as e:
        return json.dumps({"error": f"scope: {e}"})

    applicable: list[dict] | None = None
    if work is not None:
        raw = json.loads(
            ism_applicable(
                work,
                classification=manifest.scope.get("classification"),
                maturity=manifest.scope.get("maturity"),
                tags=manifest.scope.get("sections"),
                limit=200,
            )
        )
        if "error" in raw:
            return json.dumps({"error": f"ism_applicable: {raw['error']}"})
        applicable = raw.get("results") or []

    result = coverage.compute_gaps(manifest, in_scope, applicable=applicable, limit=limit)
    return json.dumps(
        {
            "scope": manifest.scope,
            "work": work,
            **result,
        },
        indent=2,
    )
```

Note: `compute_gaps` already returns `gaps`, `total_outstanding`, `shown`. The server adds `scope` and `work` to the response envelope.

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/test_server_coverage.py -v
```

Expected: 15 tests pass.

- [ ] **Step 5: Run full CI**

```bash
./scripts/ci.sh
```

Expected: `==> CI OK`.

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_coverage.py
git commit -m "feat: add ism_coverage_gaps MCP tool"
```

---

## Task 12: README documentation and manifest template

**Files:**
- Modify: `README.md`
- Create: `src/ism_mcp/data/coverage_template.toml`

- [ ] **Step 1: Create the template**

Create `src/ism_mcp/data/coverage_template.toml`:

```toml
schema_version = 1

[scope]
classification = "P"           # NC | OS | P | S | TS
maturity = "ML2"               # ML1 | ML2 | ML3, optional
sections = []                  # narrow to specific ISM sections, optional

[project]
name = ""
description = ""

# Each control entry:
#
# [controls."ISM-XXXX"]
# status = "covered"           # covered | partial | not-applicable | deferred
# how_met = """Project-specific narrative."""
# last_reviewed = 2026-05-28
# reviewed_by = "name"         # optional
# next_review = 2027-05-28     # optional
# files = ["src/path.py:1-20"]
# commits = ["abc1234"]
#
# [[controls."ISM-XXXX".urls]]
# url = "https://..."
# description = "Why this URL is relevant"
#
# [[controls."ISM-XXXX".attachments]]
# path = ".ism-coverage/evidence/ISM-XXXX/screenshot.png"
# description = "What this evidence shows"
```

- [ ] **Step 2: Document the manifest in README**

Locate the "MCP tools" table in `README.md`. Append three new rows:

```markdown
| `ism_coverage_read(project_path?, status_filter?)` | Read the project's `.ism-coverage.toml` manifest, including scope, summary counts, and curated entries. |
| `ism_coverage_upsert(identifier, status, how_met, ...)` | Create or update one entry with evidence (files, commits, urls, attachments). Validates against the ISM DB and the project filesystem. |
| `ism_coverage_gaps(work?, limit?)` | Return outstanding in-scope controls. With `work`, ranks by `ism_applicable` relevance and intersects with the manifest. |
```

Then add a new section before "Architecture":

```markdown
## Project coverage manifest

For projects pursuing IRAP review (or any internal review against the ISM), `.ism-coverage.toml` at the project root records how each in-scope control is addressed.

```toml
schema_version = 1

[scope]
classification = "P"
maturity = "ML2"
sections = ["Authentication hardening", "Cryptographic fundamentals"]

[project]
name = "demo-admin"

[controls."ISM-0428"]
status = "covered"
how_met = """
Sessions terminate after 14 min of idle activity, enforced
in the auth middleware. Re-auth requires all original factors.
"""
last_reviewed = 2026-05-28
files = ["src/auth/session.py:42-87"]
commits = ["abc1234"]

[[controls."ISM-0428".attachments]]
path = ".ism-coverage/evidence/ISM-0428/lock-prompt.png"
description = "Admin console at 14:01 showing session-expired modal"
```

Recommended layout for binary evidence:

```
your-repo/
  .ism-coverage.toml
  .ism-coverage/
    evidence/
      ISM-0428/
        lock-prompt.png
        tls-handshake.pcapng
```

A template lives at `src/ism_mcp/data/coverage_template.toml` if you want to copy and start from a known-good shape.

Reference design: `docs/superpowers/specs/2026-05-28-coverage-manifest-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md src/ism_mcp/data/coverage_template.toml
git commit -m "docs: document the coverage manifest tools and schema"
```

---

## Task 13: Final integration check and HANDOVER update

**Files:**
- Modify: `HANDOVER.md`

- [ ] **Step 1: End-to-end check against a temporary project**

```bash
TMP=$(mktemp -d)
cat > "$TMP/.ism-coverage.toml" <<'EOF'
schema_version = 1

[scope]
classification = "P"
maturity = "ML2"
sections = ["Authentication hardening", "Cryptographic fundamentals"]

[project]
name = "ad-hoc-check"

[controls."ISM-0428"]
status = "covered"
how_met = "Sessions terminate after 14 min."
last_reviewed = 2026-05-28
EOF

cd "$TMP" && uv --project /home/dudley/code/ism-mcp run python -c "
import json
from ism_mcp import server
print('--- read ---')
print(server.ism_coverage_read())
print('--- gaps (no work) ---')
print(server.ism_coverage_gaps(limit=5))
print('--- gaps (work=MFA on admins) ---')
print(server.ism_coverage_gaps(work='enforcing MFA on administrative accounts', limit=5))
"
```

Expected:
- `read` shows the seeded manifest with `summary.covered == 1`.
- `gaps` (no work) shows outstanding in-scope controls, ordered uncurated-first.
- `gaps` with work shows ranked relevant controls with `score` and `why` populated, excluding ISM-0428.

- [ ] **Step 2: Confirm `upsert` from the same temporary project**

```bash
cd "$TMP" && uv --project /home/dudley/code/ism-mcp run python -c "
import json
from ism_mcp import server
r = server.ism_coverage_upsert(
    identifier='ISM-0974',
    status='partial',
    how_met='MFA enforced for admin portal logins; service accounts still pending.',
    files=['src/auth/mfa.py'],
)
print(r)
print(server.ism_coverage_read(status_filter='partial'))
"
```

Expected: `ok=True`, `action=created`, and the read shows the new entry with `last_reviewed` set to today.

- [ ] **Step 3: Run the full CI suite**

```bash
./scripts/ci.sh
```

Expected: `==> CI OK`.

- [ ] **Step 4: Update HANDOVER.md**

Replace the "Where we are" and "Next action" sections to reflect the new state. Use this exact prose, adjusting only the date and any deferred items list:

```markdown
## Where we are

Sub-projects A (hardening), B (hybrid discovery), and D (coverage manifest) are merged. The MCP server now exposes:

- `ism_applicable(work, ...)` for ranked discovery.
- `ism_coverage_read | upsert | gaps` for per-project IRAP-grade coverage tracking.
- `ism_list_sections | classifications | maturities` as enum helpers.
- The original six tools unchanged.

The coverage manifest lives at `.ism-coverage.toml` in each consumer repo with a sibling `.ism-coverage/evidence/` for binaries. Schema and tool surface are documented in `docs/superpowers/specs/2026-05-28-coverage-manifest-design.md` and in the README.

## Next action

Open `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` and pick the next sub-project:

1. **Sub-project C: Graph and curated cuts.** `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs a brainstorm cycle before a plan is written.
2. **Sub-project E: Consumer install helper.** `ism-mcp install --project PATH`. Now unblocked because D's manifest shape is locked in. Needs a brainstorm cycle.

Either can ship next. C is a query-side extension; E is consumer-side ergonomics. Pick based on what consumers ask for first.
```

- [ ] **Step 5: Commit HANDOVER**

```bash
git add HANDOVER.md
git commit -m "docs: update handover after coverage manifest lands"
```

- [ ] **Step 6: Final working-tree check**

```bash
git status
```

Expected: `nothing to commit, working tree clean`.

---

## Deliverables at end of plan

- `coverage.py` module: dataclasses, read, validate, serialise, atomic upsert, gap computation. Plain Python, no MCP dependency.
- Three new MCP tools: `ism_coverage_read`, `ism_coverage_upsert`, `ism_coverage_gaps`.
- `store.list_in_scope(conn, classification, maturity, sections)` helper.
- `src/ism_mcp/data/coverage_template.toml` for scaffolding (future sub-project E uses it).
- Roughly 35 new tests across `test_coverage_manifest.py`, `test_coverage_read.py`, `test_coverage_validation.py`, `test_coverage_serialise.py`, `test_coverage_upsert.py`, `test_coverage_gaps.py`, `test_server_coverage.py`, plus 5 new tests in `test_store.py`.
- README section on the manifest, schema example, and recommended evidence directory layout.
- HANDOVER points the next session at sub-project C or E.

## Self-review notes for the executing agent

- The `ism_coverage_gaps(work=...)` server tool calls the in-process `ism_applicable(...)` function and parses its JSON response. This is intentionally simple. A future refactor could expose the underlying retrieval as a Python helper, but that is not required for this plan.
- `coverage.py` has zero MCP dependency. Anything that requires the ISM DB (e.g., "is this identifier in the current revision?") happens in the server-layer wrappers, not in `coverage.py`. This keeps the module testable without fixtures.
- Atomic writes use `tempfile.mkstemp` in the same directory as the manifest plus `os.replace`. Same directory is required so the rename is atomic on POSIX.
- `_is_in_scope` in the server uses `cls.normalise_classification` and `cls.normalise_maturity` from sub-project B. It silently returns `True` if the manifest's scope values are malformed — that is intentional so a typo in scope doesn't block upserts.
- The hand-rolled serialiser only supports the manifest schema's value types (int, str, list of strings, list of tables for urls and attachments, dates). If the schema grows, extend `_toml_value` and `_toml_string` accordingly.
- Some tests use `monkeypatch.chdir(tmp_path)` to put the server's cwd inside the test directory. The `find_manifest` walk-up relies on this. If a test runs the server without chdir, the walk-up will hit the real filesystem.
- `test_coverage_upsert_warns_out_of_scope` relies on the seeded manifest's `sections = ["Encryption", "Audit"]` excluding ISM-9002 (section `"Authentication"`). If the `sample_controls` fixture changes section names, this test must be updated.

## Next plan after this lands

Either sub-project C (graph and curated cuts) or sub-project E (consumer install helper). Both need a brainstorm cycle. Reference spec: `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md`.
