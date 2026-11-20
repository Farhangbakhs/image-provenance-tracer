"""Record how each candidate was fetched, and keep the page of rejected candidates

Revision ID: a3f1c9d27b44
Revises: 7c3a9e41d2f8
Create Date: 2026-11-20 20:30:00

A live trace rejected 44 of its top 50 hits as "no image on the page" and kept nothing that
could say why. Verification now writes the page's status, final URL, content type, size and
image count to `fetch_info`, and stores the fetched HTML as an artefact, whatever the verdict.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f1c9d27b44"
down_revision: str | None = "7c3a9e41d2f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("fetch_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("candidates", sa.Column("page_artefact_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_candidates_page_artefact_id_artefacts"),
        "candidates",
        "artefacts",
        ["page_artefact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_candidates_page_artefact_id"), "candidates", ["page_artefact_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_candidates_page_artefact_id"), table_name="candidates")
    op.drop_constraint(
        op.f("fk_candidates_page_artefact_id_artefacts"), "candidates", type_="foreignkey"
    )
    op.drop_column("candidates", "page_artefact_id")
    op.drop_column("candidates", "fetch_info")
