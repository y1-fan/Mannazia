<p align="center">
  <img src="frontend/public/mannaz-logo.svg" width="76" alt="Mannazia logo">
</p>

<h1 align="center">Mannazia</h1>

<p align="center">
  A self-hosted IIIF digital library for personal shelves and NAS storage.
</p>

<p align="center">
  <strong>English</strong> · <a href="README.md">中文</a>
</p>

---

Mannazia imports IIIF Presentation API 2.1 and 3.0 Manifests, previews and
catalogues books, reads them remotely from the original image service, and can
deliberately copy page images to local NAS storage.

> **Core principle: the bibliographic record and the local pages are separate.**
>
> Importing a book never downloads the whole book. It caches one cover image and
> records the book. Removing local pages keeps the catalogue entry, cover and
> thumbnails intact.

Mannazia runs as one Docker container with SQLite. It has no PostgreSQL, Redis,
Elasticsearch, message broker or GPU dependency.

## Features

- IIIF Presentation API **2.1** and **3.0**, normalized behind one internal model.
- Manifest preview with title, creator, cover, rights, Canvas count, image
  services and parser warnings.
- Automatic cover selection and a separate high-quality cover cache.
- Duplicate detection, editable metadata and tags.
- Remote reading through OpenSeadragon and IIIF Image API tiles, with a fallback
  for ordinary image URLs.
- Reading progress stored against a stable source Canvas identifier.
- Background page-thumbnail caching after import; the reader uses local
  thumbnails whenever available.
- Resumable, pausable, cancellable NAS downloads with retries, concurrency
  limits, timeouts and per-page state.
- Four download quality tiers: Reading, Standard, Appreciation and Research.
- Complete downloads are packaged as `book.cbz`; partial downloads stay as loose
  files so they can resume.
- Atomic page writes, image validation, SHA-256 records and full verification
  before a book is marked offline.
- High-quality covers survive local-page deletion.
- Shelf search covers title, creator, description, language, date, rights, tags
  and all metadata entries.
- English / Chinese UI with a persisted language switch.
- Responsive interface and keyboard navigation.
- SSRF-conscious networking: private/loopback/link-local destinations are
  blocked, DNS is validated and pinned, and every redirect is revalidated.
- SQLite WAL, foreign keys, Alembic migrations and restart reconciliation.

## Quick start

Requirements: Docker Engine 20+ with the Compose plugin.

```sh
git clone <repository-url> mannazia
cd mannazia
cp .env.example .env
mkdir -p config data books
```

Set `PUID` / `PGID` in `.env` to the NAS user who should own these directories.

```sh
docker compose build
docker compose up -d
docker compose ps
```

Open:

- UI: `http://<nas-address>:8080/`
- API docs: `http://<nas-address>:8080/api/docs`
- Health: `http://<nas-address>:8080/api/health`

`MANNAZIA_PORT` changes only the host port; the container always listens on 8080.

### Persistent directories

| Host directory | Container | Contents |
| --- | --- | --- |
| `./config` | `/config` | Reserved deployment configuration |
| `./data` | `/data` | SQLite database and WAL files |
| `./books` | `/books` | Manifest snapshots, covers, thumbnails, pages and CBZ archives |

`data/`, `books/` and `config/` are ignored by Git.

## First book

1. Open **Import** and paste a IIIF Manifest URL.
2. Review metadata, rights, page count and warnings. No pages are downloaded.
3. Add the book. Mannazia caches the cover and marks the book **Online**.
4. Open the book to read remotely. IIIF Image API pages load as viewport tiles.
5. On the book page, choose **Download to NAS** and select Reading, Standard,
   Appreciation or Research.
6. Once complete, all pages are verified and packaged into `book.cbz`; the book
   becomes **Offline**.
7. **Remove local pages** deletes pages and the CBZ while keeping the record,
   cover and thumbnails.

## Download quality

- **Reading** — smallest local copy; text remains clear and illustrations remain
  recognizable.
- **Standard** — a balanced choice for text, charts and everyday illustrations.
- **Appreciation** — more visual detail for illustrations and plates.
- **Research** — requests the largest size the source can provide, with no local
  resizing or recompression.

The first three tiers are processed locally (resized and recompressed when
needed) and always remain in colour. Research preserves the downloaded bytes,
but the largest available source image is not necessarily the archival original;
the UI says so.

Complete downloads become `book.cbz`. Partial downloads stay as loose files for
resume and retry. CBZ packaging uses ZIP store to avoid recompressing images that
are already compressed.

## Local storage layout

```text
books/<32-hex-book-id>/
    manifest.json            Original Manifest snapshot
    book.json                Normalized bibliographic snapshot
    cover.jpg                Separately cached cover
    thumbs/
        000001.jpg           Reader thumbnails
        000002.jpg
    pages/                   Loose pages during partial downloads
        000001.jpg
    book.cbz                 Page archive for a complete download
    download-manifest.json   Page mapping, hashes, states and job summary
```

- Book IDs are stable and independent of URL or title.
- SQLite stores paths relative to the book directory.
- Covers and thumbnails do not count as downloaded pages.
- Removing local pages deletes `pages/` and `book.cbz`, but keeps the record,
  cover and thumbnails.

## Book states

| State | Meaning |
| --- | --- |
| `online` | Record and cover only; pages come from the remote IIIF source |
| `queued` | Download waiting for a worker |
| `downloading` | Pages transferring |
| `paused` | Job paused; local pages retained |
| `partial` | Some pages are local and verified; remote pages are still required |
| `offline` | Every required page is verified locally |
| `error` | Latest job failed and no usable local pages remain |

On restart, active jobs become paused and incomplete page rows are reset. Completed
pages are re-verified. Resume is manual by default; set
`MANNAZIA_AUTO_RESUME_DOWNLOADS=true` to resume automatically.

## Configuration

All application variables use the `MANNAZIA_` prefix.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MANNAZIA_PORT` | `8080` | Host port published by Compose |
| `PUID` / `PGID` | `1000` | Container UID / GID and file ownership |
| `TZ` | `UTC` | Container timezone |
| `MANNAZIA_LOG_LEVEL` | `INFO` | Log level |
| `MANNAZIA_ALLOW_PRIVATE_NETWORKS` | `false` | Development switch allowing every private destination |
| `MANNAZIA_ALLOWED_PRIVATE_HOSTS` | empty | Exact private hostnames, comma separated |
| `MANNAZIA_DOWNLOAD_CONCURRENCY` | `3` | Concurrent page fetches (1–16) |
| `MANNAZIA_DOWNLOAD_MAX_WIDTH` | `0` | Optional global width ceiling for resized tiers; 0 adds no ceiling |
| `MANNAZIA_COVER_MAX_WIDTH` | `1200` | Target width of the cached cover |
| `MANNAZIA_PAGE_THUMBNAILS_ENABLED` | `true` | Cache page thumbnails after import |
| `MANNAZIA_THUMBNAIL_CONCURRENCY` | `4` | Concurrent thumbnail fetches |
| `MANNAZIA_DOWNLOAD_IMAGE_FORMAT` | `jpg` | Preferred IIIF image format |
| `MANNAZIA_DOWNLOAD_RETRIES` | `3` | Retries for transient page failures |
| `MANNAZIA_AUTO_RESUME_DOWNLOADS` | `false` | Automatically resume interrupted jobs |
| `MANNAZIA_PREVIEW_TTL_SECONDS` | `900` | Import-preview cache lifetime |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Trusted reverse-proxy addresses |

See [`.env.example`](.env.example) for all options and inline comments.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/import/preview` | Preview a Manifest |
| `POST` | `/api/books` | Import a book |
| `GET` | `/api/books` | List, search and filter books |
| `GET` | `/api/books/{id}` | Book detail |
| `PATCH` | `/api/books/{id}` | Edit metadata |
| `DELETE` | `/api/books/{id}` | Delete the book and local files |
| `GET` | `/api/books/{id}/canvases` | Canvases and image-service details |
| `GET` | `/api/books/{id}/pages/{n}` | Local page or page from CBZ |
| `GET` | `/api/books/{id}/thumbs/{n}` | Cached page thumbnail |
| `GET` | `/api/books/{id}/cover` | Cached cover |
| `GET/PUT` | `/api/books/{id}/progress` | Read/save reading progress |
| `POST` | `/api/books/{id}/downloads` | Create a job with an optional `quality` |
| `GET` | `/api/downloads` | List jobs |
| `POST` | `/api/downloads/{id}/pause` | Pause |
| `POST` | `/api/downloads/{id}/resume` | Resume |
| `POST` | `/api/downloads/{id}/cancel` | Cancel, keeping completed pages |
| `POST` | `/api/downloads/{id}/retry` | Retry failed pages |
| `DELETE` | `/api/books/{id}/local-copy` | Delete local pages, keep the record |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/system/storage` | Storage usage |

Interactive API documentation is available at `/api/docs`.

## Security

Mannazia blocks private, loopback and link-local destinations by default, rejects
credentials in URLs and non-HTTP(S) schemes, and validates every redirect and DNS
answer.

For a IIIF server on the LAN, allow only exact hostnames:

```dotenv
MANNAZIA_ALLOWED_PRIVATE_HOSTS=iiif.lan,library.local
```

There is **no built-in authentication, authorization or TLS**. Put Mannazia
behind a reverse proxy with HTTPS and authentication. Do not expose it directly
to the public internet.

## Backup and upgrade

The simplest consistent backup stops the container:

```sh
docker compose stop
tar -czf mannazia-backup-$(date +%F).tar.gz config data books .env
docker compose start
```

Back up both `data/` and `books/`: a database without pages restores records but
not offline reading, and pages without the database lose their mapping.

Upgrade:

```sh
docker compose build
docker compose up -d
docker compose logs --tail=100 mannazia
```

Database migrations run at startup. Do not run multiple containers against the
same SQLite database.

## Development

Requires Python 3.12+ and Node.js 22.12+ (Docker uses Node 24).

Backend:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: . .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
python -m pytest
ruff check app tests
ruff format --check app tests
```

Run the API from the repository root:

```sh
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8080
```

Frontend:

```sh
cd frontend
npm ci
npm run dev        # Vite :5173, proxies /api to :8080
npm run typecheck
npm run lint
npm test
npm run build      # writes frontend/dist
```

The current suites contain **97 backend tests** and **9 frontend tests**. Tests
use local fixtures and fake HTTP clients; they do not require a public IIIF
server.

Optional demo data: `python backend/scripts/seed_demo.py`. It writes to the
configured `config/`, `data/` and `books/` directories; do not run it against a
real library.

## Known limitations

- Only the primary painting image of each Canvas is downloaded.
- Audio, video, OCR, non-painting annotations, multiple image layers and complex
  resources are unsupported.
- Only painting annotations embedded in the Manifest are read; external
  AnnotationPages are not fetched.
- Research uses the maximum exposed IIIF resolution and is not guaranteed to be
  the archival original file.
- No Manifest refresh, Collection import, multi-user accounts, built-in auth or
  TLS.
- The download manager is in-process; run one application process and one
  container.
- Pages downloaded before a quality change keep their original dimensions.
- CBZ packaging happens only after every required page verifies.
- Cross-origin image tiles depend on the source server's CORS policy.
- Automatic cover selection can choose a scan target, barcode or title page;
  manual cover override is not implemented.
- No OCR, full-text search, annotation editor or reading lists. Search covers
  bibliographic metadata and tags.
- Page images must decode as JPEG, PNG, WebP or GIF. TIFF-only sources are marked
  unsupported.
- Source titles, creators, rights and metadata are shown in the language supplied
  by the institution; the UI itself is available in English and Chinese.
- Font files are large and distributed with the app. Confirm redistribution
  rights before publishing; see [`docs/FONTS.md`](docs/FONTS.md).

## Documentation

- [Development plan and implementation notes](docs/PLAN.md)
- [Fonts and licenses](docs/FONTS.md)
- [中文 README](README.md)

## Acknowledgements

Mannazia is built on the IIIF Presentation API and Image API specifications,
FastAPI, SQLAlchemy/Alembic, React, Vite and OpenSeadragon. The rune **ᛗ**
(Mannaz) is used as a visual motif; no invented historical meaning is implied.

Latin display typography uses **Michelangelus**; Chinese display typography uses
**Source Han Serif SC** (SIL Open Font License). Both are served locally, with no
third-party font CDN at runtime.

## License

The project source code does not yet include an open-source license. The
maintainer should choose and add a `LICENSE` file before publishing a public
repository.
