#!/bin/bash
set -euo pipefail

PACKAGE="${1:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
STAGE_DIR="${2:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
CONTAINER_NAME="trilby-smoke-${PACKAGE}-$$"
IMAGE="${PACKAGER_SMOKE_IMAGE:-registry.access.redhat.com/ubi10/ubi:latest}"
REPO_URL="${PACKAGER_PUBLIC_REPO_URL:-http://repo.imhzj.com/custom/el10/x86_64/}"
SMOKE_JSON="${STAGE_DIR}/smoke-test.json"
SMOKE_SCRIPT="${STAGE_DIR}/.smoke-repo/run-smoke.sh"
SMOKE_RUNNER=""
INSTALLROOT_DIR=""

cleanup() {
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  if [[ -n "$INSTALLROOT_DIR" ]]; then
    rm -rf "$INSTALLROOT_DIR"
  fi
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

SMOKE_RUNNER="$(python3 - "$SMOKE_JSON" <<'PY'
import json
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

print(data.get("runner") or "container")
PY
)"

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
dnf_args = data.get("dnf_args") or []
runner = data.get("runner") or "container"

lines = [
    "#!/bin/bash",
    "set -euo pipefail",
]

for key, value in sorted((data.get("env") or {}).items()):
    lines.append(f"export {key}={shlex.quote(value)}")

if runner == "installroot":
    lines.append(': "${INSTALLROOT:?INSTALLROOT must be set for installroot smoke tests}"')
    lines.append("SMOKE_ROOT=$INSTALLROOT")
else:
    lines.append("SMOKE_ROOT=")

dnf_prefix = ""
if runner == "installroot":
    dnf_prefix = (
        'dnf -y --installroot "$SMOKE_ROOT" --releasever=/ '
        '--setopt=reposdir="$SMOKE_ROOT/etc/yum.repos.d" '
        "--disablerepo='*' --enablerepo=local-smoke,trilby-live "
    )
else:
    dnf_prefix = "dnf -y --disablerepo='*' --enablerepo=local-smoke,trilby-live "

lines.extend(data.get("pre_install_commands") or [])
lines.append(
    dnf_prefix
    + "install "
    + (" ".join(shlex.quote(item) for item in dnf_args) + " " if dnf_args else "")
    + " ".join(shlex.quote(item) for item in install)
)

for path in data.get("files") or []:
    lines.append(f'test -e "$SMOKE_ROOT{path}"')

for unit in data.get("unit_files") or []:
    lines.append(f'test -e "$SMOKE_ROOT/usr/lib/systemd/system/{unit}"')

lines.extend(data.get("commands") or [])
lines.extend(data.get("post_install_commands") or [])

script_path.write_text("\n".join(lines) + "\n")
script_path.chmod(0o755)
PY

if [[ "$SMOKE_RUNNER" == "container" ]]; then
  podman run --name "$CONTAINER_NAME" --rm --cgroups=disabled \
    -v "$STAGE_DIR/.smoke-repo:/repo:Z,ro" \
    -v "$STAGE_DIR/.smoke-repo/local-smoke.repo:/etc/yum.repos.d/local-smoke.repo:Z,ro" \
    -v "$SMOKE_SCRIPT:/run-smoke.sh:Z,ro" \
    "$IMAGE" \
    bash /run-smoke.sh
elif [[ "$SMOKE_RUNNER" == "installroot" ]]; then
  INSTALLROOT_DIR="$(mktemp -d /tmp/trilby-installroot-${PACKAGE}-XXXXXX)"
  mkdir -p "$INSTALLROOT_DIR/root/etc/yum.repos.d"
  cat >"$INSTALLROOT_DIR/root/etc/yum.repos.d/local-smoke.repo" <<EOF
[local-smoke]
name=Local Smoke Repo
baseurl=file://${STAGE_DIR}/.smoke-repo
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
  dnf -y --installroot "$INSTALLROOT_DIR/root" --releasever=/ \
    --setopt=reposdir="$INSTALLROOT_DIR/root/etc/yum.repos.d" \
    --disablerepo='*' --enablerepo=local-smoke,trilby-live makecache
  INSTALLROOT="$INSTALLROOT_DIR/root" bash "$SMOKE_SCRIPT"
else
  echo "unsupported smoke runner: $SMOKE_RUNNER" >&2
  exit 1
fi

python3 /opt/packager/scripts/packager.py import-rpms "$STAGE_DIR"/*.rpm
