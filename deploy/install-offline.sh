#!/bin/sh
set -eu

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed or is not in PATH." >&2
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "Docker Compose is required (v2 'docker compose' or v1 'docker-compose')." >&2
    exit 1
fi

ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64)
        IMAGE_TAR="images/mannazia-amd64.tar"
        ;;
    aarch64|arm64)
        IMAGE_TAR="images/mannazia-arm64.tar"
        ;;
    *)
        echo "Unsupported architecture: $ARCH (supported: x86_64/amd64, aarch64/arm64)." >&2
        exit 1
        ;;
esac

if [ ! -f "$IMAGE_TAR" ]; then
    echo "Image archive not found: $IMAGE_TAR" >&2
    exit 1
fi

mkdir -p config data books

if [ ! -f .env ]; then
    RUN_UID=${SUDO_UID:-$(id -u)}
    RUN_GID=${SUDO_GID:-$(id -g)}
    if [ "$RUN_UID" = "0" ]; then
        RUN_UID=1000
        RUN_GID=1000
        echo "Running as root without sudo context; using PUID=1000 PGID=1000."
        echo "Edit .env before starting if your NAS user has different IDs."
    fi
    sed \
        -e "s/^PUID=.*/PUID=$RUN_UID/" \
        -e "s/^PGID=.*/PGID=$RUN_GID/" \
        .env.example > .env
    echo "Created .env with PUID=$RUN_UID and PGID=$RUN_GID."
fi

if [ "$(id -u)" = "0" ]; then
    ENV_UID=$(sed -n 's/^PUID=//p' .env | tail -n 1)
    ENV_GID=$(sed -n 's/^PGID=//p' .env | tail -n 1)
    chown -R "${ENV_UID:-${SUDO_UID:-1000}}:${ENV_GID:-${SUDO_GID:-1000}}" config data books
fi

echo "Loading image ($ARCH)..."
docker load -i "$IMAGE_TAR"

if [ "${ARCH}" = "aarch64" ] || [ "${ARCH}" = "arm64" ]; then
    docker tag mannazia:0.1.0-arm64 mannazia:0.1.0
fi

LOADED_ARCH=$(docker image inspect mannazia:0.1.0 --format '{{.Architecture}}' 2>/dev/null || true)
case "$ARCH:$LOADED_ARCH" in
    x86_64:amd64|amd64:amd64|aarch64:arm64|arm64:arm64)
        ;;
    *)
        echo "Loaded image architecture '$LOADED_ARCH' does not match host '$ARCH'." >&2
        exit 1
        ;;
esac

echo "Starting Mannazia..."
$COMPOSE -p mannazia -f compose.yaml up -d --no-build
$COMPOSE -p mannazia -f compose.yaml ps

PORT=$(sed -n 's/^MANNAZIA_PORT=//p' .env | tail -n 1)
PORT=${PORT:-8080}
echo
echo "Mannazia is starting on port $PORT."
echo "Open: http://<NAS-IP>:$PORT/"
echo "Logs: $COMPOSE -p mannazia -f compose.yaml logs -f mannazia"
