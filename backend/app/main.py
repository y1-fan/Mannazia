from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import books, downloads, imports, system
from app.config import Settings
from app.config import settings as default_settings
from app.db import Database
from app.errors import AppError, error_body
from app.iiif.fetcher import Fetcher
from app.iiif.images import ImageServiceResolver
from app.migrations import run_migrations
from app.services.downloads import DownloadManager
from app.services.library import PreviewCache
from app.services.storage import Storage
from app.services.thumbnails import ThumbnailManager

logger = logging.getLogger(__name__)


def _resolve_frontend_dir(settings: Settings) -> Path | None:
    candidates: list[Path] = []
    if settings.frontend_dir:
        candidates.append(settings.frontend_dir)
    candidates.extend(
        [
            Path.cwd() / "frontend" / "dist",
            Path(__file__).resolve().parents[2] / "frontend" / "dist",
        ]
    )
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if (resolved / "index.html").is_file():
            return resolved
    return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or default_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        settings.ensure_directories()
        run_migrations(settings)

        db = Database(settings)
        storage = Storage(settings)
        fetcher = Fetcher(settings)
        resolver = ImageServiceResolver(settings, fetcher)
        manager = DownloadManager(settings, db, storage, fetcher, resolver)
        thumbnails = ThumbnailManager(settings, db, storage, fetcher)

        app.state.settings = settings
        app.state.db = db
        app.state.storage = storage
        app.state.fetcher = fetcher
        app.state.image_resolver = resolver
        app.state.download_manager = manager
        app.state.thumbnail_manager = thumbnails
        app.state.preview_cache = PreviewCache(ttl_seconds=settings.preview_ttl_seconds)
        await manager.startup()
        await thumbnails.startup()
        logger.info("Mannazia %s ready (books: %s)", settings.version, settings.books_dir)
        try:
            yield
        finally:
            await thumbnails.shutdown()
            await manager.shutdown()
            await fetcher.aclose()
            db.dispose()

    app = FastAPI(
        title="Mannazia",
        description=(
            "A self-hosted IIIF digital library. "
            "Import Presentation API 2.1 or 3.0 Manifests, read remotely, and download "
            "page images to local NAS storage."
        ),
        version=settings.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: blob: https: http:; "
            "media-src 'self' data: blob: https: http:; "
            "connect-src 'self' https: http:; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://cdn.jsdelivr.net; "
            "worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'self'",
        )
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        code = "not_found" if exc.status_code == 404 else "http_error"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "location": list(error.get("loc", [])),
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "Some request values were invalid.",
                {"errors": errors},
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body(
                "internal_error",
                "An unexpected error occurred. Check the container logs for details.",
            ),
        )

    app.include_router(imports.router)
    app.include_router(books.router)
    app.include_router(downloads.router)
    app.include_router(system.router)

    frontend_dir = _resolve_frontend_dir(settings)
    app.state.frontend_dir = frontend_dir
    if frontend_dir is not None:
        assets = frontend_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/") or full_path == "api":
                raise StarletteHTTPException(status_code=404, detail="API endpoint not found.")
            candidate = (frontend_dir / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(frontend_dir):
                return FileResponse(candidate)
            return FileResponse(frontend_dir / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def no_frontend() -> dict[str, str]:
            return {
                "name": "Mannazia",
                "message": (
                    "The web interface has not been built. Run the Vite build or use Docker."
                ),
                "api_docs": "/api/docs",
            }

    return app


app = create_app()
