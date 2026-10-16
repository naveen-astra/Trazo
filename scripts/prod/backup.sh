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

# Git Bash on Windows rewrites arguments that look like POSIX paths
# (/var/lib/trazo) into Windows paths before docker sees them. No effect
# on Linux, where production runs; it keeps the script usable for drills.
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/../.."

DEST="${1:-backups}"
RETENTION_DAYS="${TRAZO_BACKUP_RETENTION_DAYS:-14}"
COMPOSE="docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_DUMP="$DEST/trazo-db-$STAMP.dump"
BLOB_ARCHIVE="$DEST/trazo-blobs-$STAMP.tar.gz"

mkdir -p "$DEST"
chmod 700 "$DEST"

# Written under a temporary name and renamed only once verified, so a
# failed run never leaves behind a file that looks like a good backup.
# (A failed blob step used to leave a valid-looking 20-byte archive.)
trap 'rm -f "$DB_DUMP.partial" "$BLOB_ARCHIVE.partial"' EXIT

echo "==> dumping postgres"
$COMPOSE exec -T postgres sh -c 'pg_dump --format=custom --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    >"$DB_DUMP.partial"

echo "==> archiving the blob store"
$COMPOSE exec -T control-plane tar -C /var/lib/trazo -czf - blobs \
    >"$BLOB_ARCHIVE.partial"

echo "==> verifying"
# pg_restore --list reads the whole archive's table of contents: it fails
# on a truncated or corrupt dump, which a size check alone would miss.
$COMPOSE exec -T postgres pg_restore --list <"$DB_DUMP.partial" >/dev/null
tar -tzf "$BLOB_ARCHIVE.partial" | grep -q '^blobs/' || {
    echo "backup failed: the blob archive has no blobs/ directory" >&2
    exit 1
}

mv "$DB_DUMP.partial" "$DB_DUMP"
mv "$BLOB_ARCHIVE.partial" "$BLOB_ARCHIVE"

echo "==> pruning backups older than $RETENTION_DAYS days"
find "$DEST" -maxdepth 1 -type f \( -name 'trazo-db-*.dump' -o -name 'trazo-blobs-*.tar.gz' \) \
    -mtime "+$RETENTION_DAYS" -delete

echo "==> done: $DB_DUMP, $BLOB_ARCHIVE"
