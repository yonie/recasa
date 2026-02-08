FROM node:20-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---

FROM python:3.12-slim-bookworm

# Install system dependencies including dlib build tools for face_recognition
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        -o Acquire::Retries=3 \
        -o Acquire::http::Timeout=30 \
        nginx \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgomp1 \
        cmake \
        build-essential \
        libopenblas-dev \
        liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (core + ML)
COPY backend/pyproject.toml backend/
RUN pip install --no-cache-dir -e "backend/[ml]" \
    || pip install --no-cache-dir -e backend/

# Copy backend code
COPY backend/ backend/

# Copy frontend build
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# Copy nginx config
COPY nginx/nginx.conf /etc/nginx/sites-enabled/default
RUN rm -f /etc/nginx/sites-enabled/default.bak

# Create data directories
RUN mkdir -p /data/db /data/thumbs /data/models /data/faces /data/motion_videos

# Expose port
EXPOSE 8080

# Start script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
