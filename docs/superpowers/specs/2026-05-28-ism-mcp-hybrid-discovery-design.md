# Hybrid discovery design

> Sub-project B of the ism-mcp build-out. See `2026-05-28-ism-mcp-buildout-vision.md` for context.

## Goal

Let an agent ask `ism_applicable(work_description, ...)` in plain language and get back a ranked list of ISM controls relevant to the planned or current work, with enough detail to act on without follow-up queries.

## Problem statement

The proto exposes `ism_search(query)` backed by FTS5 BM25. It works when the agent already knows the ISM's vocabulary. It fails when the agent describes work in implementation terms ("we're adding JWT refresh", "S3 bucket policy") because the ISM describes the same concepts in formal language ("session management", "cryptographic protocols for data at rest"). Recall on natural agent phrasing is poor.

## Architecture

```
work text ─► query embedder ─┐
                              ├─► numpy cosine top-50 ─┐
                              │                        │
work text ─► FTS5 BM25 top-50 ───────────────────┐     │
                                                  │     │
optional paths ─► token expander ─► extra BM25 ───┘     │
                                                        ▼
                                              RRF fusion (k=60)
                                                        │
                              optional tags/classification/maturity post-filter
                                                        │
                                              top-K results, JSON
```

Two retrievers over the same `controls` table:

- **Lexical:** the existing FTS5 index. BM25 ranking.
- **Semantic:** a sidecar `controls_embeddings(rowid, embedding BLOB)` table. Server loads the full `(N, 384) float32` matrix into memory at startup. Cosine sim = `query_vec @ M.T` (vectors are L2-normalised at ingest, so dot-product equals cosine).

Both retrievers return rowid-ranked top-50. Reciprocal Rank Fusion (`k=60`) merges them into one fused ranking. Structured filters (classification, maturity, tags) apply post-RRF. Take top-K (default 20) and emit JSON.

## Embedding model and storage

**Model:** `BAAI/bge-small-en-v1.5` via the `fastembed` library. 384-dim, ~130 MB, pure ONNX runtime wheel (no torch, no system libs). Sub-second batch embed for 1,100 controls on CPU.

**Storage:** `controls_embeddings(rowid INTEGER PRIMARY KEY REFERENCES controls(rowid) ON DELETE CASCADE, embedding BLOB NOT NULL)`. Each BLOB is 1,536 bytes (384 × float32). Whole table at 1,100 controls is ~1.7 MB. Server loads the full matrix into memory **lazily on first MCP request** (inside the existing `_conn()` helper), not at module import time, so server startup remains instant.

**What we embed (per control):**

```
f"{topic}. {section}. {description} {(pdf_excerpt or '')[:500]}"
```

Topic and section give the model coarse semantic anchors when descriptions are terse. The excerpt cap keeps the embed-time token count bounded.

**L2 normalisation at ingest** so query-time cosine collapses to `query @ M.T`.

**Model cache:** `~/.cache/fastembed/` (the library's default). First ingest downloads weights from HuggingFace; subsequent runs are offline.

**Why not sqlite-vec / DuckDB / Pinecone / Chroma:** at 1,100 documents, brute-force cosine is ~1 ms. `sqlite-vec` adds a C-extension load risk for negligible speed gain. DuckDB-VSS would mean replacing SQLite and rewriting FTS5. Pinecone / Chroma / Qdrant solve scale problems that don't exist here and split storage from the controls table.

## Tool surface

### New tool

```python
ism_applicable(
    work: str,
    classification: str | None = None,    # "NC"|"OS"|"P"|"S"|"TS" or "OFFICIAL"|"PROTECTED"|... case-insensitive
    maturity: str | None = None,          # "ML1"|"ML2"|"ML3" or "1"|"2"|"3"
    tags: list[str] | None = None,        # validated against ism_list_sections()
    paths: list[str] | None = None,       # repo paths the work touches
    limit: int = 20,
    verbose: bool = False,
) -> str
```

Returns JSON:

```json
{
  "query": "adding JWT refresh for our session API",
  "filters": {
    "classification": "OFFICIAL",
    "maturity": "ML2",
    "tags": [],
    "paths": ["src/auth/jwt.py"]
  },
  "count": 7,
  "candidates_before_filter": 12,
  "results": [
    {
      "identifier": "ISM-1781",
      "topic": "Session management",
      "section": "Authentication",
      "description": "Sessions are terminated after fifteen minutes of inactivity.",
      "applies": {"NC": true, "OS": true, "P": true, "S": false, "TS": false},
      "maturity": {"ML1": true, "ML2": true, "ML3": true},
      "score": 1.0,
      "why": ["semantic", "lexical:session", "path:jwt"]
    }
  ]
}
```

`candidates_before_filter` is always present so the agent can see how aggressive its filters were.

With `verbose=true`, each result also includes `pdf_excerpt` and `pdf_page`.

`score` is the **normalised** RRF score, ranged `[0.0, 1.0]`. Raw RRF (`sum 1/(k+rank)` across retrievers, `k=60`) is divided by its theoretical max `2/(k+1) ≈ 0.0328` so that a result topping both retrievers reads `1.0` and a result topping only one reads `~0.5`. Not a probability — purely a ranking signal. Documented as such in the tool docstring.

`why` is a short list of labels indicating which signals contributed:

- `"semantic"` — appeared in the vector retriever's top-50.
- `"lexical:<term>"` — matched FTS5 on this term.
- `"path:<token>"` — the path expander contributed this token to the lexical query.
- `"tag:<section>"` — passed the tag filter.

### New helper tools

| Tool | Purpose |
|---|---|
| `ism_list_sections()` | Distinct `section` values, the vocabulary for `tags`. |
| `ism_list_classifications()` | Returns the allowed classification enum (canonical and friendly forms). |
| `ism_list_maturities()` | Returns `["ML1", "ML2", "ML3"]`. |

### Existing tools

Unchanged. `ism_search` stays as the deterministic lexical-only path for "I know the exact term I want to grep for". The README will recommend `ism_applicable` as the default discovery tool.

## Filtering and layering

**Classification.** Normalised in one helper:

| Input (case-insensitive) | Normalised |
|---|---|
| `NC`, `OFFICIAL`, `non-classified` | `NC` |
| `OS`, `OFFICIAL:Sensitive`, `OFFICIAL-Sensitive` | `OS` |
| `P`, `PROTECTED` | `P` |
| `S`, `SECRET` | `S` |
| `TS`, `TOP_SECRET`, `TOP SECRET` | `TS` |

Bad input returns a structured error in the JSON, not an exception. Filter is post-retrieval `applies_<cls> = 1`.

**Maturity.** `ML1` / `1` / `"1"` all accepted. Filter `maturity_ml<n> = 1`.

**Tags.** Drawn from the `section` column (~15 values like "Cryptography", "Authentication", "Event logging"). Validated against `ism_list_sections()`. Unknown tag returns a structured error. Filter is post-retrieval `section IN (...)`.

**Paths.** Each path is tokenised on `/_.-`, lowercased. Tokens look up into `src/ism_mcp/path_keywords.toml`:

```toml
auth      = "authentication session token credential"
jwt       = "session token authentication"
session   = "session timeout authentication"
log       = "logging event audit"
audit     = "logging event audit"
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
rbac      = "access control authorisation role"
acl       = "access control authorisation"
permission= "access control authorisation"
sso       = "single-sign-on identity authentication"
saml      = "single-sign-on identity"
oauth     = "authentication token"
mfa       = "multi-factor authentication"
2fa       = "multi-factor authentication"
patch     = "patching vulnerability update"
update    = "patching update"
monitor   = "monitoring telemetry"
metric    = "monitoring telemetry"
trace     = "monitoring telemetry"
deploy    = "deployment configuration"
ci        = "build pipeline integrity"
pipeline  = "build pipeline integrity"
docker    = "container image"
k8s       = "container orchestration"
container = "container image"
```

Matched expansions are joined with spaces and appended to the BM25 query. They do not alter the semantic query — that stays as the verbatim `work` text. A result surfaced because of a path token gets `path:<token>` in `why`.

**Filter ordering.** Filters apply **after** RRF, never before retrieval. Both retrievers return top-50 unfiltered; RRF fuses; post-filter masks; trim to `limit`. Rationale: at this corpus size we can afford over-fetch, and pre-filtering would risk discarding strong semantic matches whose classification bits are coarse.

**Empty result handling.** `candidates_before_filter` is always present in the response. If post-filter wipes everything, the JSON additionally includes `"hint": "filters eliminated N candidates; relax classification/tags/maturity?"`.

## Ingest changes

New step after PDF excerpt attach, before `set_meta`:

```python
def embed_controls(controls: list[Control], embedder: Embedder) -> Iterator[tuple[int, bytes]]:
    """Yield (rowid, normalised float32 BLOB) for each control."""
    texts = [
        f"{c.topic}. {c.section}. {c.description} {(c.pdf_excerpt or '')[:500]}"
        for c in controls
    ]
    vectors = embedder.embed(texts)                          # (N, 384) float32
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
    for rowid, vec in enumerate(vectors, start=1):
        yield rowid, vec.tobytes()
```

Schema addition (lives in `store.SCHEMA`):

```sql
CREATE TABLE IF NOT EXISTS controls_embeddings (
    rowid     INTEGER PRIMARY KEY REFERENCES controls(rowid) ON DELETE CASCADE,
    embedding BLOB NOT NULL
);
```

Drop-and-rebuild ingest unchanged in shape, but `store.reset()` is extended to drop `controls_embeddings` alongside the existing `controls`, `controls_fts`, and `meta` tables. Cascade-delete only covers row-level deletes, not `DROP TABLE`.

**Embedder abstraction:**

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...   # (N, 384) float32

class FastEmbedEmbedder:
    """Default. Wraps fastembed.TextEmbedding('BAAI/bge-small-en-v1.5')."""

class DeterministicHashEmbedder:
    """Tests. Hashes each text to a deterministic 384-vec, L2-normalised."""
```

**CLI flag:** `ism-mcp ingest ... --no-embeddings` skips the embedder. Server detects an empty `controls_embeddings` table at startup and falls back to lexical-only with a warning. Useful for fast iteration and air-gapped first runs.

**Environment variable:** `ISM_MCP_EMBEDDER=fastembed|hash|none`. Default `fastembed`. Tests set `hash`. `none` forces lexical-only at query time even if embeddings exist.

**Time and space cost:**

| Phase | Cost |
|---|---|
| First-run model download | ~130 MB to `~/.cache/fastembed/` |
| Embed 1,100 controls | ~5 s first run, ~3 s steady-state |
| Sidecar table size | ~1.7 MB |
| Memory at server start | ~1.7 MB matrix + rowid array |
| Per-query cost | embed ~30 ms + cosine ~1 ms + FTS5 ~5 ms + RRF/filter ~1 ms |

## Module layout

```
src/ism_mcp/
  __init__.py
  __main__.py            CLI: ingest (with --no-embeddings flag), serve
  store.py               schema (now includes controls_embeddings), CRUD, FTS5 search
  ingest.py              XLSX + PDF + embed pipeline
  embed.py               Embedder Protocol, FastEmbedEmbedder, DeterministicHashEmbedder
  retrieve.py            VectorIndex (in-memory numpy), search_vec(), rrf()
  classification.py      normalise_classification() and normalise_maturity()
  paths.py               expand_paths() + path_keywords.toml loader
  subsets.py             (placeholder for sub-project C; left empty here)
  server.py              FastMCP server, all tools including ism_applicable
  data/
    path_keywords.toml
tests/
  conftest.py            db fixture, sample_controls fixture, synthetic_db fixture
  test_store.py          (from Plan #1)
  test_excerpt_extraction.py    (from Plan #1)
  test_ingest_xlsx.py    (from Plan #1)
  test_embed.py          DeterministicHashEmbedder properties
  test_retrieve.py       VectorIndex, RRF unit tests
  test_classification.py normalisation tables
  test_paths.py          path expander tests
  test_server_applicable.py    ism_applicable end-to-end with hash embedder
  test_real_embedder.py  @pytest.mark.slow, opt-in, runs once locally
```

## Testing strategy

Builds on Plan #1's pytest scaffolding.

**Unit tests, no network, no model download:**

| Module | Tests |
|---|---|
| `embed` | `DeterministicHashEmbedder` is L2-normalised, deterministic, returns shape `(N, 384)`. |
| `retrieve` (RRF) | Two ranked lists fuse to expected order; missing items get rank ∞; `k=60` default; deterministic tie-breaking. |
| `retrieve` (VectorIndex) | Insert 3 synthetic vectors, query with a known-close vector, assert ranking; empty index returns `[]`. |
| `paths` | `expand_paths(["src/auth/jwt.py"])` → `{"authentication", "session", "token", "credential"}`; unknown tokens drop silently; case-insensitive. |
| `classification` | Normalisation table; bad input raises `ValueError`. |
| `server.ism_applicable` | End-to-end with `DeterministicHashEmbedder` and 3 fixture controls: returns expected ranking; classification filter prunes correctly; empty-after-filter returns `hint`; unknown tag returns structured error. |

**Integration test, opt-in:** `tests/test_real_embedder.py` marked `@pytest.mark.slow`, skipped by default. This sub-project extends `scripts/ci.sh` from Plan #1 with a new `slow` target (`./scripts/ci.sh slow` runs `uv run pytest -m slow`). The `all` target stays fast (does not include `slow`). The slow test confirms the real `FastEmbedEmbedder` loads, vectors are 384-dim L2-normalised, and the query "session timeout" puts session-management controls in the top 5.

**Coverage target:** ≥85% on new modules. No CI gate yet; the script prints the report.

## Failure modes and fallbacks

| Failure | Behaviour |
|---|---|
| `fastembed` model download fails on first ingest | Ingest exits non-zero with a clear message recommending `--no-embeddings` or pre-warming the cache. |
| `controls_embeddings` is empty at server start | Log a one-line warning, set semantic retriever to no-op, `ism_applicable` runs lexical-only, `score` in results comes from BM25 normalisation, `why` never includes `semantic`. |
| `ISM_MCP_EMBEDDER=none` set | Same as empty-table behaviour, forced. |
| Classification / maturity / tag input invalid | JSON response includes `"error"` with the offending field. No exception across the MCP boundary. |
| All post-filter results empty | `"hint"` plus `candidates_before_filter` count. |

## Risks

1. **First-run network requirement for `fastembed`.** Mitigations: `--no-embeddings` flag; documented pre-warm command; future-work note for shipping a pre-computed embeddings sidecar.
2. **Model is English-only.** ISM is English; flagged in README for downstream consumers.
3. **Path-keyword map is hand-curated and will drift.** Kept small (~50 entries) in `path_keywords.toml`, easy to extend, tests guard the loader rather than the contents.
4. **RRF score is not a probability.** Tool docstring and README say so explicitly.
5. **Section vocabulary can change across ISM revisions.** `ism_list_sections()` is the source of truth at query time; never hardcoded.
6. **Embedder model swap requires full re-embed.** `Embedder` Protocol keeps the swap clean; ingest already drops and rebuilds.

## Deferred

| Item | Why deferred |
|---|---|
| Query-side embedding LRU cache | Marginal at ~30 ms embed; revisit after telemetry. |
| Pre-computed embeddings sidecar for air-gapped installs | Wait until someone asks. |
| Re-ranker stage (cross-encoder over top-K) | Adds torch dependency; would need Docker variant. Defer until quality measurements show a gap. |
| Per-result `confidence` calibration | RRF scores aren't probabilities. Calibration would need labelled data. |

## Dependencies

- Sub-project A (hardening) must land first.
- New top-level deps: `fastembed`, `numpy` (numpy was transitive; promote to explicit).
- No OS-level deps. No Docker required.

## Acceptance

This sub-project is done when:

- `ism_applicable("adding session timeout to our auth flow", classification="OFFICIAL", maturity="ML2")` returns ISM-1781 and related session-management controls in the top 10 against the real ingested DB.
- The full test suite passes (unit + the new modules) under `./scripts/ci.sh`.
- A new ingest run with `--no-embeddings` followed by `ism_applicable` succeeds with lexical-only ranking and the `why` field never claims `semantic`.
- README documents `ism_applicable`, the `ISM_MCP_EMBEDDER` env var, the first-run network requirement, and the recommendation to prefer `ism_applicable` over `ism_search`.
