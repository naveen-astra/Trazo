#!/usr/bin/env bash
# make seed (DEVELOPMENT_GUIDE.md §2): ingest schema/examples/sample_run.ndjson
# via the control plane's ingest API (TRZ-P1-05). Requires `make up` first.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f deploy/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source deploy/.env
    set +a
fi

BASE_URL="${CONTROL_PLANE_URL:-http://localhost:8420}"
API_KEY="${TRAZO_API_KEY:-dev-change-me}"

python3 -c "
import json
lines = [json.loads(l) for l in open('schema/examples/sample_run.ndjson') if l.strip()]
print(json.dumps({'events': lines}))
" | curl -fsS -X POST "$BASE_URL/v1/ingest/events" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d @-
echo
