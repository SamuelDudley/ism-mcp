# Coverage manifest design

> Sub-project D of the ism-mcp build-out. See `2026-05-28-ism-mcp-buildout-vision.md` for context.

## Goal

Give consumer projects a version-controlled, IRAP-grade record of how each in-scope ISM control is addressed, with secondary gap detection that tells an agent what's still missing.

## Problem statement

Sub-project B answers "what controls apply to this work?" by querying the ISM in real time. It has no memory of decisions the project has already made: which controls have been considered, how they're met, what evidence exists. Without that memory, the agent re-derives the same answer every time, can't surface coverage gaps, and can't help with audit preparation.

The headline use case is IRAP review. An assessor needs to see, per applicable control, a project-specific narrative of how the control is met and concrete evidence (commits, file ranges, screenshots, pcaps, dataflow exports, supporting docs). The secondary use case is gap detection during planning: "we're adding SAML SSO, which relevant controls don't have entries yet?"

## Architecture

```
consumer repo/                        ism-mcp server (this project)
  .ism-coverage.toml      ────►       coverage.py
    [scope]                              read_manifest()
    classification, ...                  upsert_entry()
    [controls.ISM-XXXX]                  compute_gaps()
    status, how_met, evidence...                │
                                                │
  .ism-coverage/evidence/             server.py registers three
    ISM-0428/                         @mcp.tool() wrappers around
      lock-prompt.png                 coverage.py functions.
      tls-handshake.pcapng            Gap mode reuses ism_applicable
      ...                             from sub-project B.
```

The manifest lives at the repo root (`.ism-coverage.toml`), version-controlled. A sibling `.ism-coverage/evidence/` directory is the recommended (not enforced) location for committed binary evidence so audit artefacts stay co-located with the manifest pointing at them.

The server walks up from cwd to find `.ism-coverage.toml`. The MCP server's cwd is the consumer project root in normal usage (each Claude Code session spawns its own server in the session's working directory).

## Manifest schema

TOML, single file. Top-level keys: `schema_version`, `[scope]`, `[project]`, and `[controls.<ID>]` tables.

```toml
schema_version = 1

[scope]
classification = "P"              # NC | OS | P | S | TS (or friendly: PROTECTED etc.)
maturity = "ML2"                  # ML1 | ML2 | ML3 (optional)
sections = [                      # optional: narrow to specific ISM sections
    "Authentication hardening",
    "Cryptographic fundamentals",
    "Web application development",
]

[project]
name = "wayland-remote-admin"     # informational, free-form
description = "Admin console for the foo platform"

[controls."ISM-0428"]
status = "covered"                # covered | partial | not-applicable | deferred
how_met = """
Sessions terminate after 14 min of idle activity, enforced
in the auth middleware. Re-auth requires all original factors.
"""
last_reviewed = 2026-05-28        # ISO 8601 date
reviewed_by = "sam.dudley"        # optional
next_review = 2027-05-28          # optional, IRAP cadence
files = [
    "src/auth/session.py:42-87",
    "tests/test_session_lock.py:15-60",
]
commits = ["abc1234"]

[[controls."ISM-0428".urls]]
url = "https://confluence.example/IRAP/session-policy"
description = "Authoritative session policy doc, signed off by CISO 2026-02"

[[controls."ISM-0428".attachments]]
path = ".ism-coverage/evidence/ISM-0428/lock-prompt.png"
description = "Admin console at 14:01 showing session-expired modal after 14 min idle"

[[controls."ISM-0428".attachments]]
path = ".ism-coverage/evidence/ISM-0428/tls-handshake.pcapng"
description = "TLS handshake capture confirming TLSv1.3 + AES-256-GCM"
```

### Fields per control entry

| Field | Required | Type | Meaning |
|---|---|---|---|
| `status` | yes | enum | `covered` \| `partial` \| `not-applicable` \| `deferred` |
| `how_met` | yes | string | Narrative explaining how the control is satisfied in this project's context |
| `last_reviewed` | yes (auto) | date | Auto-stamped to today on every upsert if not supplied |
| `reviewed_by` | no | string | Who signed off |
| `next_review` | no | date | When this entry needs re-confirmation |
| `files` | no | list[string] | Repo file paths, optional `:line-range` suffix |
| `commits` | no | list[string] | Git commit SHAs |
| `urls` | no | list[table] | `{url, description}` pairs |
| `attachments` | no | list[table] | `{path, description}` pairs, path must resolve on disk |

### Evidence shape rationale

`files`, `commits` stay as terse strings because the agent can resolve them (Read for files, `git show` for commits) and self-describe. `urls` and `attachments` are structured with required `description` because:

- An offline auditor can't follow URLs
- Binary attachments (PNGs, pcaps, docs) are opaque to the agent without explanation

Bare strings are not accepted for `urls` or `attachments`. The schema is asymmetric on purpose.

### Status semantics for gap detection

| Status | Meaning | Counts as gap? |
|---|---|---|
| `covered` | In compliance, evidence linked | No |
| `partial` | Some work done, more needed | Yes, surfaced with current status |
| `not-applicable` | Waived with reason | No |
| `deferred` | Acknowledged, scheduled later | Yes, surfaced with lower urgency than uncurated |
| *uncurated* (no entry) | Control in scope, never reviewed | Yes, surfaced as `uncurated` (highest urgency) |

## Tool surface

Three MCP tools, registered in `server.py`. All accept `project_path` as an optional override; the default walks up from cwd.

### `ism_coverage_read(project_path=None, status_filter=None) -> str`

Returns the full manifest as a JSON string.

```python
{
    "manifest_path": "/path/to/.ism-coverage.toml",
    "scope": {
        "classification": "P",
        "maturity": "ML2",
        "sections": ["Authentication hardening", "..."]
    },
    "project": {"name": "...", "description": "..."},
    "summary": {
        "total_curated": 47,
        "covered": 32, "partial": 8, "not_applicable": 5, "deferred": 2
    },
    "controls": {
        "ISM-0428": {
            "status": "covered",
            "how_met": "Sessions terminate after 14 min...",
            "last_reviewed": "2026-05-28",
            "reviewed_by": "sam.dudley",
            "next_review": "2027-05-28",
            "files": ["src/auth/session.py:42-87"],
            "commits": ["abc1234"],
            "urls": [{"url": "...", "description": "..."}],
            "attachments": [{"path": "...", "description": "..."}]
        }
    },
    "warnings": ["attachment missing on disk: ...", "..."]
}
```

`status_filter` narrows `controls` to a single status. The `summary` block always reflects the unfiltered totals.

`warnings` is a top-level list containing soft issues found during the read: dangling attachment paths, identifiers not present in the current ISM revision, etc. The read still succeeds.

### `ism_coverage_upsert(identifier, status, how_met, last_reviewed=None, reviewed_by=None, next_review=None, files=None, commits=None, urls=None, attachments=None, project_path=None) -> str`

Writes or updates one entry. Validation before write:

- `identifier` must exist in the ISM DB (via `store.get_control`)
- `status` must be one of the four enum values
- `urls` items must have both `url` and `description`
- `attachments` items must have both `path` and `description`, and `path` must resolve to an existing file relative to the project root
- If `identifier` is outside the declared scope, the write succeeds but the response includes a warning

Defaults applied:

- `last_reviewed` defaults to today (ISO 8601) if not supplied

Manifest writes are atomic: write to a temp file in the same directory then `os.replace` over the original. A crash mid-write leaves the original intact.

Response:

```python
{
    "ok": true,
    "identifier": "ISM-0428",
    "action": "created" | "updated",
    "warnings": []
}
```

On error:

```python
{"error": "attachment not found: .ism-coverage/evidence/ISM-0428/foo.png"}
```

### `ism_coverage_gaps(work=None, project_path=None, limit=50) -> str`

Two modes.

**With `work`:** runs `ism_applicable(work, classification=scope.classification, maturity=scope.maturity, tags=scope.sections, limit=200)`, subtracts controls already at status `covered` or `not-applicable`, returns the remainder with their current manifest status.

**Without `work`:** returns the full in-scope set minus controls at `covered`/`not-applicable`. Useful for "show me everything outstanding". Default `limit=50`; `total_outstanding` reports the unlimited count.

```python
{
    "scope": {"classification": "P", "maturity": "ML2", "sections": [...]},
    "work": "adding SAML SSO via Okta" | null,
    "total_outstanding": 87,
    "shown": 50,
    "gaps": [
        {
            "identifier": "ISM-1872",
            "topic": "Multi-factor authentication",
            "section": "Authentication hardening",
            "description": "Multi-factor authentication is used to authenticate...",
            "current_status": "partial",
            "score": 0.4912,
            "why": ["semantic", "lexical"],
            "current_entry": {
                "how_met": "Enforced for admin portal logins...",
                "last_reviewed": "2026-04-12"
            }
        }
    ]
}
```

Ordering:

- With `work`: by RRF score descending (as `ism_applicable` returns)
- Without `work`: by `(status_priority, identifier)` where priority is `uncurated > partial > deferred`

`score`, `why`, and ISM control details (`topic`, `section`, `description`) are always populated. `current_entry` is populated only when `current_status != "uncurated"`.

If no controls match a given `work` description:

```python
{"gaps": [], "total_outstanding": 0, "hint": "no controls matched the work description; rephrase or call coverage_gaps with no work argument for the full outstanding list"}
```

## Workflow scenarios

**Scenario A — Agent doing security-relevant work spots a gap.** User asks Claude to add SAML SSO. Claude calls `ism_applicable("adding SAML SSO via Okta")` for candidate controls, then `ism_coverage_gaps(work="adding SAML SSO via Okta")` for the subset not yet handled. Surfaces both: "Three relevant controls are uncurated, one is partial. Want me to draft entries as we implement?"

**Scenario B — User asks for current state.** `ism_coverage_read()` returns scope, summary counts, all controls. Agent reports: "Scope PROTECTED ML2 across 4 sections. 47 curated: 32 covered, 8 partial, 5 not-applicable, 2 deferred. 87 in-scope controls remain uncurated."

**Scenario C — Pre-audit triage.** `ism_coverage_read(status_filter="partial")` then `status_filter="deferred"` for the curated work-in-progress. `ism_coverage_gaps()` (no work arg) for the uncurated outstanding set. Agent assembles a prioritised triage list.

**Scenario D — Implementation lands, evidence recorded.** After Claude finishes implementing session timeout, agent calls `ism_coverage_upsert("ISM-0428", "covered", how_met="Sessions terminate after 14 min...", files=["src/auth/session.py:42-87", "tests/test_session_lock.py:15-60"], commits=["abc1234"], reviewed_by="sam.dudley")`. `last_reviewed` auto-stamps to today. The change shows up in `git diff` for normal PR review.

## Edge cases

| Case | Behaviour |
|---|---|
| No `.ism-coverage.toml` found from cwd | All tools return `{"error": "no manifest found", "hint": "create .ism-coverage.toml at the project root with at minimum a [scope] section"}` |
| Manifest exists but unparseable TOML | Return `{"error": "manifest at <path> is not valid TOML", "detail": "<tomllib message>"}`. No write attempted. |
| `identifier` doesn't exist in ISM DB | `coverage_upsert` returns `{"error": "no such control: ISM-9999. Use ism_search or ism_list_topics to find the right id."}` |
| Identifier in manifest no longer in ISM (revision change) | `coverage_read` includes it under `controls` with a per-entry warning. Does not drop. |
| Attachment path in TOML but file missing on disk | `coverage_read` reports it in the top-level `warnings` list. `coverage_upsert` validates only what it is writing. |
| Identifier outside declared scope | `coverage_upsert` succeeds with a warning. Does not silently drop. |
| `ism_applicable` returns nothing for `work` (gap mode) | `coverage_gaps` returns empty list with a `hint`. |
| Concurrent edits | Last write wins. Git history is the audit trail. No file locking. |
| Scope changed after entries exist | Existing entries stay. Newly-out-of-scope entries surface a warning in `coverage_read`. Migration is a manual choice. |

## Code organisation

```
src/ism_mcp/
  coverage.py             NEW. read_manifest, upsert_entry, compute_gaps. Plain functions, no MCP dependency.
  data/
    coverage_template.toml  NEW. Minimal valid manifest used by docs and (future) scaffolding.
  server.py               extend with three @mcp.tool() wrappers around coverage.py.
  store.py                unchanged.
  __main__.py             unchanged.
```

`coverage.py` exports:

```python
@dataclass(frozen=True)
class ManifestEntry:
    identifier: str
    status: Literal["covered", "partial", "not-applicable", "deferred"]
    how_met: str
    last_reviewed: date
    reviewed_by: str | None = None
    next_review: date | None = None
    files: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    urls: list[dict[str, str]] = field(default_factory=list)
    attachments: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    path: Path
    schema_version: int
    scope: dict
    project: dict
    controls: dict[str, ManifestEntry]
    warnings: list[str]


def find_manifest(start: Path) -> Path | None: ...
def read_manifest(path: Path) -> Manifest: ...
def upsert_entry(path: Path, entry: ManifestEntry) -> dict: ...
def compute_gaps(
    manifest: Manifest,
    in_scope_controls: list,
    applicable_results: list | None = None,
) -> list[dict]: ...
```

`server.py` wraps each: handles cwd-walk-up, calls into `coverage.py`, JSON-serialises with date support, returns the response string.

Atomic writes are implemented as: serialise to bytes, write to `manifest.toml.tmp` in the same directory, `os.replace(tmp, manifest.toml)`. Same directory is required so the rename is atomic on POSIX.

## Testing

All tests hermetic. No real ISM XLSX/PDF required.

| File | Coverage |
|---|---|
| `tests/test_coverage_manifest.py` | TOML parse/serialise round-trip, schema validation, evidence shape constraints, attachment-path resolution helpers |
| `tests/test_coverage_read.py` | Happy path, status filter, summary counts, missing manifest, malformed TOML, dangling-attachment warnings, identifier-not-in-current-ISM warnings |
| `tests/test_coverage_upsert.py` | Create, update, atomic write (tempfile + replace), all validation errors, identifier-not-in-ISM, out-of-scope warning, attachment-not-found, last_reviewed default |
| `tests/test_coverage_gaps.py` | With and without `work`, intersection logic, ordering (status priority and score), limit handling, total_outstanding count, empty-result hint |
| `tests/test_server_coverage.py` | End-to-end MCP tool calls via `server.ism_coverage_*`, using `tmp_path` + the existing `sample_controls` fixture |

New `conftest.py` fixtures:

- `temp_project(tmp_path, monkeypatch)`: writes a known-good `.ism-coverage.toml` into `tmp_path`, monkeypatches `os.getcwd` to that path, yields the path
- `sample_manifest_text`: a known-good TOML string covering all four status values, all evidence types

## Open questions and non-goals

| Item | Decision |
|---|---|
| Schema versioning beyond v1 | `schema_version = 1` is declared. Breaking changes bump the integer. Migration helpers not in scope until v2 is needed. |
| Cross-repo aggregation (org-level rollup) | Out of scope. The manifest is per-project. Future work if consumers ask. |
| Auto-suggesting `not-applicable` reasons | Out of scope. Agent can propose text in conversation; user reviews and supplies the final wording. |
| CI gate (PR fails if coverage regresses) | Deferred per the buildout vision. Decide after the suite stabilises. |
| Manifest scaffolding (writing the empty file with `[scope]` filled in) | Sub-project E's job. D assumes the manifest exists or surfaces the missing-manifest error. |
| Cross-control "supersedes" relationships | Out of scope. If ISM-X is satisfied because ISM-Y is, encode it in `how_met` prose. |

## Dependencies

- Sub-project A (hardening): pytest, ruff, pyright, `scripts/ci.sh`, hermetic fixtures. **Done.**
- Sub-project B (hybrid discovery): `ism_applicable` is called from `ism_coverage_gaps(work=...)`. **Done.**
- No new top-level dependencies. `tomllib` (standard library since 3.11) handles reads. Writes use a hand-rolled serialiser for the subset of TOML we emit. We control the shape, the subset is small (tables, arrays of tables, strings, dates, integers, lists of strings), and avoiding `tomli_w` keeps the dependency footprint at zero.

## Sequencing inside the plan

The implementation plan should break work into roughly the following tasks (final plan is the writing-plans skill's job, this is a sketch):

1. `coverage.py` core: dataclasses, `find_manifest`, `read_manifest`, validation helpers. TDD against `tests/test_coverage_manifest.py` and `tests/test_coverage_read.py`.
2. `coverage.py` writes: `upsert_entry` with atomic write and full validation. TDD against `tests/test_coverage_upsert.py`.
3. `coverage.py` gap computation: `compute_gaps` taking optional `ism_applicable` results. TDD against `tests/test_coverage_gaps.py`.
4. `server.py` wrappers: three `@mcp.tool()` functions, cwd-walk-up, JSON serialisation with date handling. TDD against `tests/test_server_coverage.py`.
5. Documentation: README section on the coverage manifest, link to this spec.
6. HANDOVER update: D marked done, next pointer at sub-project C or E depending on user preference.
