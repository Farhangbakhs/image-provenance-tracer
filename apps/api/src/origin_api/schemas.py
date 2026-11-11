"""Response models. These define the OpenAPI schema the web client is generated from."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from origin_core.enums import AnalystStatus, C2PAState, RunStatus


class Livez(BaseModel):
    status: Literal["ok"]
    version: str


class DependencyCheck(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None


class Readyz(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, DependencyCheck]


class StageState(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["running", "succeeded", "failed"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: dict[str, int] = {}
    quota: dict[str, int] = {}
    notes: dict[str, str] = {}
    error: str | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    asset_id: uuid.UUID
    status: RunStatus
    providers: list[str]
    stages: dict[str, StageState]
    stage_order: list[str]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_row(cls, row: Any, stage_order: list[str]) -> RunOut:
        return cls(
            id=row.id,
            case_id=row.case_id,
            asset_id=row.asset_id,
            status=row.status,
            providers=list(row.providers),
            stages={k: StageState.model_validate(v) for k, v in dict(row.stages).items()},
            stage_order=stage_order,
            error=row.error,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )


# --- Cases and assets -------------------------------------------------------------------


class CaseIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)


class AssetBrief(BaseModel):
    id: uuid.UUID
    original_filename: str | None
    width: int
    height: int
    c2pa_state: C2PAState
    created_at: datetime


class CaseOut(BaseModel):
    id: uuid.UUID
    title: str
    notes: str | None
    created_at: datetime
    assets: list[AssetBrief] = []


class Fingerprints(BaseModel):
    sha256: str
    phash: str
    dhash: str
    pdq: str
    pdq_quality: int


class CaptureTime(BaseModel):
    stated: str
    tag: str
    utc: datetime | None


class MetadataSummary(BaseModel):
    capture_time: CaptureTime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    software: str | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    credit: str | None = None
    copyright: str | None = None
    groups: list[str] = []


class MetadataOut(BaseModel):
    """`unavailable` means exiftool could not run: not the same as "no metadata"."""

    status: Literal["ok", "unavailable"]
    tool: str | None = None
    tool_version: str | None = None
    summary: MetadataSummary | None = None
    tag_count: int = 0
    error: str | None = None


class CredentialsOut(BaseModel):
    state: C2PAState
    trust_list: str
    validation_state: str | None = None
    failures: list[str] = []
    signer_issuer: str | None = None
    signer_common_name: str | None = None
    signed_at: datetime | None = None
    claim_generator: str | None = None
    title: str | None = None
    actions: list[str] = []
    error: str | None = None


class EmbeddingOut(BaseModel):
    status: Literal["computed", "pending"]
    model: str | None


class AssetOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    original_filename: str | None
    content_type: str
    width: int
    height: int
    byte_size: int
    created_at: datetime
    fingerprints: Fingerprints
    metadata: MetadataOut
    credentials: CredentialsOut
    embedding: EmbeddingOut
    display_url: str
    runs: list[RunBrief] = []


class RunBrief(BaseModel):
    id: uuid.UUID
    status: RunStatus
    created_at: datetime


class AssetEvidence(BaseModel):
    """The full stored records behind the asset panel's summaries."""

    metadata_raw: dict[str, Any] | None
    c2pa_manifest_store: dict[str, Any] | None


class UploadRejectedOut(BaseModel):
    reason: str
    message: str


# --- Sightings --------------------------------------------------------------------------


class EvidenceOut(BaseModel):
    id: uuid.UUID
    kind: str
    value: datetime
    bound: str
    confidence: str
    source_url: str | None
    detail: dict[str, Any]


class SightingOut(BaseModel):
    id: uuid.UUID
    provider: str
    page_url: str | None
    image_url: str
    domain: str
    title: str | None
    match_class: str
    match_reason: str | None
    sscd_cosine: float | None
    phash_distance: int | None
    pdq_distance: int | None
    transform: dict[str, Any] | None
    threshold_version: str
    date_lower: datetime | None
    date_upper: datetime | None
    date_confidence: str
    dating_rule_version: str | None
    deciding: EvidenceOut | None
    evidence: list[EvidenceOut]
    image_url_local: str
    variant_id: uuid.UUID | None = None
    reliability: str | None = None
    credibility: int | None = None
    grade_rationale: str | None = None
    analyst_status: AnalystStatus = AnalystStatus.ACCEPTED
    analyst_note: str | None = None
    #: The page text shown to the claim model; claim quote offsets index into it.
    extracted_text: str | None = None


class CandidateCounts(BaseModel):
    pending: int = 0
    verified: int = 0
    unrelated: int = 0
    fetch_failed: int = 0


class RunSightingsOut(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    earliest_sighting_id: uuid.UUID | None
    candidates: CandidateCounts
    notes: dict[str, str]
    sightings: list[SightingOut]


# --- Branching: variants, edges, claims, narratives -------------------------------------


class VariantOut(BaseModel):
    id: uuid.UUID
    label: str
    representative_sighting_id: uuid.UUID | None
    sighting_ids: list[uuid.UUID]


class VariantEdgeOut(BaseModel):
    parent_variant_id: uuid.UUID
    child_variant_id: uuid.UUID
    kind: str
    reason: str
    evidence: dict[str, Any]


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sighting_id: uuid.UUID
    event: str | None
    place: str | None
    claimed_date: str | None
    actor_role: str | None
    stance: str | None
    quote: str
    quote_start: int
    quote_end: int
    language: str | None
    translation: str | None
    llm_provider: str
    llm_model: str
    prompt_version: str
    analyst_status: AnalystStatus
    analyst_note: str | None


class NarrativeOut(BaseModel):
    id: uuid.UUID
    label: str
    summary: str | None
    parent_narrative_id: uuid.UUID | None
    divergence_sighting_id: uuid.UUID
    divergence_reason: str | None
    claim_ids: list[uuid.UUID]
    llm_provider: str
    llm_model: str
    prompt_version: str


class GradeOut(BaseModel):
    sighting_id: uuid.UUID
    reliability: str | None
    credibility: int | None
    rationale: str | None


class RunAnalysisOut(BaseModel):
    run_id: uuid.UUID
    variants: list[VariantOut]
    edges: list[VariantEdgeOut]
    claims: list[ClaimOut]
    narratives: list[NarrativeOut]
    grades: list[GradeOut]
    notes: dict[str, str]


class OverruleIn(BaseModel):
    """An analyst's decision on a model-made claim or a machine-made match."""

    status: Literal["accepted", "overruled"]
    note: str | None = Field(default=None, max_length=2000)
