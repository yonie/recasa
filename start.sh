#!/bin/bash
set -e

echo "=== Recasa - Intelligent Local Photo Explorer ==="
echo "Photos directory: ${PHOTOS_DIR:-/photos}"
echo "Data directory: ${DATA_DIR:-/data}"

# Start nginx in background
nginx &

# Start FastAPI backend
exec uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level "${LOG_LEVEL:-info}" \
    --workers 1
