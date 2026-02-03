#!/bin/bash
set -e

echo "Stopping containers..."
docker compose down

echo "Removing old images..."
docker compose rm -f
docker rmi archive_bot-archive-bot 2>/dev/null || true

echo "Building with no cache..."
docker compose build --no-cache

echo "Starting containers..."
docker compose up -d

echo "Showing logs (Ctrl+C to exit)..."
docker compose logs -f
