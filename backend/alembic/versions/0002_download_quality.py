"""Add per-job download quality.

Revision ID: 0002_download_quality
Revises: 0001_initial
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_download_quality"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "download_jobs",
        sa.Column(
            "quality",
            sa.String(length=20),
            server_default="research",
            nullable=False,
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_column("quality")
