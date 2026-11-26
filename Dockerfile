# syntax=docker/dockerfile:1
# check=error=true
# Multi-stage Dockerfile for Docker Autoheal with React UI

# ============================================
# Stage 1: Build React Frontend
# ============================================
FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS frontend-builder

WORKDIR /frontend

# Copy package files (including the lockfile, so `npm ci` gets exact, reproducible versions)
COPY frontend/package*.json ./

# Install exactly what's in package-lock.json (including dev dependencies needed for build).
# The cache mount keeps npm's download cache out of the layer and reuses it across local builds.
# --ignore-scripts skips lifecycle scripts; the only one in the lockfile is fsevents' (macOS-only).
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts

# Copy frontend source
COPY frontend/ ./

# Build React app
RUN npm run build

# ============================================
# Stage 2: Python Application
# ============================================
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

# OCI image annotations, so local and PR builds carry the same metadata as release builds
LABEL org.opencontainers.image.description="Automated container monitoring and healing service with React UI" \
      org.opencontainers.image.authors="Docker Autoheal" \
      org.opencontainers.image.source="https://github.com/TommyE123/docker-autoheal"

# Unbuffered stdout/stderr, so logs reach `docker logs` without Compose or other orchestrators.
# No .pyc files, so the image doesn't carry compiled copies of the app that nothing reuses.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (new structure)
COPY app/ ./app/

# Copy React build from stage 1 (vite outputs to frontend/../static which is /frontend/../static)
COPY --link --from=frontend-builder /static ./static/

# Create data and log directories
RUN mkdir -p /data/logs

# Expose ports
# 3131 - Web UI (React)
# 9090 - Prometheus metrics
EXPOSE 3131 9090

# Health check, probed with the Python already in the image, so no extra package is installed.
# urlopen raises on connection errors and on HTTP 4xx/5xx, so the probe exits non-zero on failure.
# --start-interval (Docker Engine 25.0+) probes every 5s during the start period, so the
# container reports healthy soon after it is ready instead of after the first 30s interval.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --start-interval=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://localhost:3131/health', timeout=5)"]

# Run the application
CMD ["python", "-m", "app.main"]
