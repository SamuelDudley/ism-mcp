# Next-Session Handover

> Last updated: 2026-05-28. Read this first when picking up the project.

## What this is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable, agent-friendly tools. The ISM PDF is ~700 pages and doesn't fit in a model context window. This server parses the official Cloud Controls Matrix XLSX into SQLite, attaches surrounding-paragraph excerpts from the PDF, and exposes lookup tools over stdio.

## Where we are

Hardening and hybrid discovery merged. The MCP server now exposes:

- `ism_applicable(work, ...)` for ranked discovery against a free-text work description.
- `ism_list_sections`, `ism_list_classifications`, `ism_list_maturities` as enum helpers.
- The original six tools (`ism_get`, `ism_search`, etc.) unchanged.

Embeddings are generated at ingest by `bge-small-en-v1.5` via `fastembed`. The default DB at `~/.local/share/ism-mcp/ism.db` includes the `controls_embeddings` sidecar table.

The hardening foundation (pytest, ruff, pyright, `scripts/ci.sh`, per-control PDF excerpts) is in place. Test suite is now 78 fast tests plus 2 opt-in slow tests behind `./scripts/ci.sh slow`.

## Repository layout

```
src/ism_mcp/
  __init__.py
  __main__.py        CLI entrypoint (ingest, serve)
  store.py           SQLite schema + queries + FTS5
  ingest.py          XLSX parser + PDF per-control excerpt extractor
  server.py          FastMCP server with six tools
tests/               pytest suite with hermetic fixtures
scripts/ci.sh        local CI entrypoint
docs/plans/          implementation plans
docs/superpowers/specs/   spec and vision docs
pyproject.toml       uv-managed, hatchling build, ruff + pyright + pytest config
HANDOVER.md          this file
CLAUDE.md            project conventions for AI agents
README.md            install, ingest, MCP config, dev workflow
```

## Verifying current state

```bash
uv sync
./scripts/ci.sh
uv run ism-mcp ingest \
    --xlsx "/home/dudley/code/wayland-remote/docs/ism/Cloud controls matrix template (March 2026).xlsx" \
    --pdf  "/home/dudley/code/wayland-remote/docs/ism/Information security manual (March 2026).pdf" \
    --revision 2026-03

uv run python -c "
from ism_mcp import store, server
conn = store.open_db(server.DEFAULT_DB)
print('controls:', store.count_controls(conn))
print('topics:  ', len(store.list_topics(conn)))
print('sections:', len(store.list_sections(conn)))
print('rev:     ', store.get_meta(conn, 'ism_revision'))
c = store.get_control(conn, 'ISM-1781')
print('excerpt len:', len(c.pdf_excerpt or ''))
_matrix, ids = store.load_embedding_matrix(conn, dim=384)
print('embeddings:', len(ids))
"
```

Expected output:

```
controls: 1081
topics:   444
sections: 69
rev:      2026-03
excerpt len: 708
embeddings: 1081
```

CI should print `==> CI OK`. Slow suite: `./scripts/ci.sh slow`.

## Next action

Open `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` and pick the next sub-project. The natural order is:

1. **Sub-project C: Graph and curated cuts.** `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs a brainstorm cycle before a plan is written.
2. **Sub-project D: Project coverage manifest.** `.ism-coverage.toml` in consumer repos, `ism_coverage_read/add/gaps`. Depends on the embeddings from sub-project B.
3. **Sub-project E: Consumer install helper.** `ism-mcp install --project PATH`. Depends on D's manifest format.

Each of C, D, E gets its own brainstorm and design doc before a plan is written.

## Roadmap

| Plan | Sub-project | Scope sketch |
|---|---|---|
| done | A: Hardening | Pytest, ruff, pyright, CI, per-control PDF excerpts. |
| done | B: Hybrid discovery | `ism_applicable`, embeddings, RRF, helpers. |
| next | C: Graph and curated cuts | `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs brainstorm. |
| | D: Project coverage manifest | `.ism-coverage.toml`, `ism_coverage_read/add/gaps`. Depends on B. |
| | E: Consumer install helper | `ism-mcp install --project PATH`. Depends on D. |

Deferred (revisit when consumers ask): revision diff, HTTP/SSE transport, PyPI publish, coverage gate in CI.

## Decisions made in the proto

- **SQLite + FTS5** for storage. Single file, zero ops.
- **XLSX as the catalogue source.** The PDF is for context excerpts only. XLSX `Description` is canonical.
- **Database location:** `~/.local/share/ism-mcp/ism.db` by default. Override with `--db PATH` or env var `ISM_MCP_DB`.
- **Drop-and-rebuild ingest.** No migration logic.
- **FastMCP** as the server framework. Stdio transport.
- **`uv` for dependency management.** Python 3.14+.

## Known limitations

- **No incremental updates.** Each ingest drops and rebuilds the database.
- **Single-revision database.** No history across ISM revisions. Defer to plan #3.
- **No auth on the MCP server.** Local stdio only.

## Conventions

See `CLAUDE.md` for the canonical list. Highlights:

- Conventional-commit subject prefixes (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `ci:`, `refactor:`, `build:`, `perf:`).
- No `;`, no em-dash (`—`) in commits, comments, docstrings, or source-tree text.
- No task / plan / PR numbers in comments, docstrings, or commit messages.
- Short factual docstrings. No history references.
- TDD by default. Failing test first, then implement.
- Prefer inline execution over subagent fan-out. Subagents (when used) on Opus.

## Quick orientation for a fresh agent

1. Read this file (you're here).
2. Read `CLAUDE.md` for working conventions.
3. Run the verification block in the "Verifying current state" section above.
4. Read `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` for the multi-sub-project context.
5. Brainstorm sub-project C, then write a plan under `docs/plans/`.

Branch state: `main` is the active branch. `feature/hardening-and-tests` and `feature/hybrid-discovery` were fast-forward merged and deleted. No remote configured.
