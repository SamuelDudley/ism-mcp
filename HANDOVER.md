# Next-Session Handover

> Last updated: 2026-05-29 (post install-helper). Read this first when picking up the project.

## What this is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable, agent-friendly tools. The ISM PDF is ~700 pages and doesn't fit in a model context window. This server parses the official Cloud Controls Matrix XLSX into SQLite, attaches surrounding-paragraph excerpts from the PDF, and exposes lookup tools over stdio.

## Where we are

Sub-projects A (hardening), B (hybrid discovery), D (coverage manifest), and E (consumer install helper) are merged. The MCP server now exposes:

- `ism_applicable(work, ...)` for ranked discovery.
- `ism_coverage_read | upsert | gaps` for per-project IRAP-grade coverage tracking.
- `ism_list_sections | classifications | maturities` as enum helpers.
- The original six tools unchanged.

The CLI now has `ism-mcp install --project PATH`. It writes a project-scoped `.mcp.json`, a managed CLAUDE.md guidance block, a scaffolded `.ism-coverage.toml`, and a committed `.ism/ism.db` into a consumer repo. Modes are `uvx` (default) and `docker`. The emitted config points `ISM_MCP_DB` at `${CLAUDE_PROJECT_DIR:-.}/.ism/ism.db` so it resolves on every clone. See `docs/superpowers/specs/2026-05-29-consumer-install-helper-design.md` and the README "Adopt in a project" section.

The coverage manifest lives at `.ism-coverage.toml` in each consumer repo with a sibling `.ism-coverage/evidence/` for binaries. Schema and tool surface are documented in `docs/superpowers/specs/2026-05-28-coverage-manifest-design.md` and in the README. A starter template ships at `src/ism_mcp/data/coverage_template.toml`.

Embeddings are generated at ingest by `bge-small-en-v1.5` via `fastembed`. The default DB at `~/.local/share/ism-mcp/ism.db` includes the `controls_embeddings` sidecar table.

The hardening foundation (pytest, ruff, pyright, `scripts/ci.sh`, per-control PDF excerpts) is in place. Test suite is 135 fast tests plus 2 opt-in slow tests behind `./scripts/ci.sh slow`.

The MCP server is registered at user scope in Claude Code (`claude mcp list` shows `ism: ✓ Connected`) and is reachable from any project. `~/.claude/CLAUDE.md` carries a medium-aggression trigger that prompts Claude to reach for `mcp__ism__ism_applicable` on AU government security / ISM / Essential Eight / security-review topics.

## Repository layout

```
src/ism_mcp/
  __init__.py
  __main__.py        CLI entrypoint (ingest, serve)
  store.py           SQLite schema + queries + FTS5
  ingest.py          XLSX parser + PDF per-control excerpt extractor
  retrieve.py        cosine search + Reciprocal Rank Fusion
  embed.py           embedder protocol + fastembed and hash backends
  classification.py  classification + maturity input normalisation
  paths.py           repo-path token expansion for query enrichment
  coverage.py        coverage manifest read, validate, serialise, gaps
  server.py          FastMCP server: lookup, discovery, coverage tools
  data/              path keyword map + coverage template
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

Sub-project C is the only remaining roadmap item. Open `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` and brainstorm it.

**Sub-project C: Graph and curated cuts.** `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. A query-side extension that reuses B's embeddings for the "semantically similar" neighbours. Needs a brainstorm cycle before a plan is written.

## Roadmap

| Plan | Sub-project | Scope sketch |
|---|---|---|
| done | A: Hardening | Pytest, ruff, pyright, CI, per-control PDF excerpts. |
| done | B: Hybrid discovery | `ism_applicable`, embeddings, RRF, helpers. |
| done | D: Project coverage manifest | `.ism-coverage.toml`, `ism_coverage_read/upsert/gaps`. |
| next | C: Graph and curated cuts | `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs brainstorm. |
| done | E: Consumer install helper | `ism-mcp install --project PATH`, uvx and docker modes. |

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
- **uvx and docker install modes fetch from a git remote.** `origin` now points at a local bare repo at `file:///home/dudley/code/ism-mcp.git`, which `ism-mcp install` auto-detects. This works for deployments on this machine. It is not reachable by teammates on other machines, so a team-reachable host (GitHub or private) is still pending before the emitted configs work off-machine.

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
4. Open `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` and brainstorm sub-project C.

Branch state: `main` is the active branch and up to date. `feature/consumer-install-helper`, `feature/hardening-and-tests`, `feature/hybrid-discovery`, `feature/coverage-manifest`, and `feature/audit-fixes` were fast-forward merged and deleted. No active feature branch. `origin` points at a local bare repo at `file:///home/dudley/code/ism-mcp.git` (see known limitations).

Recent post-audit fix: `store.search` now sanitises free-text into quoted FTS5 phrases, so `ism_search` and `ism_applicable` no longer raise on metacharacters (colons, Windows paths, bare boolean operators). See `store.sanitise_fts_query`.
