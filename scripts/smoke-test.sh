#!/usr/bin/env bash
# End-to-end smoke test for the private-python-registry template.
#
# Builds the image, boots a container on a named volume, exercises the
# full user journey (create user/index -> upload wheel -> pip install),
# then restarts the container on the same volume to prove persistence.
set -euo pipefail

IMAGE_TAG="${IMAGE_TAG:-private-python-registry:smoke}"
VOLUME_NAME="${VOLUME_NAME:-ppr-smoke-data}"
CONTAINER_NAME="${CONTAINER_NAME:-ppr-smoke}"
HOST_PORT="${HOST_PORT:-13141}"
ROOT_PASSWORD="smoke-root-pw"
USER_NAME="smoker"
USER_PASSWORD="smoker-pw"
INDEX_NAME="dev"
PKG_NAME="ppr_smoke_pkg"
PKG_VERSION="0.1.0"

WORK_DIR="$(mktemp -d)"
trap 'cleanup' EXIT INT TERM

log()  { printf '\033[1;34m[smoke]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[smoke]\033[0m %s\n' "$*" >&2; exit 1; }

pre_clean() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME_NAME" >/dev/null 2>&1 || true
}

cleanup() {
    log "cleaning up"
    pre_clean
    rm -rf "$WORK_DIR"
}

wait_ready() {
    local url="http://localhost:${HOST_PORT}/+api"
    for i in $(seq 1 60); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    docker logs "$CONTAINER_NAME" || true
    fail "devpi-server did not become ready on $url"
}

start_container() {
    log "starting container $CONTAINER_NAME"
    docker run -d --rm \
        --name "$CONTAINER_NAME" \
        -e PORT=3141 \
        -e DEVPI_ROOT_PASSWORD="$ROOT_PASSWORD" \
        -p "${HOST_PORT}:3141" \
        -v "${VOLUME_NAME}:/data" \
        "$IMAGE_TAG" >/dev/null
    wait_ready
}

in_container() { docker exec "$CONTAINER_NAME" "$@"; }

# --- 1. build image -------------------------------------------------------
log "building image $IMAGE_TAG"
docker build -t "$IMAGE_TAG" "$(dirname "$0")/.."

# --- 2. prepare a minimal package on the host ----------------------------
log "preparing minimal package in $WORK_DIR"
PKG_SRC="$WORK_DIR/pkg"
mkdir -p "$PKG_SRC/${PKG_NAME}"
cat > "$PKG_SRC/${PKG_NAME}/__init__.py" <<'PY'
def hello():
    return "hello from the private registry"
PY
cat > "$PKG_SRC/pyproject.toml" <<EOF
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "${PKG_NAME}"
version = "${PKG_VERSION}"
description = "Smoke-test package for private-python-registry"
requires-python = ">=3.8"

[tool.setuptools]
packages = ["${PKG_NAME}"]
EOF

# --- 3. first boot -------------------------------------------------------
pre_clean
docker volume create "$VOLUME_NAME" >/dev/null
start_container

# --- 4. create user + index, upload wheel --------------------------------
log "configuring devpi client inside container"
in_container devpi use "http://localhost:3141"
in_container devpi login root --password="$ROOT_PASSWORD"
in_container devpi user -c "$USER_NAME" password="$USER_PASSWORD" email="${USER_NAME}@example.com"
# With --restrict-modify root, only root can create indexes — do it before switching user.
in_container devpi index -c "${USER_NAME}/${INDEX_NAME}" bases=root/pypi volatile=True
in_container devpi login "$USER_NAME" --password="$USER_PASSWORD"
in_container devpi use "${USER_NAME}/${INDEX_NAME}"

log "copying package source into container and uploading via devpi upload"
in_container rm -rf /tmp/pkg
docker cp "$PKG_SRC" "${CONTAINER_NAME}:/tmp/pkg"
in_container bash -c "cd /tmp/pkg && devpi upload --no-vcs"

# --- 5. verify install via pip inside a throwaway container --------------
INDEX_URL="http://${USER_NAME}:${USER_PASSWORD}@host.docker.internal:${HOST_PORT}/${USER_NAME}/${INDEX_NAME}/+simple/"
# host.docker.internal is only reliable on Desktop; fall back to container exec
log "installing ${PKG_NAME} from the private index (via container)"
in_container bash -c "pip install --quiet --index-url http://${USER_NAME}:${USER_PASSWORD}@localhost:3141/${USER_NAME}/${INDEX_NAME}/+simple/ ${PKG_NAME}==${PKG_VERSION}"
in_container python -c "import ${PKG_NAME}; assert ${PKG_NAME}.hello().startswith('hello'), 'pkg import failed'"

# --- 6. restart on same volume, verify persistence -----------------------
log "stopping container to test persistence"
docker rm -f "$CONTAINER_NAME" >/dev/null
start_container

log "verifying package still present after restart"
in_container devpi use "http://localhost:3141/${USER_NAME}/${INDEX_NAME}"
if ! in_container devpi list "$PKG_NAME" | grep -q "$PKG_VERSION"; then
    docker logs "$CONTAINER_NAME" || true
    fail "package ${PKG_NAME}==${PKG_VERSION} missing after restart — persistence broken"
fi

log "verifying root login still valid after restart (secretfile ok)"
in_container devpi login root --password="$ROOT_PASSWORD"

log "OK — smoke test passed"
