# Typed datamodel and structured outputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every one of the 17 MCP tools returns a TypedDict with a real outputSchema and structuredContent, takes Literal-typed enum parameters, and raises ToolError on failure instead of returning `{"error": ...}` strings.

**Architecture:** One new `src/ism_mcp/models.py` holds all vocabulary Literals and response TypedDicts (functional syntax where a key is a Python keyword). Tool bodies keep building plain dicts; annotations, ToolError raises, and explicit-None backfill for conditional keys are the changes. `coverage.py` backfills None in `compute_gaps`/`compute_impact` and imports `Status` from models.

**Tech Stack:** Python 3.14, mcp 1.27.1 FastMCP, typing.TypedDict, pytest.

**Source of truth for the design:** `docs/superpowers/specs/2026-07-02-typed-datamodel-design.md`. Read it before starting.

## Global Constraints

- Python 3.14+, `from __future__ import annotations` in every module.
- No `;`, no em-dash, no marketing words, no task numbers in code, comments, docstrings, or commit messages. Default to zero comments.
- TDD: failing test first, prove the failure mode, implement, green, commit.
- `uv run ruff format src tests && ./scripts/ci.sh test` before each commit. Conventional-commit prefixes.
- No conditionally absent response keys: conditional keys are required and typed `X | None`, the code emits explicit `None`.
- `NotRequired` is banned (the SDK emits omitted keys as null and the wire validator rejects them).
- Error messages preserve existing text exactly, hints folded verbatim after `. `. Tests match ToolError messages by substring.

---

### Task 1: models.py and the Status move

**Files:**
- Create: `src/ism_mcp/models.py`
- Modify: `src/ism_mcp/coverage.py` (drop its `Status` Literal, import from models)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces every name later tasks annotate with: `Classification`, `FriendlyClassification`, `ClassificationInput`, `Maturity`, `Status`, `ChangeType`, `ChangeField`, `AppliesMap`, `MaturityMap`, `ControlRecord`, `SearchResult`, `ClassificationControls`, `TopicsList`, `TopicControls`, `Stats`, `VersionEntry`, `VersionsResult`, `SectionsList`, `ClassificationVocab`, `MaturityVocab`, `ChangedControlRef`, `RewordedEntry`, `RetitledEntry`, `MoveEndpoint`, `MovedEntry`, `ApplicabilityChange`, `MaturityChange`, `DiffSummary`, `DiffChanges`, `DiffResult`, `TimelineEntry`, `HistoryResult`, `AppliedFilters`, `ApplicableEntry`, `ApplicableResult`, `CoverageEntry`, `CoverageReadResult`, `UpsertResult`, `GapCurrentEntry`, `GapEntry`, `GapsResult`, `ImpactSummary`, `ReReviewEntry`, `RemovedUpstreamEntry`, `NewUncoveredEntry`, `ImpactResult`.

- [ ] **Step 1: Write the failing test** (`tests/test_models.py`)

```python
"""The response models mirror the payloads the tools build."""

from __future__ import annotations

from ism_mcp import coverage, models


def test_status_is_shared_with_coverage():
    assert coverage.Status is models.Status


def test_diff_result_uses_keyword_keys():
    assert set(models.DiffResult.__annotations__) == {"from", "to", "summary", "changes"}
    assert set(models.RetitledEntry.__annotations__) == {
        "identifier",
        "label",
        "title",
        "from",
        "to",
    }


def test_control_record_matches_store_as_dict_keys():
    from ism_mcp import store

    c = store.Control(
        version="v",
        identifier="ism-0001",
        label="1",
        title="t",
        control_class="c",
        guideline="g",
        section="s",
        topic="p",
        control_revision=None,
        updated=None,
        sort_id=None,
        description="d",
        applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity={"ML1": False, "ML2": False, "ML3": False},
    )
    assert set(c.as_dict()) == set(models.ControlRecord.__annotations__)


def test_no_notrequired_keys_anywhere():
    import typing

    for name in dir(models):
        obj = getattr(models, name)
        if typing.is_typeddict(obj):
            assert obj.__required_keys__ == frozenset(obj.__annotations__), name
```

- [ ] **Step 2: Run it, expect ImportError** (`uv run pytest tests/test_models.py -v` fails with `No module named 'ism_mcp.models'` or missing attribute)

- [ ] **Step 3: Create `src/ism_mcp/models.py`**

```python
"""Vocabulary literals and response models for the MCP tools. No runtime logic."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Classification = Literal["NC", "OS", "P", "S", "TS"]
FriendlyClassification = Literal[
    "OFFICIAL", "OFFICIAL:Sensitive", "PROTECTED", "SECRET", "TOP_SECRET"
]
ClassificationInput = Classification | FriendlyClassification
Maturity = Literal["ML1", "ML2", "ML3"]
Status = Literal["covered", "partial", "not-applicable", "deferred"]
ChangeType = Literal[
    "added",
    "removed",
    "reworded",
    "retitled",
    "moved",
    "applicability_changed",
    "maturity_changed",
]
ChangeField = Literal[
    "reworded", "retitled", "moved", "applicability_changed", "maturity_changed"
]


class AppliesMap(TypedDict):
    NC: bool
    OS: bool
    P: bool
    S: bool
    TS: bool


class MaturityMap(TypedDict):
    ML1: bool
    ML2: bool
    ML3: bool


class ControlRecord(TypedDict):
    version: str
    identifier: str
    label: str
    title: str
    control_class: str
    guideline: str
    section: str
    topic: str
    description: str
    control_revision: str | None
    updated: str | None
    sort_id: str | None
    applies: AppliesMap
    maturity: MaturityMap


class SearchResult(TypedDict):
    query: str
    count: int
    results: list[ControlRecord]


class ClassificationControls(TypedDict):
    classification: Classification
    count: int
    identifiers: list[str]


class TopicsList(TypedDict):
    count: int
    topics: list[str]


class TopicControls(TypedDict):
    topic: str
    count: int
    identifiers: list[str]


class Stats(TypedDict):
    active_version: str | None
    versions: int
    controls: int
    oscal_version: str | None
    git_tag: str | None
    db_path: str


class VersionEntry(TypedDict):
    version: str
    label: str | None
    published: str | None
    control_count: int | None
    git_tag: str | None
    is_active: bool


class VersionsResult(TypedDict):
    active: str | None
    count: int
    versions: list[VersionEntry]


class SectionsList(TypedDict):
    count: int
    sections: list[str]


class ClassificationVocab(TypedDict):
    canonical: list[Classification]
    friendly: list[FriendlyClassification]


class MaturityVocab(TypedDict):
    maturities: list[Maturity]


class ChangedControlRef(TypedDict):
    identifier: str
    label: str
    title: str
    section: str


class RewordedEntry(TypedDict):
    identifier: str
    label: str
    title: str
    diff: str


RetitledEntry = TypedDict(
    "RetitledEntry",
    {"identifier": str, "label": str, "title": str, "from": str, "to": str},
)


class MoveEndpoint(TypedDict):
    guideline: str
    section: str
    topic: str


MovedEntry = TypedDict(
    "MovedEntry",
    {
        "identifier": str,
        "label": str,
        "title": str,
        "from": MoveEndpoint,
        "to": MoveEndpoint,
    },
)


class ApplicabilityChange(TypedDict):
    identifier: str
    label: str
    title: str
    added: list[Classification]
    removed: list[Classification]


class MaturityChange(TypedDict):
    identifier: str
    label: str
    title: str
    added: list[Maturity]
    removed: list[Maturity]


class DiffSummary(TypedDict):
    added: int | None
    removed: int | None
    reworded: int | None
    retitled: int | None
    moved: int | None
    applicability_changed: int | None
    maturity_changed: int | None


class DiffChanges(TypedDict):
    added: list[ChangedControlRef] | None
    removed: list[ChangedControlRef] | None
    reworded: list[RewordedEntry] | None
    retitled: list[RetitledEntry] | None
    moved: list[MovedEntry] | None
    applicability_changed: list[ApplicabilityChange] | None
    maturity_changed: list[MaturityChange] | None


DiffResult = TypedDict(
    "DiffResult",
    {"from": str, "to": str, "summary": DiffSummary, "changes": DiffChanges},
)


class TimelineEntry(TypedDict):
    version: str
    title: str
    applicability: list[Classification]
    maturity: list[Maturity]
    changed: list[ChangeField]


class HistoryResult(TypedDict):
    identifier: str
    first_seen: str | None
    last_seen: str | None
    timeline: list[TimelineEntry]
    hint: str | None


class AppliedFilters(TypedDict):
    classification: Classification | None
    maturity: Maturity | None
    tags: list[str]
    paths: list[str]


class ApplicableEntry(TypedDict):
    identifier: str
    label: str
    title: str
    topic: str
    section: str
    description: str
    applies: AppliesMap
    maturity: MaturityMap
    score: float
    why: list[str]
    guideline: str | None


class ApplicableResult(TypedDict):
    query: str
    filters: AppliedFilters
    count: int
    candidates_before_filter: int
    results: list[ApplicableEntry]
    hint: str | None


class CoverageEntry(TypedDict):
    status: str
    how_met: str
    last_reviewed: str
    reviewed_against: str | None
    reviewed_by: str | None
    next_review: str | None
    files: list[str]
    commits: list[str]
    urls: list[dict[str, Any]]
    attachments: list[dict[str, Any]]


class CoverageReadResult(TypedDict):
    manifest_path: str
    scope: dict[str, Any]
    project: dict[str, Any]
    summary: dict[str, int]
    controls: dict[str, CoverageEntry]
    warnings: list[str]


class UpsertResult(TypedDict):
    ok: bool
    identifier: str
    action: Literal["created", "updated"]
    warnings: list[str]


class GapCurrentEntry(TypedDict):
    how_met: str
    last_reviewed: str


class GapEntry(TypedDict):
    identifier: str
    topic: str
    section: str
    description: str
    current_status: str
    current_entry: GapCurrentEntry | None
    score: float | None
    why: list[str] | None


class GapsResult(TypedDict):
    scope: dict[str, Any]
    work: str | None
    gaps: list[GapEntry]
    total_outstanding: int
    shown: int


class ImpactSummary(TypedDict):
    re_review: int
    removed_upstream: int
    new_uncovered: int
    still_valid: int


class ReReviewEntry(TypedDict):
    identifier: str
    status: Literal["covered", "partial"]
    reviewed_against: str
    changes: list[ChangeField]
    how_met: str
    diff: str | None


class RemovedUpstreamEntry(TypedDict):
    identifier: str
    status: Literal["covered", "partial"]
    reviewed_against: str
    hint: str


class NewUncoveredEntry(TypedDict):
    identifier: str
    label: str
    title: str
    section: str
    reason: str


class ImpactResult(TypedDict):
    manifest_path: str
    baseline_version: str | None
    target_version: str
    summary: ImpactSummary
    re_review: list[ReReviewEntry]
    removed_upstream: list[RemovedUpstreamEntry]
    new_uncovered: list[NewUncoveredEntry]
```

- [ ] **Step 4: Point `coverage.py` at the shared Status.** Replace its `Status = Literal[...]` line with `from .models import Status` (keep `Literal` import only if still used elsewhere in the module).

- [ ] **Step 5: Run the test, expect PASS** (`uv run pytest tests/test_models.py -v`, 4 tests)

- [ ] **Step 6: Full fast suite green, commit** (`./scripts/ci.sh test`, then `git add -A && git commit -m "feat: add response models and vocabulary literals"`)

### Task 2: lookup family

**Files:**
- Modify: `src/ism_mcp/server.py` (ism_get, ism_search, ism_list_by_classification, ism_list_topics, ism_list_by_topic, ism_stats, ism_versions, ism_list_sections, ism_list_classifications, ism_list_maturities)
- Test: `tests/test_server_lookups.py`, `tests/test_server_helpers.py`, `tests/test_server_versions.py` (stats and versions tests only)

**Interfaces:**
- Consumes Task 1 models. Produces the pattern every later task copies: `from mcp.server.fastmcp.exceptions import ToolError` plus `from . import models` in server.py, tools return plain dicts against model annotations, error paths `raise ToolError(...)`.

- [ ] **Step 1: Update the tests.** Drop `json.loads(...)` around every direct tool call (the tool now returns the dict). Convert the two error tests:

```python
def test_ism_get_unknown_raises(populated_db):
    with pytest.raises(ToolError, match="no such control"):
        server.ism_get("ism-0000")


def test_ism_list_by_classification_unknown_raises(populated_db):
    with pytest.raises(ToolError, match="unknown classification"):
        server.ism_list_by_classification("BOGUS")
```

with `from mcp.server.fastmcp.exceptions import ToolError` imported. The missing-database test keeps `pytest.raises(RuntimeError)`.

- [ ] **Step 2: Run, expect TypeError** (`json.loads` of dict) and DID-NOT-RAISE failures.

- [ ] **Step 3: Convert the ten tools.** Pattern for a value tool and an error tool:

```python
@mcp.tool(annotations=READ_ONLY)
def ism_get(identifier: str, version: str | None = None) -> models.ControlRecord:
    ...
    c = store.get_control(conn, identifier, version=version)
    if c is None:
        raise ToolError(f"no such control: {identifier}")
    return c.as_dict()  # type: ignore[return-value]
```

`store.Control.as_dict` is annotated `-> dict`, hence the ignore (or retype `as_dict` to `models.ControlRecord` and import models in store.py, preferred if no cycle: store may import models, models imports nothing). `ism_list_by_classification` takes `classification: models.Classification` and re-raises the store ValueError as ToolError. `ism_list_classifications` and `ism_list_maturities` return their static dicts against `ClassificationVocab`/`MaturityVocab`. Docstrings: replace `{"error": ...}` phrasing with `Fails with ...` wording.

- [ ] **Step 4: Run the three test files, expect PASS.**
- [ ] **Step 5: Commit** (`git commit -m "feat: typed returns and tool errors for the lookup tools"`)

### Task 3: diff and history

**Files:**
- Modify: `src/ism_mcp/server.py` (ism_diff, ism_history)
- Test: `tests/test_server_versions.py` (diff and history tests)

**Interfaces:**
- Consumes `models.DiffResult`, `models.DiffSummary`, `models.DiffChanges`, `models.HistoryResult`, `models.ChangeType`.

- [ ] **Step 1: Update tests.** Diff error tests become `pytest.raises(ToolError, match="no such version")` and `match="need two versions"`. Add assertions that an unfiltered diff carries all seven bucket keys non-None and a `change_types=["added"]` call has `result["changes"]["reworded"] is None`. History test asserts `hint is None` on the found path and, for an unknown id, `first_seen is None and last_seen is None and "no control" in result["hint"]`.

- [ ] **Step 2: Run, expect failures** (dict vs string, missing keys).

- [ ] **Step 3: Implement.** `ism_diff(from_version: str | None = None, to_version: str | None = None, change_types: list[models.ChangeType] | None = None) -> models.DiffResult`. Errors raise ToolError with hints folded (`"need two versions to diff. load history with ingest-history"`, `f"no such version: {v}. call ism_versions"`). The filter nulls instead of dropping:

```python
    result = diff.diff_controls(...)
    buckets = list(result["summary"])
    if change_types:
        keep = set(change_types)
        summary = {k: (result["summary"][k] if k in keep else None) for k in buckets}
        changes = {k: (result["changes"][k] if k in keep else None) for k in buckets}
    else:
        summary, changes = result["summary"], result["changes"]
    return {"from": from_v, "to": to_v, "summary": summary, "changes": changes}
```

`ism_history(identifier: str) -> models.HistoryResult`: unknown id returns `{"identifier": identifier, "first_seen": None, "last_seen": None, "timeline": [], "hint": "no control with that id in any version"}`; the found path wraps `diff.build_history` output with `{**history, "hint": None}`.

- [ ] **Step 4: Run, expect PASS. Commit** (`git commit -m "feat: typed diff and history results"`)

### Task 4: applicable and the shared helper

**Files:**
- Modify: `src/ism_mcp/server.py` (ism_applicable body extracted to `_applicable_result`, `_render_result`)
- Test: `tests/test_server_applicable.py`, `tests/test_real_embedder.py`

**Interfaces:**
- Produces `_applicable_result(work, classification, maturity, tags, paths, limit, verbose) -> models.ApplicableResult` (raises ToolError), consumed by Task 6's gaps tool.

- [ ] **Step 1: Update tests.** Drop json.loads. Error tests become ToolError matches (`"classification:"`, `"unknown tags"`). The verbose test asserts non-verbose entries carry `guideline is None` and hint-free successes carry `hint is None`.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.** Move the body into `_applicable_result` with the same logic, `raise ToolError(f"classification: {e}")` etc., `_render_result` always sets `"guideline": r["guideline"] if verbose else None`, response always sets `"hint": <text or None>`. The tool is a one-line wrapper with typed params `classification: models.ClassificationInput | None = None, maturity: models.Maturity | None = None` returning the helper's dict.
- [ ] **Step 4: Run (`uv run pytest tests/test_server_applicable.py -v`), expect PASS. Commit** (`git commit -m "feat: typed applicable results with shared helper"`)

### Task 5: coverage backfill in compute_gaps and compute_impact

**Files:**
- Modify: `src/ism_mcp/coverage.py:285-451`
- Test: `tests/test_coverage_gaps.py`, `tests/test_coverage_impact.py`, `tests/test_coverage_canonical.py`

**Interfaces:**
- `compute_gaps` gap dicts always carry `current_entry`, `score`, `why` (None-filled). `compute_impact` re_review entries always carry `diff` (None unless reworded).

- [ ] **Step 1: Update the unit tests** to assert the new always-present keys (`gap["score"] is None` without work, `item["diff"] is None` for non-reworded).
- [ ] **Step 2: Run, expect KeyError or assertion failures.**
- [ ] **Step 3: Implement.** In the no-work branch: `gap = {..., "current_entry": _current_entry(c.identifier), "score": None, "why": None}`. In the work branch: `"current_entry": _current_entry(ident)` unconditionally. In `compute_impact`: `"diff": diff_text(...) if (old is not None and "reworded" in fields) else None` inside the item literal.
- [ ] **Step 4: Run the three files, expect PASS. Commit** (`git commit -m "feat: always emit conditional gap and impact keys"`)

### Task 6: coverage tools

**Files:**
- Modify: `src/ism_mcp/server.py` (`_find_manifest_or_error` becomes `_find_manifest` raising ToolError, `_manifest_to_json`, four coverage tools)
- Test: `tests/test_server_coverage.py`

**Interfaces:**
- Consumes `_applicable_result` from Task 4 and Task 1 coverage models.

- [ ] **Step 1: Update tests.** Drop json.loads on the 23 wrapped calls. The five error tests become ToolError matches (`"no manifest found"`, `"no such control"`, `"not one of"`, `"attachment not found"`). Add: gaps-with-bad-scope raises ToolError matching `"ism_applicable: "` if such a fixture exists, else assert scope error text.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.** `_find_manifest(project_path) -> Path` raises `ToolError("no manifest found. create .ism-coverage.toml at the project root with at minimum a [scope] section")`. Tool signatures: `ism_coverage_read(project_path: str | None = None, status_filter: models.Status | None = None) -> models.CoverageReadResult`, `ism_coverage_upsert(..., status: models.Status, ...) -> models.UpsertResult` (drop the `# type: ignore` at ManifestEntry), `ism_coverage_gaps(...) -> models.GapsResult`, `ism_coverage_impact(...) -> models.ImpactResult`. Every caught ValueError/FileNotFoundError re-raises as ToolError with the same message. Impact's unknown target: `raise ToolError(f"no such target version: {target}. call ism_versions")`. Gaps replaces the json.loads round-trip:

```python
    try:
        raw = _applicable_result(work, classification=..., maturity=..., tags=..., limit=200)
    except ToolError as e:
        raise ToolError(f"ism_applicable: {e}") from e
    applicable = raw["results"]
```

- [ ] **Step 4: Run (`uv run pytest tests/test_server_coverage.py -v`), expect PASS. Commit** (`git commit -m "feat: typed coverage tools with tool errors"`)

### Task 7: schema round-trip tests, instructions, docs

**Files:**
- Create: `tests/test_server_schema.py`
- Modify: `src/ism_mcp/server.py` (instructions string), `README.md` (error-contract paragraph), `CLAUDE.md` (layout gains models.py)

**Interfaces:** none new.

- [ ] **Step 1: Write `tests/test_server_schema.py`** covering, per the spec Testing section: all 17 outputSchemas non-null, object-typed, and not `{"result": ...}`-wrapped; enum rendering for classification/status/change_types params; wire-level round-trips per response family via `mcp.shared.memory.create_connected_server_and_client_session` asserting `isError is False` and `structuredContent` equality with the direct-call payload; out-of-enum rejection through the client; `from`/`to` present in the diff schema; conditional keys null; a gaps scope failure surfacing `ism_applicable: ` by substring.
- [ ] **Step 2: Run, expect failures only if implementation drifted, fix in server.py, PASS.**
- [ ] **Step 3: Rewrite the instructions string** (typed structured results, isError failures) and sweep server docstrings for stale `{"error": ...}` phrasing.
- [ ] **Step 4: README error-contract paragraph, CLAUDE.md layout line for models.py.**
- [ ] **Step 5: Full CI** (`./scripts/ci.sh`, expect `==> CI OK`), slow suite (`./scripts/ci.sh slow`). **Commit** (`git commit -m "test: schema and wire round-trip coverage for typed tools"` then `docs:` commit if split).

## Spec coverage self-check

| Spec section | Task |
|---|---|
| Vocabulary aliases, model catalog | 1 |
| Typed input parameters | 2 (classification), 3 (change_types), 4 (classification/maturity), 6 (status, status_filter) |
| Error contract conversion set | 2, 3, 4, 6 |
| None-backfill rule | 3 (diff buckets, history), 4 (guideline, hint), 5 (gaps, impact) |
| Internal refactors (shared helper, Status move, instructions) | 4, 1, 7 |
| Testing section | 2-6 (per family), 7 (schema and wire) |
| Migration (README, CLAUDE.md) | 7 |

## Notes for the executor

- The suite stays green after every task. No intermediate red states span commits.
- `mcp.call_tool` in-process raises ToolError; only the wire client sees isError results. Message assertions by substring (clients see an `Error executing tool <name>: ` prefix).
- structuredContent comparisons: compare against the direct-call dict, never byte-compare the text block.
