#!/usr/bin/env bash
# Builds a standalone "docker compose up"-able archive for a GitHub
# Release (TRZ-P7-02). deploy/docker-compose.yml's own build contexts
# and volume mounts point *outside* deploy/ itself (control-plane/,
# dashboard/, policies/trazo/ -- see its `context:`/volume lines), so
# shipping deploy/ alone would break the moment someone extracted and
# ran it. This bundles exactly the directories those relative paths
# actually resolve against, preserving the same repo-relative layout,
# minus generated/heavy content nothing needs to build the images.
set -euo pipefail

OUT="${1:?usage: build_compose_archive.sh <output.tar.gz>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tar -czf "$OUT" -C "$REPO_ROOT" \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='dist' \
    --exclude='*.pyc' \
    deploy \
    control-plane \
    dashboard \
    policies/trazo

echo "wrote $OUT"
