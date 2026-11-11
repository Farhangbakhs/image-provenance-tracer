"""Add the Telegram watchlist and its photo index

Revision ID: 7c3a9e41d2f8
Revises: 5d1e2c7a9b30
Create Date: 2026-11-11 10:00:00

Phase 5 (behind ORIGIN_ENABLE_TELEGRAM). Reverse-image engines do not index Telegram, so
ORIGIN keeps its own index of photos from the public channels an analyst puts on the
watchlist: fingerprints, an SSCD embedding and the message metadata for each photo.
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c3a9e41d2f8"
down_revision: str | None = "5d1e2c7a9b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table(
        "telegram_channels",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("added_by", sa.Text(), nullable=False),
        sa.Column("newest_collected_id", sa.BigInteger(), nullable=True),
        sa.Column("last_collected_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_channels")),
        sa.UniqueConstraint("channel", name=op.f("uq_telegram_channels_channel")),
    )
    op.create_table(
        "telegram_posts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("photo_index", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("posted_at", TS, nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("image_artefact_id", sa.UUID(), nullable=False),
        sa.Column("forwarded_from_channel", sa.Text(), nullable=True),
        sa.Column("forwarded_from_message_id", sa.BigInteger(), nullable=True),
        sa.Column("forwarded_from_name", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("phash", sa.String(length=16), nullable=False),
        sa.Column("pdq", sa.String(length=64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=512), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("collected_via", sa.String(length=16), nullable=False),
        sa.Column("collected_at", TS, nullable=False),
        sa.CheckConstraint(
            "collected_via IN ('preview','api')", name=op.f("ck_telegram_posts_collected_via")
        ),
        sa.ForeignKeyConstraint(
            ["image_artefact_id"],
            ["artefacts.id"],
            name=op.f("fk_telegram_posts_image_artefact_id_artefacts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_posts")),
        sa.UniqueConstraint(
            "channel",
            "message_id",
            "photo_index",
            name=op.f("uq_telegram_posts_channel_message_id_photo_index"),
        ),
    )
    op.create_index(op.f("ix_telegram_posts_channel"), "telegram_posts", ["channel"])
    op.create_index(
        op.f("ix_telegram_posts_image_artefact_id"), "telegram_posts", ["image_artefact_id"]
    )
    op.create_index(
        "ix_telegram_posts_embedding_hnsw",
        "telegram_posts",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("telegram_posts")
    op.drop_table("telegram_channels")
