# Multi-version ISM and OSCAL migration design

> New sub-project of the ism-mcp build-out. See `2026-05-28-ism-mcp-buildout-vision.md` for context. Supersedes the XLSX/PDF ingest path described in the hybrid-discovery and coverage specs.

## Goal

Hold the full history of ISM releases in one database, sourced from the official OSCAL mirror, and answer two questions on top of it: "what changed between two releases?" and "given the version my project was assessed against, what do I need to re-review now that a newer ISM has dropped?". Migrating ingest to OSCAL is the enabler: it carries structured fields and a tagged release history that the XLSX/PDF source cannot.

## Problem statement

Today the server is strictly single-version. Each `ingest` calls `store.reset()`, dropping and recreating every table, so the database holds exactly one ISM. The `--revision` flag is a cosmetic metadata label. There is no temporal dimension, so a consumer who builds compliance evidence against one ISM has no way to see what a newer ISM changes, which of their covered controls now need re-review, or how a control has evolved.

The source format compounds this. Ingest parses the Cloud Controls Matrix XLSX plus surrounding-paragraph excerpts scraped from the 700-page ISM PDF. That is lossy and manual: the XLSX lacks full control text (hence the PDF excerpt workaround), and neither artefact is versioned in a way the tool can walk.

The ASD publishes the ISM in OSCAL at `https://github.com/AustralianCyberSecurityCentre/ism-oscal`. It is a 3.3 MB git repository with 24 dated, tagged releases back to 2022. Each release is a machine-readable catalog: controls carry structured `props` (classification applicability, human label, revision, updated date), full statement prose, and a group hierarchy that maps to ISM guidelines and topics. Essential Eight maturity is expressed as separate per-level resolved catalogs. This is a better source for the current single-version product and the only practical source for a historical one.

## Decisions locked during brainstorming

These were settled with the user and are not open for re-litigation in the plan.

| Decision | Choice |
|---|---|
| Source format | OSCAL only. Drop XLSX and PDF ingest, remove `openpyxl` and `pdfplumber`. |
| History depth | Full history. The schema holds every ingested release (up to all 24 tags). |
| Capabilities | All four: catalog delta, applicability/maturity changes, coverage drift, per-control history. |
| Storage strategy | One version-keyed database. Deltas computed on read (data is tiny). No precomputed diff tables. |
| Backward compatibility | An active-version pointer. Existing tools default to it and behave as today. |
| Coverage pinning | Per-entry `reviewed_against`, plus a `[scope].baseline_version` target. |
| Source fetching | Fetch by default from the official ACSC repo into a managed cache. `--oscal PATH` is the offline escape hatch. |
| Canonical identifier | The OSCAL `id` (e.g. `ism-1001`). Lookup is tolerant of `ISM-1001`, bare numbers, and labels. |
| Embedding policy | Embed the active version only by default. `--embed-all` populates history. |

## Architecture

```
github.com/AustralianCyberSecurityCentre/ism-oscal   (3.3 MB, 24 tags)
        │  ism-mcp fetch  (git clone/pull --tags)
        ▼
~/.local/share/ism-mcp/oscal/        managed cache (a git clone)
        │  ism-mcp ingest / ingest-history
        │    parse ISM_catalog.json  + ISM_E8_ML{1,2,3}-...-resolved-profile_catalog.json
        ▼
~/.local/share/ism-mcp/ism.db        ONE database, many versions
        versions(version PK, label, published, git_tag, git_commit, ...)
        controls(version, identifier, ...)        PK (version, identifier)
        controls_embeddings(version, identifier)  active version by default
        meta: active_version -> "2026.03.24"
        │
        ▼
server.py  lookup tools default to active_version (+ optional version=)
           ism_versions / ism_diff / ism_history          (cross-version)
           ism_coverage_impact                            (drift vs reviewed_against)
```

Ingest is a maintainer/build-time operation. Consumers receive a prebuilt `ism.db` copied into `.ism/ism.db` by `ism-mcp install`, exactly as today. The database now carries history, so consumers get drift and timeline queries without running ingest themselves.

## Data model

Every controls row is version-keyed. A `versions` registry holds release metadata and provenance. A `meta` key names the active version that lookup tools default to.

```sql
CREATE TABLE versions (
    version       TEXT PRIMARY KEY,   -- metadata.version, e.g. "2026.03.24"
    label         TEXT,               -- friendly, derived, e.g. "March 2026"
    published     TEXT,               -- metadata.published
    last_modified TEXT,               -- metadata.last-modified
    oscal_version TEXT,               -- metadata.oscal-version, e.g. "1.1.2"
    git_tag       TEXT,               -- e.g. "v2026.03.24"
    git_commit    TEXT,               -- resolved commit for reproducibility
    ingested_at   TEXT,               -- ISO 8601, when this row was written
    control_count INTEGER
);

CREATE TABLE controls (
    version          TEXT NOT NULL REFERENCES versions(version),
    identifier       TEXT NOT NULL,   -- OSCAL id, canonical: "ism-1001", "ism-principle-gov-01"
    label            TEXT,            -- human number: "1001", "GOV-01"
    title            TEXT,
    control_class    TEXT,            -- "ISM-control" | "ISM-principle"
    guideline        TEXT,            -- from group hierarchy
    section          TEXT,            -- from group hierarchy
    topic            TEXT,            -- from group hierarchy
    description      TEXT NOT NULL,   -- parts[statement].prose (canonical control text)
    control_revision TEXT,            -- props "revision"
    updated          TEXT,            -- props "updated"
    sort_id          TEXT,            -- props "sort-id", for stable display ordering
    applies_nc INTEGER NOT NULL, applies_os INTEGER NOT NULL, applies_p INTEGER NOT NULL,
    applies_s  INTEGER NOT NULL, applies_ts INTEGER NOT NULL,
    maturity_ml1 INTEGER NOT NULL, maturity_ml2 INTEGER NOT NULL, maturity_ml3 INTEGER NOT NULL,
    PRIMARY KEY (version, identifier)
);
CREATE INDEX controls_by_identifier ON controls(identifier);

CREATE TABLE controls_embeddings (
    version    TEXT NOT NULL,
    identifier TEXT NOT NULL,
    embedding  BLOB NOT NULL,
    PRIMARY KEY (version, identifier)
);

CREATE VIRTUAL TABLE controls_fts USING fts5(
    identifier UNINDEXED,
    description, topic, section, guideline,
    content='controls', content_rowid='rowid'
);
-- INSERT trigger mirrors today's controls_ai. FTS rows cover all versions.
-- Searches join the FTS rowid back to controls and filter c.version = ?.

-- meta gains key 'active_version' -> the version string lookup tools default to.
```

### Field mapping, OSCAL to schema

| Schema column | OSCAL source |
|---|---|
| `identifier` | control `id` (lowercased, canonical) |
| `label` | `props[name="label"].value` |
| `title` | control `title` |
| `control_class` | control `class` |
| `description` | `parts[name="statement"].prose` (joined if multiple statement parts) |
| `guideline` / `section` / `topic` | enclosing `groups` titles by nesting level |
| `control_revision` | `props[name="revision"].value` |
| `updated` | `props[name="updated"].value` |
| `sort_id` | `props[name="sort-id"].value` |
| `applies_nc..ts` | one per `props[name="applicability"].value` in {NC, OS, P, S, TS} |
| `maturity_ml1..3` | membership in `ISM_E8_ML{1,2,3}-...-resolved-profile_catalog.json` |
| `versions.version` | `metadata.version` |
| `versions.published` / `last_modified` / `oscal_version` | corresponding `metadata` fields |

The exact group-nesting-to-`guideline`/`section`/`topic` mapping is pinned in the plan by inspecting the real catalog (the hierarchy is roughly Guideline at the top, topic near the leaf). The intent is to preserve the semantics today's `ism_list_sections`, `ism_list_topics`, and the `tags` filter depend on.

### Identifier scheme

The canonical identifier is the OSCAL `id`. A normaliser resolves user input against the target version's id-and-label index, accepting:

- `ism-1001` (canonical), `ISM-1001`, `ISM-0421` (today's zero-padded XLSX form)
- a bare number `1001` (tried as `ism-1001` and zero-padded variants)
- a label such as `GOV-01`

This keeps any existing `.ism-coverage.toml` keyed on `ISM-XXXX` resolving without a rewrite. Tool output exposes `identifier`, `label`, and `title` so the human number is always visible.

### Why these changes

- `description` becomes the canonical OSCAL statement prose, which is strictly better than the XLSX text plus a PDF-excerpt workaround. `pdf_excerpt` and `pdf_page` are dropped. Section-level context, if wanted, is available from group-level `parts` prose.
- Embeddings keyed by `(version, identifier)` retire today's dependency on `rowid` insertion order, a latent correctness hazard.

## Ingest pipeline

A rewritten `ingest.py` built on the OSCAL catalog (plain `json`, no `openpyxl`/`pdfplumber`).

Per version it reads:

1. `ISM_catalog.json` (master). Recurse `groups`, collect every `control`, map fields per the table above. Applicability comes from the repeated `applicability` props.
2. `ISM_E8_ML{1,2,3}-baseline-resolved-profile_catalog.json`. The set of ids present in each gives `maturity_ml1/2/3`. Maturity is catalog membership, not a prop. Missing E8 catalogs in older releases mean maturity all zero, tolerated.
3. `metadata` for the `versions` row.

The per-classification resolved catalogs (NON_CLASSIFIED, PROTECTED, ...) are not ingested. Applicability already comes from the master props. They may be used at most as an optional validation cross-check.

### Fetching

```
ism-mcp fetch [--repo URL] [--ref main|TAG]
        Clone-or-pull into ~/.local/share/ism-mcp/oscal. git fetch --tags to refresh.
        Default URL pinned to AustralianCyberSecurityCentre/ism-oscal, overridable.
```

The payload is plain JSON (data, not executable), so the trust surface is the repo URL, which defaults to the official ACSC org. Each `versions` row records `git_tag` and `git_commit`, so a build is reproducible even though the cache can be re-pulled later. Git is already needed by the history importer, so fetch adds no dependency.

### CLI

```
ism-mcp ingest [--oscal PATH] [--version LABEL] [--fetch] [--embed/--no-embed]
        Ingest the working-tree catalog as one version. PATH defaults to the managed cache.
        --fetch refreshes the cache first. Upserts the version and sets it active.

ism-mcp ingest-history [--oscal-repo PATH] [--from TAG] [--to TAG] [--fetch] [--embed-all]
        Walk git tags via `git show <tag>:ISM_catalog.json` (no working-tree checkout).
        Ingest each release. The newest becomes active.

ism-mcp update
        Convenience: fetch latest, ingest any new release(s), re-embed the active version.
```

- No whole-database reset on ingest. Versions upsert independently. `--replace-version` re-does one version, `--fresh` wipes all for a clean rebuild.
- Embedding policy: by default embed the active version only (what `ism_applicable` searches), keeping the history walk fast. `--embed-all` populates every version for semantic operations over history and direct reword materiality scoring. The schema supports both, only population differs.
- Embedding text becomes `f"{guideline}. {topic}. {section}. {title}. {description}"`. Model and dimensions unchanged (`bge-small-en-v1.5`, 384). `--no-embeddings` lexical fallback unchanged.

## Version semantics for existing tools

All thirteen current tools keep working by defaulting to the active version. Each lookup/retrieval tool gains an optional `version` argument.

- `ism_get(identifier, version=None)`
- `ism_search(query, limit=10, version=None)`
- `ism_applicable(work, classification=None, maturity=None, tags=None, paths=None, limit=20, verbose=False, version=None)`
- `ism_list_by_classification(classification, version=None)`, `ism_list_by_topic(topic, version=None)`, `ism_list_topics(version=None)`, `ism_list_sections(version=None)`
- `ism_list_classifications()`, `ism_list_maturities()` unchanged (static enums)

Semantic search against a historical version requires that version to be embedded. Under the default policy only the active version is, so `ism_applicable(version=<older>)` falls back to lexical ranking for that version and says so in its `hint`.

`ism_stats()` expands to report the active version, total versions loaded, the active version's control count, and the source repo and commit.

## New tools

### `ism_versions() -> str`

Every loaded version, the vocabulary for `version`/`from`/`to` arguments.

```python
{
    "active": "2026.03.24",
    "count": 24,
    "versions": [
        {"version": "2026.03.24", "label": "March 2026", "published": "2026-03-24",
         "control_count": 1130, "is_active": true, "git_tag": "v2026.03.24"},
        {"version": "2025.12.9", "label": "December 2025", "published": "2025-12-09",
         "control_count": 1124, "is_active": false, "git_tag": "v2025.12.9"}
    ]
}
```

### `ism_diff(from_version=None, to_version=None, classification=None, sections=None, change_types=None, limit=200) -> str`

The catalog delta between two releases. Defaults: `from` is the version immediately before active, `to` is active, so a bare `ism_diff()` answers "what changed in the latest release". Comparison keys on the stable OSCAL id.

Change classes:

| Type | Meaning |
|---|---|
| `added` | id present in `to`, absent in `from` |
| `removed` | id present in `from`, absent in `to` |
| `reworded` | same id, `description` differs (unified diff returned, plus cosine similarity when both sides embedded) |
| `retitled` | same id, `title` differs |
| `moved` | same id, `guideline`/`section`/`topic` differs |
| `applicability_changed` | the NC/OS/P/S/TS set differs (which were added/dropped) |
| `maturity_changed` | the ML1/2/3 set differs |

`change_types` filters to a subset. `classification`/`sections` scope the comparison to controls relevant to a baseline. A low-confidence "possible rename" heuristic pairs a `removed` id with an `added` id of high description similarity and flags it as a candidate, never an assertion.

```python
{
    "from": "2025.12.9", "to": "2026.03.24",
    "filters": {"classification": null, "sections": null, "change_types": null},
    "summary": {"added": 9, "removed": 3, "reworded": 41, "retitled": 6,
                "moved": 2, "applicability_changed": 5, "maturity_changed": 4},
    "changes": {
        "added": [{"identifier": "ism-principle-gov-08", "label": "GOV-08",
                   "title": "Executive artificial intelligence accountability",
                   "section": "Cyber security principles"}],
        "reworded": [{"identifier": "ism-1001", "label": "1001",
                      "title": "...", "similarity": 0.82,
                      "diff": "@@ ... unified diff of description ... @@"}],
        "applicability_changed": [{"identifier": "ism-0421", "added": ["P"], "removed": []}]
    }
}
```

### `ism_history(identifier) -> str`

One control's evolution across all loaded versions.

```python
{
    "identifier": "ism-1001", "label": "1001",
    "first_seen": "2022.09.14", "last_seen": null,   // null = still present in active
    "timeline": [
        {"version": "2026.03.24", "title": "...", "applicability": ["NC","OS","P","S","TS"],
         "maturity": ["ML1"], "changed": ["description"]},
        {"version": "2025.12.9", "title": "...", "applicability": ["NC","OS","P","S","TS"],
         "maturity": ["ML1"], "changed": ["applicability"]}
    ]
}
```

`changed` lists which fields differ from the previous version in the timeline. The first appearance carries an empty `changed`.

## Coverage version-awareness

### Manifest schema additions (additive, no schema_version bump)

```toml
[scope]
classification = "P"
baseline_version = "2026.03.24"      # the version the project currently targets

[controls."ism-1001"]
status = "covered"
how_met = "TLS 1.3 enforced at the edge"
last_reviewed = 2025-12-15
reviewed_against = "2025.12.9"        # the ISM version this entry was assessed against
```

- `[scope].baseline_version` is the target version. Defaults to the active version when absent.
- per-entry `reviewed_against` is auto-stamped by `ism_coverage_upsert` with the active/baseline version at write time, exactly as `last_reviewed` defaults to today. An explicit argument overrides it.
- Legacy entries without `reviewed_against` inherit `baseline_version` (treated as up to date, no false drift). Every subsequent upsert stamps it, so absence only affects untouched pre-existing entries.

### `ism_coverage_upsert(...)` changes

Gains `reviewed_against=None` (defaults to the active/baseline version) and writes it into the entry. Identifier validation runs against the active version. All other behaviour unchanged.

### `ism_coverage_impact(project_path=None, target_version=None, work=None, limit=50) -> str`

The drift report. For each entry it compares `reviewed_against` to `target_version` (default `scope.baseline_version` or active) using the `ism_diff` engine, and buckets the results into actions.

```python
{
    "baseline_version": "2025.12.9", "target_version": "2026.03.24",
    "summary": {"re_review": 6, "removed_upstream": 1, "new_uncovered": 4, "still_valid": 36},
    "re_review": [
        {"identifier": "ism-1001", "status": "covered", "reviewed_against": "2025.12.9",
         "changes": ["reworded", "applicability_changed"],
         "diff": "@@ ... @@", "how_met": "TLS 1.3 enforced at the edge"}
    ],
    "removed_upstream": [
        {"identifier": "ism-9998", "status": "partial", "reviewed_against": "2025.12.9",
         "hint": "no longer in 2026.03.24; consider not-applicable or remove"}
    ],
    "new_uncovered": [
        {"identifier": "ism-principle-gov-08", "label": "GOV-08", "title": "...",
         "section": "Cyber security principles", "reason": "added", "score": 0.0}
    ],
    "still_valid": 36
}
```

- **re_review**: covered/partial entries whose control changed (reworded, applicability, or maturity) between `reviewed_against` and target.
- **removed_upstream**: entries whose control is absent at target. This is today's soft warning, made actionable.
- **new_uncovered**: controls newly in the project scope at target (added, or newly applicable/in-maturity) with no manifest entry. When `work` is supplied, intersected with `ism_applicable` and ranked, like `ism_coverage_gaps`.
- **still_valid**: a count.

`ism_coverage_read` and `ism_coverage_gaps` keep their signatures. `read`'s summary gains a drift hint ("N entries predate baseline_version").

## Edge cases

| Case | Behaviour |
|---|---|
| Only one version loaded, `ism_diff()` called | `{"error": "need two versions to diff", "hint": "load history with ingest-history, or pass from/to"}` |
| `from`/`to`/`version` names an unknown version | `{"error": "no such version: X", "hint": "call ism_versions for loaded versions"}` |
| `ism_history` for an id that never existed | `{"identifier": "...", "timeline": [], "hint": "no control with that id in any loaded version"}` |
| Reworded check where the older version is not embedded | `diff` still returned, `similarity` omitted (lexical-only) |
| E8 catalogs absent for an older release | maturity flags all zero for that version, ingest still succeeds |
| Coverage entry pinned to a version not loaded | impact lists it under a `warnings` note, does not crash; suggests loading that version |
| `reviewed_against` absent on an entry | inherits `scope.baseline_version`, treated as no drift |
| Network unavailable during `fetch` | `{"error": "fetch failed", "hint": "use --oscal PATH to ingest from a local clone"}`. `--oscal PATH` paths never touch the network. |
| Re-ingesting an already-loaded version | upsert replaces that version's rows in place. Other versions untouched. |

## Code organisation

```
src/ism_mcp/
  oscal.py          NEW. Parse an OSCAL catalog file into Control rows + version metadata.
                         Pure functions over parsed JSON, no DB or git dependency.
  fetch.py          NEW. Clone/pull the OSCAL repo into the managed cache; list and read tags.
  ingest.py         REWRITTEN. Orchestrate oscal.py over one version or a tag walk; build
                         embedding text. openpyxl/pdfplumber and XLSX/PDF code removed.
  diff.py           NEW. Pure comparison of two version row-sets -> change buckets; history
                         timeline for one identifier. No DB dependency (takes lists of rows).
  store.py          version-keyed schema; queries gain a version argument (default active);
                         set/get active_version; per-(version, identifier) embeddings.
  identifier.py     NEW (or fold into store). Normalise input to a canonical OSCAL id against
                         a version's id/label index.
  coverage.py       baseline_version + reviewed_against fields; compute_impact() reusing diff.py.
  server.py         version= on lookup tools; new ism_versions/ism_diff/ism_history/
                         ism_coverage_impact wrappers.
  classification.py unchanged.
  __main__.py       fetch / ingest / ingest-history / update subcommands; XLSX/PDF flags gone.
  data/             coverage_template.toml gains baseline_version; path keyword map unchanged.
```

Keeping `oscal.py` (parse), `diff.py` (compare), and `fetch.py` (network/git) as pure, separately testable units keeps each file focused and the orchestration in `ingest.py` thin.

## Testing

All tests hermetic. No network, no real ISM artefacts.

| File | Coverage |
|---|---|
| `tests/test_oscal_parse.py` | Map a small fixture `ISM_catalog.json` to Control rows: ids, labels, applicability props, statement prose, group-to-guideline/section/topic, principles vs controls |
| `tests/test_oscal_maturity.py` | Derive ML1/2/3 from fixture E8 resolved catalogs, including a release with E8 catalogs absent |
| `tests/test_ingest_history.py` | Build a throwaway local git repo in `tmp_path` with 2-3 tagged fixture catalogs, run the tag walk, assert versions load and active is the newest |
| `tests/test_fetch.py` | `--repo` pointed at a local bare repo; clone-then-pull refresh path. No external network |
| `tests/test_store_versions.py` | Version-keyed insert/query, active-version pointer, tolerant identifier normalisation, per-version embeddings |
| `tests/test_diff.py` | added/removed/reworded/retitled/moved/applicability_changed/maturity_changed over in-memory rows; default from/to; possible-rename heuristic |
| `tests/test_history.py` | Timeline assembly, first_seen/last_seen, per-field `changed` markers |
| `tests/test_coverage_impact.py` | re_review/removed_upstream/new_uncovered/still_valid buckets; reviewed_against default and inherit; unloaded-version warning |
| `tests/test_server_versions.py` | End-to-end MCP calls for the new tools and `version=` on existing ones |

Removed: `tests/test_ingest_xlsx.py`, `tests/test_excerpt_extraction.py`. Reworked: `tests/test_ingest_embed.py` for the new embedding text.

A small fixture OSCAL catalog (a handful of controls across two groups, both classes, plus matching tiny E8 catalogs) lives under `tests/fixtures/oscal/`. The tag-walk test constructs its own git repo from two copies of a fixture catalog with different `metadata.version` values.

## Migration and blast radius

- Identifier scheme moves from XLSX `ISM-XXXX` to canonical OSCAL ids. The tolerant normaliser keeps existing manifest keys resolving. Public v1.1 has not shipped yet (it is the current "next action" in HANDOVER), so real-world consumer manifests are effectively nil and migration cost is near zero. No bulk key-rewrite tool unless the user later asks.
- Removed: `openpyxl`, `pdfplumber` from `pyproject.toml`; `parse_xlsx`, `attach_pdf_excerpts`; `--xlsx`/`--pdf` flags; `pdf_excerpt`/`pdf_page` columns; the per-control XLSX `revision` field becomes `control_revision` sourced from OSCAL.
- Docs: README (ingest workflow, architecture, drop the single-revision limitation), HANDOVER, and the `install.py` CLAUDE.md fragment (add the new tools and version awareness). The project CLAUDE.md repository layout and tool inventory. The user-level global CLAUDE.md also references XLSX/PDF and "1081 controls"; flag it for the user (it is their personal file).
- Install and release: `install` still copies one prebuilt `ism.db`. With full history and active-only embeddings the shipped DB is low tens of MB. `prepare-public-release.sh` and the `.mcp.json` env are unaffected.

## Open questions and non-goals

| Item | Decision |
|---|---|
| Precomputed delta tables | Out of scope. On-read deltas are microseconds at this scale. Revisit only if profiling demands it. |
| Strong rename detection | Out of scope. A similarity-flagged candidate is enough; renames are rare and reviewable. |
| Ingesting per-classification resolved catalogs | Not stored. Applicability comes from master props. Optional validation cross-check only. |
| Auto-rewriting old manifest keys | Out of scope. Tolerant lookup covers it. |
| Semantic search over historical versions by default | Out of scope. `--embed-all` is opt-in. Default embeds active only. |
| Exact group-to-guideline/section/topic levels | Resolved in the plan against the real catalog nesting. |
| HTTP/SSE transport, PyPI publish, CI coverage gate | Deferred per the buildout vision, unchanged. |

## Dependencies

- Sub-projects A, B, D, E. Done and on `main`.
- Removes `openpyxl` and `pdfplumber`. Adds no third-party dependency: OSCAL is parsed with stdlib `json`, fetching shells out to `git` (already required by the history walk). `numpy` and `fastembed` are unchanged.

## Sequencing sketch

The implementation plan (writing-plans skill's job) should break work roughly into:

1. `oscal.py` parse plus `tests/test_oscal_parse.py`, `tests/test_oscal_maturity.py`, and the fixture catalog. TDD.
2. Version-keyed `store.py` and tolerant identifier normalisation, plus `tests/test_store_versions.py`. TDD.
3. `fetch.py` and `ingest.py` (single version), plus `tests/test_fetch.py`. Rework `tests/test_ingest_embed.py`.
4. `ingest-history` tag walk plus `tests/test_ingest_history.py`. CLI subcommands wired in `__main__.py`.
5. `diff.py` (delta + history) plus `tests/test_diff.py`, `tests/test_history.py`.
6. `server.py`: `version=` on existing tools, `ism_versions`/`ism_diff`/`ism_history`, plus `tests/test_server_versions.py`.
7. Coverage `baseline_version`/`reviewed_against` and `ism_coverage_impact` plus `tests/test_coverage_impact.py`.
8. Docs: README, install fragment, CLAUDE.md, HANDOVER. Remove dropped XLSX/PDF tests.
