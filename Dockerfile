FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip pip install poetry \
    && poetry config virtualenvs.create false

# Copy only dependency manifests first — this layer stays cached as long as
# pyproject.toml and poetry.lock don't change, regardless of source edits
COPY pyproject.toml poetry.lock* ./

# Install dependencies without the project root (no src/ needed yet)
# Cache mount keeps downloaded wheels across builds even when lock file changes
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --only main --no-root

# Playwright only reinstalls when dependencies actually change
RUN playwright install chromium && playwright install-deps chromium

# Source code goes last — changes here never invalidate the layers above
COPY src/ ./src/
