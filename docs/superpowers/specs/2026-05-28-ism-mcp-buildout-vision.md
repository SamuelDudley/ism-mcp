# ism-mcp build-out vision

> Multi-sub-project roadmap for taking the working prototype to a tool that agents reach for during development.

## Goal

Make `ism-mcp` the default way an agent answers three questions during day-to-day development work:

1. **"What ISM controls apply to the work I'm planning or doing right now?"**
2. **"Tell me everything I need to know about this specific control."**
3. **"Which applicable controls have we addressed in this project, and which gaps remain?"**

The proto answers (2) well enough and answers (1) only as keyword search. (3) is unaddressed. This roadmap closes those gaps.

## Audience

Coding agents (Claude Code, Codex, Cursor, IDE assistants) acting on behalf of developers in Australian Government, defence, and adjacent regulated environments. Single-tenant, local SQLite, stdio MCP.

## Non-goals

- Multi-tenant SaaS. The local-file, single-process design is a feature, not a stepping stone.
- Authoring guidance on how to satisfy a control. The ISM PDF and ASD publications own that. We surface, we don't interpret.
- Compliance attestation. The tool helps developers reason about controls. Attestation lives in the project's own artefacts (PRs, ADRs, manifests).

## Sub-projects

Decomposed in dependency order. Each sub-project is independently shippable and gets its own design doc and implementation plan.

### A. Hardening foundation

**Status:** shipped.

Pytest with hermetic fixtures, ruff, pyright, `scripts/ci.sh`, per-control PDF excerpts. Prerequisite to everything below because (i) the new modules need a test bed and (ii) per-control excerpts feed the embedding text in sub-project B.

### B. Hybrid discovery

**Status:** shipped (`docs/plans/2026-05-28-hybrid-discovery.md`).

The headline capability. Adds `ism_applicable(work, classification?, maturity?, tags?, paths?, limit?, verbose?)`, ranked by hybrid retrieval (vector + BM25 reciprocal-rank fusion) with structured post-filters.

Design doc: `2026-05-28-ism-mcp-hybrid-discovery-design.md`.

**Why first:** the gap between agent vocabulary ("JWT", "S3 bucket", "TLS termination") and ISM vocabulary ("session management", "cryptographic protocols", "network infrastructure") is the single biggest reason the proto's lexical search underwhelms in real use. Closing it unlocks all downstream work.

### C. Graph and curated cuts

Cross-references and pre-baked filters that exploit known structure in the ISM:

- `ism_neighbors(id, limit?)` — controls related to a known one (same topic, semantically similar via the B embedder, shared keywords).
- `ism_essential8(maturity_level)` — the Essential Eight subset at ML1/ML2/ML3. The ISM identifies these via topic and section text; we curate the mapping once.
- `ism_subset(name)` — named cuts for common scoping conversations: `"data-at-rest"`, `"data-in-transit"`, `"logging"`, `"web-app"`, `"identity"`, etc. Backed by a small `subsets.toml` that lists identifier sets.

**Why second:** depends on B's embeddings for "semantically similar" in `ism_neighbors`. The other helpers are independent but compose naturally with B in the agent's workflow.

### D. Project coverage manifest

**Status:** designed (`2026-05-28-coverage-manifest-design.md`), not yet executed.

Persistent project-side state so an agent can reason about "what's already addressed":

- `.ism-coverage.toml` lives in the consumer repo, version-controlled. Schema: per-control entries with `claimed_by` (file paths / PR refs), `notes`, `last_reviewed`.
- `ism_coverage_read(project_path)` returns the manifest.
- `ism_coverage_add(project_path, identifier, claimed_by, notes)` appends an entry.
- `ism_coverage_gaps(project_path, work)` runs `ism_applicable(work)` and returns the subset not already in the manifest.

**Why third:** depends on B for `gaps`. The schema and read/add tools can ship standalone, but `gaps` is what makes the whole feature pay off.

### E. Consumer install helper

One-command adoption for a new project:

- `ism-mcp install --project PATH` writes the MCP server entry to `.claude/mcp_servers.json` (or equivalent), drops a `CLAUDE.md` fragment recommending when to consult the server, and scaffolds an empty `.ism-coverage.toml`.
- Same command for Codex, Cursor, IDE config files (best-effort detection of which is present).

**Why last:** depends on D's manifest format being settled. Pure ergonomics, no new query capabilities.

## Deferred (already on HANDOVER roadmap, not in this build-out)

- Revision diff (`ism_changes_since(rev)`). Useful but not on the critical path for "what applies to my work".
- HTTP/SSE transport, auth, PyPI publish. The local stdio model is the design point, not a limitation to fix.
- Coverage gate in CI. Decision deferred until the test suite settles.

## Sequencing

```
A (hardening) ─┬─► B (hybrid discovery) ─┬─► C (graph / cuts)
               │                          ├─► D (coverage manifest)
               │                          │              │
               │                          │              ▼
               │                          │              E (install helper)
               └──────────────────────────┘
```

Each sub-project lands as: brainstorm → design doc → implementation plan → execution → merged. No sub-project blocks on a later one.

## Cross-cutting conventions

These apply to every sub-project:

- **No new top-level deps without justification.** B adds `fastembed` and `numpy` (numpy is transitive today). C, D, E should add nothing.
- **All new tools return JSON strings with explicit `error` / `hint` keys for failure modes.** No exceptions across the MCP boundary.
- **Every new tool has a docstring suitable as the MCP tool description.** The agent reads it.
- **Hermetic tests only.** Real ISM files are never required to run `./scripts/ci.sh`.
- **OS-level deps trigger a Docker variant**, not a host install. If a sub-project needs torch/CUDA or system libraries, we add a `docker/` directory rather than complicate the host install.

## Out-of-scope decisions to revisit later

| When | What |
|---|---|
| After B lands | Whether to add a query-side embedding LRU cache. |
| After C lands | Whether `ism_neighbors` and `ism_subset` should merge into one tool. |
| After D lands | Whether the manifest should also live in `.claude/` or a project-root file. |
| After E lands | Whether to publish a `cyber.gov.au`-hosted hosted pre-warmed DB for offline first-runs. |

## Maintenance

When a sub-project's design lands, append a `**Status:**` line under its heading here. When it ships, link to the merged plan. This file stays the index.
