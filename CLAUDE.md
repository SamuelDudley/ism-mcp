# Project guidance for AI agents

Read this before doing any work in this repo. Update it when conventions change.

## What this project is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable tools. It parses the official OSCAL release of the ISM (from the ACSC `ism-oscal` git mirror) into a version-keyed SQLite database holding the full ISM release history, then serves lookup, version-diff, and coverage tools over stdio. Read `README.md` for install and usage.

## Repository layout

```
src/ism_mcp/         the package
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
  coverage.py        coverage manifest read, validate, serialise, gaps, drift
  install.py         consumer-repo install writer
  server.py          FastMCP server: lookup, discovery, version, coverage tools
  data/              path keyword map + coverage template
tests/               pytest suite with hermetic fixtures (tests/fixtures/oscal mini catalogs)
scripts/ci.sh        local CI entrypoint
pyproject.toml       uv-managed, hatchling build
README.md            user-facing install and usage
```

## Build, test, dev

```bash
uv sync                      install all deps
uv run ism-mcp ingest --fetch            ingest the latest OSCAL release
uv run ism-mcp ingest-history --fetch    ingest the full tagged ISM history
uv run ism-mcp serve         start the MCP server over stdio
uv run pytest                run tests
./scripts/ci.sh              full CI suite (fmt, lint, type, test)
```

OSCAL source: `https://github.com/AustralianCyberSecurityCentre/ism-oscal` (cloned to `~/.local/share/ism-mcp/oscal`). A local clone is at `~/code/ism-oscal` for offline ingest via `--oscal-repo`.

## Conventions

### Commits

Lead every commit subject with a conventional-commit type prefix. Subject lowercase after the colon, no trailing period, no body unless genuinely needed.

```
feat:     new user-facing or API behaviour
fix:      bug fix
chore:    tooling, scaffolding, maintenance
docs:     documentation only
test:     tests only
refactor: code reshaping without behaviour change
ci:       CI workflow / pipeline
build:    build system or dependencies
perf:     performance
```

### Code style

- No `;` and no em-dash (`—`) in commit messages, commit bodies, comments, or docstrings. Use a period or restructure.
- No task / plan / PR / issue numbers anywhere this style applies (subjects, bodies, comments, docstrings). Forbidden: "Task 15", "plan #2", "lands in Task 25", "fixes #123", "TODO(plan-3)". These become dead pointers as soon as the work is done.
- No marketing words (`comprehensive`, `robust`, `powerful`).
- No emoji unless asked.
- Default to writing no comments. Add one only when the WHY is non-obvious.

### Docstrings and comments

- Factual, no prose, no paragraphs.
- Short. A function docstring is usually one sentence. A module docstring is two or three.
- Do not carry history. No "was X, now Y", no "added for the Z flow", no version references.
- Prefer plain English over jargon.

### Python specifics

- Python 3.14+, use `from __future__ import annotations` and PEP 604 union syntax (`X | None`) in module-level type hints.
- `uv` for everything dependency-related. No `pip install` instructions in user docs.
- Standard library where it suffices (sqlite3, dataclasses, argparse). Third-party only when there is a clear gain.
- Type-annotate public APIs. Internal helpers can be looser.

## Workflow

- TDD by default. Write the failing test first, prove it fails, then implement.
- Prefer inline execution over fan-out to subagents. Subagents (when used) on Opus.

## Releasing

Deployments launch the server with `uvx --from git+<repo>@<tag> ism-mcp serve`, fetching from the public GitHub repository `https://github.com/samueldudley/ism-mcp`. That repo is a clean snapshot built by `scripts/prepare-public-release.sh`. This development repository stays private (it carries `HANDOVER.md` and `docs/`), so do not push it to the public remote.

To cut a release:

1. Land the work on `main` and run `./scripts/ci.sh`. Confirm `==> CI OK`.
2. Build and publish the public snapshot. The script prints the `git init`/commit/push and `git tag -a vX.Y` commands for the public repo.

   ```bash
   ./scripts/prepare-public-release.sh
   ```

3. Point deployments at the tag, fetching from the public URL.

   ```bash
   uv run ism-mcp install --project PATH --repo https://github.com/samueldudley/ism-mcp.git --rev vX.Y
   ```

Cut a new tag per release. Do not move an existing tag. `uvx` caches a build per ref, so a moved tag keeps serving stale code until the cache is cleared with `uvx --reinstall`.

## When to update this file

Update CLAUDE.md when:

- A new convention or workflow rule is established.
- A new top-level directory or module is added.
- Build, test, or CI commands change.
- A new artifact becomes the source of truth for something.

Keep it concise. Detailed rationale belongs in the design docs or the README.
