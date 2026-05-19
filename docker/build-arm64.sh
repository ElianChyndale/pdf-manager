#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TAG="${1:-latest}"

echo "=== Build pdf-manager-app (ARM64) ==="
docker build \
  -f "${ROOT_DIR}/docker/Dockerfile.app" \
  -t "pdf-manager-app:${TAG}" \
  "${ROOT_DIR}"

echo "=== Build pdf-manager-web (ARM64) ==="
docker build \
  -f "${ROOT_DIR}/docker/Dockerfile.web" \
  -t "pdf-manager-web:${TAG}" \
  "${ROOT_DIR}"

echo ""
echo "Build done. Start with:"
echo "  cd ${ROOT_DIR}/docker/delivery"
echo "  APP_IMAGE=pdf-manager-app:${TAG} WEB_IMAGE=pdf-manager-web:${TAG} docker compose up -d"
