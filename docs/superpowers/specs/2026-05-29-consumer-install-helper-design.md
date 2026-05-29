# Consumer install helper design

> One command to adopt ism-mcp in a consumer repo, so that a teammate who clones the repo gets a working ISM server with the database in place.

## Goal

Add `ism-mcp install --project PATH`. Running it once in a consumer repo writes everything a Claude Code user needs to query the ISM against that project:

- A project-scoped `.mcp.json` entry that launches the server.
- A managed guidance block in the repo's `CLAUDE.md` telling agents when to consult the server and how to use the coverage manifest.
- A scaffolded `.ism-coverage.toml` if one does not already exist.
- The 3.2 MB ISM database committed into the repo at `.ism/ism.db`, so the server has data without a per-teammate ingest.

The test of success: a teammate clones the repo, opens it in Claude Code, approves the project server once, and `ism_applicable` works.

## Problem statement

The server runs today only because it is registered at user scope on one machine, with a launch command that embeds an absolute path to a local checkout. That does not travel. A teammate cloning a consumer repo has no server registration, no database, and no guidance on when to reach for the tool.

Two facts shape the solution:

- The database is 3.2 MB. It can be committed into the consumer repo rather than provisioned per teammate.
- `ism_applicable` embeds the query text at runtime, so semantic search needs the `bge-small-en-v1.5` model (about 130 MB) and the native `onnxruntime` whenever the server runs, not only at ingest. That native runtime is the only heavy dependency.

The launch command therefore must not embed a machine-specific path, and the database path must resolve correctly on every clone regardless of checkout location.

## Distribution modes

Two modes, selected with `--mode`, default `uvx`. Both keep semantic search.

### uvx (default)

The server is fetched and cached by `uv` from a pinned git revision.

```json
{
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "git+<repo>@<rev>", "ism-mcp", "serve"],
  "env": { "ISM_MCP_DB": "${CLAUDE_PROJECT_DIR:-.}/.ism/ism.db" }
}
```

A teammate needs only `uv`, a single static binary. First run builds the environment, first semantic query downloads the model to `~/.cache/fastembed`, and everything is cached and offline afterwards. First run needs network and a reachable remote.

### docker

For air-gapped or locked-down environments where a one-time per-developer model download is not acceptable. The image bundles Python, the package, `onnxruntime`, and the model. The committed database is mounted read-only so the image does not rebuild on each ISM revision.

```json
{
  "type": "stdio",
  "command": "docker",
  "args": [
    "run", "--rm", "-i",
    "-v", "${CLAUDE_PROJECT_DIR:-.}/.ism:/data:ro",
    "-e", "ISM_MCP_DB=/data/ism.db",
    "<image>"
  ]
}
```

docker is a documented variant. Building and hosting the image is out of scope for this work. The install command emits the entry, given an image reference.

A keyword-only fallback is not a first-class mode. A consumer who wants lexical-only ranking can set `ISM_MCP_EMBEDDER=none` in the `env` block by hand.

## Database path resolution

The server reads `ISM_MCP_DB` from its environment and needs no change. Claude Code does not guarantee the working directory of a project-scoped server, so a relative path is unsafe. The portable pattern is the documented `${CLAUDE_PROJECT_DIR:-.}` expansion, which Claude Code substitutes with the clone's project root when it loads `.mcp.json`. The default `:-.` is required because the variable is set in the server's environment rather than Claude Code's own when expanding a project-scoped or user-scoped config.

So `ISM_MCP_DB` is always written as `${CLAUDE_PROJECT_DIR:-.}/.ism/ism.db` and resolves to an absolute path on every clone.

## Command surface

```
ism-mcp install --project PATH
                [--mode uvx|docker]      default: uvx
                [--repo URL]             default: origin remote of this checkout
                [--rev REF]              default: short HEAD sha of this checkout
                [--image REF]            docker mode only
                [--db PATH]              source database, default server.DEFAULT_DB
                [--name ism]             MCP server key
                [--dry-run]
```

- `--repo` defaults to the ism-mcp checkout's `origin` remote. If no remote is set and none is passed, uvx mode errors with a hint to publish first.
- `--rev` defaults to the current short HEAD sha, pinning a reproducible build. A tag or branch may be passed.
- `install` is a CLI subcommand beside `ingest` and `serve`. It prints progress to stderr and returns an exit code. It is not an MCP tool, so the JSON `error` and `hint` response convention does not apply.

## Artifacts written into the project

1. **`.mcp.json`** at the repo root. The `mcpServers.<name>` entry is merged in, preserving any other servers already present. The file is created if absent.

2. **`CLAUDE.md`** at the repo root. A managed block delimited by `<!-- ism-mcp:begin -->` and `<!-- ism-mcp:end -->` is appended, or replaced in place if the markers already exist. The block holds a condensed trigger for when to consult the server plus the coverage workflow (`ism_coverage_read`, then `ism_coverage_gaps`, then `ism_coverage_upsert`). Text outside the markers is never touched. The file is created if absent.

3. **`.ism-coverage.toml`** at the repo root. Scaffolded from `data/coverage_template.toml` only when absent. An existing manifest is never overwritten, because it holds project evidence.

4. **`.ism/ism.db`**. The source database is copied in, creating `.ism/` if needed. Overwritten on re-run, because it is a generated artifact and a re-run is how a consumer picks up a new ISM revision. If the source database is missing, install errors with a hint to run `ingest` first.

## Idempotency

A second run converges to no diff, except a refreshed database when the source changed. The `.mcp.json` merge replaces only the named entry. The `CLAUDE.md` block is replaced between its markers. The manifest is left untouched once present. `--dry-run` reports every planned write and changes nothing on disk.

## Code organisation

A new module `src/ism_mcp/install.py` holds two layers kept separate so they test independently and so a future writer for another agent can reuse the first layer.

- Builders, pure functions with no filesystem effects:
  - `mcp_entry(mode, repo, rev, image, name) -> dict` returns the server entry dict for the chosen mode.
  - `claude_md_block() -> str` returns the managed guidance block, markers included.
- Filesystem operations:
  - `merge_mcp_json(path, name, entry)` reads, merges, and writes `.mcp.json`.
  - `write_managed_block(path, block)` appends or replaces the marked block in `CLAUDE.md`.
  - `scaffold_manifest(path, template)` writes the template only if the target is absent.
  - `copy_database(src, dst)` copies the database, creating parent directories.
  - A top-level `install(opts)` orchestrates the four writes and honours `--dry-run`.

`__main__.py` gains the `install` subcommand, which resolves `--repo` and `--rev` defaults from git, then calls `install.install`.

The split between builders and filesystem operations is the seam for later Codex or Cursor writers. v1 ships only the Claude Code writer.

## Publish prerequisite and personal migration

uvx and docker both resolve a pinned source, so ism-mcp must reach a git remote before any teammate, including the author, can run the server. The repository has no remote today.

The implementation plan documents these one-time steps in order:

1. Push ism-mcp to a remote and set `origin` on the working checkout.
2. Migrate the author's user-scope registration to uvx:

   ```
   claude mcp add ism -s user -- uvx --from git+<origin>@<rev> ism-mcp serve
   ```

   The user-scope server keeps the default database at `~/.local/share/ism-mcp/ism.db`, which the author ingests locally. It carries no `ISM_MCP_DB` override, since that path is only for project installs where the database travels with the repo.

3. Use `install --project PATH` for consumer repos.

A project-scoped entry named `ism` takes precedence over a user-scope one of the same name for that repo, which is the intended behaviour: the repo-pinned revision and committed database win inside the repo.

## Trust prompt

Claude Code prompts once per repository before using a project-scoped server from `.mcp.json`. The approval persists across sessions for that repo. `claude mcp reset-project-choices` clears it. The README notes this so a teammate is not surprised by the prompt.

## Testing

Hermetic, using `tmp_path`. No real ISM files required.

- `mcp_entry` returns the expected dict for uvx and for docker.
- `merge_mcp_json` adds the entry to an empty file, to a file with other servers (which are preserved), and replaces an existing entry of the same name.
- `write_managed_block` creates `CLAUDE.md`, appends to existing prose without disturbing it, and replaces an existing block in place.
- `scaffold_manifest` writes when absent and is a no-op when present.
- `copy_database` copies a small fixture file and errors clearly when the source is missing.
- An end-to-end install into a temporary repo, run twice, asserts the second run produces no diff apart from the database.

## Dependencies

No new third-party dependencies. `install` uses the standard library (`pathlib`, `json`, `shutil`, `subprocess` for git detection) plus the existing package modules.

## Non-goals

- Writers for Codex, Cursor, or IDE config files. The builder and filesystem split leaves room for them. They are not built here.
- Building or hosting the docker image, or any registry automation.
- Auto-detecting which agent a repo uses.
- Editing `.gitignore`. Evidence under `.ism-coverage/` and the committed database are meant to be tracked.
- A `--scope user` flag. User-scope migration is a one-time documented command.

## Sequencing inside the plan

1. Builders with their unit tests.
2. Filesystem operations with their unit tests.
3. `install` orchestration and the `--dry-run` path.
4. The `install` subcommand in `__main__.py` with git default resolution.
5. End-to-end idempotency test.
6. README "Adopt in a project" section and HANDOVER update, including the publish prerequisite and the personal migration command.
