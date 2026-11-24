# Running the whole system in containers

**Status: the files are written and checked by tests, but have not been built.** The Docker engine was not running when they were written, so `docker compose up --build` has never been run.
Watch the first build; the most likely problems are listed at the end.

## What runs

| Container | What it does | Reached at |
|---|---|---|
| `web` | nginx: serves the React app and proxies `/api` to the API without buffering (the chat streams) | http://localhost:8080 (admin page: `/#/admin`) |
| `api` | FastAPI + LangGraph, the document poller, the monitoring and admin endpoints | not published; only `web` can reach it |
| volume `storage` | database, vector index, traces, evaluation runs | survives restarts and rebuilds |

Nothing private is in an image: `.dockerignore` keeps `.env`, `secrets/`, `storage/`, real documents and training data out, and a test (`tests/unit/test_deploy_files.py`) fails if that changes.

## First start

```text
copy .env.example .env        # then fill it in (OPENAI_API_KEY, OPENAI_CHAT_MODEL, APP_SECRET_KEY, ADMIN_API_KEY, the Drive settings)
docker compose up --build -d
docker compose run --rm api python ../scripts/seed_demo_db.py --yes     # once: the six synthetic applicants (this resets the database, so never repeat it on a system in use)
docker compose run --rm api python ../scripts/sync_drive_once.py        # once: build the index from Drive (a few cents); with DRIVE_POLL_ENABLED=true it then keeps itself current
```

Your `.env` is read by Docker on your machine and passed to the `api` container as environment variables. Keep the Google key file in `./secrets/` (it is mounted read-only). Paths in `.env` such as
`./secrets/drive-service-account.json` work unchanged; absolute Windows paths do not.

## Settings worth knowing (all in `.env`)

| Setting | Why |
|---|---|
| `RAG_TOP_K=8`, `RAG_MAX_DISTANCE=0.75` | the values the evaluation chose (the code defaults are older numbers; a value in `.env` overrides them) |
| `DRIVE_POLL_ENABLED=true`, `DRIVE_SYNC_INTERVAL_SECONDS=300` | automatic ingestion |
| `CHAT_HISTORY_PERSIST=true` | conversations survive a restart (stored for `CHAT_HISTORY_RETENTION_DAYS`, 30 by default) |
| `CHAT_RATE_LIMIT_PER_MINUTE=60` | per client address; the API runs with `--proxy-headers` so the address is the visitor's, not nginx's |
| `ADMIN_API_KEY` | the admin page and endpoints are off until this is changed from the example value |

## Day to day

```text
docker compose logs -f api                                  # what the API says
docker compose exec api python ../scripts/monitor_traces.py # alerts and drift
docker compose exec api python ../scripts/retention.py      # old traces, ratings and stored chats (run nightly; --dry-run first)
docker compose exec api python ../scripts/run_evaluation.py --modes direct,rag   # add --evidently only on the host: the image does not carry the Evidently packages
docker volume ls                                            # find the volume (its name starts with the folder name, ending in _storage)
docker run --rm -v <that-volume>:/data -v ${PWD}:/backup alpine tar czf /backup/storage-backup.tgz -C /data .   # back it up
```

## Before real use (not done, on purpose)

- **TLS**: the web container speaks plain HTTP. Put a TLS-terminating proxy or load balancer in front.
- **Sign-in**: applicant verification is demo-level (application id plus registered email). Production needs the university's single sign-on, and the admin key is a development convenience.
- **Secrets**: use the platform's secret store instead of an `.env` file.
- **Images**: the crest and the AI-generated illustrations are for the demo (`docs/LICENSE_NOTES.md`).

## If the first build fails

| Symptom | Likely cause |
|---|---|
| `pip` cannot resolve a package | the lock file pins a Windows-only wheel; relax that line in `backend/requirements.lock`, or install without `-c` once |
| `api` is "unhealthy" | `docker compose logs api`: usually a missing key in `.env`, or `GOOGLE_DRIVE_CREDENTIALS_FILE` pointing at a file that is not in `./secrets/` |
| the chat answers all at once, not word by word | something between the browser and `web` is buffering; the nginx file already switches buffering off |
| rate-limit errors for everyone at once | the API sees nginx's address instead of the visitor's: check that `--proxy-headers` is still in the Dockerfile `CMD` |
