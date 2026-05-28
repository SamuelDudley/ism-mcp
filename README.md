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
| `ism_get(identifier)` | Full record for one control by ID. |
| `ism_search(query, limit=10)` | Full-text search over description, topic, section, guideline. |
| `ism_list_by_classification(classification)` | Filter to controls applicable at NC / OS / P / S / TS. |
| `ism_list_topics()` | All distinct topic strings (~440). |
| `ism_list_by_topic(topic)` | Controls under a specific topic (exact match). |
| `ism_stats()` | Total control count, ingested revision, source paths. |

Each `Control` record carries: `identifier`, `guideline`, `section`, `topic`, `revision`, `updated`, `description`, classification applicability (`NC/OS/P/S/TS`), maturity applicability (`ML1/ML2/ML3`), `pdf_excerpt`, `pdf_page`.

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
