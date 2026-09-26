#!/bin/sh
# Hands the blob volume to the unprivileged `trazo` user, then drops to it.
#
# Root is needed only for the chown: a blob volume created by an earlier,
# root-running image (every deployment before this one) is root-owned, and
# a non-root server would fail every large-payload write against it. The
# chown is skipped once ownership is already right, so a large store is not
# re-walked on every boot.
set -eu

BLOB_ROOT="${TRAZO_BLOB_ROOT:-/var/lib/trazo/blobs}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$BLOB_ROOT"
    if [ "$(stat -c %u "$BLOB_ROOT")" != "10001" ]; then
        chown -R trazo:trazo "$BLOB_ROOT"
    fi
    # setpriv changes the user but not the environment. Left as /root, HOME
    # makes asyncpg probe /root/.postgresql/ for client certificates and die
    # on the permission error instead of treating them as absent.
    export HOME=/app
    exec setpriv --reuid=trazo --regid=trazo --init-groups -- "$@"
fi

exec "$@"
