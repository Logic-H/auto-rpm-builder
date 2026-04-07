#!/bin/bash
set -euo pipefail

PACKAGE="${1:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
STAGE_DIR="${2:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
CONTAINER_NAME="trilby-smoke-${PACKAGE}-$$"
IMAGE="${PACKAGER_SMOKE_IMAGE:-registry.access.redhat.com/ubi10/ubi:latest}"
REPO_URL="${PACKAGER_PUBLIC_REPO_URL:-http://repo.imhzj.com/custom/el10/x86_64/}"
SMOKE_JSON="${STAGE_DIR}/smoke-test.json"
SMOKE_SCRIPT="${STAGE_DIR}/.smoke-repo/run-smoke.sh"

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

python3 - "$SMOKE_JSON" "$SMOKE_SCRIPT" <<'PY'
import json
import shlex
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
script_path = Path(sys.argv[2])

with config_path.open() as f:
    data = json.load(f)

install = data.get("install", [])
if not install:
    raise SystemExit("smoke test install targets are empty")

lines = [
    "#!/bin/bash",
    "set -euo pipefail",
]

for key, value in sorted((data.get("env") or {}).items()):
    lines.append(f"export {key}={shlex.quote(value)}")

lines.append("dnf -y makecache --disablerepo='*' --enablerepo=local-smoke,trilby-live")
lines.extend(data.get("pre_install_commands") or [])
lines.append(
    "dnf -y install --disablerepo='*' --enablerepo=local-smoke,trilby-live "
    + " ".join(shlex.quote(item) for item in install)
)

for path in data.get("files") or []:
    lines.append(f"test -e {shlex.quote(path)}")

for unit in data.get("unit_files") or []:
    lines.append(f"test -e /usr/lib/systemd/system/{shlex.quote(unit)}")

lines.extend(data.get("commands") or [])
lines.extend(data.get("post_install_commands") or [])

script_path.write_text("\n".join(lines) + "\n")
script_path.chmod(0o755)
PY

podman run --name "$CONTAINER_NAME" --rm --cgroups=disabled \
  -v "$STAGE_DIR/.smoke-repo:/repo:Z,ro" \
  -v "$STAGE_DIR/.smoke-repo/local-smoke.repo:/etc/yum.repos.d/local-smoke.repo:Z,ro" \
  -v "$SMOKE_SCRIPT:/run-smoke.sh:Z,ro" \
  "$IMAGE" \
  bash /run-smoke.sh

python3 /opt/packager/scripts/packager.py import-rpms "$STAGE_DIR"/*.rpm
