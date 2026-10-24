"""Mark downloads created before quality selection as legacy.

Revision ID: 0003_legacy_download_quality
Revises: 0002_download_quality
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_legacy_download_quality"
down_revision: str | None = "0002_download_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0002 gave old rows the server default. They predate the tier selector and
    # may have been downloaded with an earlier width policy.
    op.execute("UPDATE download_jobs SET quality = 'legacy' WHERE quality = 'research'")


def downgrade() -> None:
    op.execute("UPDATE download_jobs SET quality = 'research' WHERE quality = 'legacy'")
