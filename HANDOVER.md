# Next-Session Handover

> Last updated: 2026-07-02 (v2.0.2, Glama listing hardening). Read this first when picking up the project.

## What this is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable, agent-friendly tools. The ISM is ~700 pages and doesn't fit in a model context window. This server parses the official ASD OSCAL release of the ISM (from the ACSC `ism-oscal` git mirror) into a version-keyed SQLite database that holds the full ISM release history, then serves lookup, version-diff, and coverage tools over stdio.

## Where we are

Sub-projects A (hardening), B (hybrid discovery), D (coverage manifest), E (consumer install helper), and the multi-version OSCAL migration are landed.

The XLSX + PDF ingest is gone. Ingest now reads the OSCAL catalog from the ACSC mirror (`https://github.com/AustralianCyberSecurityCentre/ism-oscal`), cloned into a managed cache at `~/.local/share/ism-mcp/oscal`. The database holds every tagged ISM release (24 versions back to 2022) keyed by `(version, identifier)`, with an active-version pointer so existing lookup tools default to the newest release.

The MCP server exposes:

- `ism_applicable(work, ..., version?)` for ranked discovery (identifier-keyed retrieval over the active version).
- `ism_get | ism_search | ism_list_*` lookups, each with an optional `version` argument.
- `ism_versions()`, `ism_diff(from?, to?, change_types?)`, `ism_history(identifier)` for the release history and deltas.
- `ism_coverage_read | upsert | gaps | impact` for per-project coverage tracking and drift after an ISM update.
- `ism_stats()` reporting the active version and total versions.

CLI subcommands: `fetch`, `ingest` (one release), `ingest-history` (walk all tags), `update` (fetch + ingest latest), `serve`, `install`. Offline ingest uses `--oscal PATH` / `--oscal-repo PATH`.

Canonical identifiers are the OSCAL ids (`ism-1001`, `ism-principle-gov-01`). Lookup is tolerant of `ISM-1001`, bare numbers, and labels, so older `ISM-XXXX`-keyed coverage manifests still resolve. The coverage manifest gained `[scope].baseline_version` and per-entry `reviewed_against`, driving `ism_coverage_impact`.

Embeddings are `bge-small-en-v1.5` via `fastembed`, keyed by `(version, identifier)`. `ingest-history` embeds only the newest (active) version by default to keep the history walk fast; `--embed-all` embeds every version.

Test suite: 236 fast tests plus 3 opt-in slow tests behind `./scripts/ci.sh slow`. `openpyxl` and `pdfplumber` are removed; OSCAL is parsed with stdlib `json` and `fetch.py` shells out to `git`.

All tools carry MCP `ToolAnnotations` (`readOnlyHint` etc.). `ism_coverage_upsert` is the only tool that writes. Tool docstrings state read/write behaviour and how to choose between `ism_search` (keyword) and `ism_applicable` (free-text ranking). `glama.json` at the repo root names the maintainer for the Glama MCP directory listing (`https://glama.ai/mcp/servers/SamuelDudley/ism-mcp`).

## Repository layout

```
src/ism_mcp/
  __init__.py
  __main__.py        CLI: fetch, ingest, ingest-history, update, serve, install
  store.py           version-keyed SQLite schema + queries + FTS5 + version registry
  oscal.py           parse an OSCAL ISM catalog into version metadata and control rows
  fetch.py           clone/pull the ACSC ism-oscal mirror, list tags, read files at a tag
  ingest.py          orchestrate OSCAL ingest over a directory or a git-tag walk
  diff.py            catalog delta between two versions + per-control history
  retrieve.py        cosine search + Reciprocal Rank Fusion
  embed.py           embedder protocol + fastembed and hash backends
  classification.py  classification + maturity input normalisation
  paths.py           repo-path token expansion for query enrichment
  coverage.py        coverage manifest read, validate, serialise, gaps, drift (compute_impact)
  install.py         consumer-repo install writer
  server.py          FastMCP server: lookup, discovery, version, coverage tools
  data/              path keyword map + coverage template
tests/               pytest suite with hermetic fixtures
  fixtures/oscal/    mini ISM_catalog.json + 3 mini E8 catalogs
scripts/ci.sh        local CI entrypoint
scripts/prepare-public-release.sh  build the public tree (excludes HANDOVER.md and docs/)
.github/workflows/ci.yml  GitHub Actions: fmt, lint, type, test, slow suite
docs/plans/          older implementation plans
docs/superpowers/plans/   implementation plans (2026-06-04-multi-version-ism-oscal.md)
docs/superpowers/specs/   design and vision docs (2026-06-04-multi-version-ism-oscal-design.md)
pyproject.toml       uv-managed, hatchling build, ruff + pyright + pytest config
glama.json           maintainer metadata for the Glama MCP directory
LICENSE              MIT
HANDOVER.md          this file (private, excluded from the public tree)
CLAUDE.md            project conventions for AI agents
README.md            install, ingest, MCP config, dev workflow
```

## Verifying current state

```bash
uv sync
./scripts/ci.sh

# Ingest the full ISM history from the local OSCAL clone (no model download):
uv run ism-mcp ingest-history --oscal-repo /home/dudley/code/ism-oscal --no-embeddings

uv run python -c "
from ism_mcp import store, server
conn = server._conn()
print('versions:', len(store.list_versions(conn)))
print('active:  ', store.get_active_version(conn))
print('controls:', store.count_controls(conn))
"
```

Expected output (numbers grow as ASD publishes more releases):

```
versions: 24
active:   2026.03.24
controls: 1130
```

A real Dec-2025 to Mar-2026 diff via `server.ism_diff()` reports roughly: 27 added, 4 removed, 45 reworded, 11 retitled, 37 moved. `server.ism_history('ism-0714')` spans all 24 releases. CI prints `==> CI OK`. Slow suite: `./scripts/ci.sh slow`.

## Next action

`pyproject` is at `2.0.2`. Public releases `v2.0`, `v2.0.1`, and `v2.0.2` are tagged on `https://github.com/samueldudley/ism-mcp`. Publishing is now additive: the release script prints clone/rsync/commit/tag commands that stack a snapshot commit on top of the public history (no re-init, no force push). GitHub Actions on the public repo is green as of v2.0.2 (a pyright literal-type error in `tests/test_coverage_canonical.py` had CI red from v2.0.1 to v2.0.2).

One manual step is pending on the Glama directory listing (`https://glama.ai/mcp/servers/SamuelDudley/ism-mcp`): the owner must claim the server by signing into Glama with GitHub, which also triggers a re-index (their snapshot predates the version/diff/history tools).

Next development work is sub-project C (Graph and curated cuts). Open `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md` and brainstorm it. Note that `ism_diff`/`ism_history` already cover part of the "history" intent; the `--embed-all` history embeddings would let `ism_neighbors` work across versions.

## Roadmap

| Plan | Sub-project | Scope sketch |
|---|---|---|
| done | A: Hardening | Pytest, ruff, pyright, CI. |
| done | B: Hybrid discovery | `ism_applicable`, embeddings, RRF, helpers. |
| done | D: Project coverage manifest | `.ism-coverage.toml`, `ism_coverage_read/upsert/gaps`. |
| done | E: Consumer install helper | `ism-mcp install --project PATH`, uvx and docker modes. |
| done | Multi-version OSCAL | OSCAL ingest, version history, `ism_versions/diff/history`, coverage drift, dropped XLSX/PDF. |
| next | C: Graph and curated cuts | `ism_neighbors(id)`, `ism_essential8(level)`, `ism_subset(name)`. Needs brainstorm. |

Deferred (revisit when consumers ask): reworded cosine-similarity scoring in `ism_diff`, possible-rename heuristic, HTTP/SSE transport, PyPI publish, coverage gate in CI.

## Decisions made

- **OSCAL as the catalogue source.** The ACSC `ism-oscal` git mirror. Statement prose is the canonical control text. Applicability comes from per-control props; Essential Eight maturity from membership of the resolved E8 catalogs.
- **Version-keyed storage.** One SQLite file holds every release keyed by `(version, identifier)`. An `active_version` meta key drives default lookups. Deltas are computed on read (data is tiny).
- **Canonical identifier = the OSCAL id**, with tolerant input resolution. Embeddings keyed by `(version, identifier)`, retiring the old `rowid` dependency.
- **Embed the active version by default**, `--embed-all` for history.
- **SQLite + FTS5**, **FastMCP** stdio transport, **`uv`** + Python 3.14+. Database at `~/.local/share/ism-mcp/ism.db` (override with `--db` or `ISM_MCP_DB`).

## Known limitations

- **No auth on the MCP server.** Local stdio only.
- **Historical versions are not embedded by default**, so `ism_applicable(version=<older>)` falls back to lexical ranking unless the DB was built with `--embed-all`.
- **uvx and docker install modes fetch from a git remote.** Generate consumer configs against the public URL so the emitted `uvx --from git+...` entry resolves elsewhere. This development repo stays private and is not the public remote.

## Conventions

See `CLAUDE.md` for the canonical list. Highlights:

- Conventional-commit subject prefixes (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `ci:`, `refactor:`, `build:`, `perf:`).
- No `;`, no em-dash in commits, comments, docstrings, or source-tree text.
- No task / plan / PR numbers in comments, docstrings, or commit messages.
- Short factual docstrings. No history references.
- TDD by default. Failing test first, then implement.

## Quick orientation for a fresh agent

1. Read this file (you're here).
2. Read `CLAUDE.md` for working conventions.
3. Run the verification block in "Verifying current state" above.
4. Follow "Next action": brainstorm sub-project C from `docs/superpowers/specs/2026-05-28-ism-mcp-buildout-vision.md`.

Branch state: `main` is up to date with `origin` and all feature branches are merged and deleted. The public repo `samueldudley/ism-mcp` is at v2.0.2.
