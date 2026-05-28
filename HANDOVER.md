# Next-Session Handover

> Last updated: 2026-05-28. Read this first when picking up the project.

## What this is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable, agent-friendly tools. The ISM PDF is ~700 pages and doesn't fit in a model context window. This server parses the official Cloud Controls Matrix XLSX into SQLite, attaches surrounding-paragraph excerpts from the PDF, and exposes lookup tools over stdio.

## Where we are

Sub-projects A (hardening) and B (hybrid discovery) are merged. Sub-project D (coverage manifest) is **designed and planned but not yet executed**.

The MCP server currently exposes:

- `ism_applicable(work, ...)` for ranked discovery against a free-text work description.
- `ism_list_sections`, `ism_list_classifications`, `ism_list_maturities` as enum helpers.
- The original six tools (`ism_get`, `ism_search`, etc.) unchanged.

Embeddings are generated at ingest by `bge-small-en-v1.5` via `fastembed`. The default DB at `~/.local/share/ism-mcp/ism.db` includes the `controls_embeddings` sidecar table.

The hardening foundation (pytest, ruff, pyright, `scripts/ci.sh`, per-control PDF excerpts) is in place. Test suite is 78 fast tests plus 2 opt-in slow tests behind `./scripts/ci.sh slow`.

The MCP server is registered at user scope in Claude Code (`claude mcp list` shows `ism: ✓ Connected`) and is reachable from any project. `~/.claude/CLAUDE.md` carries a medium-aggression trigger that prompts Claude to reach for `mcp__ism__ism_applicable` on AU government security / ISM / Essential Eight / security-review topics.

Sub-project D artefacts already on `main`:

- `docs/superpowers/specs/2026-05-28-coverage-manifest-design.md` — full design spec.
- `docs/plans/2026-05-28-coverage-manifest.md` — 13-task executable plan.

The plan is approved and ready. Execution paused at the user's request before Task 1.

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

**Execute the coverage-manifest plan at `docs/plans/2026-05-28-coverage-manifest.md`.**

The plan adds `.ism-coverage.toml` and three MCP tools (`ism_coverage_read`, `ism_coverage_upsert`, `ism_coverage_gaps`) for per-project IRAP-grade coverage tracking. 13 tasks, no new top-level dependencies. Reference spec at `docs/superpowers/specs/2026-05-28-coverage-manifest-design.md`.

Decisions locked in during brainstorming:

- Primary use case: audit evidence (IRAP), secondary gap detection.
- Manifest lives at `.ism-coverage.toml` in the consumer repo root, with recommended binary evidence at `.ism-coverage/evidence/`.
- Top-level `[scope]` declaration (classification + maturity + optional sections). Sparse per-control entries. Agent proactively flags gaps via `ism_coverage_gaps`.
- Four statuses: `covered | partial | not-applicable | deferred`. Uncurated (no entry) is also a gap.
- Typed evidence arrays: `files`, `commits` as strings; `urls` and `attachments` as structured `{url|path, description}` because they're opaque to the agent and to offline auditors.
- `tomllib` for read, hand-rolled serialiser for write. No `tomli_w` dep.
- Lean 3-tool surface: read, upsert, gaps. Writes are direct (atomic via tempfile + os.replace); git review on the manifest is the audit guardrail.

After D lands, the next pick is either C (graph and curated cuts) or E (consumer install helper). Both need their own brainstorm cycles.

## Roadmap

| Plan | Sub-project | Scope sketch |
|---|---|---|
| done | A: Hardening | Pytest, ruff, pyright, CI, per-control PDF excerpts. |
| done | B: Hybrid discovery | `ism_applicable`, embeddings, RRF, helpers. |
| next | D: Project coverage manifest | `.ism-coverage.toml`, `ism_coverage_read/upsert/gaps`. Designed and planned, ready to execute. |
| | C: Graph and curated cuts | `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs brainstorm. |
| | E: Consumer install helper | `ism-mcp install --project PATH`. Needs brainstorm. Unblocked by D landing. |

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
4. Read `docs/superpowers/specs/2026-05-28-coverage-manifest-design.md` for sub-project D context.
5. Open `docs/plans/2026-05-28-coverage-manifest.md` and start executing from Task 1.

Branch state: `main` is the active branch. `feature/hardening-and-tests` and `feature/hybrid-discovery` were fast-forward merged and deleted. No active feature branch for sub-project D yet. No remote configured.
