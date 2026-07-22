#!/usr/bin/env python3
"""Export the control plane's OpenAPI schema to a static JSON file, for
dashboard type generation (`make gen-api-types`, TRZ-P2-07,
CODING_STANDARDS.md §2: "hand-written API types are a bug").

No live server needed — FastAPI builds this from route/model
introspection alone. Run via the control-plane package's own venv:
``cd control-plane && uv run python ../scripts/export_openapi_schema.py``
"""

from __future__ import annotations

import json
from pathlib import Path

from trazo_server.app import create_app

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUT_PATH = _REPO_ROOT / "dashboard" / "openapi.json"


def main() -> int:
    app = create_app()
    schema = app.openapi()
    _OUT_PATH.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {_OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
