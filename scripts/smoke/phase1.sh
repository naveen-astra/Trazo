#!/usr/bin/env bash
# Phase 1 integration checkpoint (TASKS/PHASE_1.md): seed the hand-crafted
# sample trace via the ingest API, confirm the store worker persists it
# (row counts, run rollup) and re-seeding is idempotent, read it back via
# the query API, and confirm the DLQ is empty.
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose --project-name trazo-smoke --env-file deploy/.env -f deploy/docker-compose.yml"
BASE_URL="http://localhost:8420"
RUN_ID="run_01J9Z8QK3V7XG2N4P5R6S7T8VW"

if [ -f deploy/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source deploy/.env
    set +a
fi
API_KEY="${TRAZO_API_KEY:-dev-change-me}"

cleanup() { $COMPOSE down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> compose config validates"
$COMPOSE config -q

echo "==> bringing stack up"
$COMPOSE up -d --build

echo "==> waiting for control plane health"
for i in $(seq 1 60); do
    if curl -fsS "$BASE_URL/healthz" >/dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "control plane never became healthy" >&2
        $COMPOSE logs control-plane >&2
        exit 1
    fi
    sleep 2
done

echo "==> waiting for /readyz (real Postgres + Redis checks, TRZ-P1-08)"
for i in $(seq 1 30); do
    if curl -fsS "$BASE_URL/readyz" 2>/dev/null | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['status']=='ready' else 1)"; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "control plane never became ready" >&2
        curl -fsS "$BASE_URL/readyz" || true
        $COMPOSE logs control-plane >&2
        exit 1
    fi
    sleep 2
done

seed() {
    python3 -c "
import json
lines = [json.loads(l) for l in open('schema/examples/sample_run.ndjson') if l.strip()]
print(json.dumps({'events': lines}))
" | curl -fsS -X POST "$BASE_URL/v1/ingest/events" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -d @-
}

echo "==> seeding sample_run.ndjson"
seed_response=$(seed)
echo "$seed_response"
echo "$seed_response" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['accepted'] == 9, f'expected 9 accepted, got {body}'
assert body['rejected'] == [], f'expected no rejects, got {body}'
"

echo "==> waiting for the store worker to persist the run"
for i in $(seq 1 30); do
    status=$(curl -fsS "$BASE_URL/v1/runs/$RUN_ID" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
    if [ "$status" = "ok" ]; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "run never reached status=ok (last status: '$status')" >&2
        $COMPOSE logs control-plane >&2
        exit 1
    fi
    sleep 2
done

echo "==> asserting run rollup"
curl -fsS "$BASE_URL/v1/runs/$RUN_ID" | python3 -c "
import json, sys
run = json.load(sys.stdin)
assert run['status'] == 'ok', run
assert run['framework'] == 'langgraph', run
assert run['tags'] == {'env': 'demo'}, run
assert run['totals']['llm_calls'] == 1, run
assert run['totals']['tool_calls'] == 1, run
print('run rollup OK:', run['run_id'], run['status'], run['totals'])
"

echo "==> asserting event row count"
curl -fsS "$BASE_URL/v1/runs/$RUN_ID/events?limit=100" | python3 -c "
import json, sys
body = json.load(sys.stdin)
seqs = [e['seq'] for e in body['events']]
assert seqs == list(range(9)), f'expected seq 0..8, got {seqs}'
print('event count OK:', len(seqs))
"

echo "==> re-seeding (idempotency check)"
seed >/dev/null

sleep 3

echo "==> asserting event count is unchanged after re-seed"
curl -fsS "$BASE_URL/v1/runs/$RUN_ID/events?limit=100" | python3 -c "
import json, sys
body = json.load(sys.stdin)
seqs = [e['seq'] for e in body['events']]
assert seqs == list(range(9)), f'idempotency violated: expected seq 0..8, got {seqs}'
print('idempotent re-seed OK: still', len(seqs), 'events')
"

echo "==> asserting DLQ is empty"
curl -fsS "$BASE_URL/metrics" | python3 -c "
import re, sys
text = sys.stdin.read()
match = re.search(r'^trazo_bus_dlq_depth_messages\s+([0-9.]+)', text, re.MULTILINE)
assert match, 'trazo_bus_dlq_depth_messages metric not found'
depth = float(match.group(1))
assert depth == 0.0, f'expected DLQ depth 0, got {depth}'
print('DLQ depth OK: 0')
"

echo "==> phase 1 smoke: PASS"
