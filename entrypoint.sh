#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=3141}"
: "${DEVPI_SERVERDIR:=/data/server}"
: "${DEVPI_SECRETFILE:=/data/.secret}"
: "${DEVPI_RESTRICT_MODIFY:=root}"
: "${DEVPI_TRUSTED_PROXY:=*}"
: "${DEVPI_TRUSTED_PROXY_COUNT:=1}"
: "${DEVPI_TRUSTED_PROXY_HEADERS:=x-forwarded-proto x-forwarded-for x-forwarded-host}"

# On Railway, RAILWAY_PUBLIC_DOMAIN is injected automatically for services
# with a public domain. Use it to set --outside-url so devpi-web generates
# correct https:// links (no mixed-content) unless the user overrode it.
if [ -z "${DEVPI_OUTSIDE_URL:-}" ] && [ -n "${RAILWAY_PUBLIC_DOMAIN:-}" ]; then
    DEVPI_OUTSIDE_URL="https://${RAILWAY_PUBLIC_DOMAIN}"
fi

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
    --trusted-proxy "$DEVPI_TRUSTED_PROXY"
    --trusted-proxy-count "$DEVPI_TRUSTED_PROXY_COUNT"
    --trusted-proxy-headers "$DEVPI_TRUSTED_PROXY_HEADERS"
)

if [ -n "${DEVPI_OUTSIDE_URL:-}" ]; then
    echo "[entrypoint] outside URL: $DEVPI_OUTSIDE_URL"
    server_args+=(--outside-url "$DEVPI_OUTSIDE_URL")
fi

if [ -n "$DEVPI_RESTRICT_MODIFY" ]; then
    server_args+=(--restrict-modify "$DEVPI_RESTRICT_MODIFY")
fi

if [ -n "${DEVPI_THEME_DIR:-}" ] && [ -d "$DEVPI_THEME_DIR" ]; then
    echo "[entrypoint] using devpi-web theme at $DEVPI_THEME_DIR"
    server_args+=(--theme "$DEVPI_THEME_DIR")
elif [ -n "${DEVPI_THEME_DIR:-}" ]; then
    echo "[entrypoint] warning: DEVPI_THEME_DIR=$DEVPI_THEME_DIR is set but not a directory, skipping theme"
fi

echo "[entrypoint] starting devpi-server on 0.0.0.0:$PORT"
exec devpi-server "${server_args[@]}"
