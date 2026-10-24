from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Book download states
ONLINE = "online"
QUEUED = "queued"
DOWNLOADING = "downloading"
PAUSED = "paused"
PARTIAL = "partial"
OFFLINE = "offline"
ERROR = "error"

BOOK_DOWNLOAD_STATES = {ONLINE, QUEUED, DOWNLOADING, PAUSED, PARTIAL, OFFLINE, ERROR}

# DownloadJob states
JOB_QUEUED = "queued"
JOB_DOWNLOADING = "downloading"
JOB_PAUSED = "paused"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

JOB_STATES = {JOB_QUEUED, JOB_DOWNLOADING, JOB_PAUSED, JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED}
ACTIVE_JOB_STATES = {JOB_QUEUED, JOB_DOWNLOADING, JOB_PAUSED}

# PageResource states
PAGE_PENDING = "pending"
PAGE_DOWNLOADING = "downloading"
PAGE_COMPLETE = "complete"
PAGE_FAILED = "failed"
PAGE_SKIPPED = "skipped"
