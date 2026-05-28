# ism-mcp

Agent-friendly query layer over the ASD Information Security Manual, served via MCP.

The ISM PDF is ~700 pages and does not fit in a model context window. This MCP server parses the official Cloud Controls Matrix XLSX into a local SQLite database, attaches surrounding-paragraph excerpts from the ISM PDF, and exposes a small set of typed lookup tools so that an agent (Claude Code, Codex, Cursor, etc.) can interrogate the ISM without re-reading the source documents.

## Status

Prototype. Single-tenant local SQLite, stdio-transport MCP server, no auth.

## Install

Requires `uv` and Python 3.14+.

```bash
git clone <repo-url> ism-mcp
cd ism-mcp
uv sync
```

## Ingest the ISM

Download the latest:

- Cloud controls matrix template (XLSX): https://www.cyber.gov.au/resources-business-and-government/essential-cyber-security/ism
- Information security manual (PDF): same page

Then ingest:

```bash
uv run ism-mcp ingest \
    --xlsx "Cloud controls matrix template (March 2026).xlsx" \
    --pdf  "Information security manual (March 2026).pdf" \
    --revision 2026-03
```

The database lands at `~/.local/share/ism-mcp/ism.db` by default. Override with `--db PATH`.

Re-run with a new XLSX / PDF on each quarterly revision. The ingester drops and recreates the schema, so there is no migration to worry about.

## Use as a Claude Code MCP server

Add to your Claude Code MCP configuration:

```json
{
  "mcpServers": {
    "ism": {
      "command": "uv",
      "args": ["--project", "/path/to/ism-mcp", "run", "ism-mcp", "serve"]
    }
  }
}
```

Restart Claude Code. The tools `ism_get`, `ism_search`, `ism_list_by_classification`, `ism_list_by_topic`, `ism_list_topics`, and `ism_stats` become available.

## Use programmatically

```python
from ism_mcp import store, server

conn = store.open_db(server.DEFAULT_DB)
c = store.get_control(conn, "ISM-1781")
print(c.description)

for r in store.search(conn, "session timeout", limit=5):
    print(r.identifier, r.topic)
```

## Development

```bash
uv sync                    install all deps including dev
uv run pytest              run the test suite
./scripts/ci.sh            full CI suite (fmt + lint + type + test)
./scripts/ci.sh test       single stage
```

The CI script is the source of truth for what counts as a passing build. Run it before pushing.

## MCP tools

| Tool | Purpose |
|---|---|
| `ism_applicable(work, classification?, maturity?, tags?, paths?, limit?, verbose?)` | Hybrid retrieval: rank controls relevant to a free-text description of planned or current work. Recommended default for discovery. |
| `ism_get(identifier)` | Full record for one control by ID. |
| `ism_search(query, limit=10)` | Deterministic FTS5 search. Use when you know the exact term. |
| `ism_list_by_classification(classification)` | Controls applicable at NC / OS / P / S / TS. |
| `ism_list_topics()` | Distinct topic strings. |
| `ism_list_by_topic(topic)` | Controls under a topic. |
| `ism_list_sections()` | Distinct section strings. The vocabulary for the `tags` filter on `ism_applicable`. |
| `ism_list_classifications()` | Canonical classification enum plus friendly aliases. |
| `ism_list_maturities()` | Essential Eight maturity levels. |
| `ism_stats()` | Database statistics. |
| `ism_coverage_read(project_path?, status_filter?)` | Read the project's `.ism-coverage.toml` manifest, including scope, summary counts, and curated entries. |
| `ism_coverage_upsert(identifier, status, how_met, ...)` | Create or update one entry with evidence (files, commits, urls, attachments). Validates against the ISM DB and the project filesystem. |
| `ism_coverage_gaps(work?, limit?)` | Return outstanding in-scope controls. With `work`, ranks by `ism_applicable` relevance and intersects with the manifest. |

Each `Control` record carries: `identifier`, `guideline`, `section`, `topic`, `revision`, `updated`, `description`, classification applicability (`NC/OS/P/S/TS`), maturity applicability (`ML1/ML2/ML3`), `pdf_excerpt`, `pdf_page`.

## Discovery for agents

The headline use case is `ism_applicable`. The agent describes the work in plain language, optionally narrows by classification, maturity, section tags, or repo paths, and gets back a ranked list of relevant controls.

```python
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

## Architecture

```
ism-mcp/
  src/ism_mcp/
    store.py     SQLite schema + queries, FTS5 over description/topic/section/guideline
    ingest.py    XLSX parser (openpyxl) + PDF paragraph extractor (pdfplumber)
    server.py    FastMCP server, six tools, JSON responses
    __main__.py  CLI: `ingest` and `serve` subcommands
  pyproject.toml uv-managed, hatchling build
```

Single SQLite file. One table for controls plus an FTS5 virtual table kept in sync via an `AFTER INSERT` trigger. A `meta` table records the ingested revision and source paths for `ism_stats`.

## Known limitations

- **No incremental updates.** Each ingest drops and rebuilds the database.
- **Single-revision database.** No history across ISM revisions. To diff two revisions, ingest into two database paths and diff externally.
- **No auth on the MCP server.** Suitable for local use only.

## Licence

TBD.
