# Next-Session Handover

> Last updated: 2026-05-28. Read this first when picking up the project.

## What this is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable, agent-friendly tools. The ISM PDF is ~700 pages and doesn't fit in a model context window. This server parses the official Cloud Controls Matrix XLSX into SQLite, attaches surrounding-paragraph excerpts from the PDF, and exposes six lookup tools over stdio.

## Where we are

Prototype hardened. The proto now has:

- 1081 controls ingested with 100% per-control PDF excerpt coverage (median excerpt ~194 chars, down from ~3500).
- Pytest suite with hermetic fixtures, 17 tests covering store, XLSX parser, and per-control excerpt extractor.
- Ruff and pyright configured, both clean.
- `scripts/ci.sh` as the local source of truth for fmt + lint + type + test.
- Six MCP tools register and return JSON.

The vision and the next plan are written but not yet executed:

- `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` — multi-sub-project roadmap (A→E).
- `docs/superpowers/specs/2026-05-28-ism-mcp-hybrid-discovery-design.md` — detailed design for sub-project B.
- `docs/plans/2026-05-28-hybrid-discovery.md` — 12-task executable plan for sub-project B.

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
print('rev:     ', store.get_meta(conn, 'ism_revision'))
c = store.get_control(conn, 'ISM-1781')
print('excerpt len:', len(c.pdf_excerpt or ''))
"
```

Expected output:

```
controls: 1081
topics:   444
rev:      2026-03
excerpt len: 708
```

CI should print `==> CI OK`.

## Next action

**Execute the hybrid-discovery plan at `docs/plans/2026-05-28-hybrid-discovery.md`.**

That plan adds `ism_applicable(work, classification?, maturity?, tags?, paths?)` — a hybrid retrieval tool that ranks controls relevant to a free-text work description using vector embeddings (`bge-small-en-v1.5` via `fastembed`) fused with FTS5 BM25, layered with classification, maturity, tag, and repo-path filters. 12 tasks.

Reference spec: `docs/superpowers/specs/2026-05-28-ism-mcp-hybrid-discovery-design.md`. Decisions locked in during brainstorming:

- BLOB + numpy in-memory matrix for vector storage (not sqlite-vec, not DuckDB). Reasoning in the spec.
- `fastembed` for embeddings (pure ONNX, no torch). First run downloads ~130 MB to `~/.cache/fastembed/`.
- Reciprocal Rank Fusion, k=60, normalised to [0, 1].
- Filters apply post-RRF, never pre-retrieval.
- `--no-embeddings` ingest flag falls back to lexical-only.

## Roadmap beyond the next plan

| Plan | Sub-project | Scope sketch |
|---|---|---|
| done | A: Hardening | Pytest, ruff, pyright, CI, per-control PDF excerpts. |
| next | B: Hybrid discovery | `ism_applicable`, embeddings, RRF, helpers. |
| | C: Graph and curated cuts | `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs brainstorm. |
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
5. Open `docs/plans/2026-05-28-hybrid-discovery.md` and start executing.

Branch state: `main` is the active branch. `feature/hardening-and-tests` was fast-forward merged and deleted. No remote configured.
