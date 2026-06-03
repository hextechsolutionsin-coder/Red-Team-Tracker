# =============================================================================
# Red Team Operations Tracker — Backend Dockerfile
# Builds the FastAPI / Uvicorn service.
# =============================================================================

FROM python:3.12-slim AS base

# System dependencies required by WeasyPrint (Pango, Cairo, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for the application
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure the uploads directory exists with correct ownership
RUN mkdir -p /uploads && chown appuser:appgroup /uploads

USER appuser

EXPOSE 8000

# Start Uvicorn; Alembic migrations run inside the app lifespan
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
