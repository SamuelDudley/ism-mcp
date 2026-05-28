# Hybrid Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ism_applicable(work, ...)` — a hybrid retrieval tool that ranks ISM controls relevant to a free-text work description using vector embeddings fused with FTS5 BM25, layered with classification, maturity, tag, and repo-path filters.

**Architecture:** Two retrievers over the same `controls` table. The existing FTS5 index handles lexical retrieval (BM25). A new sidecar table `controls_embeddings` stores L2-normalised float32 vectors produced at ingest by `bge-small-en-v1.5` via `fastembed`. At query time the server loads the full matrix into a numpy array, runs vector top-50 and BM25 top-50 in parallel, fuses with Reciprocal Rank Fusion (k=60), applies structured post-filters, and returns top-K.

**Tech Stack:** Python 3.14, uv, sqlite3, numpy, fastembed (ONNX runtime, no torch), pytest, ruff, pyright.

**Prerequisite:** The hardening plan `docs/plans/2026-05-28-hardening-and-tests.md` must be merged first. This plan assumes pytest, ruff, pyright, `scripts/ci.sh`, the `db` / `sample_controls` fixtures, and per-control PDF excerpts are already in place.

**Reference spec:** `docs/superpowers/specs/2026-05-28-ism-mcp-hybrid-discovery-design.md`.

---

## Task 1: Add explicit deps for fastembed and numpy

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add the deps via uv**

```bash
uv add fastembed numpy
```

`numpy` is already transitive via `pandas`/`pdfplumber`/`fastembed`. Promoting it makes the dependency explicit at the project boundary.

- [ ] **Step 2: Verify the install**

```bash
uv run python -c "import fastembed, numpy; print(fastembed.__version__, numpy.__version__)"
```

Expected: prints two versions, exits 0.

- [ ] **Step 3: Run CI to confirm nothing else broke**

```bash
./scripts/ci.sh
```

Expected: `==> CI OK`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add fastembed and numpy explicit deps"
```

---

## Task 2: Classification and maturity normalisers

**Files:**
- Create: `src/ism_mcp/classification.py`
- Create: `tests/test_classification.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_classification.py`:

```python
"""Normalisation of classification and maturity inputs."""

from __future__ import annotations

import pytest

from ism_mcp.classification import normalise_classification, normalise_maturity


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("NC", "NC"),
        ("nc", "NC"),
        ("OFFICIAL", "NC"),
        ("official", "NC"),
        ("non-classified", "NC"),
        ("OS", "OS"),
        ("OFFICIAL:Sensitive", "OS"),
        ("OFFICIAL-Sensitive", "OS"),
        ("official:sensitive", "OS"),
        ("P", "P"),
        ("PROTECTED", "P"),
        ("S", "S"),
        ("SECRET", "S"),
        ("TS", "TS"),
        ("TOP_SECRET", "TS"),
        ("TOP SECRET", "TS"),
        ("top secret", "TS"),
    ],
)
def test_normalise_classification(raw, expected):
    assert normalise_classification(raw) == expected


def test_normalise_classification_rejects_unknown():
    with pytest.raises(ValueError, match="unknown classification"):
        normalise_classification("HUSH-HUSH")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ML1", "ML1"),
        ("ml1", "ML1"),
        ("1", "ML1"),
        (1, "ML1"),
        ("ML2", "ML2"),
        ("2", "ML2"),
        ("ML3", "ML3"),
        ("3", "ML3"),
    ],
)
def test_normalise_maturity(raw, expected):
    assert normalise_maturity(raw) == expected


def test_normalise_maturity_rejects_unknown():
    with pytest.raises(ValueError, match="unknown maturity"):
        normalise_maturity("ML4")
```

- [ ] **Step 2: Run tests, expect failure**

```bash
uv run pytest tests/test_classification.py -v
```

Expected: `ModuleNotFoundError: No module named 'ism_mcp.classification'`.

- [ ] **Step 3: Implement the module**

Create `src/ism_mcp/classification.py`:

```python
"""Normalise classification and maturity inputs from agent calls."""

from __future__ import annotations


_CLASS_MAP = {
    "nc": "NC", "official": "NC", "non-classified": "NC",
    "os": "OS", "official:sensitive": "OS", "official-sensitive": "OS",
    "p": "P", "protected": "P",
    "s": "S", "secret": "S",
    "ts": "TS", "top_secret": "TS", "top secret": "TS",
}

_MATURITY_MAP = {
    "ml1": "ML1", "1": "ML1",
    "ml2": "ML2", "2": "ML2",
    "ml3": "ML3", "3": "ML3",
}


def normalise_classification(value: str) -> str:
    key = value.strip().lower()
    if key not in _CLASS_MAP:
        raise ValueError(f"unknown classification: {value!r}")
    return _CLASS_MAP[key]


def normalise_maturity(value: str | int) -> str:
    key = str(value).strip().lower()
    if key not in _MATURITY_MAP:
        raise ValueError(f"unknown maturity: {value!r}")
    return _MATURITY_MAP[key]
```

- [ ] **Step 4: Run tests, expect pass**

```bash
uv run pytest tests/test_classification.py -v
```

Expected: 22 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/classification.py tests/test_classification.py
git commit -m "feat: add classification and maturity normalisers"
```

---

## Task 3: Path-keyword expander

**Files:**
- Create: `src/ism_mcp/data/path_keywords.toml`
- Create: `src/ism_mcp/paths.py`
- Create: `tests/test_paths.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_paths.py`:

```python
"""Path tokenisation and keyword expansion."""

from __future__ import annotations

from ism_mcp.paths import expand_paths, matched_tokens


def test_expand_known_tokens():
    expanded, matched = expand_paths(["src/auth/jwt.py"])
    assert "authentication" in expanded
    assert "session" in expanded
    assert "token" in expanded
    assert "credential" in expanded
    assert "jwt" in matched
    assert "auth" in matched


def test_expand_is_case_insensitive():
    expanded, _ = expand_paths(["src/Auth/JWT.py"])
    assert "authentication" in expanded


def test_unknown_tokens_drop_silently():
    expanded, matched = expand_paths(["src/foo/bar.py"])
    assert expanded == set()
    assert matched == set()


def test_multiple_paths_merge():
    expanded, matched = expand_paths(["src/auth/jwt.py", "src/logs/audit.py"])
    assert "authentication" in expanded
    assert "logging" in expanded
    assert {"jwt", "auth", "log", "audit"}.issubset(matched)


def test_empty_input_returns_empty():
    expanded, matched = expand_paths([])
    assert expanded == set()
    assert matched == set()


def test_matched_tokens_returns_known_tokens_only():
    assert matched_tokens("src/auth/jwt.py") == {"auth", "jwt"}
    assert matched_tokens("src/foo/bar.py") == set()
```

- [ ] **Step 2: Run tests, expect failure**

```bash
uv run pytest tests/test_paths.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the keyword map**

Create `src/ism_mcp/data/path_keywords.toml`:

```toml
auth      = "authentication session token credential"
jwt       = "session token authentication"
oauth     = "authentication token"
session   = "session timeout authentication"
sso       = "single-sign-on identity authentication"
saml      = "single-sign-on identity"
mfa       = "multi-factor authentication"
"2fa"     = "multi-factor authentication"
rbac      = "access control authorisation role"
acl       = "access control authorisation"
permission = "access control authorisation"
log       = "logging event audit"
audit     = "logging event audit"
monitor   = "monitoring telemetry"
metric    = "monitoring telemetry"
trace     = "monitoring telemetry"
tls       = "encryption transport cryptography"
ssl       = "encryption transport cryptography"
crypt     = "encryption cryptography key"
cert      = "certificate cryptography"
key       = "cryptographic key management"
secret    = "cryptographic key management secrets"
vault     = "cryptographic key management secrets"
backup    = "backup recovery"
restore   = "backup recovery"
s3        = "storage cloud at-rest"
gcs       = "storage cloud at-rest"
blob      = "storage cloud at-rest"
db        = "database storage at-rest"
sql       = "database storage at-rest"
postgres  = "database storage at-rest"
mysql     = "database storage at-rest"
mongo     = "database storage at-rest"
redis     = "cache memory"
http      = "web application interface"
api       = "web application interface"
graphql   = "web application interface"
patch     = "patching vulnerability update"
update    = "patching update"
deploy    = "deployment configuration"
ci        = "build pipeline integrity"
pipeline  = "build pipeline integrity"
docker    = "container image"
k8s       = "container orchestration"
container = "container image"
```

- [ ] **Step 4: Implement the expander**

Create `src/ism_mcp/paths.py`:

```python
"""Tokenise repo paths and expand known tokens into BM25-friendly keywords."""

from __future__ import annotations

import re
import tomllib
from functools import cache
from importlib.resources import files


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@cache
def _keyword_map() -> dict[str, set[str]]:
    raw = tomllib.loads(files("ism_mcp.data").joinpath("path_keywords.toml").read_text())
    return {token.lower(): set(phrase.split()) for token, phrase in raw.items()}


def _tokens(path: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(path)]


def matched_tokens(path: str) -> set[str]:
    keywords = _keyword_map()
    return {t for t in _tokens(path) if t in keywords}


def expand_paths(paths: list[str]) -> tuple[set[str], set[str]]:
    """Return (expanded_keywords, matched_path_tokens) across all paths."""
    keywords = _keyword_map()
    expanded: set[str] = set()
    matched: set[str] = set()
    for path in paths:
        for token in _tokens(path):
            if token in keywords:
                matched.add(token)
                expanded.update(keywords[token])
    return expanded, matched
```

- [ ] **Step 5: Ensure the package can find the data file**

Verify `src/ism_mcp/data/__init__.py` exists. If not, create it as an empty file so `importlib.resources.files("ism_mcp.data")` resolves.

```bash
test -f src/ism_mcp/data/__init__.py || touch src/ism_mcp/data/__init__.py
```

- [ ] **Step 6: Run tests, expect pass**

```bash
uv run pytest tests/test_paths.py -v
```

Expected: 6 tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/ism_mcp/data/ src/ism_mcp/paths.py tests/test_paths.py
git commit -m "feat: add path-keyword expander for repo-context queries"
```

---

## Task 4: Embedder protocol with deterministic hash impl

**Files:**
- Create: `src/ism_mcp/embed.py`
- Create: `tests/test_embed.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_embed.py`:

```python
"""Embedder protocol and the deterministic hash implementation."""

from __future__ import annotations

import numpy as np

from ism_mcp.embed import DeterministicHashEmbedder, l2_normalise


def test_hash_embedder_shape_and_dtype():
    e = DeterministicHashEmbedder(dim=384)
    v = e.embed(["hello world", "another control"])
    assert v.shape == (2, 384)
    assert v.dtype == np.float32


def test_hash_embedder_is_deterministic():
    e = DeterministicHashEmbedder(dim=384)
    a = e.embed(["session timeout"])
    b = e.embed(["session timeout"])
    np.testing.assert_array_equal(a, b)


def test_hash_embedder_distinguishes_inputs():
    e = DeterministicHashEmbedder(dim=384)
    v = e.embed(["session timeout", "network encryption"])
    assert not np.allclose(v[0], v[1])


def test_hash_embedder_outputs_are_l2_normalised():
    e = DeterministicHashEmbedder(dim=384)
    v = e.embed(["foo", "bar", "baz"])
    norms = np.linalg.norm(v, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-6)


def test_l2_normalise_handles_zero_vector():
    v = np.zeros((1, 4), dtype=np.float32)
    out = l2_normalise(v)
    assert np.all(np.isfinite(out))
    assert out.shape == (1, 4)
```

- [ ] **Step 2: Run tests, expect failure**

```bash
uv run pytest tests/test_embed.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

Create `src/ism_mcp/embed.py`:

```python
"""Embedder protocol and implementations."""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


def l2_normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms < 1e-9, 1.0, norms)


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class DeterministicHashEmbedder:
    """Stable per-text vector derived from SHA-256 of the input. Test-only."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:8], "big", signed=False)
            rng = np.random.default_rng(seed)
            out[i] = rng.standard_normal(self.dim, dtype=np.float32)
        return l2_normalise(out)


class FastEmbedEmbedder:
    """Default. Wraps BAAI/bge-small-en-v1.5 via fastembed."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self.dim = 384

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array(list(self._model.embed(texts)), dtype=np.float32)
        return l2_normalise(vectors)
```

- [ ] **Step 4: Run tests, expect pass**

```bash
uv run pytest tests/test_embed.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/embed.py tests/test_embed.py
git commit -m "feat: add Embedder protocol with hash and fastembed implementations"
```

---

## Task 5: Extend store schema with controls_embeddings

**Files:**
- Modify: `src/ism_mcp/store.py`
- Modify: `tests/test_store.py` (additive)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py`:

```python
import numpy as np


def test_insert_and_fetch_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    rows = list(db.execute("SELECT rowid, identifier FROM controls ORDER BY rowid"))
    rowid_for = {row["identifier"]: row["rowid"] for row in rows}
    vectors = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    store.insert_embeddings(
        db,
        [(rowid_for["ISM-9001"], vectors[0].tobytes()),
         (rowid_for["ISM-9002"], vectors[1].tobytes()),
         (rowid_for["ISM-9003"], vectors[2].tobytes())],
    )
    matrix, ids = store.load_embedding_matrix(db, dim=4)
    assert matrix.shape == (3, 4)
    assert matrix.dtype == np.float32
    assert set(ids) == set(rowid_for.values())


def test_load_embedding_matrix_returns_empty_when_table_empty(db):
    matrix, ids = store.load_embedding_matrix(db, dim=4)
    assert matrix.shape == (0, 4)
    assert ids == []


def test_reset_drops_embeddings(db, sample_controls):
    store.insert_controls(db, sample_controls)
    row = db.execute("SELECT rowid FROM controls LIMIT 1").fetchone()
    store.insert_embeddings(db, [(row["rowid"], (b"\x00" * 16))])
    store.reset(db)
    matrix, ids = store.load_embedding_matrix(db, dim=4)
    assert ids == []
```

- [ ] **Step 2: Run tests, expect failure**

```bash
uv run pytest tests/test_store.py -v -k embedding
```

Expected: `AttributeError: module 'ism_mcp.store' has no attribute 'insert_embeddings'` (or similar).

- [ ] **Step 3: Extend `SCHEMA` in `src/ism_mcp/store.py`**

Locate the `SCHEMA` constant. Append, before the closing `"""`, the new table definition:

```sql

CREATE TABLE IF NOT EXISTS controls_embeddings (
    rowid     INTEGER PRIMARY KEY REFERENCES controls(rowid) ON DELETE CASCADE,
    embedding BLOB NOT NULL
);
```

- [ ] **Step 4: Update `reset()` in `src/ism_mcp/store.py`**

Replace the body of `reset()` with:

```python
def reset(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS controls_embeddings;
        DROP TABLE IF EXISTS controls_fts;
        DROP TABLE IF EXISTS controls;
        DROP TABLE IF EXISTS meta;
        """
    )
    conn.executescript(SCHEMA)
```

- [ ] **Step 5: Add `insert_embeddings` and `load_embedding_matrix` to `src/ism_mcp/store.py`**

Add the import near the top:

```python
import numpy as np
```

Add at the bottom of the file:

```python
def insert_embeddings(
    conn: sqlite3.Connection, rows: list[tuple[int, bytes]]
) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO controls_embeddings(rowid, embedding) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def load_embedding_matrix(
    conn: sqlite3.Connection, dim: int
) -> tuple[np.ndarray, list[int]]:
    rows = conn.execute(
        "SELECT rowid, embedding FROM controls_embeddings ORDER BY rowid"
    ).fetchall()
    if not rows:
        return np.empty((0, dim), dtype=np.float32), []
    ids = [r["rowid"] for r in rows]
    matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(rows), dim)
    return matrix.copy(), ids
```

The `.copy()` detaches the array from the underlying bytes so the connection can be closed safely.

- [ ] **Step 6: Run tests, expect pass**

```bash
uv run pytest tests/test_store.py -v
```

Expected: all store tests pass (previous tests plus the 3 new ones).

- [ ] **Step 7: Commit**

```bash
git add src/ism_mcp/store.py tests/test_store.py
git commit -m "feat: add controls_embeddings table and load_embedding_matrix"
```

---

## Task 6: VectorIndex for in-memory cosine search

**Files:**
- Create: `src/ism_mcp/retrieve.py`
- Create: `tests/test_retrieve.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_retrieve.py`:

```python
"""Vector cosine search and reciprocal-rank fusion."""

from __future__ import annotations

import numpy as np
import pytest

from ism_mcp.retrieve import VectorIndex, rrf


def test_vector_index_returns_nearest_first():
    matrix = np.array(
        [[1.0, 0.0], [0.7, 0.7], [0.0, 1.0]],
        dtype=np.float32,
    )
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    ids = [10, 20, 30]
    idx = VectorIndex(matrix, ids)
    query = np.array([1.0, 0.0], dtype=np.float32)
    query /= np.linalg.norm(query)
    results = idx.search(query, top_k=3)
    assert [rid for rid, _ in results] == [10, 20, 30]
    assert results[0][1] > results[1][1] > results[2][1]


def test_vector_index_respects_top_k():
    matrix = np.array([[1.0], [0.5], [0.1]], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    idx = VectorIndex(matrix, [1, 2, 3])
    query = np.array([1.0], dtype=np.float32)
    assert len(idx.search(query, top_k=2)) == 2


def test_vector_index_empty_returns_empty():
    idx = VectorIndex(np.empty((0, 4), dtype=np.float32), [])
    query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert idx.search(query, top_k=10) == []


def test_rrf_fuses_two_rankings():
    lex = [(10, 0.0), (20, 0.0), (30, 0.0)]
    sem = [(20, 0.0), (10, 0.0), (40, 0.0)]
    fused = rrf([lex, sem], k=60)
    ranked = [rid for rid, _ in fused]
    assert ranked[:2] == [20, 10] or ranked[:2] == [10, 20]
    assert 30 in ranked
    assert 40 in ranked


def test_rrf_top_in_both_outranks_top_in_one():
    lex = [(10, 0.0), (99, 0.0)]
    sem = [(10, 0.0), (88, 0.0)]
    fused = dict(rrf([lex, sem], k=60))
    assert fused[10] > fused[99]
    assert fused[10] > fused[88]


def test_rrf_normalised_score_is_in_unit_range():
    lex = [(10, 0.0)]
    sem = [(10, 0.0)]
    fused = rrf([lex, sem], k=60, normalised=True)
    assert fused[0][0] == 10
    assert 0.99 <= fused[0][1] <= 1.0


def test_rrf_empty_inputs_returns_empty():
    assert rrf([], k=60) == []
    assert rrf([[]], k=60) == []
```

- [ ] **Step 2: Run tests, expect failure**

```bash
uv run pytest tests/test_retrieve.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `VectorIndex` and `rrf`**

Create `src/ism_mcp/retrieve.py`:

```python
"""In-memory cosine search and Reciprocal Rank Fusion."""

from __future__ import annotations

from collections import defaultdict

import numpy as np


class VectorIndex:
    """Dense matrix of L2-normalised embeddings, brute-force cosine search."""

    def __init__(self, matrix: np.ndarray, ids: list[int]) -> None:
        if matrix.shape[0] != len(ids):
            raise ValueError("matrix rows must match ids length")
        self._matrix = matrix
        self._ids = ids

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, query: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        if self._matrix.shape[0] == 0:
            return []
        scores = self._matrix @ query
        k = min(top_k, scores.shape[0])
        order = np.argpartition(-scores, k - 1)[:k]
        order = order[np.argsort(-scores[order])]
        return [(self._ids[int(i)], float(scores[int(i)])) for i in order]


def rrf(
    rankings: list[list[tuple[int, float]]],
    k: int = 60,
    normalised: bool = True,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Returns fused [(rowid, score)] sorted by score desc."""
    accumulator: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (rowid, _score) in enumerate(ranking, start=1):
            accumulator[rowid] += 1.0 / (k + rank)
    if not accumulator:
        return []
    if normalised and rankings:
        max_score = len(rankings) / (k + 1)
        for rid in accumulator:
            accumulator[rid] = accumulator[rid] / max_score
    return sorted(accumulator.items(), key=lambda kv: (-kv[1], kv[0]))
```

- [ ] **Step 4: Run tests, expect pass**

```bash
uv run pytest tests/test_retrieve.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/retrieve.py tests/test_retrieve.py
git commit -m "feat: add VectorIndex and reciprocal rank fusion"
```

---

## Task 7: Wire embeddings into ingest

**Files:**
- Modify: `src/ism_mcp/ingest.py`
- Modify: `src/ism_mcp/__main__.py`
- Create: `tests/test_ingest_embed.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_embed.py`:

```python
"""End-to-end ingest with the deterministic hash embedder."""

from __future__ import annotations

import openpyxl

from ism_mcp import store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls, parse_xlsx


def _write_workbook(path):
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
    ws.append([
        "Guidelines for testing", "Encryption", "Network encryption",
        "ISM-9001", "1", "Jan-26",
        "Yes", "Yes", "Yes", "No", "No",
        "Yes", "No", "No",
        "All data communicated over network infrastructure is encrypted.",
        "", "", "", "", "Not Assessed", "", "", "Not Assessed", "Not Assessed", "",
    ])
    wb.save(path)


def test_embed_controls_yields_normalised_blobs(tmp_path):
    workbook = tmp_path / "ccm.xlsx"
    _write_workbook(workbook)
    controls = list(parse_xlsx(workbook))
    embedder = DeterministicHashEmbedder(dim=384)
    rows = list(embed_controls(controls, embedder))
    assert len(rows) == 1
    rowid, blob = rows[0]
    assert rowid == 1
    assert len(blob) == 384 * 4


def test_ingest_round_trip_persists_embeddings(tmp_path):
    workbook = tmp_path / "ccm.xlsx"
    _write_workbook(workbook)
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, list(parse_xlsx(workbook)))
    controls_after = [
        c for c in [store.get_control(conn, "ISM-9001")] if c is not None
    ]
    embedder = DeterministicHashEmbedder(dim=384)
    rows = list(embed_controls(controls_after, embedder))
    store.insert_embeddings(conn, rows)
    matrix, ids = store.load_embedding_matrix(conn, dim=384)
    assert matrix.shape == (1, 384)
    assert ids == [1]
```

- [ ] **Step 2: Run test, expect failure**

```bash
uv run pytest tests/test_ingest_embed.py -v
```

Expected: `ImportError: cannot import name 'embed_controls' from 'ism_mcp.ingest'`.

- [ ] **Step 3: Add `embed_controls` to `src/ism_mcp/ingest.py`**

At the top of the file, add to imports:

```python
import numpy as np
from typing import Iterator

from .embed import Embedder
from .store import Control
```

Then append:

```python
def embed_controls(
    controls: list[Control], embedder: Embedder
) -> Iterator[tuple[int, bytes]]:
    """Yield (rowid, normalised float32 BLOB) for each control."""
    texts = [
        f"{c.topic}. {c.section}. {c.description} {(c.pdf_excerpt or '')[:500]}"
        for c in controls
    ]
    vectors = embedder.embed(texts)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.where(norms < 1e-9, 1.0, norms)
    for rowid, vec in enumerate(vectors, start=1):
        yield rowid, vec.astype(np.float32).tobytes()
```

- [ ] **Step 4: Update `src/ism_mcp/__main__.py` to call embed_controls during ingest**

Read the existing `__main__.py` first to understand the ingest flow. Locate the `ingest` subcommand handler. After the `set_meta` calls and before printing the "done" line, add an embed-and-store step. The handler should also accept `--no-embeddings`.

Apply this change to the argument parser for the `ingest` subcommand:

```python
ingest_parser.add_argument(
    "--no-embeddings",
    action="store_true",
    help="skip embedding generation. Server falls back to lexical-only.",
)
```

And in the ingest handler body, after the existing insert_controls and set_meta calls, add:

```python
if args.no_embeddings:
    print("skipping embeddings (--no-embeddings)")
else:
    from .embed import FastEmbedEmbedder
    from .ingest import embed_controls

    print("embedding controls (first run downloads ~130 MB to ~/.cache/fastembed)...")
    persisted = [store.get_control(conn, c.identifier) for c in controls]
    persisted = [c for c in persisted if c is not None]
    embedder = FastEmbedEmbedder()
    rows = list(embed_controls(persisted, embedder))
    store.insert_embeddings(conn, rows)
    print(f"embedded {len(rows)} controls")
```

Note: the embedder is selectable via `ISM_MCP_EMBEDDER`. For the CLI path we always use `FastEmbedEmbedder` unless `--no-embeddings` is set. The `hash` mode is reserved for tests and is not wired into the CLI.

- [ ] **Step 5: Run the test, expect pass**

```bash
uv run pytest tests/test_ingest_embed.py -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/ingest.py src/ism_mcp/__main__.py tests/test_ingest_embed.py
git commit -m "feat: embed controls during ingest, add --no-embeddings flag"
```

---

## Task 8: List-helpers on the server

**Files:**
- Modify: `src/ism_mcp/store.py`
- Modify: `src/ism_mcp/server.py`
- Create: `tests/test_server_helpers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_helpers.py`:

```python
"""Helper tools on the MCP server: list_sections, list_classifications, list_maturities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ism_mcp import server, store


@pytest.fixture
def populated_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    return db_path


def test_list_sections_returns_distinct_sorted(populated_db):
    result = json.loads(server.ism_list_sections())
    assert result["sections"] == sorted({"Encryption", "Authentication", "Audit"})
    assert result["count"] == 3


def test_list_classifications_returns_canonical_and_friendly(populated_db):
    result = json.loads(server.ism_list_classifications())
    assert set(result["canonical"]) == {"NC", "OS", "P", "S", "TS"}
    assert "OFFICIAL" in result["friendly"]
    assert "PROTECTED" in result["friendly"]


def test_list_maturities_returns_ml1_through_ml3(populated_db):
    result = json.loads(server.ism_list_maturities())
    assert result["maturities"] == ["ML1", "ML2", "ML3"]
```

- [ ] **Step 2: Add `list_sections` to `src/ism_mcp/store.py`**

Append:

```python
def list_sections(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT section FROM controls ORDER BY section"
    ).fetchall()
    return [r["section"] for r in rows]
```

- [ ] **Step 3: Add the three helper tools to `src/ism_mcp/server.py`**

Append (before `def run() -> None:`):

```python
@mcp.tool()
def ism_list_sections() -> str:
    """List the distinct ISM Section values, the vocabulary for the `tags` filter on `ism_applicable`."""
    conn = _conn()
    sections = store.list_sections(conn)
    return json.dumps({"count": len(sections), "sections": sections}, indent=2)


@mcp.tool()
def ism_list_classifications() -> str:
    """Return the classification enum (canonical abbreviations and friendly aliases)."""
    return json.dumps(
        {
            "canonical": ["NC", "OS", "P", "S", "TS"],
            "friendly": [
                "OFFICIAL",
                "OFFICIAL:Sensitive",
                "PROTECTED",
                "SECRET",
                "TOP_SECRET",
            ],
        },
        indent=2,
    )


@mcp.tool()
def ism_list_maturities() -> str:
    """Return the Essential Eight maturity levels."""
    return json.dumps({"maturities": ["ML1", "ML2", "ML3"]}, indent=2)
```

- [ ] **Step 4: Run tests, expect pass**

```bash
uv run pytest tests/test_server_helpers.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ism_mcp/store.py src/ism_mcp/server.py tests/test_server_helpers.py
git commit -m "feat: add ism_list_sections, ism_list_classifications, ism_list_maturities"
```

---

## Task 9: ism_applicable tool

**Files:**
- Modify: `src/ism_mcp/server.py`
- Create: `tests/test_server_applicable.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_applicable.py`:

```python
"""End-to-end tests for ism_applicable with the deterministic hash embedder."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ism_mcp import server, store
from ism_mcp.embed import DeterministicHashEmbedder
from ism_mcp.ingest import embed_controls


@pytest.fixture
def populated_db(tmp_path, sample_controls, monkeypatch):
    db_path = tmp_path / "ism.db"
    conn = store.open_db(db_path)
    store.insert_controls(conn, sample_controls)
    embedder = DeterministicHashEmbedder(dim=384)
    fetched = [c for c in (store.get_control(conn, c.identifier) for c in sample_controls) if c is not None]
    store.insert_embeddings(conn, list(embed_controls(fetched, embedder)))
    conn.close()
    monkeypatch.setattr(server, "DEFAULT_DB", db_path)
    monkeypatch.setenv("ISM_MCP_EMBEDDER", "hash")
    server._reset_runtime_cache()
    yield db_path
    server._reset_runtime_cache()


def test_applicable_returns_results(populated_db):
    result = json.loads(server.ism_applicable("network encryption", limit=5))
    assert result["count"] >= 1
    ids = [r["identifier"] for r in result["results"]]
    assert "ISM-9001" in ids


def test_applicable_includes_candidates_before_filter(populated_db):
    result = json.loads(server.ism_applicable("network encryption", limit=5))
    assert "candidates_before_filter" in result


def test_applicable_classification_filter(populated_db):
    result = json.loads(
        server.ism_applicable("audit logging", classification="SECRET", limit=5)
    )
    ids = [r["identifier"] for r in result["results"]]
    assert "ISM-9003" in ids
    for r in result["results"]:
        assert r["applies"]["S"] is True


def test_applicable_empty_after_filter_includes_hint(populated_db):
    result = json.loads(
        server.ism_applicable(
            "anything",
            classification="NC",
            tags=["Audit"],
            limit=5,
        )
    )
    assert result["count"] == 0
    assert "hint" in result


def test_applicable_unknown_classification_returns_error(populated_db):
    result = json.loads(server.ism_applicable("anything", classification="HUSH"))
    assert "error" in result
    assert "classification" in result["error"].lower()


def test_applicable_unknown_tag_returns_error(populated_db):
    result = json.loads(server.ism_applicable("anything", tags=["No-Such-Section"]))
    assert "error" in result


def test_applicable_path_expansion_shows_in_why(populated_db):
    result = json.loads(
        server.ism_applicable("our auth flow", paths=["src/auth/session.py"], limit=5)
    )
    if result["count"] >= 1:
        whys = [w for r in result["results"] for w in r["why"]]
        assert any(w.startswith("path:") for w in whys)


def test_applicable_verbose_includes_excerpt(populated_db):
    result = json.loads(
        server.ism_applicable("logging events centrally", verbose=True, limit=5)
    )
    found = [r for r in result["results"] if r["identifier"] == "ISM-9003"]
    assert found and "pdf_excerpt" in found[0]
```

- [ ] **Step 2: Run tests, expect failure**

```bash
uv run pytest tests/test_server_applicable.py -v
```

Expected: `AttributeError: module 'ism_mcp.server' has no attribute 'ism_applicable'`.

- [ ] **Step 3: Extend `src/ism_mcp/server.py`**

Add the imports near the top:

```python
import os

import numpy as np

from . import classification as cls
from . import paths as pathlib_paths
from . import retrieve
from .embed import DeterministicHashEmbedder, Embedder, FastEmbedEmbedder
```

Add module-level runtime cache:

```python
_RUNTIME: dict[str, object] = {}


def _reset_runtime_cache() -> None:
    _RUNTIME.clear()


def _embedder() -> Embedder | None:
    mode = os.environ.get("ISM_MCP_EMBEDDER", "fastembed").lower()
    if mode == "none":
        return None
    if "embedder" in _RUNTIME:
        return _RUNTIME["embedder"]  # type: ignore[return-value]
    if mode == "hash":
        e: Embedder = DeterministicHashEmbedder(dim=384)
    else:
        e = FastEmbedEmbedder()
    _RUNTIME["embedder"] = e
    return e


def _vector_index(conn) -> retrieve.VectorIndex | None:
    if "vec_index" in _RUNTIME:
        return _RUNTIME["vec_index"]  # type: ignore[return-value]
    embedder = _embedder()
    if embedder is None:
        return None
    matrix, ids = store.load_embedding_matrix(conn, dim=embedder.dim)
    if len(ids) == 0:
        return None
    idx = retrieve.VectorIndex(matrix, ids)
    _RUNTIME["vec_index"] = idx
    return idx
```

Add the tool:

```python
@mcp.tool()
def ism_applicable(
    work: str,
    classification: str | None = None,
    maturity: str | None = None,
    tags: list[str] | None = None,
    paths: list[str] | None = None,
    limit: int = 20,
    verbose: bool = False,
) -> str:
    """Rank ISM controls relevant to a free-text description of planned or current work.

    Uses hybrid retrieval (semantic embeddings + FTS5 BM25) fused with Reciprocal Rank Fusion.
    Optional filters: classification (NC|OS|P|S|TS or OFFICIAL|...|TOP_SECRET), maturity (ML1|ML2|ML3),
    tags (validated against ism_list_sections), paths (repo paths whose tokens expand the lexical query).
    `score` in each result is a normalised RRF score in [0.0, 1.0], not a probability.
    """
    conn = _conn()

    try:
        norm_classification = cls.normalise_classification(classification) if classification else None
    except ValueError as e:
        return json.dumps({"error": f"classification: {e}"})

    try:
        norm_maturity = cls.normalise_maturity(maturity) if maturity else None
    except ValueError as e:
        return json.dumps({"error": f"maturity: {e}"})

    valid_sections = set(store.list_sections(conn))
    if tags:
        unknown = [t for t in tags if t not in valid_sections]
        if unknown:
            return json.dumps({"error": f"unknown tags: {unknown}. Use ism_list_sections() to discover."})

    expanded_terms, matched_path_tokens = pathlib_paths.expand_paths(paths or [])
    lexical_query = " ".join([work] + sorted(expanded_terms)) if expanded_terms else work

    lex_results = store.search(conn, lexical_query, limit=50)
    lex_ranking = [(_rowid_for(conn, c.identifier), 0.0) for c in lex_results]

    sem_ranking: list[tuple[int, float]] = []
    semantic_used = False
    idx = _vector_index(conn)
    embedder = _embedder()
    if idx is not None and embedder is not None:
        q_vec = embedder.embed([work])[0]
        sem_ranking = idx.search(q_vec, top_k=50)
        semantic_used = True

    fused = retrieve.rrf([lex_ranking, sem_ranking] if semantic_used else [lex_ranking], k=60)
    candidates_before_filter = len(fused)

    matches = _materialise(conn, fused, lex_results, matched_path_tokens, semantic_used)
    matches = _apply_filters(matches, norm_classification, norm_maturity, tags, valid_sections)
    matches = matches[:limit]

    response: dict = {
        "query": work,
        "filters": {
            "classification": norm_classification,
            "maturity": norm_maturity,
            "tags": tags or [],
            "paths": paths or [],
        },
        "count": len(matches),
        "candidates_before_filter": candidates_before_filter,
        "results": [_render_result(m, verbose) for m in matches],
    }
    if not matches and candidates_before_filter > 0:
        response["hint"] = (
            f"filters eliminated {candidates_before_filter} candidates. "
            "Relax classification, maturity, or tags."
        )
    return json.dumps(response, indent=2)


def _rowid_for(conn, identifier: str) -> int:
    row = conn.execute("SELECT rowid FROM controls WHERE identifier = ?", (identifier,)).fetchone()
    return int(row["rowid"]) if row else -1


def _materialise(
    conn,
    fused: list[tuple[int, float]],
    lex_results: list,
    matched_path_tokens: set[str],
    semantic_used: bool,
) -> list[dict]:
    lex_ids = {_rowid_for(conn, c.identifier) for c in lex_results}
    sem_ids_in_top = {rid for rid, _ in fused} - lex_ids if semantic_used else set()
    out: list[dict] = []
    for rowid, score in fused:
        row = conn.execute(
            "SELECT * FROM controls WHERE rowid = ?", (rowid,)
        ).fetchone()
        if row is None:
            continue
        why: list[str] = []
        if semantic_used and rowid in sem_ids_in_top | lex_ids:
            why.append("semantic")
        if rowid in lex_ids:
            why.append("lexical")
        for token in sorted(matched_path_tokens):
            why.append(f"path:{token}")
        out.append({"row": row, "score": float(score), "why": why})
    return out


def _apply_filters(
    matches: list[dict],
    classification: str | None,
    maturity: str | None,
    tags: list[str] | None,
    valid_sections: set[str],
) -> list[dict]:
    filtered: list[dict] = []
    for m in matches:
        r = m["row"]
        if classification and not r[f"applies_{classification.lower()}"]:
            continue
        if maturity and not r[f"maturity_{maturity.lower()}"]:
            continue
        if tags and r["section"] not in tags:
            continue
        filtered.append(m)
    return filtered


def _render_result(m: dict, verbose: bool) -> dict:
    r = m["row"]
    base = {
        "identifier": r["identifier"],
        "topic": r["topic"],
        "section": r["section"],
        "description": r["description"],
        "applies": {c: bool(r[f"applies_{c.lower()}"]) for c in store.CLASSIFICATIONS},
        "maturity": {ml: bool(r[f"maturity_{ml.lower()}"]) for ml in store.MATURITIES},
        "score": round(m["score"], 4),
        "why": m["why"],
    }
    if verbose:
        base["pdf_excerpt"] = r["pdf_excerpt"]
        base["pdf_page"] = r["pdf_page"]
    return base
```

- [ ] **Step 4: Run tests, expect pass**

```bash
uv run pytest tests/test_server_applicable.py -v
```

Expected: 8 tests pass. If a test fails because the hash embedder gives a poor ranking for the synthetic fixtures, expand `sample_controls` in `tests/conftest.py` so the relevant control has the matching keywords in `description` (the lexical retriever will then pull it in). Do not silently weaken the assertions.

- [ ] **Step 5: Confirm full suite still green**

```bash
./scripts/ci.sh
```

Expected: `==> CI OK`.

- [ ] **Step 6: Commit**

```bash
git add src/ism_mcp/server.py tests/test_server_applicable.py
git commit -m "feat: add ism_applicable hybrid retrieval tool"
```

---

## Task 10: Slow integration test against the real embedder

**Files:**
- Modify: `pyproject.toml`
- Modify: `scripts/ci.sh`
- Create: `tests/test_real_embedder.py`

- [ ] **Step 1: Register the `slow` marker**

In `pyproject.toml`, locate `[tool.pytest.ini_options]` (added in the hardening plan). Update it to:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--strict-markers", "--strict-config", "-ra", "-m", "not slow"]
markers = ["slow: integration tests that download the real fastembed model"]
```

The `-m "not slow"` excludes the slow tests from the default run.

- [ ] **Step 2: Write the integration test**

Create `tests/test_real_embedder.py`:

```python
"""Slow integration test. Downloads the real bge-small-en-v1.5 model. Opt-in only."""

from __future__ import annotations

import numpy as np
import pytest

from ism_mcp.embed import FastEmbedEmbedder


@pytest.mark.slow
def test_fastembed_returns_normalised_384_vectors():
    e = FastEmbedEmbedder()
    v = e.embed(["session timeout"])
    assert v.shape == (1, 384)
    np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


@pytest.mark.slow
def test_fastembed_orders_session_query_above_unrelated():
    e = FastEmbedEmbedder()
    vectors = e.embed(
        [
            "Sessions are terminated after fifteen minutes of inactivity.",
            "All data communicated over network infrastructure is encrypted.",
            "Events are logged to a centralised facility.",
        ]
    )
    query = e.embed(["session timeout policy"])[0]
    sims = vectors @ query
    ranked = np.argsort(-sims)
    assert ranked[0] == 0
```

- [ ] **Step 3: Extend `scripts/ci.sh` with a `slow` target**

In `scripts/ci.sh`, locate the `case "${1:-all}"` block from the hardening plan. Add a `slow)` branch:

```bash
run_slow() {
    echo "==> pytest -m slow"
    uv run pytest -m slow
}
```

```bash
case "${1:-all}" in
    fmt)  run_fmt ;;
    lint) run_lint ;;
    type) run_type ;;
    test) run_test ;;
    slow) run_slow ;;
    all)
        run_fmt
        run_lint
        run_type
        run_test
        ;;
    *)
        echo "Unknown target: $1" >&2
        echo "Usage: $0 [fmt|lint|type|test|slow|all]" >&2
        exit 2
        ;;
esac
```

Note: `all` deliberately does NOT include `slow`. Run `./scripts/ci.sh slow` separately when you want to exercise the real embedder.

- [ ] **Step 4: Confirm fast suite excludes slow tests**

```bash
./scripts/ci.sh
```

Expected: `==> CI OK`, slow tests deselected by the `-m "not slow"` config.

- [ ] **Step 5: Run the slow suite locally**

```bash
./scripts/ci.sh slow
```

First run downloads ~130 MB to `~/.cache/fastembed/`. Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml scripts/ci.sh tests/test_real_embedder.py
git commit -m "test: add slow integration test for the real fastembed embedder"
```

---

## Task 11: Update the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add `ism_applicable` and helpers to the MCP tools table**

Locate the `## MCP tools` section. Replace the table with:

```markdown
| Tool | Purpose |
|---|---|
| `ism_applicable(work, classification?, maturity?, tags?, paths?, limit?, verbose?)` | Hybrid retrieval: rank controls relevant to a free-text description of planned or current work. Recommended default for discovery. |
| `ism_get(identifier)` | Full record for one control by ID. |
| `ism_search(query, limit=10)` | Deterministic FTS5 search. Use when you know the exact term. |
| `ism_neighbors(id)` (planned, sub-project C) | Related controls. |
| `ism_list_by_classification(classification)` | Controls applicable at NC / OS / P / S / TS. |
| `ism_list_topics()` | Distinct topic strings. |
| `ism_list_by_topic(topic)` | Controls under a topic. |
| `ism_list_sections()` | Distinct section strings. The vocabulary for the `tags` filter on `ism_applicable`. |
| `ism_list_classifications()` | Canonical classification enum plus friendly aliases. |
| `ism_list_maturities()` | Essential Eight maturity levels. |
| `ism_stats()` | Database statistics. |
```

- [ ] **Step 2: Add a "Discovery for agents" section before "Architecture"**

Insert:

```markdown
## Discovery for agents

The headline use case is `ism_applicable`. The agent describes the work in plain language, optionally narrows by classification, maturity, section tags, or repo paths, and gets back a ranked list of relevant controls.

```python
# example tool call from an agent
ism_applicable(
    work="adding JWT refresh and idle session timeout to our auth flow",
    classification="OFFICIAL",
    maturity="ML2",
    paths=["src/auth/jwt.py", "src/auth/session.py"],
    limit=10,
)
```

Returns a ranked list with `identifier`, `topic`, `section`, `description`, `applies`, `maturity`, a normalised RRF `score` in `[0.0, 1.0]`, and a `why` list naming the signals that surfaced each result (`semantic`, `lexical`, `path:<token>`). `verbose=true` adds the PDF excerpt.

Under the hood: a `bge-small-en-v1.5` embedding of the work text is cosine-matched against per-control embeddings, fused with FTS5 BM25 via Reciprocal Rank Fusion, then post-filtered.

### First-run network requirement

The first ingest after install downloads the embedding model (~130 MB) to `~/.cache/fastembed/`. Subsequent runs are offline. To pre-warm:

```bash
uv run python -c "
from fastembed import TextEmbedding
TextEmbedding('BAAI/bge-small-en-v1.5')
"
```

To skip embeddings entirely (offline first run, or for fast iteration during development):

```bash
uv run ism-mcp ingest --xlsx PATH --pdf PATH --no-embeddings
```

Without embeddings, `ism_applicable` falls back to lexical-only ranking. Results are still useful but recall on natural-language queries is lower.

### Environment variables

| Var | Values | Effect |
|---|---|---|
| `ISM_MCP_DB` | path | Override the database location. Default `~/.local/share/ism-mcp/ism.db`. |
| `ISM_MCP_EMBEDDER` | `fastembed` (default), `hash`, `none` | Force a specific embedder at server start. `hash` is test-only. `none` disables semantic retrieval. |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document ism_applicable, first-run network, env vars"
```

---

## Task 12: Final integration check and HANDOVER update

**Files:**
- Modify: `HANDOVER.md`

- [ ] **Step 1: Clean-slate real ingest**

```bash
rm -f ~/.local/share/ism-mcp/ism.db
uv run ism-mcp ingest \
    --xlsx "/home/dudley/code/wayland-remote/docs/ism/Cloud controls matrix template (March 2026).xlsx" \
    --pdf  "/home/dudley/code/wayland-remote/docs/ism/Information security manual (March 2026).pdf" \
    --revision 2026-03
```

Expected:

```
done. 1081 controls in /home/dudley/.local/share/ism-mcp/ism.db
embedding controls (first run downloads ~130 MB to ~/.cache/fastembed)...
embedded 1081 controls
```

- [ ] **Step 2: Spot-check ism_applicable against the real DB**

```bash
uv run python -c "
import os
os.environ.pop('ISM_MCP_EMBEDDER', None)
from ism_mcp import server
print(server.ism_applicable(
    work='adding session timeout and JWT refresh to our auth flow',
    classification='OFFICIAL',
    maturity='ML2',
    paths=['src/auth/jwt.py'],
    limit=5,
))
"
```

Expected: at least one of the top 5 results has `topic` containing "Session" or "Authentication", `applies['NC']` is true, `maturity['ML2']` is true, and `why` includes `semantic` and at least one `path:` token.

- [ ] **Step 3: Confirm `--no-embeddings` fallback path works**

```bash
rm -f /tmp/ism-no-embed.db
uv run ism-mcp ingest \
    --xlsx "/home/dudley/code/wayland-remote/docs/ism/Cloud controls matrix template (March 2026).xlsx" \
    --pdf  "/home/dudley/code/wayland-remote/docs/ism/Information security manual (March 2026).pdf" \
    --revision 2026-03 \
    --db /tmp/ism-no-embed.db \
    --no-embeddings

ISM_MCP_DB=/tmp/ism-no-embed.db uv run python -c "
from ism_mcp import server
import json
result = json.loads(server.ism_applicable('session timeout', limit=3))
for r in result['results']:
    assert 'semantic' not in r['why'], r['why']
print('OK: lexical-only fallback works')
"
```

Expected: `OK: lexical-only fallback works`.

- [ ] **Step 4: Run the full CI suite**

```bash
./scripts/ci.sh
```

Expected: `==> CI OK`.

- [ ] **Step 5: Run the slow suite**

```bash
./scripts/ci.sh slow
```

Expected: 2 tests pass.

- [ ] **Step 6: Update `HANDOVER.md`**

Replace the "Where we are" and "Next action" sections to reflect the new state. Use this exact prose, adjusting only the date and any deferred items list:

```markdown
## Where we are

Hardening and hybrid discovery merged. The MCP server now exposes:

- `ism_applicable(work, ...)` for ranked discovery against a free-text work description.
- `ism_list_sections`, `ism_list_classifications`, `ism_list_maturities` as enum helpers.
- The original six tools (`ism_get`, `ism_search`, etc.) unchanged.

Embeddings are generated at ingest by `bge-small-en-v1.5` via `fastembed`. The default DB at `~/.local/share/ism-mcp/ism.db` includes the `controls_embeddings` sidecar table.

The hardening foundation (pytest, ruff, pyright, `scripts/ci.sh`, per-control PDF excerpts) is in place.

## Next action

Open `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` and pick the next sub-project. The natural order is:

1. **Sub-project C: Graph and curated cuts.** `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs a brainstorm cycle before a plan is written.
2. **Sub-project D: Project coverage manifest.** `.ism-coverage.toml` in consumer repos, `ism_coverage_read/add/gaps`. Depends on the embeddings from sub-project B.
3. **Sub-project E: Consumer install helper.** `ism-mcp install --project PATH`. Depends on D's manifest format.

Each of C, D, E gets its own brainstorm and design doc before a plan is written.
```

- [ ] **Step 7: Final verification of working tree**

```bash
git status
```

Expected: `nothing to commit, working tree clean` (except for the HANDOVER edit if not yet committed).

- [ ] **Step 8: Commit HANDOVER**

```bash
git add HANDOVER.md
git commit -m "docs: update handover after hybrid discovery lands"
```

---

## Deliverables at end of plan

- `ism_applicable` tool registered, returning RRF-fused results with `why` annotations.
- Three enum helpers: `ism_list_sections`, `ism_list_classifications`, `ism_list_maturities`.
- `controls_embeddings` sidecar table populated at ingest by `fastembed` + `bge-small-en-v1.5`.
- `--no-embeddings` ingest flag and `ISM_MCP_EMBEDDER` env var for fallback control.
- 30+ new tests across `test_classification`, `test_paths`, `test_embed`, `test_retrieve`, `test_ingest_embed`, `test_server_helpers`, `test_server_applicable`, plus opt-in slow integration tests.
- `scripts/ci.sh` extended with a `slow` target. `all` stays fast.
- README documents `ism_applicable`, the first-run network requirement, and the env vars.
- HANDOVER points the next session at sub-project C.

## Self-review notes for the executing agent

- The hardening plan must land first. If `tests/conftest.py` does not yet contain the `db` and `sample_controls` fixtures, stop and run the hardening plan first.
- `importlib.resources.files("ism_mcp.data")` requires `src/ism_mcp/data/__init__.py` to exist. Task 3 creates it. If you see `ModuleNotFoundError: ism_mcp.data`, that file is missing.
- `numpy` must be a real top-level dep, not just transitive. Task 1 promotes it explicitly.
- The `ISM_MCP_EMBEDDER` env var is read on first use, then cached on the `_RUNTIME` dict. Tests must call `server._reset_runtime_cache()` in setup and teardown.
- If `fastembed` first-run network access fails, the test for the real embedder fails. That is expected and acceptable for the slow suite. Document it in HANDOVER if it happens during the final integration check.
- If pyright complains about the `Embedder` Protocol intersection with `FastEmbedEmbedder` lacking an explicit `dim` attribute at class definition time, ensure `dim` is set in `__init__`. The Protocol allows that.
- The path expander uses `tomllib` (standard library since Python 3.11) and `importlib.resources` for package-data access. No new deps.

## Next plan after this lands

Sub-project C (graph and curated cuts). Brainstorm cycle required before plan is written. Reference spec `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md`.
