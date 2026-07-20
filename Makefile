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
	bash scripts/seed.sh

dev-server:
	cd control-plane && uv run python -m trazo_server

dev-dash:
	cd dashboard && npm run dev

test:
	cd sdk && uv run pytest
	cd control-plane && uv run pytest

test-int:
	# Same suite as 'test': the integration tests self-skip without live
	# Postgres/Redis and execute for real once 'make up' has provided them
	# (DEVELOPMENT_GUIDE.md §4). Run `make up` first.
	cd sdk && uv run pytest
	cd control-plane && uv run pytest

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
