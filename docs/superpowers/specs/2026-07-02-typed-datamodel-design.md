# Typed datamodel and structured outputs design

## Goal

Give every one of the 17 MCP tools a truthful, machine-readable contract: JSON Schema enums on constrained input parameters, a real `outputSchema` with `structuredContent` on every response, and protocol-level error signalling via `ToolError` instead of `{"error": ...}` payloads embedded in success results.

## Problem statement

Every tool today is annotated `-> str` and returns `json.dumps(...)`. Under mcp 1.27.1 that already publishes a junk output schema (`{"result": {"type": "string"}}`) and emits `structuredContent` of `{"result": "<json blob>"}`. Agents cannot rely on field names, constrained vocabularies are prose-only, and failures are ordinary successes that every caller must sniff for an `error` key. Output typing also cannot coexist with the embedded-error convention, so the error contract must change at the same time.

## Decisions locked during brainstorming

- **Errors raise `ToolError`** (`mcp.server.fastmcp.exceptions.ToolError`). Real MCP clients receive `isError=true` with a text message. Soft cases stay successes: an unknown id in `ism_history` (empty timeline plus hint), empty `ism_applicable` results (hint), empty search results.
- **Strict input enums.** `Literal` types on every constrained parameter, enumerating canonical plus friendly spellings where both exist. Free-form spellings ("official-sensitive", integer maturity 2) stop working at the MCP layer. The normalisation helpers in `classification.py` stay for internal use and defence in depth.
- **Modelling idiom: `typing.TypedDict`** (functional syntax where a key is a Python keyword). Stdlib-first per CLAUDE.md and zero construction ceremony: the existing dict-building code keeps working, only annotations change.
- **No conditionally absent keys. Every key is required; conditional ones are `X | None` and the code emits explicit `None`.** Empirical probing showed `NotRequired` cannot deliver absence: FastMCP's synthesized model emits omitted keys as `null` in `structuredContent` regardless, and the wire-level jsonschema validator then rejects that `null` against a non-nullable type, failing the whole call. Making nullability explicit keeps the schema truthful, keeps the text block and `structuredContent` carrying the same JSON object, and gives agents one stable shape per tool.
- **Response payload shapes otherwise do not change**; the full delta is under Behaviour changes.

## SDK facts this design relies on (verified empirically against mcp 1.27.1)

- TypedDict return annotations produce a full object `outputSchema`; plain dict literals returned against them validate and serialise.
- `Literal['a','b']` parameters render as `{"enum": [...]}` in `inputSchema`. `list[Literal[...]]` and `Literal[...] | None` both work. Out-of-enum calls are rejected before the function body runs.
- Raising any exception inside a tool reaches clients as `CallToolResult(isError=true)`.
- FastMCP validates returns against the output schema (pydantic lax mode) and dual-emits: an indent-2 JSON text block plus `structuredContent`. The text serialiser changes from `json.dumps` to `pydantic_core.to_json`, so non-ASCII characters in control text render as raw UTF-8 instead of `\u` escapes.
- Nested TypedDicts, lists of TypedDicts, and `dict[str, TypedDict]` fields all generate correct `$defs` schemas, and a `dict[str, int]` field passes dynamic keys through intact.
- Functional-syntax TypedDicts with `from`/`to` keys render those keys literally in both `outputSchema` and `structuredContent`, and plain dict returns validate against them.
- `NotRequired`/`total=False` keys are emitted as `null` when omitted (no true absence), and the lowlevel wire handler independently jsonschema-validates `structuredContent` against the published schema, so that `null` fails the whole call on the wire with `Output validation error` even though in-process `FastMCP.call_tool` succeeds. Consequence: `NotRequired` is banned from this design as a correctness requirement; conditional keys are required and nullable instead.
- In-process `FastMCP.call_tool` validates only against the synthesized pydantic model; the published-schema jsonschema validation runs only in the lowlevel wire handler. Tests must therefore include wire-level round-trips via `mcp.shared.memory.create_connected_server_and_client_session`.
- Every exception raised inside a tool reaches clients as `CallToolResult(isError=true)` with text `Error executing tool <name>: <message>`. `ToolError` and `ValueError` are wrapped identically; `ToolError` is used for explicit intent, and message assertions must match on substring, not equality.
- The text block is `pydantic_core.to_json(raw_result, indent=2)` of the unvalidated return and `structuredContent` is the validated `model_dump`. They are value-equivalent only when the payload exactly matches the declared model (no extra keys, no int-for-float coercions); key order and non-ASCII rendering can differ. No test may compare the two byte-for-byte.
- TypedDict validation silently strips any key the model does not declare from `structuredContent` (the text block keeps it). Consequence: the test suite must assert `structuredContent` equals the raw payload for representative calls, so a forgotten field fails CI instead of vanishing quietly.
- `@mcp.tool(annotations=...)` and typed returns coexist; both surfaces appear on the listed tool.

## Architecture

One new module, `src/ism_mcp/models.py`, holding all vocabulary `Literal` aliases and response TypedDicts. No runtime logic. `server.py` imports models for annotations; `coverage.py` imports `Status` from models (today it defines its own `Status` literal; it moves so both share one definition without circularity, since models imports nothing internal).

Changes per tool in `server.py`: the return annotation, `json.dumps` removal, error returns replaced with `raise ToolError(...)`, typed parameters, and explicit `None` for every key that is conditional today. The None-backfill touches dict construction beyond annotations: `_render_result` always sets `guideline` (None unless verbose), `ism_applicable` and `ism_history` always set `hint`, the unknown-id history path sets `first_seen`/`last_seen` to None, and the `ism_diff` `change_types` filter nulls unrequested buckets instead of deleting the keys. In `coverage.py`, `compute_gaps` always emits `current_entry`, `score`, and `why` (None where it omits them today) and `compute_impact` always emits `diff` on re-review entries.

## Vocabulary aliases (models.py)

```python
Classification = Literal["NC", "OS", "P", "S", "TS"]
FriendlyClassification = Literal[
    "OFFICIAL", "OFFICIAL:Sensitive", "PROTECTED", "SECRET", "TOP_SECRET"
]
ClassificationInput = Classification | FriendlyClassification
Maturity = Literal["ML1", "ML2", "ML3"]
Status = Literal["covered", "partial", "not-applicable", "deferred"]
ChangeType = Literal[
    "added", "removed", "reworded", "retitled", "moved",
    "applicability_changed", "maturity_changed",
]
ChangeField = Literal[
    "reworded", "retitled", "moved", "applicability_changed", "maturity_changed"
]
```

## Response model catalog

Shared:

- `AppliesMap`: `{NC, OS, P, S, TS: bool}` (exactly five keys).
- `MaturityMap`: `{ML1, ML2, ML3: bool}`.
- `ControlRecord`: `version, identifier, label, title, control_class, guideline, section, topic, description: str`, `control_revision, updated, sort_id: str | None`, `applies: AppliesMap`, `maturity: MaturityMap`. Matches `store.Control.as_dict` exactly.

Per tool:

| Tool | Return model | Notes |
|---|---|---|
| ism_get | `ControlRecord` | whole payload is the record |
| ism_search | `SearchResult{query: str, count: int, results: list[ControlRecord]}` | |
| ism_list_by_classification | `ClassificationControls{classification: Classification, count: int, identifiers: list[str]}` | |
| ism_list_topics | `TopicsList{count: int, topics: list[str]}` | |
| ism_list_by_topic | `TopicControls{topic: str, count: int, identifiers: list[str]}` | |
| ism_stats | `Stats{active_version: str | None, versions: int, controls: int, oscal_version: str | None, git_tag: str | None, db_path: str}` | |
| ism_versions | `VersionsResult{active: str | None, count: int, versions: list[VersionEntry]}`, `VersionEntry{version: str, label: str | None, published: str | None, control_count: int | None, git_tag: str | None, is_active: bool}` | |
| ism_list_sections | `SectionsList{count: int, sections: list[str]}` | |
| ism_list_classifications | `ClassificationVocab{canonical: list[Classification], friendly: list[FriendlyClassification]}` | |
| ism_list_maturities | `MaturityVocab{maturities: list[Maturity]}` | |
| ism_diff | `DiffResult` (functional: `{"from": str, "to": str, "summary": DiffSummary, "changes": DiffChanges}`) | see below |
| ism_history | `HistoryResult{identifier: str, first_seen: str | None, last_seen: str | None, timeline: list[TimelineEntry], hint: str | None}`, `TimelineEntry{version: str, title: str, applicability: list[Classification], maturity: list[Maturity], changed: list[ChangeField]}` | |
| ism_applicable | `ApplicableResult{query: str, filters: AppliedFilters, count: int, candidates_before_filter: int, results: list[ApplicableEntry], hint: str | None}` | |
| ism_coverage_read | `CoverageReadResult{manifest_path: str, scope: dict[str, Any], project: dict[str, Any], summary: dict[str, int], controls: dict[str, CoverageEntry], warnings: list[str]}` | |
| ism_coverage_upsert | `UpsertResult{ok: bool, identifier: str, action: Literal["created", "updated"], warnings: list[str]}` | |
| ism_coverage_gaps | `GapsResult{scope: dict[str, Any], work: str | None, gaps: list[GapEntry], total_outstanding: int, shown: int}` | |
| ism_coverage_impact | `ImpactResult{manifest_path: str, baseline_version: str | None, target_version: str, summary: ImpactSummary, re_review: list[ReReviewEntry], removed_upstream: list[RemovedUpstreamEntry], new_uncovered: list[NewUncoveredEntry]}` | |

Detail models:

- `DiffSummary` and `DiffChanges`: TypedDicts with all seven bucket keys required and nullable (`int | None` and `list[...] | None`). An unrequested bucket under a `change_types` filter is `null`; an unfiltered call populates all seven. Bucket value types: `added`/`removed`: `list[ChangedControlRef]` where `ChangedControlRef{identifier, label, title, section: str}`; `reworded`: `list[RewordedEntry{identifier, label, title, diff: str}]`; `retitled`: `list[RetitledEntry]` (functional, has `from`/`to`: str plus identifier, label, title); `moved`: `list[MovedEntry]` (functional, `from`/`to`: `MoveEndpoint{guideline, section, topic: str}` plus identifier, label, title); `applicability_changed`: `list[ApplicabilityChange{identifier, label, title: str, added: list[Classification], removed: list[Classification]}]`; `maturity_changed`: same with `list[Maturity]`. Modelling buckets as fixed keys avoids union-typed lists entirely.
- `AppliedFilters{classification: Classification | None, maturity: Maturity | None, tags: list[str], paths: list[str]}`.
- `ApplicableEntry{identifier, label, title, topic, section, description: str, applies: AppliesMap, maturity: MaturityMap, score: float, why: list[str], guideline: str | None}` (`guideline` populated only with `verbose=true`, `null` otherwise).
- `CoverageEntry{status: str, how_met: str, last_reviewed: str, reviewed_against: str | None, reviewed_by: str | None, next_review: str | None, files: list[str], commits: list[str], urls: list[dict[str, Any]], attachments: list[dict[str, Any]]}`. `status` stays plain `str` (the read path accepts any status string from a hand-edited manifest) and `urls`/`attachments` stay loose dicts (their key sets are only validated on upsert). The scalar fields are typed `str` even though the read path never checked them; the consequence for pathological manifests is declared as Behaviour change 7.
- `summary` in `CoverageReadResult` is `dict[str, int]`, not a fixed TypedDict: it carries the five standard counters plus one dynamic key per nonstandard status found in a hand-edited manifest.
- `GapEntry{identifier, topic, section, description: str, current_status: str, current_entry: GapCurrentEntry | None, score: float | None, why: list[str] | None}`, `GapCurrentEntry{how_met: str, last_reviewed: str}`. `current_entry` is `null` when uncurated; `score`/`why` are `null` outside work mode.
- `ImpactSummary{re_review: int, removed_upstream: int, new_uncovered: int, still_valid: int}`.
- `ReReviewEntry{identifier: str, status: Literal["covered", "partial"], reviewed_against: str, changes: list[ChangeField], how_met: str, diff: str | None}` (`diff` populated iff reworded, `null` otherwise).
- `RemovedUpstreamEntry{identifier: str, status: Literal["covered", "partial"], reviewed_against: str, hint: str}`.
- `NewUncoveredEntry{identifier, label, title, section, reason: str}`.

## Typed input parameters

| Tool | Param | New type |
|---|---|---|
| ism_list_by_classification | classification | `Classification` (canonical uppercase only; today's case-insensitive tolerance drops at the MCP layer, `store` keeps it for direct calls) |
| ism_applicable | classification | `ClassificationInput | None` |
| ism_applicable | maturity | `Maturity | None` (drops `"1"`/`2` tolerance at the protocol layer) |
| ism_diff | change_types | `list[ChangeType] | None` (today unknown names silently yield empty buckets; the enum rejects them) |
| ism_coverage_upsert | status | `Status` (removes the `type: ignore` at the ManifestEntry construction) |
| ism_coverage_read | status_filter | `Status | None` (today unvalidated; a typo silently returned an empty map) |

Everything else keeps its current type: `identifier` and `version` parameters stay `str` (dynamic or deliberately tolerant vocabularies), `tags`/`paths` stay `list[str] | None` (validated against the live DB), `limit` stays `int` with the existing clamp to [1, 200].

## Error contract

Every current `{"error": ...}` return becomes `raise ToolError(message)`. Hints fold verbatim into the message after the main clause, separated by `. `: `"no such version: 2020.01.01. call ism_versions"`. Existing message texts are preserved exactly (clients additionally see FastMCP's mandatory `Error executing tool <name>: ` prefix). The full conversion set:

- ism_get: unknown control.
- ism_list_by_classification: unknown classification (unreachable through MCP once the enum lands, kept for direct calls).
- ism_diff: need two versions (hint folded), no earlier version, no such version (hint folded).
- ism_applicable: unknown classification, unknown maturity, unknown tags.
- All four coverage tools: no manifest found (hint folded), manifest parse errors.
- ism_coverage_gaps and ism_coverage_impact: scope errors (the other two coverage tools have no scope-error path).
- ism_coverage_upsert: unknown control, date format, every `validate_entry` failure, and the caught `FileNotFoundError` from `upsert_entry`'s internal manifest read.
- ism_coverage_impact: no such target version (hint folded).
- ism_coverage_gaps: nested applicable failures propagate as ToolError with the `ism_applicable: ` prefix preserved.

Not errors (unchanged): `_conn()` missing-DB `RuntimeError` and `IncompatibleSchemaError` keep raising as-is (FastMCP already wraps any exception into an isError result with the message). `ism_history` unknown id and `ism_applicable` filtered-to-empty stay soft successes with hints.

## Behaviour changes (the honest list)

1. Text content stays indent-2 JSON, but `structuredContent` changes from `{"result": "<blob>"}` to the real object. Any client reading `structuredContent["result"]` breaks; none are known to exist.
2. Failures switch channels: `isError=true` instead of a parseable `{"error": ...}` success. This is the point of the redesign.
3. Conditionally absent keys become explicit nulls everywhere: `guideline` (non-verbose), `hint` (both tools that carry one), `current_entry`/`score`/`why` on gap entries, `diff` on re-review entries, filtered-out `ism_diff` buckets, and `first_seen`/`last_seen` on the unknown-id history path. Keys never disappear from a payload; unpopulated means `null`.
4. Enum-typed inputs reject spellings the old normaliser or validator accepted (`"official sensitive"`, `maturity=2`, lowercase canonical codes on `ism_list_by_classification`, unknown `change_types` names, invalid `status_filter`). Rejection happens at the MCP layer with a pydantic message.
5. `ism_coverage_gaps` calls the applicable logic directly (shared helper) instead of `json.loads`-ing its own sibling tool's string output.
6. The JSON text block switches serialiser: non-ASCII characters in control text render as raw UTF-8 instead of `\u` escapes.
7. Hand-edited manifests carrying non-string scalars in typed fields (`how_met = 3`, `files = [1]`, `reviewed_against = 2025.12`) now fail every manifest-reading tool with a clean manifest validation error raised by `coverage._entry_from_dict`, instead of passing through (or, worse, surfacing as an opaque output-schema validation dump from gaps or impact). `urls`, `attachments`, `scope`, and `project` remain loose by design, and `status` accepts any string on read.

## Internal refactors

- `ism_applicable` body extracts into `_applicable_result(...) -> ApplicableResult` used by both the tool and `ism_coverage_gaps` (removes the tool-calls-tool JSON round-trip at server.py:752-763).
- `coverage.compute_gaps`'s `applicable` parameter type tightens to the entry shape it reads (`identifier`, `score`, `why`); TypedDicts are plain dicts at runtime so no call-site conversion is needed.
- `coverage.py` imports `Status` from `models.py` instead of defining it.
- The FastMCP `instructions` string is rewritten with two edits: drop the "all tools return JSON strings" claim in favour of typed structured results, and replace the `{"error": ...}` failure sentence with isError semantics.
- Docstrings drop `Returns {"error": ...}` phrasing in favour of `Fails with ...` wording.

## Testing

Existing suite: 53 `json.loads(tool(...))` sites lose the `json.loads` (tools now return dicts); 12 error-dict assertions become `pytest.raises(ToolError)`; the missing-DB `RuntimeError` test is unchanged. New tests, in a new `tests/test_server_schema.py`:

- every tool's `outputSchema` is non-null and object-typed, and none is the wrapped `{"result": ...}` shape;
- enum parameters render as JSON Schema enums (spot-check classification, status, change_types);
- a wire-level round-trip per response family via `create_connected_server_and_client_session`, exercising the published-schema jsonschema validation and asserting `isError` is false with non-null `structuredContent`;
- out-of-enum inputs (classification, maturity, status, change_types) are rejected at the MCP layer without the tool body running;
- `from`/`to` keys appear literally in the diff schema and a retitled/moved payload round-trips;
- `structuredContent` equals the raw returned payload for one representative call per response family (catches TypedDict validation silently stripping an undeclared key);
- conditional keys (`guideline`, `hint`, `current_entry`, `diff`, filtered diff buckets) are present with `null` when not applicable;
- error paths raise ToolError with the expected message asserted by substring, including the `ism_applicable: ` prefix on a gaps scope failure.

## Migration and blast radius

`server.py` (all 17 tools plus helpers), new `models.py`, `coverage.py` (Status import, `compute_gaps`/`compute_impact` None-backfill and annotations), 6 test files touched, README gains a short error-contract paragraph (isError, no `{"error": ...}` payloads). `install.py`: no change, its generated guidance does not describe error behaviour. CLAUDE.md repository layout gains `models.py`; HANDOVER.md updates at branch close. Tool annotations (`READ_ONLY`, `WRITES_MANIFEST`) are preserved on every decorator. `store.py` changes only the `Control.as_dict` return annotation to `models.ControlRecord`. No oscal/ingest/retrieve changes: they already return typed dataclasses or plain dicts; `diff.py` is untouched (the history `hint`/`first_seen`/`last_seen` backfill happens in the tool body).

## Non-goals

- No output-side pydantic models: TypedDict covers every confirmed need (keyword keys, nullable conditionals, dynamic maps via `dict[str, T]` fields).
- No new tools, no payload redesign beyond the honest list above.
- No PyPI or transport changes.

## Sequencing sketch

1. `models.py` with vocabulary aliases and all TypedDicts; coverage imports Status.
2. Lookup family (get, search, list_*, stats, versions, sections, vocab tools): typed returns, ToolError, test updates.
3. Diff and history family, including the keyword-key models.
4. Applicable family plus the shared `_applicable_result` helper.
5. Coverage family (read, upsert, gaps, impact): typed params, loose read models, ToolError.
6. Schema round-trip test module, instructions/docstring updates, README, full CI.
