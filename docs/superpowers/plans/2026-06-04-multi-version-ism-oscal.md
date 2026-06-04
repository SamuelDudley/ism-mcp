# Multi-version ISM and OSCAL migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the XLSX/PDF ingest with the official OSCAL mirror, hold every ISM release in one version-keyed database, and add catalog-diff, per-control history, and coverage-drift tools on top.

**Architecture:** One SQLite database gains a `versions` registry and an `active_version` pointer; `controls` and `controls_embeddings` are keyed by `(version, identifier)`. Existing lookup tools default to the active version. Deltas are computed on read from version rows (data is tiny). Ingest parses OSCAL JSON from a git clone of `AustralianCyberSecurityCentre/ism-oscal`, walking tags for full history.

**Tech Stack:** Python 3.14, sqlite3 + FTS5, numpy, fastembed (`bge-small-en-v1.5`, 384-dim), stdlib `json`/`subprocess`/`difflib`. uv + hatchling. pytest, ruff, pyright via `./scripts/ci.sh`.

**Source of truth for the design:** `docs/superpowers/specs/2026-06-04-multi-version-ism-oscal-design.md`. Read it before starting.

---

## Conventions for every task

- TDD: write the failing test, run it, see it fail for the stated reason, implement, run it green, commit.
- All modules start with `from __future__ import annotations`.
- No `;`, no em-dash, no marketing words, no task/issue numbers in code, comments, docstrings, or commit messages. Default to no comments.
- Run the focused test with `uv run pytest <path>::<name> -v`. Before each commit run `uv run ruff format src tests && ./scripts/ci.sh test` unless the task says otherwise.
- Commit messages use conventional-commit prefixes (`feat:`, `refactor:`, `test:`, `chore:`, `docs:`, `build:`).

## File structure (created or rewritten)

```
src/ism_mcp/
  store.py        REWRITTEN schema + version registry + version-aware queries + identifier normalise + identifier-keyed embeddings
  oscal.py        NEW   parse one OSCAL catalog dict into VersionMeta + Control rows (pure, no DB/git)
  fetch.py        NEW   clone/pull the OSCAL repo, list tags, read a file at a tag (subprocess git)
  ingest.py       REWRITTEN orchestrate oscal over a dir or a tag walk, build embeddings (no openpyxl/pdfplumber)
  diff.py         NEW   pure comparison of two Control lists into change buckets, plus per-control history
  retrieve.py     EDIT  make VectorIndex / rrf id-type generic (identifiers are strings)
  embed.py        unchanged
  classification.py unchanged
  coverage.py     EDIT  reviewed_against field + serialise + compute_impact
  server.py       EDIT  retrieval keyed on identifier, version= on lookups, new ism_versions/ism_diff/ism_history/ism_coverage_impact, ism_stats
  __main__.py     REWRITTEN fetch / ingest / ingest-history / update subcommands
  data/coverage_template.toml  EDIT add baseline_version
tests/
  fixtures/oscal/ NEW   mini ISM_catalog.json + 3 mini E8 catalogs
  conftest.py     EDIT  sample_controls -> new Control shape
  test_store_versions.py   NEW
  test_store.py            EDIT to new Control shape and version-aware queries
  test_retrieve.py         EDIT string ids
  test_oscal_parse.py      NEW
  test_oscal_maturity.py   NEW
  test_fetch.py            NEW
  test_ingest_oscal.py     NEW
  test_ingest_embed.py     EDIT new embedding text + identifier keys
  test_cli.py              EDIT new subcommands
  test_diff.py             NEW
  test_history.py          NEW
  test_server_versions.py  NEW (ism_versions/diff/history + version= params)
  test_server_applicable.py EDIT identifier-keyed retrieval still works
  test_server_lookups.py    EDIT new Control fields
  test_server_coverage.py   EDIT reviewed_against + impact
  test_coverage_impact.py   NEW
  test_ingest_xlsx.py       DELETE
  test_excerpt_extraction.py DELETE
pyproject.toml    EDIT drop openpyxl + pdfplumber
README.md / HANDOVER.md / CLAUDE.md  EDIT docs
```

Phases A through F each leave the suite green. Phase G is cleanup and docs. Work the phases in order. Within a phase, the tasks are ordered by dependency.

---

# Phase A: version-keyed data layer

## Task A1: new schema, dataclasses, and version registry

**Files:**
- Modify: `src/ism_mcp/store.py` (SCHEMA lines 15-60, Control dataclass lines 67-94, add registry functions)
- Test: `tests/test_store_versions.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_store_versions.py`:

```python
"""Tests for the versions registry and active-version pointer in store.py."""

from __future__ import annotations

import sqlite3

import pytest

from ism_mcp import store


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    yield conn
    conn.close()


def test_schema_has_versions_table(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(versions)")}
    assert {"version", "label", "published", "oscal_version", "git_tag", "control_count"} <= cols


def test_controls_primary_key_is_version_and_identifier(db):
    pk = [r["name"] for r in db.execute("PRAGMA table_info(controls)") if r["pk"]]
    assert pk == ["version", "identifier"]


def test_upsert_and_list_versions(db):
    store.upsert_version(
        db,
        version="2025.12.9",
        label="December 2025",
        published="2025-12-09",
        last_modified="2025-12-09",
        oscal_version="1.1.2",
        git_tag="v2025.12.9",
        git_commit="abc",
        ingested_at="2026-06-04T00:00:00Z",
        control_count=2,
    )
    store.upsert_version(
        db,
        version="2026.03.24",
        label="March 2026",
        published="2026-03-24",
        last_modified="2026-03-24",
        oscal_version="1.1.2",
        git_tag="v2026.03.24",
        git_commit="def",
        ingested_at="2026-06-04T00:00:00Z",
        control_count=3,
    )
    versions = store.list_versions(db)
    assert [v["version"] for v in versions] == ["2026.03.24", "2025.12.9"]
    assert store.get_version(db, "2025.12.9")["control_count"] == 2


def test_upsert_version_replaces_existing(db):
    for count in (2, 5):
        store.upsert_version(
            db,
            version="2025.12.9",
            label="December 2025",
            published="2025-12-09",
            last_modified="2025-12-09",
            oscal_version="1.1.2",
            git_tag=None,
            git_commit=None,
            ingested_at="2026-06-04T00:00:00Z",
            control_count=count,
        )
    assert store.get_version(db, "2025.12.9")["control_count"] == 5
    assert len(store.list_versions(db)) == 1


def test_active_version_round_trip(db):
    assert store.get_active_version(db) is None
    store.set_active_version(db, "2026.03.24")
    assert store.get_active_version(db) == "2026.03.24"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store_versions.py -v`
Expected: FAIL. `PRAGMA table_info(versions)` returns no rows (no such table) and `store.upsert_version` raises `AttributeError`.

- [ ] **Step 3: Replace the SCHEMA constant**

In `src/ism_mcp/store.py`, replace the entire `SCHEMA = """ ... """` block (lines 15-60) with:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    version       TEXT PRIMARY KEY,
    label         TEXT,
    published     TEXT,
    last_modified TEXT,
    oscal_version TEXT,
    git_tag       TEXT,
    git_commit    TEXT,
    ingested_at   TEXT,
    control_count INTEGER
);

CREATE TABLE IF NOT EXISTS controls (
    version          TEXT NOT NULL,
    identifier       TEXT NOT NULL,
    label            TEXT,
    title            TEXT,
    control_class    TEXT,
    guideline        TEXT NOT NULL,
    section          TEXT NOT NULL,
    topic            TEXT NOT NULL,
    description      TEXT NOT NULL,
    control_revision TEXT,
    updated          TEXT,
    sort_id          TEXT,
    applies_nc      INTEGER NOT NULL,
    applies_os      INTEGER NOT NULL,
    applies_p       INTEGER NOT NULL,
    applies_s       INTEGER NOT NULL,
    applies_ts      INTEGER NOT NULL,
    maturity_ml1    INTEGER NOT NULL,
    maturity_ml2    INTEGER NOT NULL,
    maturity_ml3    INTEGER NOT NULL,
    PRIMARY KEY (version, identifier)
);

CREATE INDEX IF NOT EXISTS controls_by_identifier ON controls(identifier);

CREATE VIRTUAL TABLE IF NOT EXISTS controls_fts USING fts5(
    identifier UNINDEXED,
    description,
    topic,
    section,
    guideline,
    content='controls',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS controls_ai AFTER INSERT ON controls BEGIN
    INSERT INTO controls_fts(rowid, identifier, description, topic, section, guideline)
    VALUES (new.rowid, new.identifier, new.description, new.topic, new.section, new.guideline);
END;

CREATE TRIGGER IF NOT EXISTS controls_ad AFTER DELETE ON controls BEGIN
    INSERT INTO controls_fts(controls_fts, rowid, identifier, description, topic, section, guideline)
    VALUES ('delete', old.rowid, old.identifier, old.description, old.topic, old.section, old.guideline);
END;

CREATE TABLE IF NOT EXISTS controls_embeddings (
    version    TEXT NOT NULL,
    identifier TEXT NOT NULL,
    embedding  BLOB NOT NULL,
    PRIMARY KEY (version, identifier)
);
"""

ACTIVE_VERSION_KEY = "active_version"
```

The `controls_ad` delete trigger keeps the external-content FTS index in sync when a version is replaced (the old schema never deleted rows, so it had no delete trigger).

- [ ] **Step 4: Replace the Control dataclass**

Replace the `Control` dataclass (lines 67-94) with:

```python
@dataclass(frozen=True)
class Control:
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
    applies: dict[str, bool]
    maturity: dict[str, bool]

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "identifier": self.identifier,
            "label": self.label,
            "title": self.title,
            "control_class": self.control_class,
            "guideline": self.guideline,
            "section": self.section,
            "topic": self.topic,
            "description": self.description,
            "control_revision": self.control_revision,
            "updated": self.updated,
            "sort_id": self.sort_id,
            "applies": dict(self.applies),
            "maturity": dict(self.maturity),
        }
```

- [ ] **Step 5: Add registry functions**

Append to `src/ism_mcp/store.py` (after `get_meta`):

```python
def upsert_version(
    conn: sqlite3.Connection,
    *,
    version: str,
    label: str | None,
    published: str | None,
    last_modified: str | None,
    oscal_version: str | None,
    git_tag: str | None,
    git_commit: str | None,
    ingested_at: str,
    control_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO versions(
            version, label, published, last_modified, oscal_version,
            git_tag, git_commit, ingested_at, control_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            label=excluded.label, published=excluded.published,
            last_modified=excluded.last_modified, oscal_version=excluded.oscal_version,
            git_tag=excluded.git_tag, git_commit=excluded.git_commit,
            ingested_at=excluded.ingested_at, control_count=excluded.control_count
        """,
        (
            version, label, published, last_modified, oscal_version,
            git_tag, git_commit, ingested_at, control_count,
        ),
    )
    conn.commit()


def list_versions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM versions ORDER BY version DESC").fetchall()
    return [dict(r) for r in rows]


def get_version(conn: sqlite3.Connection, version: str) -> dict | None:
    row = conn.execute("SELECT * FROM versions WHERE version = ?", (version,)).fetchone()
    return dict(row) if row else None


def delete_version(conn: sqlite3.Connection, version: str) -> None:
    conn.execute("DELETE FROM controls_embeddings WHERE version = ?", (version,))
    conn.execute("DELETE FROM controls WHERE version = ?", (version,))
    conn.execute("DELETE FROM versions WHERE version = ?", (version,))
    conn.commit()


def set_active_version(conn: sqlite3.Connection, version: str) -> None:
    set_meta(conn, ACTIVE_VERSION_KEY, version)


def get_active_version(conn: sqlite3.Connection) -> str | None:
    return get_meta(conn, ACTIVE_VERSION_KEY)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_store_versions.py -v`
Expected: PASS (5 tests).

Note: the rest of `store.py` (insert_controls, _row_to_control, queries, embeddings) still references the old Control shape and will be fixed in A2 and A3. Do not run the full suite yet.

- [ ] **Step 7: Commit**

```bash
git add src/ism_mcp/store.py tests/test_store_versions.py
git commit -m "feat: version-keyed schema and version registry in store"
```

---

## Task A2: version-aware control queries and identifier normalisation

**Files:**
- Modify: `src/ism_mcp/store.py` (`_row_to_control`, `insert_controls`, `get_control`, `search`, `list_*`, `count_controls`, add `normalise_identifier`, `list_controls`)
- Modify: `tests/conftest.py` (`sample_controls`)
- Modify: `tests/test_store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Update the shared fixture**

Replace `sample_controls` in `tests/conftest.py` with the new Control shape. The three controls now carry a `version`, plus `label`/`title`/`control_class`/`sort_id`, and drop `pdf_excerpt`/`pdf_page`:

```python
@pytest.fixture
def sample_controls() -> list[store.Control]:
    """A small set of synthetic controls covering the schema's optional fields."""
    v = "2026.03.24"
    return [
        store.Control(
            version=v,
            identifier="ism-9001",
            label="9001",
            title="Control: ism-9001",
            control_class="ISM-control",
            guideline="Guidelines for testing",
            section="Encryption",
            topic="Network encryption",
            control_revision="1",
            updated="May-26",
            sort_id="catalog[1].group[01].control[1]",
            description="All data communicated over network infrastructure is encrypted.",
            applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": False},
        ),
        store.Control(
            version=v,
            identifier="ism-9002",
            label="9002",
            title="Control: ism-9002",
            control_class="ISM-control",
            guideline="Guidelines for testing",
            section="Authentication",
            topic="Session management",
            control_revision="2",
            updated="Jun-26",
            sort_id="catalog[1].group[02].control[1]",
            description="Sessions are terminated after fifteen minutes of inactivity.",
            applies={"NC": True, "OS": True, "P": True, "S": False, "TS": False},
            maturity={"ML1": True, "ML2": True, "ML3": True},
        ),
        store.Control(
            version=v,
            identifier="ism-9003",
            label="9003",
            title="Control: ism-9003",
            control_class="ISM-control",
            guideline="Guidelines for testing",
            section="Audit",
            topic="Event logging",
            control_revision="1",
            updated="May-26",
            sort_id="catalog[1].group[03].control[1]",
            description="Events are logged to a centralised facility.",
            applies={"NC": False, "OS": False, "P": False, "S": True, "TS": True},
            maturity={"ML1": False, "ML2": False, "ML3": True},
        ),
    ]
```

- [ ] **Step 2: Rewrite test_store.py for the new shape**

Replace `tests/test_store.py` in full. Identifiers are now lowercase `ism-NNNN`, controls carry a version, queries take a `version` argument defaulting to the active version, and there are no pdf fields. Embeddings are keyed by identifier.

```python
"""Tests for store.py: insert, get, FTS search, classification filter, meta, versions."""

from __future__ import annotations

import numpy as np
import pytest

from ism_mcp import store

V = "2026.03.24"


def _activate(db):
    store.set_active_version(db, V)


def test_insert_and_get_round_trip(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    fetched = store.get_control(db, "ism-9001")
    assert fetched is not None
    assert fetched.identifier == "ism-9001"
    assert fetched.description == sample_controls[0].description
    assert fetched.applies == sample_controls[0].applies
    assert fetched.version == V


def test_get_returns_none_for_missing(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    assert store.get_control(db, "ism-0000") is None


def test_get_control_tolerant_identifier_forms(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    for raw in ("ISM-9001", "ism-9001", "9001"):
        c = store.get_control(db, raw)
        assert c is not None and c.identifier == "ism-9001"


def test_count_controls(db, sample_controls):
    _activate(db)
    assert store.count_controls(db) == 0
    store.insert_controls(db, sample_controls)
    assert store.count_controls(db) == 3


def test_fts_search_by_keyword(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    results = store.search(db, "encryption", limit=10)
    assert [c.identifier for c in results] == ["ism-9001"]


def test_search_tolerates_fts_metacharacters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    results = store.search(db, "network: encryption")
    assert [c.identifier for c in results] == ["ism-9001"]


def test_search_does_not_raise_on_operator_soup(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    for query in ["rate AND OR limit", "(unbalanced", "* prefix", "NEAR(x", "C:\\path"]:
        assert isinstance(store.search(db, query), list)


def test_list_by_classification_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    ts = store.list_by_classification(db, "TS")
    assert {c.identifier for c in ts} == {"ism-9001", "ism-9003"}
    nc = store.list_by_classification(db, "NC")
    assert {c.identifier for c in nc} == {"ism-9001", "ism-9002"}


def test_list_topics_and_by_topic(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    assert "Network encryption" in store.list_topics(db)
    network = store.list_by_topic(db, "Network encryption")
    assert [c.identifier for c in network] == ["ism-9001"]


def test_queries_scope_to_a_version(db, sample_controls):
    store.insert_controls(db, sample_controls)
    older = [
        store.Control(**{**c.as_dict(), "version": "2025.12.9", "applies": c.applies, "maturity": c.maturity})
        for c in sample_controls[:1]
    ]
    store.insert_controls(db, older)
    store.set_active_version(db, V)
    assert store.count_controls(db) == 3
    assert store.count_controls(db, version="2025.12.9") == 1
    assert store.get_control(db, "ism-9002", version="2025.12.9") is None


def test_meta_set_and_get(db):
    store.set_meta(db, "active_version", "2026.03")
    assert store.get_meta(db, "active_version") == "2026.03"
    assert store.get_meta(db, "missing_key") is None


def test_insert_and_fetch_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    vectors = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]], dtype=np.float32)
    store.insert_embeddings(
        db,
        [
            (V, "ism-9001", vectors[0].tobytes()),
            (V, "ism-9002", vectors[1].tobytes()),
            (V, "ism-9003", vectors[2].tobytes()),
        ],
    )
    matrix, ids = store.load_embedding_matrix(db, dim=4, version=V)
    assert matrix.shape == (3, 4)
    assert matrix.dtype == np.float32
    assert ids == ["ism-9001", "ism-9002", "ism-9003"]


def test_load_embedding_matrix_empty(db):
    matrix, ids = store.load_embedding_matrix(db, dim=4, version=V)
    assert matrix.shape == (0, 4)
    assert ids == []


def test_delete_version_drops_controls_and_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    store.insert_embeddings(db, [(V, "ism-9001", (b"\x00" * 16))])
    store.upsert_version(
        db, version=V, label="March 2026", published=None, last_modified=None,
        oscal_version=None, git_tag=None, git_commit=None,
        ingested_at="2026-06-04T00:00:00Z", control_count=3,
    )
    store.delete_version(db, V)
    store.set_active_version(db, V)
    assert store.count_controls(db) == 0
    assert store.load_embedding_matrix(db, dim=4, version=V)[1] == []
    # FTS stays in sync after delete:
    assert store.search(db, "encryption", limit=10) == []


def test_list_in_scope_combines_filters(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    rows = store.list_in_scope(db, classification="TS", maturity="ML3", sections=["Audit"])
    assert {c.identifier for c in rows} == {"ism-9003"}


def test_list_in_scope_rejects_unknown_classification(db, sample_controls):
    store.insert_controls(db, sample_controls)
    _activate(db)
    with pytest.raises(ValueError, match="classification"):
        store.list_in_scope(db, classification="XX", maturity=None, sections=None)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL. `insert_controls` writes the old column list and `get_control` takes no `version`, so most tests error.

- [ ] **Step 4: Rewrite the store functions**

In `src/ism_mcp/store.py`:

Replace `_row_to_control` (lines 168-181) with:

```python
def _row_to_control(row: sqlite3.Row) -> Control:
    return Control(
        version=row["version"],
        identifier=row["identifier"],
        label=row["label"],
        title=row["title"],
        control_class=row["control_class"],
        guideline=row["guideline"],
        section=row["section"],
        topic=row["topic"],
        description=row["description"],
        control_revision=row["control_revision"],
        updated=row["updated"],
        sort_id=row["sort_id"],
        applies={c: bool(row[f"applies_{c.lower()}"]) for c in CLASSIFICATIONS},
        maturity={m: bool(row[f"maturity_{m.lower()}"]) for m in MATURITIES},
    )
```

Replace `insert_controls` (lines 131-165) with:

```python
def insert_controls(conn: sqlite3.Connection, controls: Iterable[Control]) -> int:
    count = 0
    for c in controls:
        conn.execute(
            """
            INSERT INTO controls(
                version, identifier, label, title, control_class,
                guideline, section, topic, description, control_revision, updated, sort_id,
                applies_nc, applies_os, applies_p, applies_s, applies_ts,
                maturity_ml1, maturity_ml2, maturity_ml3
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.version, c.identifier, c.label, c.title, c.control_class,
                c.guideline, c.section, c.topic, c.description, c.control_revision, c.updated, c.sort_id,
                int(c.applies["NC"]), int(c.applies["OS"]), int(c.applies["P"]),
                int(c.applies["S"]), int(c.applies["TS"]),
                int(c.maturity["ML1"]), int(c.maturity["ML2"]), int(c.maturity["ML3"]),
            ),
        )
        count += 1
    conn.commit()
    return count
```

Add a version resolver and identifier normaliser. Insert after `get_active_version`:

```python
import re as _re

_ID_DIGITS = _re.compile(r"\d+")


def _resolve_version(conn: sqlite3.Connection, version: str | None) -> str | None:
    return version if version is not None else get_active_version(conn)


def normalise_identifier(
    conn: sqlite3.Connection, raw: str, version: str | None = None
) -> str | None:
    """Resolve a user identifier (ism-1001, ISM-1001, 1001, or a label) to a canonical id."""
    version = _resolve_version(conn, version)
    if version is None:
        return None
    low = raw.strip().lower()
    row = conn.execute(
        "SELECT identifier FROM controls WHERE version = ? AND lower(identifier) = ?",
        (version, low),
    ).fetchone()
    if row:
        return row["identifier"]
    digits = "".join(_ID_DIGITS.findall(low))
    if digits and ("ism" in low or low == digits):
        cand = f"ism-{int(digits):04d}"
        row = conn.execute(
            "SELECT identifier FROM controls WHERE version = ? AND identifier = ?",
            (version, cand),
        ).fetchone()
        if row:
            return row["identifier"]
    row = conn.execute(
        "SELECT identifier FROM controls WHERE version = ? AND upper(label) = ?",
        (version, raw.strip().upper()),
    ).fetchone()
    return row["identifier"] if row else None
```

Replace `get_control` (lines 184-186) with:

```python
def get_control(
    conn: sqlite3.Connection, identifier: str, version: str | None = None
) -> Control | None:
    version = _resolve_version(conn, version)
    if version is None:
        return None
    row = conn.execute(
        "SELECT * FROM controls WHERE version = ? AND identifier = ?", (version, identifier)
    ).fetchone()
    if row is None:
        canon = normalise_identifier(conn, identifier, version)
        if canon is not None:
            row = conn.execute(
                "SELECT * FROM controls WHERE version = ? AND identifier = ?", (version, canon)
            ).fetchone()
    return _row_to_control(row) if row else None
```

Replace `search` (lines 199-213) with:

```python
def search(
    conn: sqlite3.Connection, query: str, limit: int = 10, version: str | None = None
) -> list[Control]:
    version = _resolve_version(conn, version)
    match = sanitise_fts_query(query)
    if not match or version is None:
        return []
    rows = conn.execute(
        """
        SELECT c.* FROM controls c
        JOIN controls_fts ON controls_fts.rowid = c.rowid
        WHERE controls_fts MATCH ? AND c.version = ?
        ORDER BY rank
        LIMIT ?
        """,
        (match, version, limit),
    ).fetchall()
    return [_row_to_control(r) for r in rows]
```

Replace `list_by_classification`, `list_in_scope`, `list_by_topic`, `list_topics`, `list_sections`, `count_controls` so each accepts `version: str | None = None`, resolves it, and adds `version = ?` to the WHERE clause. Full bodies:

```python
def list_by_classification(
    conn: sqlite3.Connection, classification: str, version: str | None = None
) -> list[Control]:
    cls = classification.upper()
    if cls not in CLASSIFICATIONS:
        raise ValueError(
            f"unknown classification {classification!r}, expected one of {CLASSIFICATIONS}"
        )
    version = _resolve_version(conn, version)
    rows = conn.execute(
        f"SELECT * FROM controls WHERE version = ? AND applies_{cls.lower()} = 1 "
        "ORDER BY identifier",
        (version,),
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_in_scope(
    conn: sqlite3.Connection,
    classification: str | None,
    maturity: str | None,
    sections: list[str] | None,
    version: str | None = None,
) -> list[Control]:
    version = _resolve_version(conn, version)
    where: list[str] = ["version = ?"]
    params: list = [version]
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
    clause = "WHERE " + " AND ".join(where)
    rows = conn.execute(
        f"SELECT * FROM controls {clause} ORDER BY identifier", params
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_by_topic(
    conn: sqlite3.Connection, topic: str, version: str | None = None
) -> list[Control]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT * FROM controls WHERE version = ? AND topic = ? ORDER BY identifier",
        (version, topic),
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_topics(conn: sqlite3.Connection, version: str | None = None) -> list[str]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT DISTINCT topic FROM controls WHERE version = ? ORDER BY topic", (version,)
    ).fetchall()
    return [r["topic"] for r in rows]


def list_sections(conn: sqlite3.Connection, version: str | None = None) -> list[str]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT DISTINCT section FROM controls WHERE version = ? ORDER BY section", (version,)
    ).fetchall()
    return [r["section"] for r in rows]


def list_controls(conn: sqlite3.Connection, version: str | None = None) -> list[Control]:
    """All controls for a version, ordered by sort_id then identifier. Used by diff."""
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT * FROM controls WHERE version = ? ORDER BY sort_id, identifier", (version,)
    ).fetchall()
    return [_row_to_control(r) for r in rows]
```

Replace `count_controls` (lines 279-280) with:

```python
def count_controls(conn: sqlite3.Connection, version: str | None = None) -> int:
    version = _resolve_version(conn, version)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM controls WHERE version = ?", (version,)
    ).fetchone()
    return int(row["n"])
```

Keep the existing `_re` import at the top of the module if one already exists; the `sanitise_fts_query` helper already imports `re` as `_FTS_WORD`. If `import re` is not present at module top, the `import re as _re` line added above covers the normaliser. Move that import to the top of the file with the other imports during ruff-format if it complains.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_store.py tests/test_store_versions.py -v`
Expected: PASS. Embeddings tests still reference `insert_embeddings`/`load_embedding_matrix` with the new identifier signature, which you implement in A3 — if those two tests fail with a signature error, that is expected; finish A3 before the full green.

Implementer note: A2 and A3 both touch the embeddings functions. Apply A3's Step 3 now if `test_insert_and_fetch_embeddings` fails, then re-run.

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/store.py tests/conftest.py tests/test_store.py
git commit -m "refactor: version-aware control queries and tolerant identifier lookup"
```

---

## Task A3: identifier-keyed embeddings and generic VectorIndex

**Files:**
- Modify: `src/ism_mcp/store.py` (`insert_embeddings`, `load_embedding_matrix`)
- Modify: `src/ism_mcp/retrieve.py` (`VectorIndex`, `rrf` id type)
- Modify: `tests/test_retrieve.py`
- Test: `tests/test_store.py` (the two embedding tests from A2), `tests/test_retrieve.py`

- [ ] **Step 1: Write the failing test**

Identifiers are now strings, so `VectorIndex`/`rrf` ids become `str`. Update the existing cases in `tests/test_retrieve.py` that pass integer ids (e.g. `1`, `2`) to string ids (e.g. `"ism-0001"`, `"ism-0002"`), then append two new tests:

```python
def test_vector_index_returns_string_ids():
    import numpy as np

    from ism_mcp import retrieve

    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    idx = retrieve.VectorIndex(matrix, ["ism-0001", "ism-0002"])
    hits = idx.search(np.array([1.0, 0.0], dtype=np.float32), top_k=1)
    assert hits[0][0] == "ism-0001"


def test_rrf_fuses_string_ids():
    from ism_mcp import retrieve

    fused = retrieve.rrf([[("a", 0.0), ("b", 0.0)], [("b", 0.0), ("a", 0.0)]])
    assert {rid for rid, _ in fused} == {"a", "b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retrieve.py::test_vector_index_returns_string_ids -v`
Expected: FAIL at the type-check stage or, if it runs, on pyright. Functionally the current code may pass; the change is mainly typing. Proceed to make the ids generic so pyright stays green.

- [ ] **Step 3: Update store embeddings to identifier keys**

Replace `insert_embeddings` (lines 283-289) and `load_embedding_matrix` (lines 292-301) with:

```python
def insert_embeddings(
    conn: sqlite3.Connection, rows: list[tuple[str, str, bytes]]
) -> int:
    """rows are (version, identifier, embedding_bytes)."""
    conn.executemany(
        "INSERT OR REPLACE INTO controls_embeddings(version, identifier, embedding) "
        "VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def load_embedding_matrix(
    conn: sqlite3.Connection, dim: int, version: str | None = None
) -> tuple[np.ndarray, list[str]]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT identifier, embedding FROM controls_embeddings WHERE version = ? "
        "ORDER BY identifier",
        (version,),
    ).fetchall()
    if not rows:
        return np.empty((0, dim), dtype=np.float32), []
    ids = [r["identifier"] for r in rows]
    matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(rows), dim)
    return matrix.copy(), ids
```

- [ ] **Step 4: Make retrieve.py id-generic**

In `src/ism_mcp/retrieve.py`, retype the ids as `str` (identifiers). Replace the top of the file and the two definitions:

```python
from __future__ import annotations

from collections import defaultdict

import numpy as np


class VectorIndex:
    """Dense matrix of L2-normalised embeddings, brute-force cosine search."""

    def __init__(self, matrix: np.ndarray, ids: list[str]) -> None:
        if matrix.shape[0] != len(ids):
            raise ValueError("matrix rows must match ids length")
        self._matrix = matrix
        self._ids = ids

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, query: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        k = max(0, min(top_k, self._matrix.shape[0]))
        if k == 0:
            return []
        scores = self._matrix @ query
        order = np.argpartition(-scores, k - 1)[:k]
        order = order[np.argsort(-scores[order])]
        return [(self._ids[int(i)], float(scores[int(i)])) for i in order]


def rrf(
    rankings: list[list[tuple[str, float]]],
    k: int = 60,
    normalised: bool = True,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. Returns fused [(id, score)] sorted by score desc."""
    accumulator: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (rid, _score) in enumerate(ranking, start=1):
            accumulator[rid] += 1.0 / (k + rank)
    if not accumulator:
        return []
    if normalised and rankings:
        max_score = len(rankings) / (k + 1)
        for rid in accumulator:
            accumulator[rid] = accumulator[rid] / max_score
    return sorted(accumulator.items(), key=lambda kv: (-kv[1], kv[0]))
```

The `(-score, id)` tie-break is deterministic because ids within any single call are homogeneous strings.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_retrieve.py tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/store.py src/ism_mcp/retrieve.py tests/test_retrieve.py
git commit -m "refactor: key embeddings by identifier and make fusion id-generic"
```

---

# Phase B: OSCAL parser

## Task B1: parse metadata and controls from a catalog dict

**Files:**
- Create: `src/ism_mcp/oscal.py`
- Create: `tests/fixtures/oscal/ISM_catalog.json`
- Test: `tests/test_oscal_parse.py`

- [ ] **Step 1: Create the fixture catalog**

Create `tests/fixtures/oscal/ISM_catalog.json`:

```json
{
  "catalog": {
    "uuid": "fixture-catalog",
    "metadata": {
      "title": "Information security manual",
      "published": "2025-12-09T07:27:00.000000Z",
      "last-modified": "2025-12-09T07:27:00.000000Z",
      "version": "2025.12.9",
      "oscal-version": "1.1.2"
    },
    "groups": [
      {
        "id": "g-roles",
        "title": "Guidelines for cyber security roles",
        "groups": [
          {
            "id": "g-roles-ciso",
            "title": "Chief information security officer",
            "groups": [
              {
                "id": "g-roles-ciso-lead",
                "title": "Providing cyber security leadership",
                "controls": [
                  {
                    "id": "ism-0714",
                    "class": "ISM-control",
                    "title": "Control: ism-0714",
                    "props": [
                      {"name": "sort-id", "value": "catalog[1].group[03].group[1].group[1].control[1]"},
                      {"name": "revision", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "3"},
                      {"name": "updated", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "Dec-25"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "NC"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "OS"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "P"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "S"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "TS"}
                    ],
                    "parts": [
                      {"id": "ism-0714_smt", "name": "statement", "prose": "A chief information security officer provides cyber security leadership."}
                    ]
                  },
                  {
                    "id": "ism-1997",
                    "class": "ISM-control",
                    "title": "Control: ism-1997",
                    "props": [
                      {"name": "sort-id", "value": "catalog[1].group[03].group[1].group[1].control[2]"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "TS"}
                    ],
                    "parts": [
                      {"id": "ism-1997_smt", "name": "statement", "prose": "Clear roles and responsibilities for cyber security are defined."}
                    ]
                  }
                ]
              }
            ]
          }
        ]
      },
      {
        "id": "g-prin",
        "title": "Cyber security principles",
        "groups": [
          {
            "id": "g-prin-the",
            "title": "The cyber security principles",
            "groups": [
              {
                "id": "g-prin-gov",
                "title": "Govern cyber security principles",
                "controls": [
                  {
                    "id": "ism-principle-gov-01",
                    "class": "ISM-principle",
                    "title": "Executive cyber security accountability",
                    "props": [
                      {"name": "sort-id", "value": "catalog[1].group[02].group[1].group[1].control[01]"},
                      {"name": "label", "value": "GOV-01"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "NC"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "OS"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "P"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "S"},
                      {"name": "applicability", "ns": "https://cyber.gov.au/ns/ism/oscal/3.0", "value": "TS"}
                    ],
                    "parts": [
                      {"id": "ism-principle-gov-01_smt", "name": "statement", "prose": "The board of directors or executive committee is accountable for cyber security."}
                    ]
                  }
                ]
              }
            ]
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_oscal_parse.py`:

```python
"""Tests for parsing an OSCAL ISM catalog into VersionMeta and Control rows."""

from __future__ import annotations

import json
from pathlib import Path

from ism_mcp import oscal

FIXTURE = Path(__file__).parent / "fixtures" / "oscal" / "ISM_catalog.json"


def _catalog() -> dict:
    return json.loads(FIXTURE.read_text())["catalog"]


def test_parse_metadata():
    meta = oscal.parse_metadata(_catalog())
    assert meta.version == "2025.12.9"
    assert meta.oscal_version == "1.1.2"
    assert meta.published.startswith("2025-12-09")


def test_parse_controls_yields_all_with_hierarchy():
    controls = list(oscal.parse_controls(_catalog(), maturity_sets={}))
    by_id = {c.identifier: c for c in controls}
    assert set(by_id) == {"ism-0714", "ism-1997", "ism-principle-gov-01"}

    c = by_id["ism-0714"]
    assert c.version == "2025.12.9"
    assert c.guideline == "Guidelines for cyber security roles"
    assert c.section == "Chief information security officer"
    assert c.topic == "Providing cyber security leadership"
    assert c.description.startswith("A chief information security officer")
    assert c.control_class == "ISM-control"
    assert c.control_revision == "3"
    assert c.updated == "Dec-25"
    assert c.applies == {"NC": True, "OS": True, "P": True, "S": True, "TS": True}
    assert c.label == "714"


def test_restricted_applicability():
    by_id = {c.identifier: c for c in oscal.parse_controls(_catalog(), maturity_sets={})}
    c = by_id["ism-1997"]
    assert c.applies == {"NC": False, "OS": False, "P": False, "S": False, "TS": True}
    assert c.control_revision is None


def test_principle_uses_label_prop():
    by_id = {c.identifier: c for c in oscal.parse_controls(_catalog(), maturity_sets={})}
    p = by_id["ism-principle-gov-01"]
    assert p.label == "GOV-01"
    assert p.control_class == "ISM-principle"
    assert p.title == "Executive cyber security accountability"


def test_maturity_from_sets():
    sets = {"ML1": {"ism-0714"}, "ML2": {"ism-0714"}, "ML3": {"ism-1997"}}
    by_id = {c.identifier: c for c in oscal.parse_controls(_catalog(), maturity_sets=sets)}
    assert by_id["ism-0714"].maturity == {"ML1": True, "ML2": True, "ML3": False}
    assert by_id["ism-1997"].maturity == {"ML1": False, "ML2": False, "ML3": True}
    assert by_id["ism-principle-gov-01"].maturity == {"ML1": False, "ML2": False, "ML3": False}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_oscal_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ism_mcp.oscal'`.

- [ ] **Step 4: Create the parser**

Create `src/ism_mcp/oscal.py`:

```python
"""Parse an OSCAL ISM catalog dict into version metadata and Control rows."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .store import CLASSIFICATIONS, MATURITIES, Control

APPLICABILITY_VALUES = set(CLASSIFICATIONS)
_NUMERIC_ID = re.compile(r"^ism-0*(\d+)$")


@dataclass(frozen=True)
class VersionMeta:
    version: str
    title: str
    published: str | None
    last_modified: str | None
    oscal_version: str | None


def load_catalog(path: Path) -> dict:
    """Read an OSCAL file and return the dict under the top-level 'catalog' key."""
    return json.loads(Path(path).read_text())["catalog"]


def parse_metadata(catalog: dict) -> VersionMeta:
    md = catalog.get("metadata", {})
    return VersionMeta(
        version=md["version"],
        title=md.get("title", ""),
        published=md.get("published"),
        last_modified=md.get("last-modified"),
        oscal_version=md.get("oscal-version"),
    )


def walk_controls(catalog: dict) -> Iterator[tuple[dict, str, str, str]]:
    """Yield (control, guideline, section, topic) for every control in the catalog.

    All ISM controls sit at group depth three: top group is the guideline, the
    first nested group is the section, the second nested group is the topic.
    """

    def walk(groups: list[dict], path: list[str]) -> Iterator[tuple[dict, str, str, str]]:
        for group in groups:
            new_path = path + [group.get("title", "")]
            for control in group.get("controls", []):
                guideline = new_path[0] if len(new_path) > 0 else ""
                section = new_path[1] if len(new_path) > 1 else ""
                topic = new_path[2] if len(new_path) > 2 else ""
                yield control, guideline, section, topic
            yield from walk(group.get("groups", []), new_path)

    yield from walk(catalog.get("groups", []), [])


def prop_values(control: dict, name: str) -> list[str]:
    return [p["value"] for p in control.get("props", []) if p.get("name") == name]


def first_prop(control: dict, name: str) -> str | None:
    values = prop_values(control, name)
    return values[0] if values else None


def applicability(control: dict) -> dict[str, bool]:
    present = set(prop_values(control, "applicability")) & APPLICABILITY_VALUES
    return {c: c in present for c in CLASSIFICATIONS}


def maturity(identifier: str, maturity_sets: dict[str, set[str]]) -> dict[str, bool]:
    return {m: identifier in maturity_sets.get(m, set()) for m in MATURITIES}


def statement_prose(control: dict) -> str:
    parts = control.get("parts", [])
    for part in parts:
        if part.get("name") == "statement":
            return part.get("prose", "")
    return parts[0].get("prose", "") if parts else ""


def derive_label(control: dict) -> str:
    label = first_prop(control, "label")
    if label:
        return label
    match = _NUMERIC_ID.match(control["id"])
    return match.group(1) if match else control["id"]


def collect_control_ids(catalog: dict) -> set[str]:
    return {control["id"] for control, _g, _s, _t in walk_controls(catalog)}


def parse_controls(
    catalog: dict, maturity_sets: dict[str, set[str]]
) -> Iterator[Control]:
    version = catalog.get("metadata", {})["version"]
    for control, guideline, section, topic in walk_controls(catalog):
        identifier = control["id"]
        yield Control(
            version=version,
            identifier=identifier,
            label=derive_label(control),
            title=control.get("title", ""),
            control_class=control.get("class", ""),
            guideline=guideline,
            section=section,
            topic=topic,
            description=statement_prose(control),
            control_revision=first_prop(control, "revision"),
            updated=first_prop(control, "updated"),
            sort_id=first_prop(control, "sort-id"),
            applies=applicability(control),
            maturity=maturity(identifier, maturity_sets),
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_oscal_parse.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/oscal.py tests/fixtures/oscal/ISM_catalog.json tests/test_oscal_parse.py
git commit -m "feat: OSCAL catalog parser for metadata and controls"
```

---

## Task B2: derive Essential Eight maturity from resolved catalogs

**Files:**
- Create: `tests/fixtures/oscal/ISM_E8_ML1-baseline-resolved-profile_catalog.json` (and ML2, ML3)
- Test: `tests/test_oscal_maturity.py`

- [ ] **Step 1: Create the three E8 fixture catalogs**

Each E8 fixture is a catalog wrapping a single group with the included controls. Create `tests/fixtures/oscal/ISM_E8_ML1-baseline-resolved-profile_catalog.json`:

```json
{
  "catalog": {
    "uuid": "fixture-e8-ml1",
    "metadata": {"title": "ISM E8 ML1", "version": "2025.12.9", "oscal-version": "1.1.2"},
    "groups": [
      {"id": "g", "title": "Essential Eight", "controls": [
        {"id": "ism-0714", "class": "ISM-control", "title": "Control: ism-0714",
         "parts": [{"id": "ism-0714_smt", "name": "statement", "prose": "x"}]}
      ]}
    ]
  }
}
```

Create `tests/fixtures/oscal/ISM_E8_ML2-baseline-resolved-profile_catalog.json` with controls `ism-0714` and `ism-1997`. Create `tests/fixtures/oscal/ISM_E8_ML3-baseline-resolved-profile_catalog.json` with control `ism-1997` only. Use the same wrapper shape, listing the relevant control objects in the `controls` array.

- [ ] **Step 2: Write the failing test**

Create `tests/test_oscal_maturity.py`:

```python
"""Tests for deriving Essential Eight maturity from resolved E8 catalogs."""

from __future__ import annotations

import json
from pathlib import Path

from ism_mcp import oscal

FX = Path(__file__).parent / "fixtures" / "oscal"


def _load(name: str) -> dict:
    return json.loads((FX / name).read_text())["catalog"]


def test_collect_control_ids_from_e8():
    ids = oscal.collect_control_ids(_load("ISM_E8_ML2-baseline-resolved-profile_catalog.json"))
    assert ids == {"ism-0714", "ism-1997"}


def test_maturity_sets_feed_parse_controls():
    sets = {
        "ML1": oscal.collect_control_ids(_load("ISM_E8_ML1-baseline-resolved-profile_catalog.json")),
        "ML2": oscal.collect_control_ids(_load("ISM_E8_ML2-baseline-resolved-profile_catalog.json")),
        "ML3": oscal.collect_control_ids(_load("ISM_E8_ML3-baseline-resolved-profile_catalog.json")),
    }
    catalog = _load("ISM_catalog.json")
    by_id = {c.identifier: c for c in oscal.parse_controls(catalog, sets)}
    assert by_id["ism-0714"].maturity == {"ML1": True, "ML2": True, "ML3": False}
    assert by_id["ism-1997"].maturity == {"ML1": False, "ML2": True, "ML3": True}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_oscal_maturity.py -v`
Expected: FAIL only if `collect_control_ids` has a bug, otherwise it should PASS because B1 already implemented `collect_control_ids`. If it passes immediately, that is acceptable; the test still guards the behaviour.

- [ ] **Step 4: Implement (if needed)**

`collect_control_ids` was added in B1. No code change expected. If the E8 wrapper nests controls differently from `walk_controls` expectations (controls directly under a top group rather than depth three), confirm `walk_controls` yields them regardless of depth (it walks all groups and yields any `controls` it finds at any level). It does.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_oscal_maturity.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/oscal/ISM_E8_*.json tests/test_oscal_maturity.py
git commit -m "test: derive Essential Eight maturity from resolved catalogs"
```

---

# Phase C: fetch, ingest, and CLI

## Task C1: git fetch helper

**Files:**
- Create: `src/ism_mcp/fetch.py`
- Test: `tests/test_fetch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetch.py`. It builds a real local git repo with two tagged commits, then exercises clone, tag listing, and reading a file at a tag. No network.

```python
"""Tests for the OSCAL git fetch helper against a local source repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ism_mcp import fetch


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "ISM_catalog.json").write_text('{"v": 1}')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "v1")
    _git(repo, "tag", "v2025.12.9")
    (repo / "ISM_catalog.json").write_text('{"v": 2}')
    _git(repo, "commit", "-aqm", "v2")
    _git(repo, "tag", "v2026.03.24")
    return repo


def test_ensure_clone_then_list_tags(source_repo: Path, tmp_path: Path):
    cache = tmp_path / "cache"
    repo_dir = fetch.ensure_clone(repo=str(source_repo), cache=cache)
    assert repo_dir.is_dir()
    tags = fetch.list_tags(repo_dir)
    assert tags == ["v2025.12.9", "v2026.03.24"]


def test_read_file_at_tag(source_repo: Path, tmp_path: Path):
    repo_dir = fetch.ensure_clone(repo=str(source_repo), cache=tmp_path / "cache")
    assert fetch.read_file_at_tag(repo_dir, "v2025.12.9", "ISM_catalog.json") == '{"v": 1}'
    assert fetch.read_file_at_tag(repo_dir, "v2026.03.24", "ISM_catalog.json") == '{"v": 2}'


def test_ensure_clone_is_idempotent(source_repo: Path, tmp_path: Path):
    cache = tmp_path / "cache"
    first = fetch.ensure_clone(repo=str(source_repo), cache=cache)
    second = fetch.ensure_clone(repo=str(source_repo), cache=cache)
    assert first == second
    assert fetch.list_tags(second) == ["v2025.12.9", "v2026.03.24"]


def test_missing_file_at_tag_raises(source_repo: Path, tmp_path: Path):
    repo_dir = fetch.ensure_clone(repo=str(source_repo), cache=tmp_path / "cache")
    with pytest.raises(fetch.GitError):
        fetch.read_file_at_tag(repo_dir, "v2025.12.9", "does_not_exist.json")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ism_mcp.fetch'`.

- [ ] **Step 3: Create the fetch helper**

Create `src/ism_mcp/fetch.py`:

```python
"""Clone or update the OSCAL ISM mirror and read files at tags. Shells out to git."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_REPO = "https://github.com/AustralianCyberSecurityCentre/ism-oscal.git"
DEFAULT_CACHE = Path.home() / ".local/share/ism-mcp/oscal"


class GitError(RuntimeError):
    pass


def _git(repo_dir: Path | None, *args: str) -> str:
    cmd = ["git"]
    if repo_dir is not None:
        cmd += ["-C", str(repo_dir)]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def ensure_clone(repo: str = DEFAULT_REPO, cache: Path = DEFAULT_CACHE) -> Path:
    """Clone `repo` into `cache` if absent, otherwise fetch tags. Return the repo dir."""
    cache = Path(cache)
    if (cache / ".git").is_dir():
        _git(cache, "fetch", "--tags", "--force", "origin")
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    _git(None, "clone", "--quiet", repo, str(cache))
    return cache


def list_tags(repo_dir: Path) -> list[str]:
    out = _git(Path(repo_dir), "tag", "--sort=v:refname")
    return [line.strip() for line in out.splitlines() if line.strip()]


def read_file_at_tag(repo_dir: Path, tag: str, relpath: str) -> str:
    return _git(Path(repo_dir), "show", f"{tag}:{relpath}")


def current_commit(repo_dir: Path, ref: str = "HEAD") -> str:
    return _git(Path(repo_dir), "rev-parse", ref).strip()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/fetch.py tests/test_fetch.py
git commit -m "feat: git fetch helper for the OSCAL mirror"
```

---

## Task C2: rewrite ingest orchestration

**Files:**
- Modify: `src/ism_mcp/ingest.py` (full rewrite)
- Modify: `tests/test_ingest_embed.py`
- Create: `tests/test_ingest_oscal.py`
- Test: `tests/test_ingest_oscal.py`, `tests/test_ingest_embed.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_oscal.py`:

```python
"""Tests for OSCAL ingest orchestration over a directory."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from ism_mcp import ingest, store

FX = Path(__file__).parent / "fixtures" / "oscal"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def oscal_dir(tmp_path: Path) -> Path:
    d = tmp_path / "oscal"
    d.mkdir()
    for f in FX.glob("*.json"):
        shutil.copy(f, d / f.name)
    return d


def test_load_version_from_dir(oscal_dir: Path):
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    assert vmeta.version == "2025.12.9"
    by_id = {c.identifier: c for c in controls}
    assert by_id["ism-0714"].maturity == {"ML1": True, "ML2": True, "ML3": False}


def test_ingest_version_writes_controls_and_registry(db, oscal_dir: Path):
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    ingest.ingest_version(db, vmeta, controls, embedder=None, git_tag="v2025.12.9", git_commit="abc")
    assert store.get_active_version(db) == "2025.12.9"
    assert store.count_controls(db) == 3
    assert store.get_version(db, "2025.12.9")["git_tag"] == "v2025.12.9"


def test_ingest_version_is_idempotent(db, oscal_dir: Path):
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    ingest.ingest_version(db, vmeta, controls)
    ingest.ingest_version(db, vmeta, controls)
    assert store.count_controls(db) == 3
    assert len(store.list_versions(db)) == 1


def test_version_label_humanises():
    assert ingest.version_label("2026.03.24") == "March 2026"
    assert ingest.version_label("2025.12.9") == "December 2025"
```

Update `tests/test_ingest_embed.py` to use the new identifier-keyed embeddings and embedding text. Replace its body with:

```python
"""End-to-end ingest with the deterministic hash embedder."""

from __future__ import annotations

import sqlite3

import numpy as np

from ism_mcp import ingest, store
from ism_mcp.embed import DeterministicHashEmbedder


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def test_embed_controls_yields_identifier_keyed_unit_vectors(sample_controls):
    embedder = DeterministicHashEmbedder(dim=384)
    rows = list(ingest.embed_controls(sample_controls, embedder))
    assert [ident for ident, _ in rows] == [c.identifier for c in sample_controls]
    vec = np.frombuffer(rows[0][1], dtype=np.float32)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5


def test_embedding_text_includes_hierarchy_and_description(sample_controls):
    text = ingest.embedding_text(sample_controls[0])
    assert "Network encryption" in text
    assert "encrypted" in text


def test_ingest_version_with_embedder_populates_matrix(sample_controls):
    db = _db()
    from ism_mcp.oscal import VersionMeta

    vmeta = VersionMeta(
        version="2026.03.24", title="ISM", published=None, last_modified=None, oscal_version="1.1.2"
    )
    ingest.ingest_version(db, vmeta, sample_controls, embedder=DeterministicHashEmbedder(dim=384))
    matrix, ids = store.load_embedding_matrix(db, dim=384, version="2026.03.24")
    assert matrix.shape == (3, 384)
    assert set(ids) == {c.identifier for c in sample_controls}
    db.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ingest_oscal.py tests/test_ingest_embed.py -v`
Expected: FAIL. `ingest.load_version_from_dir`, `ingest.ingest_version`, `ingest.embedding_text`, `ingest.version_label` do not exist; the old `parse_xlsx`/`attach_pdf_excerpts` still occupy the module.

- [ ] **Step 3: Rewrite ingest.py**

Replace the full contents of `src/ism_mcp/ingest.py` with:

```python
"""Orchestrate OSCAL ingest: parse a catalog directory or a git tag into the store."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import fetch, oscal, store
from .embed import Embedder, l2_normalise
from .oscal import VersionMeta
from .store import Control

CATALOG_FILE = "ISM_catalog.json"
E8_FILES = {
    "ML1": "ISM_E8_ML1-baseline-resolved-profile_catalog.json",
    "ML2": "ISM_E8_ML2-baseline-resolved-profile_catalog.json",
    "ML3": "ISM_E8_ML3-baseline-resolved-profile_catalog.json",
}
_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def version_label(version: str) -> str:
    """Humanise a version like 2026.03.24 to 'March 2026'. Falls back to the input."""
    parts = version.split(".")
    try:
        year, month = int(parts[0]), int(parts[1])
        return f"{_MONTHS[month - 1]} {year}"
    except (IndexError, ValueError):
        return version


def _maturity_sets_from_dir(oscal_dir: Path) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for ml, fname in E8_FILES.items():
        path = oscal_dir / fname
        sets[ml] = oscal.collect_control_ids(oscal.load_catalog(path)) if path.is_file() else set()
    return sets


def load_version_from_dir(oscal_dir: Path) -> tuple[VersionMeta, list[Control]]:
    catalog = oscal.load_catalog(Path(oscal_dir) / CATALOG_FILE)
    sets = _maturity_sets_from_dir(Path(oscal_dir))
    return oscal.parse_metadata(catalog), list(oscal.parse_controls(catalog, sets))


def load_version_from_tag(repo_dir: Path, tag: str) -> tuple[VersionMeta, list[Control]]:
    catalog = json.loads(fetch.read_file_at_tag(repo_dir, tag, CATALOG_FILE))["catalog"]
    sets: dict[str, set[str]] = {}
    for ml, fname in E8_FILES.items():
        try:
            sub = json.loads(fetch.read_file_at_tag(repo_dir, tag, fname))["catalog"]
            sets[ml] = oscal.collect_control_ids(sub)
        except fetch.GitError:
            sets[ml] = set()
    return oscal.parse_metadata(catalog), list(oscal.parse_controls(catalog, sets))


def embedding_text(c: Control) -> str:
    return f"{c.guideline}. {c.section}. {c.topic}. {c.title}. {c.description}"


def embed_controls(
    controls: Iterable[Control], embedder: Embedder
) -> Iterator[tuple[str, bytes]]:
    controls = list(controls)
    vectors = l2_normalise(embedder.embed([embedding_text(c) for c in controls]))
    for c, vec in zip(controls, vectors, strict=True):
        yield c.identifier, vec.astype(np.float32).tobytes()


def ingest_version(
    conn,
    vmeta: VersionMeta,
    controls: list[Control],
    embedder: Embedder | None = None,
    git_tag: str | None = None,
    git_commit: str | None = None,
    make_active: bool = True,
) -> dict:
    store.delete_version(conn, vmeta.version)
    store.insert_controls(conn, controls)
    store.upsert_version(
        conn,
        version=vmeta.version,
        label=version_label(vmeta.version),
        published=vmeta.published,
        last_modified=vmeta.last_modified,
        oscal_version=vmeta.oscal_version,
        git_tag=git_tag,
        git_commit=git_commit,
        ingested_at=datetime.now(UTC).isoformat(),
        control_count=len(controls),
    )
    embedded = 0
    if embedder is not None:
        rows = [(vmeta.version, ident, blob) for ident, blob in embed_controls(controls, embedder)]
        embedded = store.insert_embeddings(conn, rows)
    if make_active:
        store.set_active_version(conn, vmeta.version)
    return {"version": vmeta.version, "controls": len(controls), "embedded": embedded}
```

Note: `l2_normalise` is imported from `embed`; `embedder.embed` already normalises, so this is a cheap idempotent safety net that also keeps a single normalisation path.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_oscal.py tests/test_ingest_embed.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/ingest.py tests/test_ingest_oscal.py tests/test_ingest_embed.py
git commit -m "feat: OSCAL ingest orchestration with version registry and embeddings"
```

---

## Task C3: CLI subcommands

**Files:**
- Modify: `src/ism_mcp/__main__.py` (rewrite `cmd_ingest`, add `cmd_fetch`, `cmd_ingest_history`, `cmd_update`, rebuild parser)
- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Replace `tests/test_cli.py` with tests that drive the new subcommands. `ingest-history` runs against a local git repo built from the fixtures.

```python
"""CLI orchestration: fetch, ingest, ingest-history subcommands."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ism_mcp import __main__ as cli
from ism_mcp import store

FX = Path(__file__).parent / "fixtures" / "oscal"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def oscal_dir(tmp_path: Path) -> Path:
    d = tmp_path / "oscal"
    d.mkdir()
    for f in FX.glob("*.json"):
        shutil.copy(f, d / f.name)
    return d


@pytest.fixture
def history_repo(tmp_path: Path, oscal_dir: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(oscal_dir, repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "dec")
    _git(repo, "tag", "v2025.12.9")
    catalog = (repo / "ISM_catalog.json").read_text().replace("2025.12.9", "2026.03.24")
    (repo / "ISM_catalog.json").write_text(catalog)
    _git(repo, "commit", "-aqm", "mar")
    _git(repo, "tag", "v2026.03.24")
    return repo


def test_ingest_one_version(oscal_dir: Path, tmp_path: Path, monkeypatch):
    db = tmp_path / "ism.db"
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "none")
    rc = cli.main(["ingest", "--oscal", str(oscal_dir), "--db", str(db), "--no-embeddings"])
    assert rc == 0
    conn = store.open_db(db)
    assert store.get_active_version(conn) == "2025.12.9"
    assert store.count_controls(conn) == 3
    conn.close()


def test_ingest_history_walks_tags(history_repo: Path, tmp_path: Path):
    db = tmp_path / "ism.db"
    rc = cli.main(
        ["ingest-history", "--oscal-repo", str(history_repo), "--db", str(db), "--no-embeddings"]
    )
    assert rc == 0
    conn = store.open_db(db)
    assert {v["version"] for v in store.list_versions(conn)} == {"2025.12.9", "2026.03.24"}
    assert store.get_active_version(conn) == "2026.03.24"
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL. `cli.main` does not accept an argv list yet, and the `--oscal`/`ingest-history` options do not exist.

- [ ] **Step 3: Rewrite the CLI**

In `src/ism_mcp/__main__.py`:

Replace `cmd_ingest` (lines 14-57) with the OSCAL version, and add the new commands above `main`:

```python
def _embedder_or_none(no_embeddings: bool):
    if no_embeddings:
        return None
    from .embed import FastEmbedEmbedder

    print(
        "embedding controls (first run downloads ~130 MB to ~/.cache/fastembed)...",
        file=sys.stderr,
    )
    return FastEmbedEmbedder()


def cmd_ingest(args: argparse.Namespace) -> int:
    db_path = Path(args.db or server.DEFAULT_DB)
    oscal_dir = Path(args.oscal) if args.oscal else fetch.DEFAULT_CACHE
    if args.fetch:
        print("fetching OSCAL mirror...", file=sys.stderr)
        oscal_dir = fetch.ensure_clone(cache=oscal_dir)
    print(f"writing to {db_path}", file=sys.stderr)
    conn = store.open_db(db_path)
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    print(f"parsed {len(controls)} controls for {vmeta.version}", file=sys.stderr)
    embedder = _embedder_or_none(args.no_embeddings)
    result = ingest.ingest_version(conn, vmeta, controls, embedder=embedder)
    conn.close()
    print(f"done. {result}", file=sys.stderr)
    return 0


def cmd_ingest_history(args: argparse.Namespace) -> int:
    db_path = Path(args.db or server.DEFAULT_DB)
    repo_dir = Path(args.oscal_repo) if args.oscal_repo else fetch.DEFAULT_CACHE
    if args.fetch or not (repo_dir / ".git").is_dir():
        print("fetching OSCAL mirror...", file=sys.stderr)
        repo_dir = fetch.ensure_clone(cache=repo_dir)
    tags = fetch.list_tags(repo_dir)
    if args.from_tag:
        tags = [t for t in tags if t >= args.from_tag]
    if args.to_tag:
        tags = [t for t in tags if t <= args.to_tag]
    if not tags:
        print("no tags matched the range", file=sys.stderr)
        return 1
    conn = store.open_db(db_path)
    # Default policy: embed only the newest (active) version. --embed-all embeds every
    # version. --no-embeddings embeds none. Build the embedder once and choose per version.
    embedder = None if args.no_embeddings else _embedder_or_none(False)
    for i, tag in enumerate(tags):
        is_last = i == len(tags) - 1
        use = embedder if (args.embed_all or is_last) else None
        vmeta, controls = ingest.load_version_from_tag(repo_dir, tag)
        commit = fetch.current_commit(repo_dir, tag)
        ingest.ingest_version(
            conn, vmeta, controls, embedder=use,
            git_tag=tag, git_commit=commit, make_active=is_last,
        )
        print(f"  ingested {tag} ({len(controls)} controls)", file=sys.stderr)
    conn.close()
    print(f"done. {len(tags)} versions", file=sys.stderr)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    repo_dir = fetch.ensure_clone(cache=Path(args.oscal_repo) if args.oscal_repo else fetch.DEFAULT_CACHE)
    db_path = Path(args.db or server.DEFAULT_DB)
    conn = store.open_db(db_path)
    tags = fetch.list_tags(repo_dir)
    if not tags:
        print("no tags found", file=sys.stderr)
        return 1
    latest = tags[-1]
    vmeta, controls = ingest.load_version_from_tag(repo_dir, latest)
    embedder = _embedder_or_none(args.no_embeddings)
    ingest.ingest_version(
        conn, vmeta, controls, embedder=embedder,
        git_tag=latest, git_commit=fetch.current_commit(repo_dir, latest), make_active=True,
    )
    conn.close()
    print(f"done. active version {vmeta.version}", file=sys.stderr)
    return 0
```

Add the import at the top of the module (with the other `from . import` lines):

```python
from . import fetch, ingest, install, server, store
```

(keep `install` if already imported; add `fetch` and `ingest` if missing.)

Replace the `main` function's signature and the ingest subparser. Change `def main() -> int:` to:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ism-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Parse one OSCAL ISM release into the database.")
    p_ingest.add_argument("--oscal", help="Path to an OSCAL clone (default: managed cache).")
    p_ingest.add_argument("--db", help=f"Output database path (default: {server.DEFAULT_DB}).")
    p_ingest.add_argument("--fetch", action="store_true", help="Refresh the managed cache first.")
    p_ingest.add_argument(
        "--no-embeddings", action="store_true",
        help="skip embedding generation. Server falls back to lexical-only.",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_hist = sub.add_parser(
        "ingest-history", help="Walk OSCAL git tags and ingest every release."
    )
    p_hist.add_argument("--oscal-repo", help="Path to an OSCAL clone (default: managed cache).")
    p_hist.add_argument("--from", dest="from_tag", help="Earliest tag to include (e.g. v2024.12.19).")
    p_hist.add_argument("--to", dest="to_tag", help="Latest tag to include.")
    p_hist.add_argument("--fetch", action="store_true", help="Refresh the managed cache first.")
    p_hist.add_argument(
        "--embed-all", action="store_true", help="Embed every version, not just the newest."
    )
    p_hist.add_argument(
        "--no-embeddings", action="store_true", help="skip all embedding generation."
    )
    p_hist.set_defaults(func=cmd_ingest_history)

    p_update = sub.add_parser("update", help="Fetch and ingest the latest OSCAL release.")
    p_update.add_argument("--oscal-repo", help="Path to an OSCAL clone (default: managed cache).")
    p_update.add_argument("--db", help=f"Database path (default: {server.DEFAULT_DB}).")
    p_update.add_argument("--no-embeddings", action="store_true", help="skip embeddings.")
    p_update.set_defaults(func=cmd_update)

    p_serve = sub.add_parser("serve", help="Run the MCP server over stdio.")
    p_serve.add_argument("--db", help=f"Database path (default: {server.DEFAULT_DB}).")
    p_serve.set_defaults(func=cmd_serve)
```

Keep the existing `install` subparser block unchanged. Change the final two lines of `main` from:

```python
    args = parser.parse_args()
    return args.func(args)
```

to:

```python
    args = parser.parse_args(argv)
    return args.func(args)
```

If `if __name__ == "__main__": raise SystemExit(main())` exists at the bottom, leave it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite so far**

Run: `./scripts/ci.sh test`
Expected: Phases A through C tests pass. Tests still referencing XLSX (`test_ingest_xlsx.py`, `test_excerpt_extraction.py`) and the server tools (Phase D onward) will FAIL or error because the server still uses the old retrieval. That is expected at this point. Do not delete the XLSX tests yet (Phase G) but note the count. If you prefer a green bar between phases, you may temporarily `git rm` the two XLSX test files now and finalise their removal in Phase G.

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/__main__.py tests/test_cli.py
git commit -m "feat: fetch, ingest, ingest-history, and update CLI subcommands"
```

---

# Phase D: server retrieval and version-aware lookups

## Task D1: retrieval keyed on identifier

**Files:**
- Modify: `src/ism_mcp/server.py` (`_vector_index`, `_rowid_for` removal, `_materialise`, `_render_result`, `ism_applicable`, `_conn` error text)
- Modify: `tests/test_server_applicable.py` (`populated_db` fixture and identifiers)
- Test: `tests/test_server_applicable.py`

- [ ] **Step 1: Update the server test fixture**

In `tests/test_server_applicable.py`, the `populated_db` fixture must set an active version and embed via the new identifier-keyed path. Replace it with:

```python
@pytest.fixture
def populated_db(tmp_path, sample_controls, monkeypatch):
    from ism_mcp.ingest import embed_controls

    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    version = sample_controls[0].version
    store.upsert_version(
        conn, version=version, label="March 2026", published=None, last_modified=None,
        oscal_version="1.1.2", git_tag=None, git_commit=None,
        ingested_at="2026-06-04T00:00:00Z", control_count=len(sample_controls),
    )
    store.set_active_version(conn, version)
    embedder = DeterministicHashEmbedder(dim=384)
    rows = [(version, ident, blob) for ident, blob in embed_controls(sample_controls, embedder)]
    store.insert_embeddings(conn, rows)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "hash")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()
```

Update any assertions in that file referencing `ISM-9001` to `ism-9001`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server_applicable.py -v`
Expected: FAIL. `ism_applicable` still calls `_rowid_for` and `_materialise` queries by `rowid`, and `_vector_index` loads without a version, so retrieval breaks or returns nothing.

- [ ] **Step 3: Rewrite the retrieval internals**

In `src/ism_mcp/server.py`:

Replace `_vector_index` (lines 59-70) with a version-scoped loader:

```python
def _vector_index(conn) -> retrieve.VectorIndex | None:
    if "vec_index" in _RUNTIME:
        return _RUNTIME["vec_index"]  # type: ignore[return-value]
    embedder = _embedder()
    if embedder is None:
        return None
    version = store.get_active_version(conn)
    if version is None:
        return None
    matrix, ids = store.load_embedding_matrix(conn, dim=embedder.dim, version=version)
    if len(ids) == 0:
        return None
    idx = retrieve.VectorIndex(matrix, ids)
    _RUNTIME["vec_index"] = idx
    return idx
```

Delete `_rowid_for` (lines 281-283).

Replace `_materialise` (lines 290-314) so it fetches controls by identifier within the active version:

```python
def _materialise(
    conn,
    fused: list[tuple[str, float]],
    lex_ids: set[str],
    sem_ids: set[str],
    path_keywords: dict[str, set[str]],
    semantic_used: bool,
) -> list[dict]:
    version = store.get_active_version(conn)
    out: list[dict] = []
    for identifier, score in fused:
        row = conn.execute(
            "SELECT * FROM controls WHERE version = ? AND identifier = ?",
            (version, identifier),
        ).fetchone()
        if row is None:
            continue
        why: list[str] = []
        if semantic_used and identifier in sem_ids:
            why.append("semantic")
        if identifier in lex_ids:
            why.append("lexical")
        if path_keywords:
            words = {w for f in _TEXT_FIELDS for w in _WORD_RE.findall(str(row[f]).lower())}
            for token in sorted(path_keywords):
                if path_keywords[token] & words:
                    why.append(f"path:{token}")
        out.append({"row": row, "score": float(score), "why": why})
    return out
```

Replace `_render_result` (lines 336-351), dropping the pdf fields and adding label/title/guideline:

```python
def _render_result(m: dict, verbose: bool) -> dict:
    r = m["row"]
    base = {
        "identifier": r["identifier"],
        "label": r["label"],
        "title": r["title"],
        "topic": r["topic"],
        "section": r["section"],
        "description": r["description"],
        "applies": {c: bool(r[f"applies_{c.lower()}"]) for c in store.CLASSIFICATIONS},
        "maturity": {ml: bool(r[f"maturity_{ml.lower()}"]) for ml in store.MATURITIES},
        "score": round(m["score"], 4),
        "why": m["why"],
    }
    if verbose:
        base["guideline"] = r["guideline"]
    return base
```

In `ism_applicable` (lines 195-278), change the lexical ranking to use identifiers instead of rowids. Replace the line:

```python
    lex_ranking = [(_rowid_for(conn, c.identifier), 0.0) for c in lex_results]
```

with:

```python
    lex_ranking = [(c.identifier, 0.0) for c in lex_results]
```

The rest of `ism_applicable` already uses `idx.search` (now returns identifier ids), `retrieve.rrf` (now id-generic), `lex_ids`/`sem_ids` (now identifier sets), and `_materialise`/`_apply_filters`/`_render_result`. No other change needed there.

Update the `_conn` error text (lines 73-86) from the XLSX hint to:

```python
            f"ISM database not found at {path}. "
            "Run `ism-mcp ingest` or `ism-mcp ingest-history` first."
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_server_applicable.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_applicable.py
git commit -m "refactor: key server retrieval on identifier and active version"
```

---

## Task D2: version params, ism_stats, and ism_versions

**Files:**
- Modify: `src/ism_mcp/server.py` (`ism_get`, `ism_search`, `ism_list_*`, `ism_stats`, add `ism_versions`)
- Modify: `tests/test_server_lookups.py`, `tests/test_server_helpers.py` (identifiers and stats keys)
- Create: `tests/test_server_versions.py`
- Test: `tests/test_server_versions.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_versions.py` (the diff/history parts come in Phase E; this covers versions and version params):

```python
"""Server tests for ism_versions, ism_stats, and version= parameters."""

from __future__ import annotations

import json

import pytest

from ism_mcp import server, store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls


@pytest.fixture
def two_version_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    new = sample_controls
    old = [
        store.Control(**{**c.as_dict(), "version": "2025.12.9"}) for c in sample_controls[:2]
    ]
    store.insert_controls(conn, old)
    store.insert_controls(conn, new)
    for ver, label, count in [("2025.12.9", "December 2025", 2), ("2026.03.24", "March 2026", 3)]:
        store.upsert_version(
            conn, version=ver, label=label, published=ver.replace(".", "-"),
            last_modified=None, oscal_version="1.1.2", git_tag=f"v{ver}", git_commit="x",
            ingested_at="2026-06-04T00:00:00Z", control_count=count,
        )
    store.set_active_version(conn, "2026.03.24")
    embedder = DeterministicHashEmbedder(dim=384)
    rows = [("2026.03.24", i, b) for i, b in embed_controls(new, embedder)]
    store.insert_embeddings(conn, rows)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.delenv("ISM_MCP_DB", raising=False)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "hash")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_ism_versions_lists_active_first(two_version_db):
    out = json.loads(server.ism_versions())
    assert out["active"] == "2026.03.24"
    assert out["count"] == 2
    assert out["versions"][0]["version"] == "2026.03.24"
    assert out["versions"][0]["is_active"] is True


def test_ism_stats_reports_active_version(two_version_db):
    out = json.loads(server.ism_stats())
    assert out["active_version"] == "2026.03.24"
    assert out["versions"] == 2
    assert out["controls"] == 3


def test_ism_get_defaults_to_active_and_accepts_version(two_version_db):
    active = json.loads(server.ism_get("ism-9003"))
    assert active["version"] == "2026.03.24"
    missing = json.loads(server.ism_get("ism-9003", version="2025.12.9"))
    assert "error" in missing


def test_ism_get_tolerant_identifier(two_version_db):
    out = json.loads(server.ism_get("ISM-9001"))
    assert out["identifier"] == "ism-9001"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server_versions.py -v`
Expected: FAIL. `server.ism_versions` does not exist and `ism_stats`/`ism_get` lack the new shape.

- [ ] **Step 3: Add version params and the new tools**

In `src/ism_mcp/server.py`:

Replace `ism_get` (lines 89-96):

```python
@mcp.tool()
def ism_get(identifier: str, version: str | None = None) -> str:
    """Get the full record for one ISM control by identifier (e.g. `ism-1781`).

    Defaults to the active ISM version. Pass `version` (see ism_versions) for a historical one.
    """
    conn = _conn()
    c = store.get_control(conn, identifier, version=version)
    if c is None:
        return json.dumps({"error": f"no such control: {identifier}"})
    return json.dumps(c.as_dict(), indent=2)
```

Replace `ism_search` (lines 99-107):

```python
@mcp.tool()
def ism_search(query: str, limit: int = 10, version: str | None = None) -> str:
    """Full-text search over ISM control text and topics. Defaults to the active version."""
    conn = _conn()
    results = store.search(conn, query, limit=_clamp_limit(limit), version=version)
    return json.dumps(
        {"query": query, "count": len(results), "results": [c.as_dict() for c in results]},
        indent=2,
    )
```

Add a `version: str | None = None` parameter to `ism_list_by_classification`, `ism_list_by_topic`, `ism_list_topics`, and `ism_list_sections`, threading it into the matching `store.list_*` call. For example `ism_list_sections`:

```python
@mcp.tool()
def ism_list_sections(version: str | None = None) -> str:
    """List the distinct ISM Section values, the vocabulary for the `tags` filter."""
    conn = _conn()
    sections = store.list_sections(conn, version=version)
    return json.dumps({"count": len(sections), "sections": sections}, indent=2)
```

Apply the same `version=version` threading to the other three list tools (keep their existing bodies, add the parameter and pass it through).

Replace `ism_stats` (lines 147-160):

```python
@mcp.tool()
def ism_stats() -> str:
    """Report database statistics: active version, total versions, and control count."""
    conn = _conn()
    active = store.get_active_version(conn)
    row = store.get_version(conn, active) if active else None
    return json.dumps(
        {
            "active_version": active,
            "versions": len(store.list_versions(conn)),
            "controls": store.count_controls(conn) if active else 0,
            "oscal_version": row["oscal_version"] if row else None,
            "git_tag": row["git_tag"] if row else None,
            "db_path": str(_active_db()),
        },
        indent=2,
    )
```

Add `ism_versions` near the other enumeration tools:

```python
@mcp.tool()
def ism_versions() -> str:
    """List loaded ISM versions, newest first. The vocabulary for version/from/to arguments."""
    conn = _conn()
    active = store.get_active_version(conn)
    versions = store.list_versions(conn)
    return json.dumps(
        {
            "active": active,
            "count": len(versions),
            "versions": [
                {
                    "version": v["version"],
                    "label": v["label"],
                    "published": v["published"],
                    "control_count": v["control_count"],
                    "git_tag": v["git_tag"],
                    "is_active": v["version"] == active,
                }
                for v in versions
            ],
        },
        indent=2,
    )
```

- [ ] **Step 4: Fix the other server tests for the new shape**

In `tests/test_server_lookups.py` and `tests/test_server_helpers.py`, update identifiers from `ISM-9001` to `ism-9001`, set an active version in any fixture that builds a DB (use the `two_version_db`-style `upsert_version` + `set_active_version` calls, or import a shared fixture), and update `ism_stats` assertions from `ism_revision`/`xlsx_source` to `active_version`/`versions`. If these files build their own DB inline, add `store.upsert_version(...)` and `store.set_active_version(...)` after `insert_controls`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_server_versions.py tests/test_server_lookups.py tests/test_server_helpers.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_versions.py tests/test_server_lookups.py tests/test_server_helpers.py
git commit -m "feat: version-aware lookups, ism_versions, and rebuilt ism_stats"
```

---

# Phase E: diff and history

## Task E1: pure diff and history engine

**Files:**
- Create: `src/ism_mcp/diff.py`
- Test: `tests/test_diff.py`, `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diff.py`:

```python
"""Tests for the pure diff engine over Control lists."""

from __future__ import annotations

from ism_mcp import diff
from ism_mcp.store import Control


def _ctl(identifier, *, version="v", description="d", title="t", section="s", topic="tp",
         guideline="g", applies=None, maturity=None) -> Control:
    return Control(
        version=version, identifier=identifier, label=identifier, title=title,
        control_class="ISM-control", guideline=guideline, section=section, topic=topic,
        description=description, control_revision=None, updated=None, sort_id=identifier,
        applies=applies or {"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity=maturity or {"ML1": False, "ML2": False, "ML3": False},
    )


def test_added_and_removed():
    old = [_ctl("ism-0001")]
    new = [_ctl("ism-0001"), _ctl("ism-0002")]
    result = diff.diff_controls(old, new)
    assert [c["identifier"] for c in result["changes"]["added"]] == ["ism-0002"]
    assert result["changes"]["removed"] == []
    assert result["summary"]["added"] == 1


def test_reworded_emits_unified_diff():
    old = [_ctl("ism-0001", description="old text")]
    new = [_ctl("ism-0001", description="new text")]
    result = diff.diff_controls(old, new)
    reworded = result["changes"]["reworded"]
    assert reworded[0]["identifier"] == "ism-0001"
    assert "old text" in reworded[0]["diff"]
    assert "new text" in reworded[0]["diff"]


def test_applicability_and_maturity_changes():
    old = [_ctl("ism-0001", applies={"NC": False, "OS": True, "P": True, "S": True, "TS": True},
                maturity={"ML1": False, "ML2": False, "ML3": False})]
    new = [_ctl("ism-0001", applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True},
                maturity={"ML1": True, "ML2": False, "ML3": False})]
    result = diff.diff_controls(old, new)
    appl = result["changes"]["applicability_changed"][0]
    assert appl["added"] == ["NC"] and appl["removed"] == []
    mat = result["changes"]["maturity_changed"][0]
    assert mat["added"] == ["ML1"]


def test_retitled_and_moved():
    old = [_ctl("ism-0001", title="A", topic="old topic")]
    new = [_ctl("ism-0001", title="B", topic="new topic")]
    result = diff.diff_controls(old, new)
    assert result["changes"]["retitled"][0]["identifier"] == "ism-0001"
    assert result["changes"]["moved"][0]["identifier"] == "ism-0001"


def test_changed_fields_helper():
    a = _ctl("ism-0001", description="x", applies={"NC": True, "OS": True, "P": True, "S": True, "TS": True})
    b = _ctl("ism-0001", description="y", applies={"NC": False, "OS": True, "P": True, "S": True, "TS": True})
    assert set(diff.changed_fields(a, b)) == {"reworded", "applicability_changed"}
```

Create `tests/test_history.py`:

```python
"""Tests for the per-control history timeline."""

from __future__ import annotations

from ism_mcp import diff
from ism_mcp.store import Control


def _ctl(version, description="d", applies=None) -> Control:
    return Control(
        version=version, identifier="ism-0001", label="1", title="t",
        control_class="ISM-control", guideline="g", section="s", topic="tp",
        description=description, control_revision=None, updated=None, sort_id="1",
        applies=applies or {"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity={"ML1": False, "ML2": False, "ML3": False},
    )


def test_history_marks_changed_fields_and_bounds():
    order = ["2025.09.10", "2025.12.9", "2026.03.24"]
    by_version = {
        "2025.09.10": _ctl("2025.09.10", description="a"),
        "2025.12.9": _ctl("2025.12.9", description="a"),
        "2026.03.24": _ctl("2026.03.24", description="b"),
    }
    out = diff.build_history("ism-0001", order, by_version)
    assert out["first_seen"] == "2025.09.10"
    assert out["last_seen"] is None
    timeline = {t["version"]: t for t in out["timeline"]}
    assert timeline["2025.09.10"]["changed"] == []
    assert timeline["2025.12.9"]["changed"] == []
    assert "reworded" in timeline["2026.03.24"]["changed"]


def test_history_records_removal():
    order = ["2025.12.9", "2026.03.24"]
    by_version = {"2025.12.9": _ctl("2025.12.9"), "2026.03.24": None}
    out = diff.build_history("ism-0001", order, by_version)
    assert out["last_seen"] == "2025.12.9"
    assert [t["version"] for t in out["timeline"]] == ["2025.12.9"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_diff.py tests/test_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ism_mcp.diff'`.

- [ ] **Step 3: Create the diff engine**

Create `src/ism_mcp/diff.py`:

```python
"""Pure comparison of Control sets across versions, plus per-control history."""

from __future__ import annotations

import difflib

from .store import CLASSIFICATIONS, MATURITIES, Control


def _applicability_list(c: Control) -> list[str]:
    return [k for k in CLASSIFICATIONS if c.applies.get(k)]


def _maturity_list(c: Control) -> list[str]:
    return [k for k in MATURITIES if c.maturity.get(k)]


def unified_diff(old_text: str, new_text: str) -> str:
    lines = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), lineterm="", n=2
    )
    return "\n".join(lines)


def changed_fields(old: Control, new: Control) -> list[str]:
    """Which aspects of a same-identifier control changed from old to new."""
    fields: list[str] = []
    if old.description != new.description:
        fields.append("reworded")
    if old.title != new.title:
        fields.append("retitled")
    if (old.guideline, old.section, old.topic) != (new.guideline, new.section, new.topic):
        fields.append("moved")
    if old.applies != new.applies:
        fields.append("applicability_changed")
    if old.maturity != new.maturity:
        fields.append("maturity_changed")
    return fields


def _set_delta(old_keys: list[str], new_keys: list[str]) -> tuple[list[str], list[str]]:
    added = [k for k in new_keys if k not in old_keys]
    removed = [k for k in old_keys if k not in new_keys]
    return added, removed


def diff_controls(from_list: list[Control], to_list: list[Control]) -> dict:
    """Compare two versions' control lists into change buckets."""
    from_by = {c.identifier: c for c in from_list}
    to_by = {c.identifier: c for c in to_list}

    buckets: dict[str, list[dict]] = {
        "added": [], "removed": [], "reworded": [], "retitled": [],
        "moved": [], "applicability_changed": [], "maturity_changed": [],
    }

    for ident, c in to_by.items():
        if ident not in from_by:
            buckets["added"].append(
                {"identifier": ident, "label": c.label, "title": c.title, "section": c.section}
            )
    for ident, c in from_by.items():
        if ident not in to_by:
            buckets["removed"].append(
                {"identifier": ident, "label": c.label, "title": c.title, "section": c.section}
            )

    for ident in from_by.keys() & to_by.keys():
        old, new = from_by[ident], to_by[ident]
        for field in changed_fields(old, new):
            entry: dict = {"identifier": ident, "label": new.label, "title": new.title}
            if field == "reworded":
                entry["diff"] = unified_diff(old.description, new.description)
            elif field == "applicability_changed":
                a, r = _set_delta(_applicability_list(old), _applicability_list(new))
                entry["added"], entry["removed"] = a, r
            elif field == "maturity_changed":
                a, r = _set_delta(_maturity_list(old), _maturity_list(new))
                entry["added"], entry["removed"] = a, r
            elif field == "moved":
                entry["from"] = {"guideline": old.guideline, "section": old.section, "topic": old.topic}
                entry["to"] = {"guideline": new.guideline, "section": new.section, "topic": new.topic}
            elif field == "retitled":
                entry["from"], entry["to"] = old.title, new.title
            buckets[field].append(entry)

    for key in buckets:
        buckets[key].sort(key=lambda e: e["identifier"])
    summary = {key: len(value) for key, value in buckets.items()}
    return {"summary": summary, "changes": buckets}


def build_history(
    identifier: str, order: list[str], by_version: dict[str, Control | None]
) -> dict:
    """Assemble one control's timeline across versions given in chronological order."""
    timeline: list[dict] = []
    first_seen: str | None = None
    last_present: str | None = None
    prev: Control | None = None
    for version in order:
        c = by_version.get(version)
        if c is None:
            continue
        if first_seen is None:
            first_seen = version
        last_present = version
        changed = changed_fields(prev, c) if prev is not None else []
        timeline.append(
            {
                "version": version,
                "title": c.title,
                "applicability": _applicability_list(c),
                "maturity": _maturity_list(c),
                "changed": changed,
            }
        )
        prev = c
    present_now = bool(order) and by_version.get(order[-1]) is not None
    return {
        "identifier": identifier,
        "first_seen": first_seen,
        "last_seen": None if present_now else last_present,
        "timeline": timeline,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_diff.py tests/test_history.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/diff.py tests/test_diff.py tests/test_history.py
git commit -m "feat: pure diff and per-control history engine"
```

---

## Task E2: ism_diff and ism_history tools

**Files:**
- Modify: `src/ism_mcp/server.py` (add `ism_diff`, `ism_history`)
- Modify: `tests/test_server_versions.py`
- Test: `tests/test_server_versions.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server_versions.py`:

```python
def test_ism_diff_defaults_to_latest_vs_previous(two_version_db):
    import json

    out = json.loads(server.ism_diff())
    assert out["from"] == "2025.12.9"
    assert out["to"] == "2026.03.24"
    # ism-9003 exists only in the active (new) version per the fixture:
    assert "ism-9003" in {c["identifier"] for c in out["changes"]["added"]}


def test_ism_diff_explicit_versions_and_unknown(two_version_db):
    import json

    bad = json.loads(server.ism_diff(from_version="9999.99.99", to_version="2026.03.24"))
    assert "error" in bad


def test_ism_history_timeline(two_version_db):
    import json

    out = json.loads(server.ism_history("ism-9001"))
    assert out["identifier"] == "ism-9001"
    assert [t["version"] for t in out["timeline"]] == ["2025.12.9", "2026.03.24"]


def test_ism_diff_single_version_errors(populated_db):
    import json

    out = json.loads(server.ism_diff())
    assert "error" in out
```

(The `populated_db` fixture from `test_server_applicable.py` is single-version; import it or duplicate a minimal single-version fixture in this file. Simplest: add a local `single_version_db` fixture mirroring `populated_db`.)

Add a `single_version_db` fixture to `tests/test_server_versions.py` modelled on `populated_db` from Task D1 (one version, active set, embedded) so `test_ism_diff_single_version_errors` has a one-version database. Use it instead of `populated_db` in that test.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server_versions.py -k "diff or history" -v`
Expected: FAIL. `server.ism_diff` and `server.ism_history` do not exist.

- [ ] **Step 3: Add the tools**

In `src/ism_mcp/server.py`, add `from . import diff` to the imports, then add:

```python
@mcp.tool()
def ism_diff(
    from_version: str | None = None,
    to_version: str | None = None,
    change_types: list[str] | None = None,
) -> str:
    """Catalog delta between two ISM versions.

    Defaults compare the version before active (from) to the active version (to), so a
    bare call answers 'what changed in the latest release'. `change_types` narrows the
    buckets (added, removed, reworded, retitled, moved, applicability_changed,
    maturity_changed). Use ism_versions to see loadable versions.
    """
    conn = _conn()
    versions = [v["version"] for v in store.list_versions(conn)]  # newest first
    if len(versions) < 2 and (from_version is None or to_version is None):
        return json.dumps(
            {"error": "need two versions to diff", "hint": "load history with ingest-history"}
        )
    to_v = to_version or store.get_active_version(conn) or versions[0]
    if from_version is not None:
        from_v = from_version
    else:
        later = [v for v in versions if v < to_v]
        from_v = later[0] if later else None
    if from_v is None:
        return json.dumps({"error": "no earlier version to compare against to_version"})
    for v in (from_v, to_v):
        if store.get_version(conn, v) is None:
            return json.dumps({"error": f"no such version: {v}", "hint": "call ism_versions"})

    result = diff.diff_controls(store.list_controls(conn, from_v), store.list_controls(conn, to_v))
    if change_types:
        result = {
            "summary": {k: v for k, v in result["summary"].items() if k in change_types},
            "changes": {k: v for k, v in result["changes"].items() if k in change_types},
        }
    return json.dumps({"from": from_v, "to": to_v, **result}, indent=2)


@mcp.tool()
def ism_history(identifier: str) -> str:
    """Show one control's evolution across every loaded ISM version."""
    conn = _conn()
    versions = [v["version"] for v in store.list_versions(conn)]
    order = sorted(versions)  # chronological, ascending
    canon = None
    for v in reversed(order):
        canon = store.normalise_identifier(conn, identifier, version=v)
        if canon is not None:
            break
    if canon is None:
        return json.dumps(
            {"identifier": identifier, "timeline": [], "hint": "no control with that id in any version"}
        )
    by_version = {v: store.get_control(conn, canon, version=v) for v in order}
    return json.dumps(diff.build_history(canon, order, by_version), indent=2)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_server_versions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_versions.py
git commit -m "feat: ism_diff and ism_history MCP tools"
```

---

# Phase F: coverage drift

## Task F1: reviewed_against field and compute_impact

**Files:**
- Modify: `src/ism_mcp/coverage.py` (`ManifestEntry`, `_entry_from_dict`, `serialise_manifest`, add `compute_impact`)
- Modify: `src/ism_mcp/data/coverage_template.toml`
- Test: `tests/test_coverage_impact.py`, plus update `tests/test_coverage_*` that build entries

- [ ] **Step 1: Write the failing test**

Create `tests/test_coverage_impact.py`:

```python
"""Tests for coverage drift computation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ism_mcp import coverage, diff
from ism_mcp.store import Control


def _ctl(version, identifier, description="d", applies=None) -> Control:
    return Control(
        version=version, identifier=identifier, label=identifier, title="t",
        control_class="ISM-control", guideline="g", section="s", topic="tp",
        description=description, control_revision=None, updated=None, sort_id=identifier,
        applies=applies or {"NC": True, "OS": True, "P": True, "S": True, "TS": True},
        maturity={"ML1": False, "ML2": False, "ML3": False},
    )


def _entry(identifier, status="covered", reviewed_against="2025.12.9") -> coverage.ManifestEntry:
    return coverage.ManifestEntry(
        identifier=identifier, status=status, how_met="x",
        last_reviewed=date(2025, 12, 15), reviewed_against=reviewed_against,
    )


def _manifest(entries) -> coverage.Manifest:
    return coverage.Manifest(
        path=Path("/tmp/.ism-coverage.toml"), schema_version=1,
        scope={"classification": "P", "baseline_version": "2026.03.24"},
        project={}, controls={e.identifier: e for e in entries}, warnings=[],
    )


def test_reviewed_against_round_trips_through_toml():
    text = coverage.serialise_manifest(_manifest([_entry("ism-0001")]))
    assert 'reviewed_against = "2025.12.9"' in text
    parsed = coverage.read_manifest_text(text, Path("/tmp/.ism-coverage.toml"))
    assert parsed.controls["ism-0001"].reviewed_against == "2025.12.9"


def test_compute_impact_buckets():
    manifest = _manifest([_entry("ism-0001"), _entry("ism-0002"), _entry("ism-0003")])

    target_controls = {
        "ism-0001": _ctl("2026.03.24", "ism-0001", description="CHANGED"),
        "ism-0002": _ctl("2026.03.24", "ism-0002", description="d"),
        "ism-0003": None,  # removed upstream
    }
    reviewed_controls = {
        "ism-0001": _ctl("2025.12.9", "ism-0001", description="d"),
        "ism-0002": _ctl("2025.12.9", "ism-0002", description="d"),
        "ism-0003": _ctl("2025.12.9", "ism-0003", description="d"),
    }
    in_scope_target = [
        _ctl("2026.03.24", "ism-0001"),
        _ctl("2026.03.24", "ism-0002"),
        _ctl("2026.03.24", "ism-0009"),  # new, uncovered
    ]

    def lookup(version, identifier):
        return (target_controls if version == "2026.03.24" else reviewed_controls).get(identifier)

    out = coverage.compute_impact(
        manifest=manifest,
        target_version="2026.03.24",
        lookup=lookup,
        in_scope_target=in_scope_target,
        changed_fields=diff.changed_fields,
        diff_text=diff.unified_diff,
    )
    assert {e["identifier"] for e in out["re_review"]} == {"ism-0001"}
    assert out["re_review"][0]["changes"] == ["reworded"]
    assert {e["identifier"] for e in out["removed_upstream"]} == {"ism-0003"}
    assert {e["identifier"] for e in out["new_uncovered"]} == {"ism-0009"}
    assert out["summary"]["still_valid"] == 1  # ism-0002 unchanged and present
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_coverage_impact.py -v`
Expected: FAIL. `ManifestEntry` has no `reviewed_against`, and `coverage.compute_impact` does not exist.

- [ ] **Step 3: Add the field, serialise it, and implement compute_impact**

In `src/ism_mcp/coverage.py`:

Add `reviewed_against` to `ManifestEntry` (after `next_review`):

```python
    reviewed_against: str | None = None
```

In `_entry_from_dict`, pass it through. Add to the `ManifestEntry(...)` call:

```python
        reviewed_against=body.get("reviewed_against"),
```

In `serialise_manifest`, emit it inside the per-control block, after the `last_reviewed` line:

```python
        if entry.reviewed_against:
            lines.append(f"reviewed_against = {_toml_value(entry.reviewed_against)}")
```

Append `compute_impact` to the module:

```python
from collections.abc import Callable  # add to the imports at the top of the file


def compute_impact(
    manifest: Manifest,
    target_version: str,
    lookup: Callable[[str, str], object],
    in_scope_target: list,
    changed_fields: Callable[[object, object], list[str]],
    diff_text: Callable[[str, str], str],
    limit: int = 50,
) -> dict:
    """Bucket coverage entries by what a move to `target_version` requires.

    `lookup(version, identifier)` returns a Control-like object or None.
    `changed_fields(old, new)` and `diff_text(old_text, new_text)` come from diff.py.
    `in_scope_target` is the list of in-scope controls at the target version.
    """
    baseline = manifest.scope.get("baseline_version")
    re_review: list[dict] = []
    removed: list[dict] = []
    still_valid = 0

    for ident, entry in manifest.controls.items():
        if entry.status not in ("covered", "partial"):
            continue
        against = entry.reviewed_against or baseline or target_version
        target = lookup(target_version, ident)
        if target is None:
            removed.append(
                {
                    "identifier": ident,
                    "status": entry.status,
                    "reviewed_against": against,
                    "hint": f"no longer in {target_version}; consider not-applicable or remove",
                }
            )
            continue
        old = lookup(against, ident)
        fields = changed_fields(old, target) if old is not None else []
        if fields:
            item = {
                "identifier": ident,
                "status": entry.status,
                "reviewed_against": against,
                "changes": fields,
                "how_met": entry.how_met,
            }
            if old is not None and "reworded" in fields:
                item["diff"] = diff_text(old.description, target.description)
            re_review.append(item)
        else:
            still_valid += 1

    curated = set(manifest.controls)
    new_uncovered = [
        {
            "identifier": c.identifier,
            "label": c.label,
            "title": c.title,
            "section": c.section,
            "reason": "in scope at target, no manifest entry",
        }
        for c in in_scope_target
        if c.identifier not in curated
    ]

    re_review.sort(key=lambda e: e["identifier"])
    removed.sort(key=lambda e: e["identifier"])
    new_uncovered.sort(key=lambda e: e["identifier"])
    return {
        "baseline_version": baseline,
        "target_version": target_version,
        "summary": {
            "re_review": len(re_review),
            "removed_upstream": len(removed),
            "new_uncovered": len(new_uncovered),
            "still_valid": still_valid,
        },
        "re_review": re_review[:limit],
        "removed_upstream": removed[:limit],
        "new_uncovered": new_uncovered[:limit],
    }
```

Update `src/ism_mcp/data/coverage_template.toml` to seed a baseline:

```toml
schema_version = 1

[scope]
classification = "P"
sections = []
baseline_version = ""

[project]
name = ""
description = ""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_coverage_impact.py -v`
Expected: PASS.

- [ ] **Step 5: Check the other coverage tests still pass**

Run: `uv run pytest tests/test_coverage_serialise.py tests/test_coverage_read.py tests/test_coverage_upsert.py tests/test_coverage_manifest.py tests/test_coverage_validation.py -v`
Expected: PASS. `reviewed_against` is optional and defaults to `None`, so existing entries are unaffected. If a serialise round-trip test asserts exact text, update it to allow the new optional line (only emitted when set).

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/coverage.py src/ism_mcp/data/coverage_template.toml tests/test_coverage_impact.py
git commit -m "feat: coverage reviewed_against pin and compute_impact"
```

---

## Task F2: stamp reviewed_against and the ism_coverage_impact tool

**Files:**
- Modify: `src/ism_mcp/server.py` (`ism_coverage_upsert` stamps reviewed_against; add `ism_coverage_impact`)
- Modify: `tests/test_server_coverage.py`
- Test: `tests/test_server_coverage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server_coverage.py` (reuse its existing manifest+DB fixtures; they must now set an active version and a `baseline_version` in scope). Add:

```python
def test_upsert_stamps_reviewed_against_active_version(coverage_env):
    import json

    out = json.loads(server.ism_coverage_upsert("ism-9001", "covered", "done"))
    assert out["ok"] is True
    read = json.loads(server.ism_coverage_read())
    assert read["controls"]["ism-9001"]["reviewed_against"] == "2026.03.24"


def test_coverage_impact_reports_new_uncovered(coverage_env):
    import json

    out = json.loads(server.ism_coverage_impact())
    assert out["target_version"] == "2026.03.24"
    assert "summary" in out
```

`coverage_env` is the existing fixture in this file that writes a manifest and points the server at a populated DB. Extend it so the DB has an active version `2026.03.24` (call `store.upsert_version` + `store.set_active_version`), the manifest `[scope]` includes `baseline_version = "2026.03.24"`, and `ism_coverage_read`'s output exposes `reviewed_against` (it will once `_manifest_to_json` includes it, below).

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server_coverage.py -k "reviewed_against or impact" -v`
Expected: FAIL. `ism_coverage_impact` does not exist and upsert does not stamp `reviewed_against`.

- [ ] **Step 3: Implement the server wiring**

In `src/ism_mcp/server.py`:

In `ism_coverage_upsert`, add a `reviewed_against: str | None = None` parameter (place it after `next_review`), and when building the `ManifestEntry`, default it to the active version:

```python
    entry = coverage.ManifestEntry(
        identifier=identifier,
        status=status,  # type: ignore[arg-type]
        how_met=how_met,
        last_reviewed=last_reviewed_date,
        reviewed_by=reviewed_by,
        next_review=next_review_date,
        reviewed_against=reviewed_against or store.get_active_version(conn),
        files=list(files or []),
        commits=list(commits or []),
        urls=list(urls or []),
        attachments=list(attachments or []),
    )
```

In `_manifest_to_json` (lines 367-399), add `reviewed_against` to the per-control dict so reads expose it:

```python
            "reviewed_against": entry.reviewed_against,
```

(insert alongside `last_reviewed`).

Add the impact tool:

```python
@mcp.tool()
def ism_coverage_impact(
    project_path: str | None = None,
    target_version: str | None = None,
    limit: int = 50,
) -> str:
    """Report what a newer ISM version means for the project's coverage.

    Buckets covered/partial entries into re_review (control changed since it was assessed),
    removed_upstream (control gone at target), and new_uncovered (now in scope, no entry).
    `target_version` defaults to scope.baseline_version or the active version.
    """
    from . import diff

    path, err = _find_manifest_or_error(project_path)
    if err is not None:
        return json.dumps(err)
    assert path is not None
    try:
        manifest = coverage.read_manifest(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    conn = _conn()
    target = target_version or manifest.scope.get("baseline_version") or store.get_active_version(conn)
    if target is None or store.get_version(conn, target) is None:
        return json.dumps({"error": f"no such target version: {target}", "hint": "call ism_versions"})

    try:
        in_scope_target = store.list_in_scope(
            conn,
            classification=manifest.scope.get("classification"),
            maturity=manifest.scope.get("maturity"),
            sections=manifest.scope.get("sections"),
            version=target,
        )
    except ValueError as e:
        return json.dumps({"error": f"scope: {e}"})

    def lookup(version: str, identifier: str):
        return store.get_control(conn, identifier, version=version)

    result = coverage.compute_impact(
        manifest=manifest,
        target_version=target,
        lookup=lookup,
        in_scope_target=in_scope_target,
        changed_fields=diff.changed_fields,
        diff_text=diff.unified_diff,
        limit=_clamp_limit(limit),
    )
    return json.dumps({"manifest_path": str(path), **result}, indent=2)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_server_coverage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_coverage.py
git commit -m "feat: ism_coverage_impact and reviewed_against stamping"
```

---

# Phase G: cleanup and docs

## Task G1: remove legacy formats and dead code

**Files:**
- Delete: `tests/test_ingest_xlsx.py`, `tests/test_excerpt_extraction.py`
- Modify: `pyproject.toml` (drop `openpyxl`, `pdfplumber`)
- Verify: no remaining references to `parse_xlsx`, `attach_pdf_excerpts`, `pdf_excerpt`, `openpyxl`, `pdfplumber`

- [ ] **Step 1: Delete the obsolete tests**

```bash
git rm tests/test_ingest_xlsx.py tests/test_excerpt_extraction.py
```

- [ ] **Step 2: Drop the dependencies**

In `pyproject.toml`, remove these two lines from `dependencies`:

```toml
    "openpyxl>=3.1.5",
    "pdfplumber>=0.11.9",
```

Then run `uv sync` to update the lockfile.

- [ ] **Step 3: Grep for dead references**

Run:

```bash
grep -rn "openpyxl\|pdfplumber\|parse_xlsx\|attach_pdf_excerpts\|pdf_excerpt\|pdf_page\|extract_excerpts" src tests
```

Expected: no matches. If any helper functions remain in `ingest.py` from the old PDF path (e.g. `extract_excerpts_from_lines`, `_paragraph_before`, `_str_or_none`, `_yes`), they were removed when `ingest.py` was rewritten in C2. Confirm `ingest.py` matches the C2 content exactly. Remove any stragglers.

- [ ] **Step 4: Run the full suite**

Run: `./scripts/ci.sh`
Expected: `==> CI OK`. This is the first point where the whole suite (fmt, lint, type, test) must be green. Fix any ruff or pyright findings (unused imports, the relocated `import re`, the `Callable` import in coverage).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: drop XLSX and PDF ingest dependencies and tests"
```

---

## Task G2: documentation

**Files:**
- Modify: `README.md`, `HANDOVER.md`, `CLAUDE.md`, `src/ism_mcp/install.py` (the injected CLAUDE.md guidance block)

- [ ] **Step 1: README**

Rewrite the ingest and architecture sections:
- Replace the XLSX/PDF download-and-ingest workflow with: `ism-mcp ingest` (fetches from the official OSCAL repo into `~/.local/share/ism-mcp/oscal` by default), `ism-mcp ingest-history` (full release history), `ism-mcp update`, and `--oscal PATH` for offline use.
- Replace the "single-revision / no history" limitation with the multi-version capability and the new tools (`ism_versions`, `ism_diff`, `ism_history`, `ism_coverage_impact`).
- Update the architecture line from "XLSX parser (openpyxl) + PDF paragraph extractor (pdfplumber)" to "OSCAL catalog parser (stdlib json) over the ACSC ism-oscal git mirror".
- Note that identifiers are OSCAL ids (`ism-1001`), with tolerant lookup for `ISM-1001`, bare numbers, and labels.

- [ ] **Step 2: CLAUDE.md (project)**

Update the repository layout block to add `oscal.py`, `fetch.py`, `diff.py` and to change `ingest.py`'s description to OSCAL. Update the CLI line to `ingest, ingest-history, fetch, update, serve, install`. Update the build/dev commands' `ingest` example to the OSCAL form.

- [ ] **Step 3: install.py guidance block**

In `src/ism_mcp/install.py`, the managed CLAUDE.md block lists the tools. Add `ism_versions`, `ism_diff`, `ism_history`, and `ism_coverage_impact`, and add a sentence that the database carries ISM version history so the agent can check `ism_coverage_impact` when a newer ISM lands. If `test_install_builders.py` asserts on the block text, update that assertion.

- [ ] **Step 4: HANDOVER.md**

Follow the CLAUDE.md "Closing a development branch" checklist when the branch lands. For now, update HANDOVER's state to note the multi-version OSCAL work, the new module list, the new tool inventory, and a verification block:

```bash
uv run ism-mcp ingest-history --oscal-repo /home/dudley/code/ism-oscal --db /tmp/ism-history.db
uv run python -c "from ism_mcp import store; c=store.open_db(__import__('pathlib').Path('/tmp/ism-history.db')); print(len(store.list_versions(c)), 'versions', store.count_controls(c), 'controls in', store.get_active_version(c))"
```

Expected: 24 versions, ~1130 controls in 2026.03.24 (numbers will grow as ASD publishes more releases).

- [ ] **Step 5: Run CI and commit**

Run: `./scripts/ci.sh`
Expected: `==> CI OK`.

```bash
git add -A
git commit -m "docs: OSCAL ingest, multi-version tools, and history"
```

- [ ] **Step 6: Real-data smoke test (manual, not committed)**

Run the real ingest against the local clone to confirm the parser handles the full catalog:

```bash
uv run ism-mcp ingest-history --oscal-repo /home/dudley/code/ism-oscal --db /tmp/ism-history.db
uv run ism-mcp serve --db /tmp/ism-history.db   # smoke: start, then Ctrl-C
```

Confirm 24 versions load and the active version has ~1130 controls. This catches any real-catalog edge case the fixtures miss (for example a control at an unexpected group depth). If found, add a fixture and a test, then fix the parser.

---

## Spec coverage self-check

| Spec requirement | Task |
|---|---|
| versions table, version-keyed controls, active pointer | A1 |
| identifier-keyed embeddings, retire rowid dependency | A2, A3 |
| canonical OSCAL id + tolerant lookup | A2 |
| OSCAL parser: metadata, controls, applicability, statement, label, group mapping | B1 |
| E8 maturity via resolved-catalog membership | B2 |
| fetch by default, official ACSC repo, offline path, provenance | C1, C3 |
| ingest (one version), ingest-history (tag walk), update, embed-active-only default | C2, C3 |
| drop openpyxl/pdfplumber and XLSX/PDF code+tests | C2, G1 |
| version= on existing lookup tools; ism_stats rebuilt | D2 |
| retrieval keyed on identifier within active version | D1 |
| ism_versions | D2 |
| ism_diff (default latest-vs-previous; all change classes) | E1, E2 |
| ism_history timeline | E1, E2 |
| coverage baseline_version + reviewed_against | F1, F2 |
| ism_coverage_impact (re_review / removed_upstream / new_uncovered / still_valid) | F1, F2 |
| docs: README, CLAUDE, HANDOVER, install fragment | G2 |

## Notes for the executor

- Phases A through C leave the server tests red (the server still expects the old retrieval until Phase D). If you want a green bar between every phase, run only the phase's own test files until Phase D, then run `./scripts/ci.sh test`. The whole suite must be green by the end of G1.
- The `ism_diff()` default uses string comparison on `YYYY.MM.DD` version keys, which sorts chronologically. This holds for all real ISM versions. The single-digit-day tags (e.g. `2025.12.9`) still order correctly against same-month multi-digit days because months differ; if two same-month patch releases ever need ordering, compare on the `published` date instead. Note this in the code only if a test exposes it.
- Keep `from __future__ import annotations` at the top of every new module.
- Run `uv run ruff format src tests` before each commit.

### Deferred from the spec (intentional, not dropped)

The spec mentions two refinements this plan leaves out of the first cut. They are deferred, not forgotten:

- **Reworded cosine similarity.** The spec notes `ism_diff` could attach a semantic similarity score to a reworded control to rank trivial vs material edits. Because the default policy embeds only the active version, historical versions usually lack embeddings, so the score would usually be absent. The unified diff already conveys the change. Add later behind a check that both sides are embedded, augmenting the `reworded` entry in the `ism_diff` server tool.
- **Possible-rename heuristic.** The spec notes a low-confidence pairing of a removed id with an added id of high text similarity. Strong rename detection is explicitly out of scope; this is a later additive feature on top of `diff.diff_controls`, flagged as a candidate and never asserted.
```
