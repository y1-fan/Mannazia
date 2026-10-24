"""Initial Mannazia schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("manifest_url", sa.Text(), nullable=False),
        sa.Column("api_version", sa.String(length=4), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("creator", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=100), nullable=True),
        sa.Column("date_display", sa.String(length=200), nullable=True),
        sa.Column("rights", sa.Text(), nullable=True),
        sa.Column("rights_uri", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("total_canvases", sa.Integer(), server_default="0", nullable=False),
        sa.Column("download_state", sa.String(length=20), server_default="online", nullable=False),
        sa.Column("tags", sa.Text(), server_default="[]", nullable=False),
        sa.Column("metadata_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("extra_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("source_snapshot", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("last_refresh_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_url", name="uq_books_manifest_url"),
    )
    op.create_index("ix_books_download_state", "books", ["download_state"])

    op.create_table(
        "canvases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("book_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=500), server_default="", nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("image_service_id", sa.Text(), nullable=True),
        sa.Column("image_service_json", sa.Text(), nullable=True),
        sa.Column("related_resources_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("annotations_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("unsupported", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "sequence", name="uq_canvas_book_sequence"),
    )
    op.create_index("ix_canvases_book_id", "canvases", ["book_id"])
    op.create_index("ix_canvases_source_id", "canvases", ["source_id"])
    op.create_index("ix_canvas_book_sequence", "canvases", ["book_id", "sequence"])

    op.create_table(
        "page_resources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("book_id", sa.String(length=32), nullable=False),
        sa.Column("canvas_id", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canvas_id", name="uq_page_canvas"),
    )
    op.create_index("ix_page_resources_book_id", "page_resources", ["book_id"])
    op.create_index("ix_page_resources_canvas_id", "page_resources", ["canvas_id"])
    op.create_index("ix_page_resources_status", "page_resources", ["status"])

    op.create_table(
        "download_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("book_id", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("total_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bytes_downloaded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_download_jobs_book_id", "download_jobs", ["book_id"])
    op.create_index("ix_download_jobs_state", "download_jobs", ["state"])
    op.create_index("ix_download_job_book_state", "download_jobs", ["book_id", "state"])

    op.create_table(
        "reading_progress",
        sa.Column("book_id", sa.String(length=32), nullable=False),
        sa.Column("canvas_id", sa.String(length=32), nullable=True),
        sa.Column("source_canvas_id", sa.Text(), nullable=True),
        sa.Column("sequence_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id"),
    )


def downgrade() -> None:
    op.drop_table("reading_progress")
    op.drop_table("download_jobs")
    op.drop_table("page_resources")
    op.drop_table("canvases")
    op.drop_table("books")
