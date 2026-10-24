FROM node:24-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MANNAZIA_CONFIG_DIR=/config \
    MANNAZIA_DATA_DIR=/data \
    MANNAZIA_BOOKS_DIR=/books

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --from=frontend /src/dist ./frontend/dist

RUN groupadd --gid "${APP_GID}" mannazia \
    && useradd --uid "${APP_UID}" --gid mannazia --home-dir /app --no-create-home \
        --shell /usr/sbin/nologin mannazia \
    && mkdir -p /config /data /books \
    && chown -R mannazia:mannazia /app /config /data /books \
    && chmod +x /usr/local/bin/entrypoint.sh

USER mannazia
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
