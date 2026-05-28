# ism-mcp Hardening and Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the working prototype into a maintainable foundation by tightening PDF excerpt extraction, adding a pytest suite with hermetic fixtures, adding ruff and pyright, and wiring a local `scripts/ci.sh` source-of-truth that mirrors sibling projects.

**Architecture:** No structural changes to the package. New `tests/` directory with hermetic fixtures (synthetic XLSX generated in-test via openpyxl, PDF behaviour mocked at the `pdfplumber` boundary). New `scripts/ci.sh` runs ruff + pyright + pytest. Per-control PDF excerpt logic moves into its own function in `ingest.py` so it is testable independently.

**Tech Stack:** Python 3.14, uv, pytest, ruff, pyright, openpyxl (for fixture generation), pdfplumber (already a dep, mocked in tests).

---

## Task 1: Add dev dependencies and pytest configuration

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add dev dependencies via uv**

```bash
uv add --dev pytest pytest-cov ruff pyright
```

This updates `pyproject.toml`'s `[dependency-groups]` (or equivalent) and `uv.lock`.

- [ ] **Step 2: Confirm pytest runs**

```bash
uv run pytest --version
```

Expected: prints a pytest version, exits 0.

- [ ] **Step 3: Add `[tool.pytest.ini_options]` to `pyproject.toml`**

Append the following section to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--strict-markers", "--strict-config", "-ra"]
```

- [ ] **Step 4: Create the empty test package**

Create `tests/__init__.py` as an empty file.

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures for ism-mcp tests."""
```

- [ ] **Step 5: Confirm pytest discovers the empty suite**

```bash
uv run pytest
```

Expected: `no tests ran in 0.XXs`. Exit 0.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/
git commit -m "chore: add pytest, ruff, pyright dev deps and pytest config"
```

---

## Task 2: Add a shared in-memory database fixture

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write the fixture**

Replace `tests/conftest.py` with:

```python
"""Shared pytest fixtures for ism-mcp tests."""

from __future__ import annotations

import sqlite3

import pytest

from ism_mcp import store


@pytest.fixture
def db() -> sqlite3.Connection:
    """An empty in-memory SQLite database with the ism-mcp schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def sample_controls() -> list[store.Control]:
    """A small set of synthetic controls covering the schema's optional fields."""
    return [
        store.Control(
            identifier="ISM-9001",
            guideline="Guidelines for testing",
            section="Encryption",
            topic="Network encryption",
            revision="1",
            updated="May-26",
            description="All data communicated over network infrastructure is encrypted.",
            applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": False},
        ),
        store.Control(
            identifier="ISM-9002",
            guideline="Guidelines for testing",
            section="Authentication",
            topic="Session management",
            revision="2",
            updated="Jun-26",
            description="Sessions are terminated after fifteen minutes of inactivity.",
            applies={"NC": True, "OS": True, "P": True, "S": False, "TS": False},
            maturity={"ML1": True, "ML2": True, "ML3": True},
        ),
        store.Control(
            identifier="ISM-9003",
            guideline="Guidelines for testing",
            section="Audit",
            topic="Event logging",
            revision="1",
            updated="May-26",
            description="Events are logged to a centralised facility.",
            applies={"NC": False, "OS": False, "P": False, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": True},
            pdf_excerpt="Centralised event logging is required for all SECRET workloads.",
            pdf_page=42,
        ),
    ]
```

- [ ] **Step 2: Confirm pytest still passes**

```bash
uv run pytest
```

Expected: `no tests ran`. Exit 0.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add db and sample_controls pytest fixtures"
```

---

## Task 3: Test the store CRUD and FTS paths

**Files:**
- Create: `tests/test_store.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_store.py`:

```python
"""Tests for store.py: insert, get, FTS search, classification filter, meta."""

from __future__ import annotations

from ism_mcp import store


def test_insert_and_get_round_trip(db, sample_controls):
    store.insert_controls(db, sample_controls)
    fetched = store.get_control(db, "ISM-9001")
    assert fetched is not None
    assert fetched.identifier == "ISM-9001"
    assert fetched.description == sample_controls[0].description
    assert fetched.applies == sample_controls[0].applies


def test_get_returns_none_for_missing(db):
    assert store.get_control(db, "ISM-0000") is None


def test_count_controls(db, sample_controls):
    assert store.count_controls(db) == 0
    store.insert_controls(db, sample_controls)
    assert store.count_controls(db) == 3


def test_fts_search_by_keyword(db, sample_controls):
    store.insert_controls(db, sample_controls)
    results = store.search(db, "encryption", limit=10)
    assert [c.identifier for c in results] == ["ISM-9001"]


def test_fts_search_returns_empty_for_no_match(db, sample_controls):
    store.insert_controls(db, sample_controls)
    assert store.search(db, "xyzzy", limit=10) == []


def test_list_by_classification_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    ts = store.list_by_classification(db, "TS")
    assert {c.identifier for c in ts} == {"ISM-9001", "ISM-9003"}
    nc = store.list_by_classification(db, "NC")
    assert {c.identifier for c in nc} == {"ISM-9001", "ISM-9002"}


def test_list_by_classification_rejects_unknown(db):
    import pytest
    with pytest.raises(ValueError, match="unknown classification"):
        store.list_by_classification(db, "XX")


def test_list_topics_and_by_topic(db, sample_controls):
    store.insert_controls(db, sample_controls)
    topics = store.list_topics(db)
    assert "Network encryption" in topics
    network = store.list_by_topic(db, "Network encryption")
    assert [c.identifier for c in network] == ["ISM-9001"]


def test_meta_set_and_get(db):
    store.set_meta(db, "ism_revision", "2026-03")
    assert store.get_meta(db, "ism_revision") == "2026-03"
    store.set_meta(db, "ism_revision", "2026-06")
    assert store.get_meta(db, "ism_revision") == "2026-06"
    assert store.get_meta(db, "missing_key") is None
```

- [ ] **Step 2: Run the tests**

```bash
uv run pytest tests/test_store.py -v
```

Expected: 9 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_store.py
git commit -m "test: cover store CRUD, FTS, classification filter, meta"
```

---

## Task 4: Refactor PDF excerpt extraction into a testable per-control function

**Files:**
- Modify: `src/ism_mcp/ingest.py`

The current `attach_pdf_excerpts` extracts whole subsections (paragraphs grouped by blank line in `pdfplumber` text). The fix: find the `Control: ISM-NNNN` anchor that the ISM PDF emits for every control, and take the narrative paragraph immediately preceding it. The PDF is structured so each control has a short label line of the form `Control: ISM-NNNN; Revision: N; Updated: MMM-YY; Applicable: ...` directly following the prose that describes it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_excerpt_extraction.py`:

```python
"""Tests for the per-control PDF excerpt extractor."""

from __future__ import annotations

from ism_mcp.ingest import extract_excerpts_from_text


def test_extracts_narrative_paragraph_preceding_control_label():
    text = """Some unrelated content here.

Encryption ensures confidentiality. All data on the wire is protected.
Control: ISM-9001; Revision: 1; Updated: May-26; Applicable: NC, OS, P, S, TS

Logging events centrally helps detection. Aggregated logs enable correlation.
Control: ISM-9003; Revision: 1; Updated: May-26; Applicable: S, TS

Trailing prose."""
    excerpts = extract_excerpts_from_text(text, page_no=42)
    assert "ISM-9001" in excerpts
    assert "ISM-9003" in excerpts
    assert "Encryption ensures confidentiality" in excerpts["ISM-9001"][0]
    assert "All data on the wire" in excerpts["ISM-9001"][0]
    assert "Control: ISM-9001" not in excerpts["ISM-9001"][0]
    assert excerpts["ISM-9001"][1] == 42
    assert "Logging events centrally" in excerpts["ISM-9003"][0]


def test_returns_empty_for_text_without_control_labels():
    assert extract_excerpts_from_text("just prose without any labels", page_no=1) == {}


def test_multiple_controls_in_one_label_block():
    text = """A shared paragraph that two controls reference.
Control: ISM-1000; Revision: 1; Updated: May-26; Applicable: NC
Control: ISM-1001; Revision: 1; Updated: May-26; Applicable: NC"""
    excerpts = extract_excerpts_from_text(text, page_no=5)
    assert "ISM-1000" in excerpts and "ISM-1001" in excerpts
    assert excerpts["ISM-1000"][0] == excerpts["ISM-1001"][0]
    assert "shared paragraph" in excerpts["ISM-1000"][0]
```

- [ ] **Step 2: Run test, expect failure**

```bash
uv run pytest tests/test_excerpt_extraction.py -v
```

Expected: ImportError or "function not found".

- [ ] **Step 3: Implement `extract_excerpts_from_text` in `ingest.py`**

Add to `src/ism_mcp/ingest.py` (place above `attach_pdf_excerpts`):

```python
def extract_excerpts_from_text(text: str, page_no: int) -> dict[str, tuple[str, int]]:
    """Return a mapping of identifier to (excerpt, page) for every Control: label in the text.

    The excerpt is the narrative paragraph immediately preceding the control's label line.
    Consecutive label lines (multiple controls sharing one narrative) all map to the same excerpt.
    """
    label_re = re.compile(r"^\s*Control:\s*(ISM-\d{3,4})\b", re.M)
    lines = text.splitlines()

    label_positions: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        m = label_re.match(line)
        if m:
            label_positions.append((idx, m.group(1)))

    excerpts: dict[str, tuple[str, int]] = {}
    i = 0
    while i < len(label_positions):
        run_start = i
        while i + 1 < len(label_positions) and label_positions[i + 1][0] == label_positions[i][0] + 1:
            i += 1
        narrative = _paragraph_before(lines, label_positions[run_start][0])
        for j in range(run_start, i + 1):
            excerpts[label_positions[j][1]] = (narrative, page_no)
        i += 1
    return excerpts


def _paragraph_before(lines: list[str], label_line_idx: int) -> str:
    end = label_line_idx
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    start = end
    while start > 0 and lines[start - 1].strip() and not lines[start - 1].lstrip().startswith("Control:"):
        start -= 1
    return " ".join(line.strip() for line in lines[start:end] if line.strip())
```

- [ ] **Step 4: Run the test again**

```bash
uv run pytest tests/test_excerpt_extraction.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Rewire `attach_pdf_excerpts` to use the new extractor**

Replace the body of `attach_pdf_excerpts` in `src/ism_mcp/ingest.py` with:

```python
def attach_pdf_excerpts(controls: list[Control], pdf_path: Path) -> list[Control]:
    """Walk the PDF once, extract per-control excerpts, attach them to controls by identifier."""
    excerpts: dict[str, tuple[str, int]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if "Control:" not in text:
                continue
            for cid, (excerpt, pno) in extract_excerpts_from_text(text, page_no).items():
                excerpts.setdefault(cid, (excerpt, pno))
    return [
        Control(
            **{
                **c.as_dict(),
                "pdf_excerpt": excerpts.get(c.identifier, (None, None))[0],
                "pdf_page": excerpts.get(c.identifier, (None, None))[1],
            }
        )
        if c.identifier in excerpts
        else c
        for c in controls
    ]
```

- [ ] **Step 6: Remove the now-unused `_paragraphs` helper**

In `src/ism_mcp/ingest.py`, delete the `_paragraphs` function and its `Iterator` import if it is no longer referenced.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 8: Sanity-check against the real PDF**

```bash
uv run ism-mcp ingest \
    --xlsx "/home/dudley/code/wayland-remote/docs/ism/Cloud controls matrix template (March 2026).xlsx" \
    --pdf  "/home/dudley/code/wayland-remote/docs/ism/Information security manual (March 2026).pdf" \
    --revision 2026-03

uv run python -c "
from ism_mcp import store, server
conn = store.open_db(server.DEFAULT_DB)
c = store.get_control(conn, 'ISM-1781')
print('excerpt length:', len(c.pdf_excerpt or ''))
print('first 200 chars:', (c.pdf_excerpt or '')[:200])
"
```

Expected: excerpt length under ~600 chars (down from ~3500), and the excerpt is the network-encryption narrative paragraph, not the whole surrounding subsection.

- [ ] **Step 9: Commit**

```bash
git add src/ism_mcp/ingest.py tests/test_excerpt_extraction.py
git commit -m "fix: extract per-control PDF excerpts instead of whole subsections"
```

---

## Task 5: Test the XLSX ingester with a generated workbook

**Files:**
- Create: `tests/test_ingest_xlsx.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_ingest_xlsx.py`:

```python
"""Tests for the XLSX parser using a synthetic workbook generated in-test."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from ism_mcp.ingest import parse_xlsx


def _write_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Controls - January 2026"
    ws.append(["ISM Controls"] + [""] * 24)
    ws.append([
        "Guideline", "Section", "Topic", "Identifier", "Revision", "Updated",
        "NC", "OS", "P", "S", "TS",
        "ML1", "ML2", "ML3",
        "Description",
        "Scoping1", "Scoping2", "Scoping3",
        "Provider", "Implementation Status", "Comments",
        "Consumer Responsibility", "Consumer Impl", "Consumer Config", "Comments",
    ])
    ws.append([
        "Guidelines for testing", "Encryption", "Network encryption",
        "ISM-9001", "1", "Jan-26",
        "Yes", "Yes", "Yes", "No", "No",
        "Yes", "No", "No",
        "All data communicated over network infrastructure is encrypted.",
        "", "", "", "", "Not Assessed", "", "", "Not Assessed", "Not Assessed", "",
    ])
    ws.append([
        "Guidelines for testing", "Audit", "Event logging",
        "ISM-9002", "2", "Feb-26",
        "No", "No", "Yes", "Yes", "Yes",
        "No", "Yes", "Yes",
        "Events are logged to a centralised facility.",
        "", "", "", "", "Not Assessed", "", "", "Not Assessed", "Not Assessed", "",
    ])
    wb.save(path)


def test_parse_extracts_all_ism_rows(tmp_path):
    workbook = tmp_path / "ccm.xlsx"
    _write_workbook(workbook)
    controls = list(parse_xlsx(workbook))
    assert {c.identifier for c in controls} == {"ISM-9001", "ISM-9002"}


def test_parse_populates_classification_and_maturity(tmp_path):
    workbook = tmp_path / "ccm.xlsx"
    _write_workbook(workbook)
    by_id = {c.identifier: c for c in parse_xlsx(workbook)}
    assert by_id["ISM-9001"].applies == {"NC": True, "OS": True, "P": True, "S": False, "TS": False}
    assert by_id["ISM-9001"].maturity == {"ML1": True, "ML2": False, "ML3": False}
    assert by_id["ISM-9002"].applies == {"NC": False, "OS": False, "P": True, "S": True, "TS": True}
    assert by_id["ISM-9002"].maturity == {"ML1": False, "ML2": True, "ML3": True}


def test_parse_skips_non_ism_rows(tmp_path):
    workbook = tmp_path / "ccm.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Controls - January 2026"
    ws.append(["ISM Controls"] + [""] * 24)
    ws.append([
        "Guideline", "Section", "Topic", "Identifier", "Revision", "Updated",
        "NC", "OS", "P", "S", "TS",
        "ML1", "ML2", "ML3",
        "Description",
        "x", "x", "x", "x", "x", "x", "x", "x", "x", "x",
    ])
    ws.append(["g", "s", "t", "not-an-id", "1", "Jan-26", "Yes", "Yes", "Yes", "No", "No",
               "No", "No", "No", "desc", "", "", "", "", "", "", "", "", "", ""])
    wb.save(workbook)
    assert list(parse_xlsx(workbook)) == []


def test_parse_raises_when_controls_sheet_missing(tmp_path):
    workbook = tmp_path / "empty.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "OnlyInfo"
    wb.save(workbook)
    with pytest.raises(ValueError, match="no 'Controls - ...' sheet"):
        list(parse_xlsx(workbook))
```

- [ ] **Step 2: Run the tests**

```bash
uv run pytest tests/test_ingest_xlsx.py -v
```

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ingest_xlsx.py
git commit -m "test: cover XLSX parser with a synthetic workbook fixture"
```

---

## Task 6: Add ruff and pyright configuration

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Append ruff configuration to `pyproject.toml`**

Append:

```toml
[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["B011"]
```

- [ ] **Step 2: Append pyright configuration to `pyproject.toml`**

Append:

```toml
[tool.pyright]
include = ["src", "tests"]
pythonVersion = "3.14"
typeCheckingMode = "standard"
reportMissingTypeStubs = false
```

- [ ] **Step 3: Run ruff format and fix until clean**

```bash
uv run ruff format src tests
uv run ruff check src tests --fix
uv run ruff check src tests
```

Expected: `All checks passed!` from the third command.

- [ ] **Step 4: Run pyright and fix issues**

```bash
uv run pyright
```

Expected: `0 errors, 0 warnings, 0 informations`.

If pyright reports type errors in the existing code, fix them. Likely areas:
- Add `from __future__ import annotations` at the top of any module that uses PEP 604 unions in function signatures.
- The `_str_or_none` and `_yes` helpers in `ingest.py` accept `Any`. Annotate them as `def _yes(v: object) -> bool` and similar.
- The trailing fixture types in `conftest.py` (`yield conn` inside a generator) should use `Generator[sqlite3.Connection, None, None]`.

- [ ] **Step 5: Run pytest to confirm formatting changes did not break tests**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src tests
git commit -m "chore: configure ruff and pyright, fix lint and type issues"
```

---

## Task 7: Add the local CI script

**Files:**
- Create: `scripts/ci.sh`

- [ ] **Step 1: Write the script**

Create `scripts/ci.sh`:

```bash
#!/usr/bin/env bash
# Local CI entrypoint. Single source of truth for the check suite.
#
# Usage:
#   ./scripts/ci.sh              run all checks
#   ./scripts/ci.sh fmt          run only ruff format check
#   ./scripts/ci.sh lint         run only ruff lint
#   ./scripts/ci.sh type         run only pyright
#   ./scripts/ci.sh test         run only pytest
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

run_fmt() {
    echo "==> ruff format --check"
    uv run ruff format --check src tests
}

run_lint() {
    echo "==> ruff check"
    uv run ruff check src tests
}

run_type() {
    echo "==> pyright"
    uv run pyright
}

run_test() {
    echo "==> pytest"
    uv run pytest
}

case "${1:-all}" in
    fmt)  run_fmt ;;
    lint) run_lint ;;
    type) run_type ;;
    test) run_test ;;
    all)
        run_fmt
        run_lint
        run_type
        run_test
        ;;
    *)
        echo "Unknown target: $1" >&2
        echo "Usage: $0 [fmt|lint|type|test|all]" >&2
        exit 2
        ;;
esac

echo "==> CI OK"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/ci.sh
```

- [ ] **Step 3: Run it end-to-end**

```bash
./scripts/ci.sh
```

Expected: each stage prints its `==>` header and the final line is `==> CI OK`. Exit 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/ci.sh
git commit -m "ci: add local CI script for fmt, lint, type, test"
```

---

## Task 8: Update README with the new dev workflow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a "Development" section**

Append the following to `README.md`, after the existing "Use programmatically" section and before "MCP tools":

```markdown
## Development

```bash
uv sync                    install all deps including dev
uv run pytest              run the test suite
./scripts/ci.sh            full CI suite (fmt + lint + type + test)
./scripts/ci.sh test       single stage
```

The CI script is the source of truth for what counts as a passing build. Run it before pushing.
```

- [ ] **Step 2: Refresh the "Known limitations of the proto" section**

In `README.md`, replace the existing "Known limitations of the proto" section with:

```markdown
## Known limitations

- **No incremental updates.** Each ingest drops and rebuilds the database.
- **Single-revision database.** No history across ISM revisions. To diff two revisions, ingest into two database paths and diff externally.
- **No auth on the MCP server.** Suitable for local use only.
```

The "PDF excerpts are subsection-wide" entry is removed because Task 4 fixed it.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add Development section, refresh limitations after excerpt fix"
```

---

## Task 9: Final integration check

- [ ] **Step 1: Clean slate ingest**

```bash
rm -f ~/.local/share/ism-mcp/ism.db
uv run ism-mcp ingest \
    --xlsx "/home/dudley/code/wayland-remote/docs/ism/Cloud controls matrix template (March 2026).xlsx" \
    --pdf  "/home/dudley/code/wayland-remote/docs/ism/Information security manual (March 2026).pdf" \
    --revision 2026-03
```

Expected: `done. 1081 controls in /home/dudley/.local/share/ism-mcp/ism.db`.

- [ ] **Step 2: Spot-check the tightened excerpt**

```bash
uv run python -c "
from ism_mcp import store, server
conn = store.open_db(server.DEFAULT_DB)
c = store.get_control(conn, 'ISM-1781')
print('len:', len(c.pdf_excerpt or ''))
print(c.pdf_excerpt)
"
```

Expected: excerpt length under ~600 chars, content is the network-encryption narrative paragraph specifically.

- [ ] **Step 3: Run the full CI suite**

```bash
./scripts/ci.sh
```

Expected: `==> CI OK`.

- [ ] **Step 4: Verify the MCP server starts and registers all tools**

```bash
uv run python -c "
import asyncio
from ism_mcp import server
tools = asyncio.run(server.mcp.list_tools())
for t in tools:
    print(f'{t.name}')
print(f'({len(tools)} tools)')
"
```

Expected: six tools printed (`ism_get`, `ism_search`, `ism_list_by_classification`, `ism_list_topics`, `ism_list_by_topic`, `ism_stats`).

- [ ] **Step 5: Verify clean working tree**

```bash
git status
```

Expected: `nothing to commit, working tree clean`.

---

## Deliverables at end of plan

- pytest suite with hermetic fixtures (no dependency on the real ISM files)
- Per-control PDF excerpts instead of whole subsections (verified shorter and topic-correct)
- ruff and pyright pass clean
- `scripts/ci.sh` runs fmt + lint + type + test
- README documents the dev workflow
- Working tree clean, all tests pass, CI passes

## Self-review notes for the executing agent

If you find:

- pyright complains about the `Generator` fixture return type. Use `from collections.abc import Generator` and annotate `db()` as `-> Generator[sqlite3.Connection, None, None]`.
- pyright complains about untyped third-party imports. Add `# pyright: ignore[reportMissingTypeStubs]` on the import line or set `reportMissingTypeStubs = false` (already in the config).
- Ruff's `B008` flags pdfplumber's `with pdfplumber.open(...)` context manager. It does not — but if it does, add `# noqa: B008`.
- The real-PDF spot-check excerpt is still wider than expected. Inspect the page text with `page.extract_text()` directly. Some ISM pages have non-standard layout (Essential Eight maturity tables, for example) where the `Control:` label is in a different position. Document any new failure mode in HANDOVER.md's "Known limitations" section.
- The synthetic XLSX header in Task 5 needs adjustment to match `parse_xlsx`'s `required` set. The required columns are `{Identifier, Description, Guideline, Section, Topic}`. If you change the parser's required set, mirror it in the test.

## Next plan after this lands

Plan #2: capability expansion (`ism_neighbors`, `ism_essential8`, `ism_export`). Sketch in HANDOVER.md.
