#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=3141}"
: "${DEVPI_SERVERDIR:=/data/server}"
: "${DEVPI_SECRETFILE:=/data/.secret}"
: "${DEVPI_RESTRICT_MODIFY:=root}"

INIT_SENTINEL="/data/.initialized"

mkdir -p /data "$DEVPI_SERVERDIR"

if [ ! -f "$DEVPI_SECRETFILE" ]; then
    echo "[entrypoint] generating persistent secret at $DEVPI_SECRETFILE"
    umask 077
    head -c 32 /dev/urandom | base64 > "$DEVPI_SECRETFILE"
    chmod 600 "$DEVPI_SECRETFILE"
fi

if [ ! -f "$INIT_SENTINEL" ]; then
    echo "[entrypoint] initializing devpi server in $DEVPI_SERVERDIR"
    init_args=(--serverdir "$DEVPI_SERVERDIR")
    if [ -n "${DEVPI_ROOT_PASSWORD:-}" ]; then
        init_args+=(--root-passwd "$DEVPI_ROOT_PASSWORD")
    fi
    devpi-init "${init_args[@]}"
    touch "$INIT_SENTINEL"
else
    echo "[entrypoint] existing devpi state detected, skipping devpi-init"
fi

server_args=(
    --serverdir "$DEVPI_SERVERDIR"
    --secretfile "$DEVPI_SECRETFILE"
    --host 0.0.0.0
    --port "$PORT"
    --request-timeout 60
)

if [ -n "$DEVPI_RESTRICT_MODIFY" ]; then
    server_args+=(--restrict-modify "$DEVPI_RESTRICT_MODIFY")
fi

echo "[entrypoint] starting devpi-server on 0.0.0.0:$PORT"
exec devpi-server "${server_args[@]}"
