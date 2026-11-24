# API image. Build from the REPOSITORY ROOT:  docker build -f backend/Dockerfile -t cu-helpdesk-api .
# NOT BUILT where it was written (the Docker engine was not running): the first `docker compose build` is the real test.
#
# The image holds code and the synthetic demo data only. Keys come from the environment (docker-compose.yml passes your .env in at run time),
# the Google key file is mounted read-only, and documents come from Google Drive; none of them are ever copied into the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# The app locates data/, storage/ and secrets/ relative to the repository root, so the same layout is kept here.
WORKDIR /srv/helpdesk

# Dependencies first (cached until the requirement files change); versions are held to the lock file, as in CI.
COPY backend/requirements.txt backend/requirements.lock backend/
RUN pip install -r backend/requirements.txt -c backend/requirements.lock

COPY backend/app backend/app
COPY scripts scripts
COPY data/synthetic_applicants.csv data/
COPY data/eval data/eval

# A non-root user owns the only writable places: storage (database, vector index, traces) and, if present, nothing else.
RUN useradd --create-home --uid 10001 helpdesk \
    && mkdir -p storage secrets \
    && chown -R helpdesk:helpdesk storage
USER helpdesk

WORKDIR /srv/helpdesk/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

# --proxy-headers: behind the web container the client address arrives in X-Forwarded-For, which the per-client rate limits need.
# --forwarded-allow-ips=*: only the web container can reach this port (it is not published), so every caller is trusted to set it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
