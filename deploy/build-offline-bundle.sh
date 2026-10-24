#!/bin/sh
set -eu

# Usage: ./deploy/build-offline-bundle.sh [version]
# Requires the two images to exist locally:
#   mannazia:0.1.0
#   mannazia:0.1.0-arm64

cd "$(dirname "$0")/.."

VERSION=${1:-0.1.0}
NAME="mannazia-offline-$VERSION"
OUT="dist-offline/$NAME"

if ! docker image inspect "mannazia:$VERSION" >/dev/null 2>&1; then
    echo "Missing image mannazia:$VERSION" >&2
    exit 1
fi
if ! docker image inspect "mannazia:$VERSION-arm64" >/dev/null 2>&1; then
    echo "Missing image mannazia:$VERSION-arm64" >&2
    exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT/images"

cp deploy/compose.offline.yaml "$OUT/compose.yaml"
cp deploy/install-offline.sh "$OUT/install.sh"
cp deploy/README-offline.zh-CN.md "$OUT/README.md"
cp docs/DEPLOYMENT.zh-CN.md "$OUT/DEPLOYMENT.zh-CN.md"
cp .env.example "$OUT/.env.example"
cp LICENSE "$OUT/LICENSE"

chmod +x "$OUT/install.sh"

echo "Saving amd64 image..."
docker save -o "$OUT/images/mannazia-amd64.tar" "mannazia:$VERSION"

echo "Saving arm64 image..."
docker save -o "$OUT/images/mannazia-arm64.tar" "mannazia:$VERSION-arm64"

echo "Creating archive..."
tar -C dist-offline -czf "dist-offline/$NAME.tar.gz" "$NAME"

echo
echo "Created: dist-offline/$NAME.tar.gz"
du -h "dist-offline/$NAME.tar.gz" 2>/dev/null || true
