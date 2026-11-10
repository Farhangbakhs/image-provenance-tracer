"""Add the no_earlier_than bound and the observed evidence kind

Revision ID: 5d1e2c7a9b30
Revises: b4ffc87f6b93
Create Date: 2026-11-11 00:30:00

A capture or signing time is a lower bound for when an image could first appear online, and
ORIGIN's own fetch time is an upper bound. The original vocabularies could express neither.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d1e2c7a9b30"
down_revision: str | None = "b4ffc87f6b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS_OLD = [
    "platform",
    "c2pa",
    "wayback_page",
    "wayback_image",
    "provider_crawl",
    "page_metadata",
    "http_last_modified",
    "exif",
]
KINDS_NEW = ["observed", *KINDS_OLD]
BOUNDS_OLD = ["exact", "no_later_than", "claimed"]
BOUNDS_NEW = ["exact", "no_later_than", "no_earlier_than", "claimed"]


def _check(name: str, column: str, values: list[str]) -> None:
    allowed = ", ".join(f"'{v}'" for v in values)
    # op.f(): the names are already final; do not run them through the naming convention.
    op.drop_constraint(op.f(name), "timestamp_evidence", type_="check")
    op.create_check_constraint(op.f(name), "timestamp_evidence", f"{column} IN ({allowed})")


def upgrade() -> None:
    _check("ck_timestamp_evidence_evidence_kind", "kind", KINDS_NEW)
    _check("ck_timestamp_evidence_bound_type", "bound", BOUNDS_NEW)


def downgrade() -> None:
    _check("ck_timestamp_evidence_evidence_kind", "kind", KINDS_OLD)
    _check("ck_timestamp_evidence_bound_type", "bound", BOUNDS_OLD)
