FROM node:20-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---

FROM python:3.11-slim-bookworm

# Install system dependencies:
#   - build-essential, cmake, g++: needed to compile insightface C++ extensions
#   - libgl1, libglib2.0-0, etc.: OpenCV and image processing runtime deps
#   - nginx: reverse proxy for serving frontend + API
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    build-essential \
    cmake \
    g++ \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (better caching)
# ML deps (insightface, torch, etc.) are mandatory for face/tag detection
COPY backend/pyproject.toml backend/
RUN pip install --no-cache-dir -e "backend/[ml]"

# Copy backend code
COPY backend/ backend/

# Copy frontend build
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# Copy nginx config
COPY nginx/nginx.conf /etc/nginx/sites-enabled/default
RUN rm -f /etc/nginx/sites-enabled/default.bak

# Remove build tools to reduce image size (runtime deps stay)
RUN apt-get purge -y --auto-remove build-essential cmake g++ \
    && rm -rf /var/lib/apt/lists/*

# Create data directories
RUN mkdir -p /data/db /data/thumbs /data/models /data/faces /data/motion_videos

# Expose port
EXPOSE 8080

# Start script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
