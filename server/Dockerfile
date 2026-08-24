FROM python:3.11-slim

WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl && rm -rf /var/lib/apt/lists/*

# ★ Build context is the REPO ROOT (see docker-compose.yml's `build.context: .` +
# `dockerfile: server/Dockerfile`), not server/ — `COPY ../data` from a server/-rooted
# context is outside the build context and Docker refuses it outright. Every COPY below is
# written relative to the repo root instead.
COPY server/pyproject.toml ./
RUN pip install --no-cache-dir -e . || true

COPY server/. .
RUN pip install --no-cache-dir -e .

# Reference data is read at import time (agent/loader.py resolves it as ../../data from
# server/agent/, i.e. /srv/data here); it must be inside the image.
COPY data /srv/data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
