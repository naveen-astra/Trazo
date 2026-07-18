#!/usr/bin/env bash
# Phase 0 integration checkpoint (TASKS/PHASE_0.md): a clean
# `docker compose up` reaches healthy, /healthz and /readyz return 200,
# and the dashboard placeholder serves.
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose --project-name trazo-smoke --env-file deploy/.env -f deploy/docker-compose.yml"

cleanup() { $COMPOSE down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> compose config validates"
$COMPOSE config -q

echo "==> bringing stack up"
$COMPOSE up -d --build

echo "==> waiting for control plane health"
for i in $(seq 1 60); do
    if curl -fsS http://localhost:8420/healthz >/dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "control plane never became healthy" >&2
        $COMPOSE logs control-plane >&2
        exit 1
    fi
    sleep 2
done

echo "==> /healthz"
curl -fsS http://localhost:8420/healthz
echo

echo "==> /readyz"
curl -fsS http://localhost:8420/readyz
echo

echo "==> /metrics responds"
curl -fsS http://localhost:8420/metrics/ | head -3

echo "==> dashboard placeholder serves"
for i in $(seq 1 30); do
    if curl -fsS http://localhost:5173/ | grep -qi "trazo"; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "dashboard never served" >&2
        $COMPOSE logs dashboard >&2
        exit 1
    fi
    sleep 2
done

echo "==> phase 0 smoke: PASS"
