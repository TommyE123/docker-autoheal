# Multi-stage Dockerfile for Docker Auto-Heal Service with React UI

# ============================================
# Stage 1: Build React Frontend
# ============================================
FROM node:26-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94 AS frontend-builder

WORKDIR /frontend

# Copy package files (including the lockfile, so `npm ci` gets exact, reproducible versions)
COPY frontend/package*.json ./

# Install exactly what's in package-lock.json (including dev dependencies needed for build)
RUN npm ci

# Copy frontend source
COPY frontend/ ./

# Build React app
RUN npm run build

# ============================================
# Stage 2: Python Application
# ============================================
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

LABEL maintainer="Docker Auto-Heal Service"
LABEL description="Automated container monitoring and healing service with React UI"

# Set working directory
WORKDIR /app

# renovate: datasource=deb depName=curl versioning=deb registryUrl=https://deb.debian.org/debian?suite=trixie&components=main&binaryArch=amd64
ARG CURL_VERSION=8.14.1-2+deb13u7

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl="${CURL_VERSION}" \
        libcurl4t64="${CURL_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (new structure)
COPY app/ ./app/

# Copy React build from stage 1 (vite outputs to frontend/../static which is /frontend/../static)
COPY --from=frontend-builder /static ./static/

# Create data and log directories
RUN mkdir -p /data/logs

# Expose ports
# 3131 - Web UI (React)
# 9090 - Prometheus metrics
EXPOSE 3131 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["curl", "-f", "http://localhost:3131/health"]

# Run the application
CMD ["python", "-m", "app.main"]
