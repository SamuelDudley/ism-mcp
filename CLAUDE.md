# Project guidance for AI agents

Read this before doing any work in this repo. Update it when conventions change.

## What this project is

`ism-mcp` is a local MCP server that exposes the ASD Information Security Manual as queryable tools. It parses the Cloud Controls Matrix XLSX and the ISM PDF into a SQLite database, then serves lookup tools (`ism_get`, `ism_search`, etc.) over stdio. Read `README.md` for install and usage, and `HANDOVER.md` for current state and next planned work.

## Repository layout

```
src/ism_mcp/         the package
  __init__.py
  __main__.py        CLI: ingest, serve, install
  store.py           SQLite schema + queries + FTS5
  ingest.py          XLSX parser + PDF per-control excerpt extractor
  retrieve.py        cosine search + Reciprocal Rank Fusion
  embed.py           embedder protocol + fastembed and hash backends
  classification.py  classification + maturity input normalisation
  paths.py           repo-path token expansion for query enrichment
  coverage.py        coverage manifest read, validate, serialise, gaps
  install.py         consumer-repo install writer
  server.py          FastMCP server: lookup, discovery, coverage tools
  data/              path keyword map + coverage template
tests/               pytest suite with hermetic fixtures
docs/plans/              older implementation plans
docs/superpowers/plans/  implementation plans
docs/superpowers/specs/  design and vision docs
scripts/ci.sh        local CI entrypoint
pyproject.toml       uv-managed, hatchling build
HANDOVER.md          session-to-session handover
README.md            user-facing install and usage
```

## Build, test, dev

```bash
uv sync                      install all deps
uv run ism-mcp ingest --xlsx PATH [--pdf PATH] [--revision LABEL]
uv run ism-mcp serve         start the MCP server over stdio
uv run pytest                run tests
./scripts/ci.sh              full CI suite (fmt, lint, type, test)
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

### Closing a development branch

When a plan is complete and its branch is about to land on `main`, run this checklist in order. **`HANDOVER.md` MUST be current before a new session can start work.** A stale handover sends the next agent down the wrong path or makes them redo decisions.

1. Run `./scripts/ci.sh` on the feature branch. Confirm `==> CI OK`.
2. Rebase the feature branch onto current `main` (planning artifacts that landed on `main` mid-flight come along).
3. Fast-forward merge into `main` (`git merge --ff-only <branch>`).
4. Run `./scripts/ci.sh` on `main`. Confirm `==> CI OK`.
5. Push `main` to `origin`.
6. Delete the merged feature branch (`git branch -d <branch>`).
7. **Update `HANDOVER.md`** so it reflects:
   - Plans completed in this round (mark DONE in the roadmap table).
   - The next plan's exact file path under "Next action", with one-line description of scope.
   - Decisions locked in for the next plan (so the next agent does not re-litigate them).
   - Current branch state (`main` is up to date, feature branch deleted).
   - Any deferred items or known gaps that affect the next plan.
   - Quick-orientation steps point at the next plan, not the one just finished.
8. Commit and push the HANDOVER update.
9. **Fact-check and update `CLAUDE.md`.** Read it against the code that just landed and fix anything stale: the repository layout and module list, the CLI subcommands and tool inventory named in prose, the build and test commands, and any new convention or source-of-truth artifact this round introduced. Commit and push if it changed.
10. Working tree clean. Done.

If you cannot complete step 7 (the writing agent does not have enough context, or the next plan has not been written yet), say so explicitly. Do not leave a stale handover claiming the project is in a state it is not.

## Releasing

Deployments launch the server with `uvx --from git+<origin>@<tag> ism-mcp serve`, so a release is a tagged revision pushed to `origin`. `origin` is a bare repo at `file:///home/dudley/code/ism-mcp.git`. It serves deployments on this machine. A team-reachable host (GitHub or private) is still pending before off-machine consumers can fetch.

To cut a release:

1. Land the work on `main` and run `./scripts/ci.sh`. Confirm `==> CI OK`.
2. Tag an annotated version and push `main` with the tag.

   ```bash
   git tag -a v2 -m "ism-mcp v2 <one-line scope>"
   git push origin main v2
   ```

3. Point deployments at the tag. With the install helper, pass the tag as the revision.

   ```bash
   uv run ism-mcp install --project PATH --rev v2
   ```

   For a hand-managed registration, set `@v2` in the `uvx --from git+<origin>@v2` args, then reconnect the MCP client.

Cut a new tag per release. Do not move an existing tag. `uvx` caches a build per ref, so a moved tag keeps serving stale code until the cache is cleared with `uvx --reinstall`.

## When to update this file

Update CLAUDE.md when:

- A new convention or workflow rule is established.
- A new top-level directory or module is added.
- Build, test, or CI commands change.
- A new artifact becomes the source of truth for something.

Keep it concise. Detailed rationale belongs in the design docs or the README.
