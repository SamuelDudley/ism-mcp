# ism-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/samueldudley/ism-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/samueldudley/ism-mcp/actions/workflows/ci.yml)

Agent-friendly query layer over the ASD Information Security Manual, served via MCP.

The ISM is ~700 pages and does not fit in a model context window. This MCP server parses the official ASD OSCAL release of the ISM into a local SQLite database and exposes a small set of typed lookup tools so that an agent (Claude Code, Codex, Cursor, etc.) can interrogate the ISM without re-reading the source documents. It holds the full ISM release history, so it can also report what changed between versions and what a newer ISM means for a project's existing compliance work.

## Status

Single-tenant and local: SQLite storage, stdio-transport MCP server, no auth, no network listener. Ingest fetches the OSCAL source over git. Suitable for local and per-project use, not multi-tenant or networked deployment.

## Install

Requires `uv` and Python 3.14+.

```bash
git clone https://github.com/samueldudley/ism-mcp.git
cd ism-mcp
uv sync
```

## Ingest the ISM

The source is the official ASD OSCAL mirror, [`AustralianCyberSecurityCentre/ism-oscal`](https://github.com/AustralianCyberSecurityCentre/ism-oscal). `ism-mcp` clones it into a managed cache (`~/.local/share/ism-mcp/oscal`) the first time, so a plain ingest needs no manual download:

```bash
uv run ism-mcp ingest --fetch          # fetch latest, ingest it as the active version
uv run ism-mcp ingest-history --fetch   # fetch, then ingest every tagged ISM release (full history)
uv run ism-mcp update                   # fetch latest and ingest any new release
```

The database lands at `~/.local/share/ism-mcp/ism.db` by default. Override with `--db PATH`. For an offline or air-gapped environment, clone the OSCAL repo yourself and point at it: `--oscal PATH` (single version) or `--oscal-repo PATH` (history). Run `ism-mcp ingest --help` for the full flag list.

The first ingest downloads the embedding model once (see [First-run network requirement](#first-run-network-requirement)). Pass `--no-embeddings` to skip it and fall back to lexical-only ranking. `ingest-history` embeds only the newest release by default (fast); pass `--embed-all` to embed every version.

Versions are upserted independently, so re-ingesting a release replaces just that version. There is no whole-database rebuild on each quarterly release. If you are upgrading from an older XLSX-based database, its schema is incompatible: ingest refuses it with a clear error, so pass `--fresh` once to wipe and rebuild.

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

Restart Claude Code. The tools listed under [MCP tools](#mcp-tools) become available, led by `ism_applicable` for ranked discovery.

## Adopt in a project

`ism-mcp install` writes everything a teammate needs into a consumer repo. The database is committed into the repo, so a clone has data without a local ingest.

```bash
uv run ism-mcp install --project /path/to/consumer-repo
```

This writes, all idempotent on re-run:

- `.mcp.json` with the `ism` server entry. Other servers in the file are kept.
- A managed block in `CLAUDE.md` between `<!-- ism-mcp:begin -->` and `<!-- ism-mcp:end -->`, telling agents when to consult the server.
- `.ism-coverage.toml` scaffolded from the template, only if absent. An existing manifest is never overwritten.
- `.ism/ism.db`, the database, refreshed on each run.

The default `uvx` mode launches the server with `uvx --from git+<repo>@<rev> ism-mcp serve`. `--repo` defaults to this checkout's `origin` remote and `--rev` to its short HEAD, so the entry pins a reproducible build. A teammate needs only `uv`. The first semantic query downloads the embedding model once, then runs offline.

For air-gapped or locked-down environments, `--mode docker --image <ref>` emits a `docker run` entry that mounts the committed database. Building and hosting the image is left to you.

The database path uses Claude Code's `${CLAUDE_PROJECT_DIR:-.}` expansion, so it resolves to each teammate's project root. Claude Code prompts once per repo to trust a project-scoped server. `claude mcp reset-project-choices` clears the approval.

Use `--dry-run` to see the planned writes without changing anything.

### Fetching from the published remote

`uvx` and `docker` both fetch a pinned source. Point `ism-mcp install` at the published repository with `--repo https://github.com/samueldudley/ism-mcp.git` (if you cloned from there, that is already your `origin` and the default works). To register the server at user scope against the published source:

```bash
claude mcp add ism -s user -- uvx --from git+https://github.com/samueldudley/ism-mcp.git@v1.1 ism-mcp serve
```

The user-scope server keeps the default database at `~/.local/share/ism-mcp/ism.db`, which you ingest locally. It carries no `ISM_MCP_DB` override, since that path is only for project installs where the database travels with the repo.

## Use programmatically

```python
from ism_mcp import store, server

conn = store.open_db(server.DEFAULT_DB)
c = store.get_control(conn, "ism-1781")  # also accepts ISM-1781, 1781, or a label
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

The table lists the bare tool names. Claude Code invokes them under the server key prefix, so `ism_applicable` is called as `mcp__ism__ism_applicable` (replace `ism` if you installed under a different `--name`).

| Tool | Purpose |
|---|---|
| `ism_applicable(work, classification?, maturity?, tags?, paths?, limit?, verbose?, version?)` | Hybrid retrieval: rank controls relevant to a free-text description of planned or current work. Recommended default for discovery. |
| `ism_get(identifier, version?)` | Full record for one control by ID. Lookup tolerates `ism-1781`, `ISM-1781`, `1781`, or a label. |
| `ism_search(query, limit=10, version?)` | Deterministic FTS5 search. Use when you know the exact term. |
| `ism_list_by_classification(classification, version?)` | Controls applicable at NC / OS / P / S / TS. |
| `ism_list_topics(version?)` | Distinct topic strings. |
| `ism_list_by_topic(topic, version?)` | Controls under a topic. |
| `ism_list_sections(version?)` | Distinct section strings. The vocabulary for the `tags` filter on `ism_applicable`. |
| `ism_list_classifications()` | Canonical classification enum plus friendly aliases. |
| `ism_list_maturities()` | Essential Eight maturity levels. |
| `ism_versions()` | Loaded ISM releases, newest first. The vocabulary for `version` / `from` / `to` arguments. |
| `ism_diff(from_version?, to_version?, change_types?)` | Catalog delta between two releases. Defaults to the latest release versus the one before it. |
| `ism_history(identifier)` | One control's evolution (text, title, applicability, maturity) across every loaded release. |
| `ism_stats()` | Database statistics: active version, total versions, control count. |
| `ism_coverage_read(project_path?, status_filter?)` | Read the project's `.ism-coverage.toml` manifest, including scope, summary counts, and curated entries. |
| `ism_coverage_upsert(identifier, status, how_met, ...)` | Create or update one entry with evidence (files, commits, urls, attachments). Stamps the entry with the active ISM version. |
| `ism_coverage_gaps(work?, limit?)` | Return outstanding in-scope controls. With `work`, ranks by `ism_applicable` relevance and intersects with the manifest. |
| `ism_coverage_impact(project_path?, target_version?, limit?)` | After an ISM update, flag covered controls to re-review, controls removed upstream, and newly in-scope controls with no entry. |

Lookup and listing tools default to the active ISM version. Pass `version` (see `ism_versions`) to target a historical release. Each `Control` record carries: `version`, `identifier`, `label`, `title`, `control_class`, `guideline`, `section`, `topic`, `description`, `control_revision`, `updated`, `sort_id`, classification applicability (`NC/OS/P/S/TS`), and maturity applicability (`ML1/ML2/ML3`).

Every tool publishes a JSON output schema and returns structured content that validates against it. Constrained parameters (`classification`, `maturity`, `status`, `change_types`, `status_filter`) are schema enums, so invalid values are rejected before the tool runs. Failures arrive as MCP tool errors (`isError` with a message), never as `{"error": ...}` payloads inside a successful result. Keys are never conditionally absent: a key that does not apply to a given call is present with a `null` value.

## Discovery for agents

The headline use case is `ism_applicable`. The agent describes the work in plain language, optionally narrows by classification, maturity, section tags, or repo paths, and gets back a ranked list of relevant controls.

```python
ism_applicable(
    work="adding JWT refresh and idle session timeout to our auth flow",
    classification="OFFICIAL",
    paths=["src/auth/jwt.py", "src/auth/session.py"],
    limit=10,
)
```

Returns a ranked list with `identifier`, `label`, `title`, `topic`, `section`, `description`, `applies`, `maturity`, a normalised RRF `score` in `[0.0, 1.0]`, and a `why` list naming the signals that surfaced each result (`semantic`, `lexical`, `path:<token>`). `verbose=true` adds the `guideline`.

> **Maturity is Essential Eight only.** `ML1/ML2/ML3` exist for the ~123 controls mapped to the Essential Eight Maturity Model, not the wider ISM (~1130 controls). Passing `maturity=` (here, or in a manifest `[scope]`) drops every control with no maturity rating, so a `PROTECTED` scope collapses to the subset that is also Essential Eight at that level. Leave `maturity` unset unless you are specifically tracking Essential Eight maturity.

Under the hood: a `bge-small-en-v1.5` embedding of the work text is cosine-matched against per-control embeddings, fused with FTS5 BM25 via Reciprocal Rank Fusion, then post-filtered.

### First-run network requirement

The first ingest after install downloads the embedding model (~130 MB) to `~/.cache/fastembed/`. Subsequent runs are offline. To pre-warm:

```bash
uv run python -c "
from fastembed import TextEmbedding
TextEmbedding('BAAI/bge-small-en-v1.5')
"
```

To skip embeddings entirely (offline first run, or for fast iteration during development):

```bash
uv run ism-mcp ingest --fetch --no-embeddings
```

Without embeddings, `ism_applicable` falls back to lexical-only ranking. Results are still useful but recall on natural-language queries is lower.

### Environment variables

| Var | Values | Effect |
|---|---|---|
| `ISM_MCP_DB` | path | Override the database location. Default `~/.local/share/ism-mcp/ism.db`. |
| `ISM_MCP_EMBEDDER` | `fastembed` (default), `hash`, `none` | Force a specific embedder at server start. `hash` is test-only. `none` disables semantic retrieval. |

## Project coverage manifest

For projects pursuing IRAP review (or any internal review against the ISM), `.ism-coverage.toml` at the project root records how each in-scope control is addressed.

```toml
schema_version = 1

[scope]
classification = "P"
sections = ["Authentication hardening", "Cryptographic fundamentals"]
baseline_version = "2026.03.24"

[project]
name = "demo-admin"

[controls."ism-0428"]
status = "covered"
how_met = """
Sessions terminate after 14 min of idle activity, enforced
in the auth middleware. Re-auth requires all original factors.
"""
last_reviewed = 2026-05-28
reviewed_against = "2026.03.24"
files = ["src/auth/session.py:42-87"]
commits = ["abc1234"]

[[controls."ism-0428".attachments]]
path = ".ism-coverage/evidence/ism-0428/lock-prompt.png"
description = "Admin console at 14:01 showing session-expired modal"
```

`[scope]` defines the in-scope control set that `ism_coverage_gaps` measures against. Set `classification` (and optionally narrow by `sections`). `baseline_version` records the ISM release the project currently targets; each entry's `reviewed_against` records the release it was assessed against, and `ism_coverage_impact` uses the two to flag drift when a newer ISM lands. Do not set `maturity` unless you are tracking Essential Eight maturity specifically: it filters to the Essential Eight subset and drops every other control from scope (see the maturity note under [Discovery for agents](#discovery-for-agents)).

Recommended layout for binary evidence:

```
your-repo/
  .ism-coverage.toml
  .ism-coverage/
    evidence/
      ISM-0428/
        lock-prompt.png
        tls-handshake.pcapng
```

A template lives at `src/ism_mcp/data/coverage_template.toml` if you want to copy and start from a known-good shape. The fields and their allowed values are shown in the example above.

The manifest is machine-managed: `ism_coverage_upsert` rewrites the whole file, so comments are not preserved. Keep narrative in `how_met` and evidence in the structured fields rather than in TOML comments.


## Architecture

```
ism-mcp/
  src/ism_mcp/
    store.py          version-keyed SQLite schema + queries, FTS5, version registry
    oscal.py          parse an OSCAL ISM catalog into version metadata and control rows
    fetch.py          clone/pull the ACSC ism-oscal mirror, list tags, read files at a tag
    ingest.py         orchestrate OSCAL ingest over a directory or a git-tag walk
    diff.py           catalog delta between two versions + per-control history
    retrieve.py       cosine search + Reciprocal Rank Fusion
    embed.py          embedder protocol + fastembed and hash backends
    classification.py classification + maturity input normalisation
    paths.py          repo-path token expansion for query enrichment
    coverage.py       coverage manifest read, validate, serialise, gaps, drift
    install.py        consumer-repo install writer
    server.py         FastMCP server: lookup, discovery, version, coverage tools
    __main__.py       CLI: fetch, ingest, ingest-history, update, serve, install
    data/             path keyword map + coverage template
  pyproject.toml uv-managed, hatchling build
```

Single SQLite file. A `versions` registry plus controls and embeddings keyed by `(version, identifier)`, with an FTS5 virtual table kept in sync via insert and delete triggers. A `meta` table records the active version that lookup tools default to.

## Known limitations

- **No auth on the MCP server.** Suitable for local use only.

## Licence

MIT. See [LICENSE](LICENSE).

This licence covers the code in this repository. The ISM itself is Commonwealth of Australia content published by the ACSC under its own terms. You download and ingest the ISM separately; it is not redistributed here.
