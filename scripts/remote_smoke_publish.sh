#!/bin/bash
set -euo pipefail

PACKAGE="${1:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
STAGE_DIR="${2:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
CONTAINER_NAME="trilby-smoke-${PACKAGE}-$$"
IMAGE="${PACKAGER_SMOKE_IMAGE:-registry.access.redhat.com/ubi10/ubi:latest}"
REPO_URL="${PACKAGER_PUBLIC_REPO_URL:-http://repo.imhzj.com/custom/el10/x86_64/}"
SMOKE_JSON="${STAGE_DIR}/smoke-test.json"

cleanup() {
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf "$STAGE_DIR/.smoke-repo"
}
trap cleanup EXIT

if [[ ! -d "$STAGE_DIR" ]]; then
  echo "stage dir not found: $STAGE_DIR" >&2
  exit 1
fi
if [[ ! -f "$SMOKE_JSON" ]]; then
  echo "smoke test config not found: $SMOKE_JSON" >&2
  exit 1
fi

mkdir -p "$STAGE_DIR/.smoke-repo"
find "$STAGE_DIR/.smoke-repo" -mindepth 1 -delete
cp -f "$STAGE_DIR"/*.rpm "$STAGE_DIR/.smoke-repo/"
createrepo_c --update "$STAGE_DIR/.smoke-repo"

cat >"$STAGE_DIR/.smoke-repo/local-smoke.repo" <<EOF
[local-smoke]
name=Local Smoke Repo
baseurl=file:///repo
enabled=1
gpgcheck=0
repo_gpgcheck=0

[trilby-live]
name=Trilby Live Repo
baseurl=${REPO_URL}
enabled=1
gpgcheck=0
repo_gpgcheck=0
EOF

INSTALL_ARGS="$(python3 - "$SMOKE_JSON" <<'PY'
import json
import shlex
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

print(" ".join(shlex.quote(item) for item in data.get("install", [])))
PY
)"

FILE_CHECKS="$(python3 - "$SMOKE_JSON" <<'PY'
import json
import shlex
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

for path in data.get("files", []):
    print(f"test -e {shlex.quote(path)}")
PY
)"

COMMAND_CHECKS="$(python3 - "$SMOKE_JSON" <<'PY'
import json
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

for cmd in data.get("commands", []):
    print(cmd)
PY
)"

if [[ -z "$INSTALL_ARGS" ]]; then
  echo "smoke test install targets are empty for $PACKAGE" >&2
  exit 1
fi

podman run --name "$CONTAINER_NAME" --rm --cgroups=disabled \
  -v "$STAGE_DIR/.smoke-repo:/repo:Z,ro" \
  -v "$STAGE_DIR/.smoke-repo/local-smoke.repo:/etc/yum.repos.d/local-smoke.repo:Z,ro" \
  "$IMAGE" \
  bash -lc "
    set -euo pipefail
    dnf -y makecache --disablerepo='*' --enablerepo=local-smoke,trilby-live
    dnf -y install --disablerepo='*' --enablerepo=local-smoke,trilby-live ${INSTALL_ARGS}
    ${FILE_CHECKS}
    ${COMMAND_CHECKS}
  "

python3 /opt/packager/scripts/packager.py import-rpms "$STAGE_DIR"/*.rpm
