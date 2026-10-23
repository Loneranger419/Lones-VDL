#!/bin/sh
# Start as root only long enough to make the local data volume writable, then drop to
# PUID:PGID (match the owner of the archive share so CIFS/NFS writes succeed).
# Never chowns the archive: it may be a network share with its own permission model.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DATA_DIR="${LONES_VDL_DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR" "$HOME" "$XDG_CACHE_HOME"
    chown -R "$PUID:$PGID" "$DATA_DIR"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- "$@"
fi

exec "$@"
