# Next-Session Handover

> Last updated: 2026-05-28. Read this first when picking up the project.

## What this is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable, agent-friendly tools. The ISM PDF is ~700 pages and doesn't fit in a model context window. This server parses the official Cloud Controls Matrix XLSX into SQLite, attaches surrounding-paragraph excerpts from the PDF, and exposes six lookup tools over stdio.

## Where we are

Prototype committed and working end-to-end. 1081 controls ingested with 100% PDF excerpt coverage. Six MCP tools register and return JSON. Smoke-tested locally.

What is NOT done: no tests, no lint, no CI, no type checking, PDF excerpts are coarse (whole subsections rather than per-control).

## Repository layout

```
src/ism_mcp/
  __init__.py
  __main__.py        CLI entrypoint (ingest, serve)
  store.py           SQLite schema + queries + FTS5
  ingest.py          XLSX parser + PDF paragraph extractor
  server.py          FastMCP server with six tools
pyproject.toml       uv-managed, hatchling build
HANDOVER.md          this file
CLAUDE.md            project conventions for AI agents
README.md            install, ingest, MCP config
docs/plans/          implementation plans
```

## Verifying current state

```bash
uv sync
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
"
```

Expected output:

```
controls: 1081
topics:   444
rev:      2026-03
```

## Next action

**Execute the hardening plan at `docs/plans/2026-05-28-hardening-and-tests.md`.**

That plan tightens PDF excerpt extraction (whole subsections → per-control paragraphs), adds a pytest suite with hermetic fixtures, adds ruff + pyright, and adds a local `scripts/ci.sh`. After it lands, the proto becomes a maintainable foundation that the broader roadmap can build on.

Total scope: 9 tasks.

## Roadmap beyond plan #1

| Plan | Theme | Scope sketch |
|---|---|---|
| 1 | Hardening + tests | PDF excerpt fix, pytest, ruff, pyright, CI script. |
| 2 | Capability expansion | `ism_neighbors(id)`, `ism_essential8(level)`, `ism_export(filter, format)`. |
| 3 | Revision history | Multi-revision storage, `ism_changes_since(rev)`, diff renderer. |
| 4 | Transport polish | HTTP/SSE transport option, optional auth, packaging to PyPI. |
| 5 | Quality of life for consumers | CLAUDE.md snippet generator (`ism-mcp install --project PATH` writes the recommended MCP config and consult-this-server prompt to a project). |

These are sketches, not commitments. Re-prioritise based on which consumers (wayland-remote, others) end up depending on this.

## Decisions made in the proto

- **SQLite + FTS5** for storage. Single file, zero ops, full-text search via SQLite's built-in FTS5 extension. No external services.
- **XLSX as the catalogue source.** The PDF is for context excerpts only. The XLSX has the canonical control text in the `Description` column.
- **Database location:** `~/.local/share/ism-mcp/ism.db` by default. Override with `--db PATH` or env var `ISM_MCP_DB`.
- **Drop-and-rebuild ingest.** Each `ingest` invocation drops the schema and re-creates it. No migration logic. Ingest takes ~23s including PDF excerpts.
- **FastMCP** as the server framework (from the `mcp` Python SDK). Stdio transport.
- **`uv` for dependency management.** No `pip install` instructions in the docs. Python 3.14+.

## Known limitations to address

1. **PDF excerpts are subsection-wide.** The paragraph extractor groups by blank line in `pdfplumber`'s extracted text. PDFs do not preserve paragraph breaks reliably. Result: many controls share the same multi-paragraph excerpt. Fix in plan #1.
2. **No tests.** Adds risk to all subsequent changes. Fix in plan #1.
3. **No lint or type check.** `ruff` and `pyright` are zero-effort wins. Fix in plan #1.
4. **No CI script.** Mirror the `scripts/ci.sh` pattern from sibling projects. Fix in plan #1.
5. **Single revision in DB.** Cannot diff revisions today. Defer to plan #3.
6. **No auth on the MCP server.** Local stdio only. Document the constraint, don't fix until needed.

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
4. Open `docs/plans/2026-05-28-hardening-and-tests.md` and start executing.

Total reading time before execution: 10 minutes.
