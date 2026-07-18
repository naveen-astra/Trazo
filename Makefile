# Trazo developer entry points (DEVELOPMENT_GUIDE §2–3).
# Requires: docker compose v2, uv, node 20 + npm.

COMPOSE := docker compose --project-name trazo --env-file deploy/.env -f deploy/docker-compose.yml
PHASE ?= 0

.PHONY: up down nuke seed dev-server dev-dash test test-int lint fmt smoke demo

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

nuke:
	$(COMPOSE) down --volumes --remove-orphans

seed:
	@echo "seed: sample-trace ingest lands with TRZ-P1-01 (schema/examples/)"; exit 1

dev-server:
	cd control-plane && uv run python -m trazo_server

dev-dash:
	cd dashboard && npm run dev

test:
	cd sdk && uv run pytest
	cd control-plane && uv run pytest

test-int:
	@echo "test-int: integration tests land with Phase 1 (needs compose up)"; exit 1

lint:
	uvx ruff check .
	uvx ruff format --check .
	cd sdk && uv run mypy
	cd control-plane && uv run mypy
	cd dashboard && npm run lint && npm run format

fmt:
	uvx ruff format .
	cd dashboard && npx prettier --write .

smoke:
	bash scripts/smoke/phase$(PHASE).sh

demo:
	@echo "demo: demo agents land with TRZ-P3-02/03"; exit 1
