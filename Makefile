# macOS/Linux shortcuts. Windows users: see the PowerShell commands in README.md.
PY ?= python3
VENV = backend/.venv
BIN = $(VENV)/bin

.PHONY: setup setup-backend setup-frontend run-backend run-frontend seed test test-unit lint build verify secrets package graph

setup: setup-backend setup-frontend

setup-backend:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -r backend/requirements-dev.txt

setup-frontend:
	cd frontend && npm install

run-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

run-frontend:
	cd frontend && npm run dev

seed:
	$(BIN)/python scripts/seed_demo_db.py --yes

test:
	cd backend && .venv/bin/pytest

test-unit:
	cd backend && .venv/bin/pytest tests/unit

lint:
	cd backend && .venv/bin/ruff check app tests ../scripts

build:
	cd frontend && npm run build

secrets:
	$(PY) scripts/check_secrets.py

verify: lint test build secrets

graph:
	$(BIN)/python scripts/export_graph_diagram.py

package: verify
	$(PY) scripts/package_repo.py
