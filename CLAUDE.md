# Project guidance for AI agents

Read this before doing any work in this repo. Update it when conventions change.

## What this project is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable tools. It parses the Cloud Controls Matrix XLSX and the ISM PDF into a SQLite database, then serves lookup tools (`ism_get`, `ism_search`, etc.) over stdio. Read `README.md` for install and usage, and `HANDOVER.md` for current state and next planned work.

## Repository layout

```
src/ism_mcp/         the package
  store.py           SQLite schema + queries + FTS5
  ingest.py          XLSX parser + PDF paragraph extractor
  server.py          FastMCP server, six tools
  __main__.py        CLI: ingest, serve
tests/               pytest suite (added in plan #1)
docs/plans/          implementation plans
scripts/             local CI and helper scripts (added in plan #1)
pyproject.toml       uv-managed, hatchling build
HANDOVER.md          session-to-session handover
README.md            user-facing install and usage
```

## Build, test, dev

```bash
uv sync                      install all deps
uv run ism-mcp ingest --xlsx PATH [--pdf PATH] [--revision LABEL]
uv run ism-mcp serve         start the MCP server over stdio
uv run pytest                run tests (after plan #1)
./scripts/ci.sh              full CI suite (after plan #1)
```

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
- Plans under `docs/plans/` are executable: each task is self-contained with full code and verification steps.
- Prefer inline execution over fan-out to subagents. Subagents (when used) on Opus.
- Keep `HANDOVER.md` current at the end of any substantive session.

## When to update this file

Update CLAUDE.md when:

- A new convention or workflow rule is established.
- A new top-level directory or module is added.
- Build, test, or CI commands change.
- A new artifact becomes the source of truth for something.

Keep it concise. Detailed rationale belongs in the design docs or the README.
