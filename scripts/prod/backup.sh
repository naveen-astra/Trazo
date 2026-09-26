#!/usr/bin/env bash
# Back up a production Trazo deployment: the database and the blob store.
#
#   scripts/prod/backup.sh [destination-dir]      # default: ./backups
#
# Writes one timestamped PostgreSQL dump (custom format, restorable with
# pg_restore) and one blob-store tarball, then deletes backups older than
# TRAZO_BACKUP_RETENTION_DAYS (default 14). Safe to run while the stack is
# serving traffic; schedule it from cron, for example nightly:
#
#   15 3 * * * cd /opt/trazo && scripts/prod/backup.sh >> /var/log/trazo-backup.log 2>&1
#
# Restore instructions are in deploy/README.md.
set -euo pipefail

cd "$(dirname "$0")/../.."

DEST="${1:-backups}"
RETENTION_DAYS="${TRAZO_BACKUP_RETENTION_DAYS:-14}"
COMPOSE="docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$DEST"
chmod 700 "$DEST"

echo "==> dumping postgres"
$COMPOSE exec -T postgres sh -c 'pg_dump --format=custom --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    >"$DEST/trazo-db-$STAMP.dump"

echo "==> archiving the blob store"
$COMPOSE exec -T control-plane tar -C /var/lib/trazo -czf - blobs \
    >"$DEST/trazo-blobs-$STAMP.tar.gz"

# A zero-byte dump means the command above failed in a way that still
# produced a file; never let that masquerade as a good backup.
for file in "$DEST/trazo-db-$STAMP.dump" "$DEST/trazo-blobs-$STAMP.tar.gz"; do
    if [ ! -s "$file" ]; then
        echo "backup failed: $file is empty" >&2
        rm -f "$file"
        exit 1
    fi
done

echo "==> pruning backups older than $RETENTION_DAYS days"
find "$DEST" -maxdepth 1 -type f -name 'trazo-*' -mtime "+$RETENTION_DAYS" -delete

echo "==> done: $DEST/trazo-db-$STAMP.dump, $DEST/trazo-blobs-$STAMP.tar.gz"
