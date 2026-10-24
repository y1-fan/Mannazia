# Mannazia — Implementation Plan

Mannazia is a self-hosted IIIF digital library for NAS devices. The central rule is that a
bibliographic record is independent of the local copy: importing a Manifest never downloads the
book's pages.

## Scope and architecture

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, SQLite (WAL), httpx, Pillow.
- **Frontend:** React 19 + TypeScript + Vite, OpenSeadragon for deep zoom, plain CSS design system.
  Serif typography is local: **Michelangelus** for Latin text and **Source Han Serif SC** for
  Chinese text, with bilingual English/Chinese UI and a language switch.
- **Deployment:** Single multi-stage Docker image; FastAPI serves the compiled SPA and the API.
  Compose bind-mounts `./config`, `./data`, `./books`.
- **Background work:** One in-process async download manager. SQLite is the source of truth, so
  task state survives restarts. Downloads interrupted by a restart become `paused` and are
  reconciled at startup; the user can resume or retry them.

```
frontend/          React application
backend/app/
  api/             REST routers
  iiif/            URL safety, HTTP client, Presentation 2/3 normalization, Image API requests
  models/          SQLAlchemy models
  services/        import, library, progress, storage, download manager
  main.py          app factory, lifespan, SPA serving
backend/alembic/   schema migrations
backend/tests/     pytest suite with local fixtures and fakes
```

## Key decisions

1. **Normalization boundary.** `backend/app/iiif/normalize.py` converts Presentation API 2.1 and
   3.0 into one internal model. The API/UI never branch on IIIF version.
2. **Safe fetching.** A dedicated fetcher accepts only HTTP(S), rejects credentials and
   non-global IPs, validates every DNS answer, pins the validated IP for the connection, sets the
   original Host header/SNI, revalidates every redirect, caps redirects/time/bytes, and ignores
   proxy environment variables. Administrator allow-listed hosts are the only exception.
3. **Preview then import.** `POST /api/import/preview` fetches and normalizes a Manifest and
   returns a short-lived, server-side preview token. `POST /api/books` persists the cached preview
   (or refetches if it expired). Manifest URLs are de-duplicated.
4. **Storage layout.** `/books/<book-id>/{manifest.json,book.json,download-manifest.json,pages/}`.
   Only relative paths are stored in SQLite. Downloads stream to `.part` files, are verified with
   Pillow, SHA-256 hashed, and atomically moved into place.
5. **Download states.** Book `download_state`: `online` (no local pages), `queued`,
   `downloading`, `paused`, `partial` (some verified local pages / unsupported canvases),
   `offline` (every canvas has a verified local primary image), `error` (download failed with no
   usable local pages). A job completing does not by itself make a book offline; every required
   page resource and file is verified first.
6. **Reading.** Local pages are served by the app. Remote pages use the recorded image URL or the
   IIIF Image API service directly in OpenSeadragon; ordinary images fall back to a plain image
   viewer. Progress is saved by source Canvas id when available, with sequence-index fallback.
7. **Security posture.** No generic proxy. Only restricted routes for Manifests and recorded page
   resources. Browser-facing link/URL fields are restricted to HTTP(S) by the normalizer and
   guarded again in the UI. The app is intended for a trusted LAN/reverse proxy, not direct public
   exposure.

## Implementation phases

1. Project scaffolding, configuration, SQLite models and Alembic migration.
2. IIIF fetch safety + Presentation 2/3 normalizer + Image API request derivation.
3. Import preview/import, books/canvases/progress CRUD, storage APIs.
4. Download manager, state reconciliation, local page serving, recovery.
5. React UI: bookshelf, import preview, detail, reader, downloads, settings.
6. Backend/frontend tests, lint/type checks, Docker build, README and operational docs.

## Delivered and verified

- Full backend suite (97 tests) covering parser, security, API, storage, integrity, cover
  selection/backfill/caching, download
  transitions, pause/resume/cancel, restart recovery, failed-page retry and partial/error states.
- Frontend Vitest suite (9 tests), ESLint, TypeScript checking and production Vite build.
- Cover selection fix: prefer a front-cover-labelled Canvas, otherwise the first readable Canvas;
  preserve the source Manifest thumbnail as fallback metadata; backfill legacy records; never use
  a later downloaded page as the cover when the selected cover page is missing.
- Cover caching: import downloads and verifies one cover image at the configured width (default
  1200 px) into the book directory, without counting it as a page or changing the `online` state.
- Bilingual English/Chinese interface with a persisted language switch. Serif typography uses
  locally hosted Michelangelus for Latin headings/prose and Source Han Serif SC for Chinese
  headings/prose; navigation and compact UI labels stay on the system sans stack. Font files are
  served from `/fonts` (no CDN dependency). Chinese UI, mixed-script headings and date formatting
  were visually checked in a headless browser; localStorage persistence is unit-tested.
- Lighthouse audit of the built container: Accessibility 100, Best Practices 100, SEO 100.
- Ruff formatting/linting for backend app, tests, migrations and demo script.
- Multi-stage Docker image built on `linux/amd64`; container ran as a non-root user with a healthy
  Compose service.
- Real end-to-end check in the container against a public IIIF Manifest: preview, import,
  36-page download, verified `offline` state, container restart, local page serving, local-copy
  deletion while keeping the record. Compose with persistent volumes was smoke-tested with import
  and restart.
- The `linux/arm64` image was successfully built with Docker buildx/QEMU. Runtime smoke tests were
  performed on `linux/amd64` only.

## Deliberate MVP limitations (documented in README)

- Downloads only the primary painting image of each Canvas (no audio/video, OCR, annotation
  bodies, or multiple image layers). Canvases without an image keep a book `partial`.
- Downloads offer four colour quality tiers: Reading, Standard, Appreciation and Research.
  The first three are resized/recompressed locally; Research keeps the downloaded bytes and uses
  the maximum available resolution. `MANNAZIA_DOWNLOAD_MAX_WIDTH` is an optional global ceiling;
  IIIF Image API level-0 services always return native resolution.
- Complete downloads are packaged into `book.cbz` and served from the archive; page thumbnails
  are cached locally at import for the reader strip.
- Refresh/re-import of an existing record is not exposed as a separate UI flow; the original
  Manifest is snapshotted and the URL is retained for future work.
- Deep zoom for remote pages depends on the IIIF server's CORS policy; the plain-image fallback
  keeps ordinary images readable.
- One application process is assumed (background download manager is in-process).
- No built-in authentication; deploy behind a trusted reverse proxy with TLS.
