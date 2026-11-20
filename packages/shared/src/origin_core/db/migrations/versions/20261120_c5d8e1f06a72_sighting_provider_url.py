"""Keep the provider's link on a sighting, and add the blocked candidate status

Revision ID: c5d8e1f06a72
Revises: a3f1c9d27b44
Create Date: 2026-11-20 21:00:00

Lens links are google.com redirects, and sightings stored them as the page URL: the console
showed "www.google.com" as the source, and archive lookups and source grading ran against a
redirect. `page_url` now holds the publisher's page after redirects, and `provider_url` keeps
the provider's own link. A hit whose redirect ended on Google's own consent or captcha page is
`blocked`, not "no image on the page".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d8e1f06a72"
down_revision: str | None = "a3f1c9d27b44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_OLD = ["pending", "verified", "unrelated", "fetch_failed"]
STATUS_NEW = [*STATUS_OLD, "blocked"]


def _status_check(values: list[str]) -> None:
    allowed = ", ".join(f"'{v}'" for v in values)
    op.drop_constraint(op.f("ck_candidates_candidate_status"), "candidates", type_="check")
    op.create_check_constraint(
        op.f("ck_candidates_candidate_status"), "candidates", f"status IN ({allowed})"
    )


def upgrade() -> None:
    op.add_column("sightings", sa.Column("provider_url", sa.Text(), nullable=True))
    _status_check(STATUS_NEW)


def downgrade() -> None:
    op.execute("UPDATE candidates SET status = 'fetch_failed' WHERE status = 'blocked'")
    _status_check(STATUS_OLD)
    op.drop_column("sightings", "provider_url")
