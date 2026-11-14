# Three stages, so a rebuild only redoes what changed:
#   frontend-builder  npm build; reruns only when frontend/ changes
#   python-deps       compiles the Python dependencies (insightface needs a C++
#                     toolchain); reruns only when backend/pyproject.toml changes
#   runtime           slim image without the toolchain; a code change only
#                     re-copies backend/
# Builds natively on arm64 (Raspberry Pi 5) as well as amd64. Base images are
# pinned to a patch release and Debian version (both publish arm64), so a
# rebuild does not silently pick up a new runtime; bump them deliberately.

FROM node:20.20.2-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---

FROM python:3.11.18-slim-bookworm AS python-deps

# build-essential, cmake, g++: compile insightface's C++ extension (and
# reverse-geocoder's) where no wheel exists, e.g. on aarch64.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Dependencies go into a venv that the runtime stage copies whole. Only
# pyproject.toml is needed here, so code changes never invalidate this layer.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/
# ML deps (insightface, onnxruntime, ...) are mandatory for face detection.
RUN pip install --no-cache-dir "./backend[ml]" \
    && pip uninstall -y recasa

# ---

FROM python:3.11.18-slim-bookworm

# Runtime libraries only:
#   - libgl1, libglib2.0-0, etc.: OpenCV and image processing
#   - nginx: reverse proxy for serving frontend + API
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Create data directories
RUN mkdir -p /data/db /data/thumbs /data/models /data/faces /data/motion_videos

# nginx config and start script
COPY nginx/nginx.conf /etc/nginx/sites-enabled/default
COPY nginx/security-headers.conf /etc/nginx/snippets/recasa-security-headers.conf
COPY nginx/proxy.conf /etc/nginx/snippets/recasa-proxy.conf
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Frontend build, then the backend code last: it changes most often.
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist
COPY backend/ backend/

EXPOSE 8080

CMD ["/app/start.sh"]
