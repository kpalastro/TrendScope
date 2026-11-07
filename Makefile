SHELL := /bin/bash
PYTHON ?= backend/.venv/bin/python
PIP ?= backend/.venv/bin/pip

.PHONY: help up down logs ps build backend-install frontend-install dev-backend dev-frontend seed sync sync-force report test test-backend migrate reset clean

help:
	@echo "TrendScope AI — Phase 1"
	@echo ""
	@echo "  make up                Build and run the full stack with Docker Compose"
	@echo "  make down              Stop the stack (keeps the Postgres volume)"
	@echo "  make logs              Follow all service logs"
	@echo "  make clean             Stop the stack and delete its database volume"
	@echo ""
	@echo "  make backend-install   Create backend/.venv and install Python dependencies"
	@echo "  make frontend-install  npm install for the web app"
	@echo "  make dev-backend       Run FastAPI on :8000 with reload (SQLite by default)"
	@echo "  make dev-frontend      Run Next.js on :3000"
	@echo ""
	@echo "  make seed              Seed categories, sources, admin and scoring profile"
	@echo "  make sync              Run one deterministic mock sync"
	@echo "  make sync-force        Run a mock sync even if demo data exists"
	@echo "  make report            Generate last week's report"
	@echo "  make test              Run the backend test suite"
	@echo "  make migrate           Apply Alembic migrations"

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

build:
	docker compose build

backend-install:
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt

frontend-install:
	cd frontend && npm install

dev-backend:
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

seed:
	cd backend && .venv/bin/python -m app.cli init --demo

sync:
	cd backend && .venv/bin/python -m app.cli sync

sync-force:
	cd backend && .venv/bin/python -m app.cli init --demo --force-sync

report:
	cd backend && .venv/bin/python -m app.cli report

test:
	cd backend && .venv/bin/python -m pytest -q

migrate:
	cd backend && .venv/bin/alembic upgrade head

clean:
	docker compose down -v

reset: clean
