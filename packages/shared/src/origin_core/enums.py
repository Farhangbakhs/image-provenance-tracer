"""Closed vocabularies shared by the database, the pipeline and the API."""

from __future__ import annotations

from enum import StrEnum


class C2PAState(StrEnum):
    NONE = "none"
    PRESENT_UNTRUSTED = "present_untrusted"
    VALID_TRUSTED = "valid_trusted"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProviderCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    CACHED = "cached"
    REPLAYED = "replayed"
    SKIPPED_QUOTA = "skipped_quota"
    SKIPPED_BREAKER = "skipped_breaker"


class QuotaPeriod(StrEnum):
    HOUR = "hour"
    MONTH = "month"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    UNRELATED = "unrelated"
    FETCH_FAILED = "fetch_failed"


class MatchClass(StrEnum):
    EXACT = "exact"
    NEAR_DUPLICATE = "near_duplicate"
    DERIVATIVE = "derivative"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DateConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class EvidenceKind(StrEnum):
    #: ORIGIN itself fetched the page or image at this time: proof it existed by then.
    OBSERVED = "observed"
    PLATFORM = "platform"
    C2PA = "c2pa"
    WAYBACK_PAGE = "wayback_page"
    WAYBACK_IMAGE = "wayback_image"
    PROVIDER_CRAWL = "provider_crawl"
    PAGE_METADATA = "page_metadata"
    HTTP_LAST_MODIFIED = "http_last_modified"
    EXIF = "exif"


class BoundType(StrEnum):
    #: The sighting appeared at this time (a platform's own post timestamp).
    EXACT = "exact"
    #: The sighting existed by this time (an archive capture, a crawl, our own fetch).
    NO_LATER_THAN = "no_later_than"
    #: The sighting cannot predate this time (the picture was taken or signed then).
    NO_EARLIER_THAN = "no_earlier_than"
    #: Someone states this time (a page's published date): plausible, not proven.
    CLAIMED = "claimed"


class VariantEdgeKind(StrEnum):
    CROP = "crop"
    MIRROR = "mirror"
    RESIZE = "resize"
    OVERLAY = "overlay"
    RECOMPRESS = "recompress"


class PropagationKind(StrEnum):
    FORWARD = "forward"
    CREDIT = "credit"
    EMBED = "embed"
    VIA = "via"


class AnalystStatus(StrEnum):
    ACCEPTED = "accepted"
    OVERRULED = "overruled"


class SourceKind(StrEnum):
    DOMAIN = "domain"
    TELEGRAM_CHANNEL = "telegram_channel"


class Actor(StrEnum):
    SYSTEM = "system"
    ANALYST = "analyst"
    AGENT = "agent"


class ArtefactKind(StrEnum):
    ORIGINAL = "original"
    DISPLAY = "display"
    FETCHED_IMAGE = "fetched_image"
    PAGE_HTML = "page_html"
    PROVIDER_RAW = "provider_raw"
    LLM_RAW = "llm_raw"
    EXPORT = "export"
