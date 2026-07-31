# Trazo developer entry points (DEVELOPMENT_GUIDE §2–3).
# Requires: docker compose v2, uv, node 20 + npm.

COMPOSE := docker compose --project-name trazo --env-file deploy/.env -f deploy/docker-compose.yml
PHASE ?= 0
AGENT ?= research-assistant

.PHONY: up down nuke seed dev-server dev-dash test test-int lint fmt smoke demo gen-api-types

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
	# MASTER_PLAN.md §4.3 / DEMO_RUNBOOK.md step 1-2: bring up the stack (if
	# not already) and trace one real run into it -- AGENT=research-assistant
	# (default, LangGraph) or AGENT=content-pipeline (CrewAI). Open the
	# dashboard at http://localhost:5173 before running this, so the run's
	# live arrival is visible -- the rest of the six-step demo (chaos
	# injection, policy enforcement, replay, fidelity harness) is
	# DEMO_RUNBOOK.md's job, not this one command's.
	$(COMPOSE) up -d --build
	case "$(AGENT)" in \
		research-assistant) EXTRA=langgraph ;; \
		content-pipeline) EXTRA=crewai ;; \
		*) echo "unknown AGENT=$(AGENT) (expected research-assistant or content-pipeline)" >&2; exit 1 ;; \
	esac; \
	uv run --project sdk --extra "$$EXTRA" --extra demos \
		python demos/$(AGENT)/run.py --endpoint http://localhost:8420

gen-api-types:
	# CODING_STANDARDS.md §2: "hand-written API types are a bug" -- this is
	# the one command that actually makes that true, wiring the two steps
	# scripts/export_openapi_schema.py's own docstring already assumed
	# existed under this name.
	cd control-plane && uv run python ../scripts/export_openapi_schema.py
	cd dashboard && npm run gen-api-types
