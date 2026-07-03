"""Vocabulary literals and response models for the MCP tools. No runtime logic."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Classification = Literal["NC", "OS", "P", "S", "TS"]
FriendlyClassification = Literal[
    "OFFICIAL", "OFFICIAL:Sensitive", "PROTECTED", "SECRET", "TOP_SECRET"
]
ClassificationInput = Classification | FriendlyClassification
Maturity = Literal["ML1", "ML2", "ML3"]
Status = Literal["covered", "partial", "not-applicable", "deferred"]
ChangeType = Literal[
    "added",
    "removed",
    "reworded",
    "retitled",
    "moved",
    "applicability_changed",
    "maturity_changed",
]
ChangeField = Literal["reworded", "retitled", "moved", "applicability_changed", "maturity_changed"]


class AppliesMap(TypedDict):
    NC: bool
    OS: bool
    P: bool
    S: bool
    TS: bool


class MaturityMap(TypedDict):
    ML1: bool
    ML2: bool
    ML3: bool


class ControlRecord(TypedDict):
    version: str
    identifier: str
    label: str
    title: str
    control_class: str
    guideline: str
    section: str
    topic: str
    description: str
    control_revision: str | None
    updated: str | None
    sort_id: str | None
    applies: AppliesMap
    maturity: MaturityMap


class SearchResult(TypedDict):
    query: str
    count: int
    results: list[ControlRecord]


class ClassificationControls(TypedDict):
    classification: Classification
    count: int
    identifiers: list[str]


class TopicsList(TypedDict):
    count: int
    topics: list[str]


class TopicControls(TypedDict):
    topic: str
    count: int
    identifiers: list[str]


class Stats(TypedDict):
    active_version: str | None
    versions: int
    controls: int
    oscal_version: str | None
    git_tag: str | None
    db_path: str


class VersionEntry(TypedDict):
    version: str
    label: str | None
    published: str | None
    control_count: int | None
    git_tag: str | None
    is_active: bool


class VersionsResult(TypedDict):
    active: str | None
    count: int
    versions: list[VersionEntry]


class SectionsList(TypedDict):
    count: int
    sections: list[str]


class ClassificationVocab(TypedDict):
    canonical: list[Classification]
    friendly: list[FriendlyClassification]


class MaturityVocab(TypedDict):
    maturities: list[Maturity]


class ChangedControlRef(TypedDict):
    identifier: str
    label: str
    title: str
    section: str


class RewordedEntry(TypedDict):
    identifier: str
    label: str
    title: str
    diff: str


RetitledEntry = TypedDict(
    "RetitledEntry",
    {"identifier": str, "label": str, "title": str, "from": str, "to": str},
)


class MoveEndpoint(TypedDict):
    guideline: str
    section: str
    topic: str


MovedEntry = TypedDict(
    "MovedEntry",
    {
        "identifier": str,
        "label": str,
        "title": str,
        "from": MoveEndpoint,
        "to": MoveEndpoint,
    },
)


class ApplicabilityChange(TypedDict):
    identifier: str
    label: str
    title: str
    added: list[Classification]
    removed: list[Classification]


class MaturityChange(TypedDict):
    identifier: str
    label: str
    title: str
    added: list[Maturity]
    removed: list[Maturity]


class DiffSummary(TypedDict):
    added: int | None
    removed: int | None
    reworded: int | None
    retitled: int | None
    moved: int | None
    applicability_changed: int | None
    maturity_changed: int | None


class DiffChanges(TypedDict):
    added: list[ChangedControlRef] | None
    removed: list[ChangedControlRef] | None
    reworded: list[RewordedEntry] | None
    retitled: list[RetitledEntry] | None
    moved: list[MovedEntry] | None
    applicability_changed: list[ApplicabilityChange] | None
    maturity_changed: list[MaturityChange] | None


DiffResult = TypedDict(
    "DiffResult",
    {"from": str, "to": str, "summary": DiffSummary, "changes": DiffChanges},
)


class TimelineEntry(TypedDict):
    version: str
    title: str
    applicability: list[Classification]
    maturity: list[Maturity]
    changed: list[ChangeField]


class HistoryResult(TypedDict):
    identifier: str
    first_seen: str | None
    last_seen: str | None
    timeline: list[TimelineEntry]
    hint: str | None


class AppliedFilters(TypedDict):
    classification: Classification | None
    maturity: Maturity | None
    tags: list[str]
    paths: list[str]


class ApplicableEntry(TypedDict):
    identifier: str
    label: str
    title: str
    topic: str
    section: str
    description: str
    applies: AppliesMap
    maturity: MaturityMap
    score: float
    why: list[str]
    guideline: str | None


class RankedControlRef(TypedDict):
    identifier: str
    score: float
    why: list[str]


class ApplicableResult(TypedDict):
    query: str
    filters: AppliedFilters
    count: int
    candidates_before_filter: int
    results: list[ApplicableEntry]
    hint: str | None


class CoverageEntry(TypedDict):
    status: str
    how_met: str
    last_reviewed: str
    reviewed_against: str | None
    reviewed_by: str | None
    next_review: str | None
    files: list[str]
    commits: list[str]
    urls: list[dict[str, Any]]
    attachments: list[dict[str, Any]]


class CoverageReadResult(TypedDict):
    manifest_path: str
    scope: dict[str, Any]
    project: dict[str, Any]
    summary: dict[str, int]
    controls: dict[str, CoverageEntry]
    warnings: list[str]


class UpsertResult(TypedDict):
    ok: bool
    identifier: str
    action: Literal["created", "updated"]
    warnings: list[str]


class GapCurrentEntry(TypedDict):
    how_met: str
    last_reviewed: str


class GapEntry(TypedDict):
    identifier: str
    topic: str
    section: str
    description: str
    current_status: str
    current_entry: GapCurrentEntry | None
    score: float | None
    why: list[str] | None


class GapsResult(TypedDict):
    scope: dict[str, Any]
    work: str | None
    gaps: list[GapEntry]
    total_outstanding: int
    shown: int


class ImpactSummary(TypedDict):
    re_review: int
    removed_upstream: int
    new_uncovered: int
    still_valid: int


class ReReviewEntry(TypedDict):
    identifier: str
    status: Literal["covered", "partial"]
    reviewed_against: str
    changes: list[ChangeField]
    how_met: str
    diff: str | None


class RemovedUpstreamEntry(TypedDict):
    identifier: str
    status: Literal["covered", "partial"]
    reviewed_against: str
    hint: str


class NewUncoveredEntry(TypedDict):
    identifier: str
    label: str
    title: str
    section: str
    reason: str


class ImpactResult(TypedDict):
    manifest_path: str
    baseline_version: str | None
    target_version: str
    summary: ImpactSummary
    re_review: list[ReReviewEntry]
    removed_upstream: list[RemovedUpstreamEntry]
    new_uncovered: list[NewUncoveredEntry]
