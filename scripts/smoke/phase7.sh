#!/usr/bin/env bash
# Phase 7 checkpoint (TASKS/PHASE_7.md): "`make benchmark` regenerates
# RQ1+RQ2 tables from corpus manifests; `pip install dist/trazo-*.whl` in a
# clean venv traces a toy agent against compose; demo script executes
# clean."
#
# Three parts, in order:
#   1. Benchmark reproducibility, offline, no compose needed (mirrors the
#      Makefile's `benchmark` target exactly, rather than shelling out to
#      `make`, since `make` is not installed in every dev environment this
#      script needs to run in -- e.g. this repo's own Windows dev machine).
#   2. Build the real wheel, install it (with the langgraph+demos extras,
#      since a base install has no framework adapter or demo deps) into a
#      throwaway venv that has never seen this repo's dev dependencies, and
#      trace the research-assistant demo through it against a live compose
#      stack -- proving the *packaged* artifact works, not just the dev
#      venv `uv run --project sdk` always uses everywhere else in this repo.
#   3. The same demo script run (`demos/research-assistant/run.py`) is the
#      literal "demo script" TASKS/PHASE_7.md's checkpoint line refers to
#      (DEMO_RUNBOOK.md Step 2) -- its clean exit in part 2 already covers
#      this bullet, so there is no separate third command.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO_ROOT="$(pwd)"

echo "==> [1/2] benchmark reproducibility (offline, no compose)"
uv run --project sdk python benchmark/detection/runner.py
uv run --project sdk python benchmark/fidelity/run_harness.py

echo "==> [2/2] packaged wheel traces a real demo against live compose"

COMPOSE="docker compose --project-name trazo-smoke7 --env-file deploy/.env -f deploy/docker-compose.yml"
BASE_URL="http://localhost:8420"
DIST_DIR="$REPO_ROOT/dist"
VENV_DIR="$(mktemp -d)"

if [ -f deploy/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source deploy/.env
    set +a
fi
API_KEY="${TRAZO_API_KEY:-dev-change-me}"

cleanup() {
    $COMPOSE down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$VENV_DIR"
}
trap cleanup EXIT

echo "==> building the wheel"
rm -rf "$DIST_DIR"
uv build sdk --wheel -o "$DIST_DIR" --clear
WHEEL="$(ls "$DIST_DIR"/trazo-*.whl)"
echo "built: $WHEEL"

echo "==> creating a clean venv with no dev dependencies"
uv venv "$VENV_DIR" >/dev/null
if [ -x "$VENV_DIR/Scripts/python.exe" ]; then
    VENV_PY="$VENV_DIR/Scripts/python.exe" # Windows venv layout
else
    VENV_PY="$VENV_DIR/bin/python" # POSIX venv layout
fi

echo "==> installing the packaged wheel (langgraph + demos extras only)"
uv pip install --python "$VENV_PY" "${WHEEL}[langgraph,demos]" >/dev/null

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

echo "==> tracing demos/research-assistant/run.py through the packaged wheel's venv"
RUN_OUTPUT="$("$VENV_PY" demos/research-assistant/run.py --endpoint "$BASE_URL" 2>&1)"
echo "$RUN_OUTPUT"
RUN_ID="$(echo "$RUN_OUTPUT" | grep -o 'TRAZO_RUN_ID=[A-Za-z0-9_]*' | cut -d= -f2)"
if [ -z "$RUN_ID" ]; then
    echo "demo run did not print TRAZO_RUN_ID" >&2
    exit 1
fi
echo "run_id: $RUN_ID"

echo "==> asserting the run landed and finished ok"
for i in $(seq 1 30); do
    STATUS="$(curl -fsS "$BASE_URL/v1/runs/$RUN_ID" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")"
    if [ "$STATUS" = "ok" ]; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "run never reached status=ok (last seen: $STATUS)" >&2
        exit 1
    fi
    sleep 2
done
echo "run status OK: $RUN_ID -> $STATUS"

echo "==> phase 7 smoke: PASS"
