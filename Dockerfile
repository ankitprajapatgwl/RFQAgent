# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# RFQ Agent — application image
# Runs the FastAPI auth service (JSON API + HTML pages) under uvicorn.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Predictable, quiet Python + pip behaviour inside the container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# `curl` is used only by the container HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install the package (editable) + its dependencies. The source is copied first
# because an editable install keeps import paths pointing at /app/src, which is
# what the app relies on to locate the templates/ and static/ directories.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .

# Application assets (changed more often than dependencies -> later layer).
COPY templates ./templates
COPY static ./static
COPY main.py ./

# Writable runtime directory (SQLite fallback / generated artifacts).
RUN mkdir -p /app/data

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
