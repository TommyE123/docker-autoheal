# Multi-stage Dockerfile for Docker Auto-Heal Service with React UI

# ============================================
# Stage 1: Build React Frontend
# ============================================
FROM node:18-alpine@sha256:8d6421d663b4c28fd3ebc498332f249011d118945588d0a35cb9bc4b8ca09d9e AS frontend-builder

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
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

LABEL maintainer="Docker Auto-Heal Service"
LABEL description="Automated container monitoring and healing service with React UI"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (new structure)
COPY app/ ./app/
COPY run.py ./

# Copy React build from stage 1 (vite outputs to frontend/../static which is /frontend/../static)
COPY --from=frontend-builder /static ./static/

# Create data and log directories
RUN mkdir -p /data/logs

# Expose ports
# 8080 - Web UI (React)
# 9090 - Prometheus metrics
EXPOSE 8080 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:3131/health || exit 1

# Run the application
CMD ["python", "-m", "app.main"]

