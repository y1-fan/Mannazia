from __future__ import annotations

import os

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.config import Settings
from app.errors import AppError
from app.schemas import HealthOut, StorageOut, SystemInfoOut

router = APIRouter(prefix="/api", tags=["system"])

SECURITY_NOTICE = (
    "Mannazia blocks private, loopback, link-local and reserved network destinations by "
    "default to prevent SSRF. Do not expose it directly to the public internet: put it "
    "behind a trusted reverse proxy with authentication and HTTPS. A public Manifest URL "
    "does not imply that its contents are public domain."
)


@router.get("/health", response_model=HealthOut, summary="Application health")
def health(request: Request) -> HealthOut:
    app = request.app
    try:
        with app.state.db.session() as session:
            session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:
        raise AppError(
            "The database is unavailable.", status_code=503, code="database_unavailable"
        ) from exc
    books_directory = "ok" if os.access(app.state.settings.books_dir, os.W_OK) else "not writable"
    if books_directory != "ok":
        raise AppError(
            "The books directory is not writable.",
            status_code=503,
            code="books_dir_unavailable",
        )
    return HealthOut(
        status="ok",
        version=app.state.settings.version,
        database=database,
        books_directory=books_directory,
        active_downloads=len(app.state.download_manager.running_job_ids()),
    )


@router.get("/system/storage", response_model=StorageOut, summary="Storage usage")
def storage_usage(request: Request) -> StorageOut:
    usage = request.app.state.storage.usage()
    return StorageOut(**usage.as_dict())


@router.get("/system/info", response_model=SystemInfoOut, summary="Runtime configuration")
def system_info(request: Request) -> SystemInfoOut:
    settings: Settings = request.app.state.settings
    return SystemInfoOut(
        name=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        download_concurrency=settings.download_concurrency,
        download_max_width=settings.download_max_width,
        cover_max_width=settings.cover_max_width,
        download_image_format=settings.download_image_format,
        max_manifest_bytes=settings.max_manifest_bytes,
        max_image_bytes=settings.max_image_bytes,
        allowed_private_host_count=len(settings.allowed_private_host_set),
        allow_private_networks=settings.allow_private_networks,
        auto_resume_downloads=settings.auto_resume_downloads,
        security_notice=SECURITY_NOTICE,
    )
