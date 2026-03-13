#!/usr/bin/env bash
#
# deploy.sh - Pull CNCSearch, rebuild and restart cncsearch + caddy
#
# Usage: bash deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../homeserver/docker-compose.yml"

cd "$SCRIPT_DIR"

echo "=== CNCSearch Deploy ==="

echo "[1/3] Pulling latest code..."
git pull

echo "[2/3] Rebuilding and restarting cncsearch + caddy..."
docker compose -f "$COMPOSE_FILE" up -d --build cncsearch caddy

echo "[3/3] Showing logs (Ctrl+C to stop watching)..."
docker compose -f "$COMPOSE_FILE" logs -f --tail=30 cncsearch caddy
