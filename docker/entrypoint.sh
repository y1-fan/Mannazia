#!/bin/sh
set -eu

mkdir -p "$MANNAZIA_CONFIG_DIR" "$MANNAZIA_DATA_DIR" "$MANNAZIA_BOOKS_DIR"

# The image runs as an unprivileged user. Bind-mounted directories must be
# writable by that UID/GID; see README "NAS permissions".
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8080 \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --timeout-graceful-shutdown 20 \
  --log-level "$(printf '%s' "${MANNAZIA_LOG_LEVEL:-INFO}" | tr '[:upper:]' '[:lower:]')"
