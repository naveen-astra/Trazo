#!/usr/bin/env bash
# Phase 2 integration checkpoint (TASKS/PHASE_2.md): run the toy LangGraph
# agent (sdk/tests/agents/research_assistant.py) instrumented against a
# live control plane, confirm the full run/step/llm/tool event sequence
# (with fingerprints + state hashes) lands in the store, and confirm the
# live firehose (TRZ-P2-06) delivered the same events while the run was in
# flight — not just after the fact.
#
# The dashboard's own "timeline renders" checkpoint line is covered
# separately by dashboard/tests/timeline.spec.ts (Playwright, run via
# `npm run test:e2e` against this same compose stack) — kept out of this
# script so a missing/uninstalled browser doesn't block the backend check.
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose --project-name trazo-smoke --env-file deploy/.env -f deploy/docker-compose.yml"
BASE_URL="http://localhost:8420"
PROJECT="phase2-smoke"

if [ -f deploy/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source deploy/.env
    set +a
fi
API_KEY="${TRAZO_API_KEY:-dev-change-me}"

FIREHOSE_LOG="$(mktemp)"
FIREHOSE_PID=""
cleanup() {
    [ -n "$FIREHOSE_PID" ] && kill "$FIREHOSE_PID" >/dev/null 2>&1 || true
    rm -f "$FIREHOSE_LOG"
    $COMPOSE down --volumes --remove-orphans >/dev/null 2>&1 || true
}
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

echo "==> waiting for /readyz"
for i in $(seq 1 30); do
    if curl -fsS "$BASE_URL/readyz" 2>/dev/null | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['status']=='ready' else 1)"; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "control plane never became ready" >&2
        $COMPOSE logs control-plane >&2
        exit 1
    fi
    sleep 2
done

echo "==> subscribing to the live firehose before the run starts"
curl -fsS -N --max-time 45 "$BASE_URL/v1/live/firehose?project=$PROJECT" >"$FIREHOSE_LOG" 2>/dev/null &
FIREHOSE_PID=$!
sleep 1 # let the SSE connection establish before the run emits anything

echo "==> running the toy LangGraph agent, instrumented, against the live control plane"
TRAZO_ENDPOINT="$BASE_URL" TRAZO_API_KEY="$API_KEY" \
    uv run --project sdk --extra langgraph python scripts/smoke/run_toy_agent.py

echo "==> waiting for the store worker to persist the run"
RUN_ID=""
for i in $(seq 1 30); do
    RUN_ID=$(curl -fsS "$BASE_URL/v1/runs?project=$PROJECT" 2>/dev/null | python3 -c "
import json, sys
runs = json.load(sys.stdin)['runs']
print(runs[0]['run_id'] if runs and runs[0]['status'] != 'running' else '')
" 2>/dev/null || echo "")
    if [ -n "$RUN_ID" ]; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "run never reached a terminal status" >&2
        $COMPOSE logs control-plane >&2
        exit 1
    fi
    sleep 2
done
echo "run_id: $RUN_ID"

echo "==> asserting run rollup"
curl -fsS "$BASE_URL/v1/runs/$RUN_ID" | python3 -c "
import json, sys
run = json.load(sys.stdin)
assert run['status'] == 'ok', run
assert run['framework'] == 'langgraph', run
assert run['totals']['llm_calls'] == 1, run
assert run['totals']['tool_calls'] == 1, run
print('run rollup OK:', run['run_id'], run['status'], run['totals'])
"

echo "==> asserting the full event sequence (kinds, fingerprints, state hashes)"
curl -fsS "$BASE_URL/v1/runs/$RUN_ID/events?limit=100" | python3 -c "
import json, sys
events = json.load(sys.stdin)['events']
kinds = [e['kind'] for e in events]
assert kinds.count('run.started') == 1, kinds
assert kinds.count('run.finished') == 1, kinds
assert kinds.count('step.started') == 2, kinds
assert kinds.count('step.finished') == 2, kinds
assert kinds.count('llm.call') == 1, kinds
assert kinds.count('tool.call') == 1, kinds
assert len(events) == 8, kinds

for e in events:
    if e['kind'] in ('llm.call', 'tool.call'):
        assert e['fingerprint'] and e['fingerprint'].startswith('sha256:'), e
    if e['kind'] == 'step.started':
        assert e['payload']['state_before_hash'].startswith('sha256:'), e
    if e['kind'] == 'step.finished':
        assert e['payload']['state_after_hash'].startswith('sha256:'), e

seqs = [e['seq'] for e in events]
assert seqs == sorted(seqs) and len(seqs) == len(set(seqs)), seqs
print('event sequence OK:', kinds)
"

echo "==> stopping the firehose subscription and asserting it saw the same events live"
kill "$FIREHOSE_PID" >/dev/null 2>&1 || true
wait "$FIREHOSE_PID" 2>/dev/null || true
FIREHOSE_PID=""

python3 -c "
import json, sys
kinds = []
with open('$FIREHOSE_LOG', encoding='utf-8') as f:
    for line in f:
        if line.startswith('data:'):
            kinds.append(json.loads(line[len('data:'):])['kind'])
assert kinds.count('run.started') == 1, kinds
assert kinds.count('run.finished') == 1, kinds
assert kinds.count('llm.call') == 1, kinds
assert kinds.count('tool.call') == 1, kinds
print('firehose live-delivery OK:', kinds)
"

echo "==> phase 2 smoke: PASS"
