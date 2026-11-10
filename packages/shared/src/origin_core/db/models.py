"""ORM models: the evidence store.

Integrity rules that the schema itself enforces (see the initial migration for triggers):

* a claim cannot exist without a sighting (`claims.sighting_id` NOT NULL, FK);
* a narrative cannot exist without at least one claim (deferred constraint trigger);
* `audit_events` is append-only (UPDATE and DELETE are rejected by a trigger);
* every stored artefact records its SHA-256, size, source and fetch time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from origin_core.db.base import Base, created_at, str_enum, uuid_pk
from origin_core.enums import (
    Actor,
    AnalystStatus,
    ArtefactKind,
    BoundType,
    C2PAState,
    CandidateStatus,
    Confidence,
    DateConfidence,
    EvidenceKind,
    MatchClass,
    PropagationKind,
    ProviderCallStatus,
    QuotaPeriod,
    RunStatus,
    SourceKind,
    VariantEdgeKind,
)

EMBEDDING_DIM = 512
TS = TIMESTAMP(timezone=True)


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[Any]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True
    )


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(
        TS, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Artefact(Base):
    """One stored byte sequence and how we obtained it. Storage keys are content-addressed."""

    __tablename__ = "artefacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[ArtefactKind] = mapped_column(str_enum(ArtefactKind, "artefact_kind"))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    http_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("byte_size >= 0", name="byte_size_non_negative"),)


class Asset(Base):
    """The uploaded query image."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = _fk("cases.id")
    original_artefact_id: Mapped[uuid.UUID] = _fk("artefacts.id", ondelete="RESTRICT")
    display_artefact_id: Mapped[uuid.UUID | None] = _fk(
        "artefacts.id", nullable=True, ondelete="RESTRICT"
    )
    original_filename: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    phash: Mapped[str] = mapped_column(String(16), nullable=False)
    dhash: Mapped[str] = mapped_column(String(16), nullable=False)
    pdq: Mapped[str] = mapped_column(String(64), nullable=False)
    pdq_quality: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    metadata_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    c2pa_state: Mapped[C2PAState] = mapped_column(str_enum(C2PAState, "c2pa_state"))
    c2pa_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (UniqueConstraint("case_id", "sha256"),)


class Run(Base):
    """One execution of the pipeline over one asset."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = _fk("cases.id")
    asset_id: Mapped[uuid.UUID] = _fk("assets.id")
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus, "run_status"), nullable=False, server_default=RunStatus.QUEUED.value
    )
    providers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    stages: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class ProviderCall(Base):
    """Every outbound provider query, including cache hits, replays and skips."""

    __tablename__ = "provider_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[ProviderCallStatus] = mapped_column(
        str_enum(ProviderCallStatus, "provider_call_status"), nullable=False
    )
    raw_artefact_id: Mapped[uuid.UUID | None] = _fk(
        "artefacts.id", nullable=True, ondelete="RESTRICT"
    )
    units: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        Index("ix_provider_calls_provider_request_hash", "provider", "request_hash"),
        CheckConstraint("units >= 0", name="units_non_negative"),
    )


class ProviderQuota(Base):
    """Units spent per provider per period. Debited under a row lock."""

    __tablename__ = "provider_quota"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    period_kind: Mapped[QuotaPeriod] = mapped_column(str_enum(QuotaPeriod, "quota_period"))
    period_start: Mapped[datetime] = mapped_column(TS, nullable=False)
    limit_units: Mapped[int] = mapped_column(Integer, nullable=False)
    used_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("provider", "period_kind", "period_start"),
        CheckConstraint("used_units >= 0 AND used_units <= limit_units", name="within_limit"),
    )


class Source(Base):
    """A publisher (domain) or channel, graded for reliability on the Admiralty scale (A-F)."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind, "source_kind"))
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    reliability: Mapped[str] = mapped_column(String(1), nullable=False, server_default="F")
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TS, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("reliability IN ('A','B','C','D','E','F')", name="grade"),)


class Candidate(Base):
    """An unverified provider hit. Never shown as evidence until verified into a sighting."""

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    provider_call_id: Mapped[uuid.UUID] = _fk("provider_calls.id")
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    provider_date: Mapped[datetime | None] = mapped_column(TS)
    provider_rank: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[CandidateStatus] = mapped_column(
        str_enum(CandidateStatus, "candidate_status"),
        nullable=False,
        server_default=CandidateStatus.PENDING.value,
    )
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("page_url IS NOT NULL OR image_url IS NOT NULL", name="has_url"),
    )


class Variant(Base):
    """A cluster of sightings that show the same picture in the same form."""

    __tablename__ = "variants"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    label: Mapped[str] = mapped_column(Text, nullable=False)
    representative_sighting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sightings.id", ondelete="SET NULL", use_alter=True),
    )
    created_at: Mapped[datetime] = created_at()


class Sighting(Base):
    """A verified appearance of the query image (or a derivative) at a URL."""

    __tablename__ = "sightings"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), unique=True
    )
    image_artefact_id: Mapped[uuid.UUID] = _fk("artefacts.id", ondelete="RESTRICT")
    page_artefact_id: Mapped[uuid.UUID | None] = _fk(
        "artefacts.id", nullable=True, ondelete="RESTRICT"
    )
    variant_id: Mapped[uuid.UUID | None] = _fk("variants.id", nullable=True, ondelete="SET NULL")
    source_id: Mapped[uuid.UUID | None] = _fk("sources.id", nullable=True, ondelete="SET NULL")
    page_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))

    match_class: Mapped[MatchClass] = mapped_column(str_enum(MatchClass, "match_class"))
    phash_distance: Mapped[int | None] = mapped_column(SmallInteger)
    pdq_distance: Mapped[int | None] = mapped_column(SmallInteger)
    sscd_cosine: Mapped[float | None] = mapped_column(Float)
    homography_inliers: Mapped[int | None] = mapped_column(Integer)
    transform: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    threshold_version: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    date_lower: Mapped[datetime | None] = mapped_column(TS)
    date_upper: Mapped[datetime | None] = mapped_column(TS)
    date_confidence: Mapped[DateConfidence] = mapped_column(
        str_enum(DateConfidence, "date_confidence"),
        nullable=False,
        server_default=DateConfidence.UNKNOWN.value,
    )
    deciding_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("timestamp_evidence.id", ondelete="SET NULL", use_alter=True),
    )
    dating_rule_version: Mapped[str | None] = mapped_column(Text)

    reliability: Mapped[str | None] = mapped_column(String(1))
    credibility: Mapped[int | None] = mapped_column(SmallInteger)
    grade_rationale: Mapped[str | None] = mapped_column(Text)

    analyst_status: Mapped[AnalystStatus] = mapped_column(
        str_enum(AnalystStatus, "sighting_analyst_status"),
        nullable=False,
        server_default=AnalystStatus.ACCEPTED.value,
    )
    analyst_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint(
            "date_lower IS NULL OR date_upper IS NULL OR date_lower <= date_upper",
            name="date_interval_ordered",
        ),
        CheckConstraint(
            "reliability IS NULL OR reliability IN ('A','B','C','D','E','F')", name="reliability"
        ),
        CheckConstraint("credibility IS NULL OR credibility BETWEEN 1 AND 6", name="credibility"),
        Index(
            "ix_sightings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class TimestampEvidence(Base):
    """One dating signal for one sighting, kept separately so the deciding signal is auditable."""

    __tablename__ = "timestamp_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    sighting_id: Mapped[uuid.UUID] = _fk("sightings.id")
    kind: Mapped[EvidenceKind] = mapped_column(str_enum(EvidenceKind, "evidence_kind"))
    value: Mapped[datetime] = mapped_column(TS, nullable=False)
    bound: Mapped[BoundType] = mapped_column(str_enum(BoundType, "bound_type"))
    confidence: Mapped[Confidence] = mapped_column(str_enum(Confidence, "confidence"))
    source_url: Mapped[str | None] = mapped_column(Text)
    artefact_id: Mapped[uuid.UUID | None] = _fk("artefacts.id", nullable=True, ondelete="RESTRICT")
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = created_at()


class VariantEdge(Base):
    """A derived-from link between variants (parent is the source of the child)."""

    __tablename__ = "variant_edges"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    parent_variant_id: Mapped[uuid.UUID] = _fk("variants.id")
    child_variant_id: Mapped[uuid.UUID] = _fk("variants.id")
    kind: Mapped[VariantEdgeKind] = mapped_column(str_enum(VariantEdgeKind, "variant_edge_kind"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("parent_variant_id <> child_variant_id", name="not_self"),
        UniqueConstraint("parent_variant_id", "child_variant_id", "kind"),
    )


class PropagationEdge(Base):
    """An explicit link between two sightings: a forward, a credit, an embed or a "via" link."""

    __tablename__ = "propagation_edges"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    from_sighting_id: Mapped[uuid.UUID] = _fk("sightings.id")
    to_sighting_id: Mapped[uuid.UUID] = _fk("sightings.id")
    kind: Mapped[PropagationKind] = mapped_column(str_enum(PropagationKind, "propagation_kind"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint("from_sighting_id <> to_sighting_id", name="not_self"),)


class Claim(Base):
    """What one sighting's text says the image shows. Always tied to its sighting."""

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    sighting_id: Mapped[uuid.UUID] = _fk("sightings.id")
    event: Mapped[str | None] = mapped_column(Text)
    place: Mapped[str | None] = mapped_column(Text)
    claimed_date: Mapped[str | None] = mapped_column(Text)
    claimed_date_lower: Mapped[datetime | None] = mapped_column(TS)
    claimed_date_upper: Mapped[datetime | None] = mapped_column(TS)
    actor_role: Mapped[str | None] = mapped_column(Text)
    stance: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_end: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    translation: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    analyst_status: Mapped[AnalystStatus] = mapped_column(
        str_enum(AnalystStatus, "claim_analyst_status"),
        nullable=False,
        server_default=AnalystStatus.ACCEPTED.value,
    )
    analyst_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("quote_start >= 0 AND quote_end > quote_start", name="quote_span"),
    )


class Narrative(Base):
    """A cluster of mutually consistent claims. Must contain at least one claim."""

    __tablename__ = "narratives"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    label: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    parent_narrative_id: Mapped[uuid.UUID | None] = _fk(
        "narratives.id", nullable=True, ondelete="SET NULL"
    )
    divergence_sighting_id: Mapped[uuid.UUID] = _fk("sightings.id")
    divergence_reason: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()


class NarrativeClaim(Base):
    __tablename__ = "narrative_claims"

    narrative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("narratives.id", ondelete="CASCADE"), primary_key=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True
    )


class AuditEvent(Base):
    """Append-only log of every action taken in a case or run."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    case_id: Mapped[uuid.UUID | None] = _fk("cases.id", nullable=True, ondelete="RESTRICT")
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="RESTRICT")
    actor: Mapped[Actor] = mapped_column(str_enum(Actor, "actor"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


Index(
    "ix_assets_embedding_hnsw",
    Asset.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
