#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE="${1:?usage: publish_remote.sh <package> [remote]}"
REMOTE="${2:-${PACKAGER_REMOTE:-cloud-user@repo.imhzj.com}}"
STATE_FILE="$ROOT/state/${PACKAGE}.json"
STAGE_ROOT="${PACKAGER_REMOTE_STAGE_ROOT:-/home/cloud-user/auto-rpm-builder-stage}"
STAGE_DIR="${STAGE_ROOT}/${PACKAGE}"
REMOTE_HELPER="${STAGE_DIR}/remote_smoke_publish.sh"
LOCAL_SMOKE_JSON="$(mktemp)"
SSH_KEY="${PACKAGER_REMOTE_KEY:-$HOME/.ssh/id_ed25519}"
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

cleanup() {
  rm -f "$LOCAL_SMOKE_JSON"
}
trap cleanup EXIT

if [[ ! -f "$STATE_FILE" ]]; then
  echo "state file not found: $STATE_FILE" >&2
  exit 1
fi

mapfile -t RPMS < <(
  python3 - "$STATE_FILE" <<'PY'
import json
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

for path in data.get("last_built_rpms", []):
    print(path)
PY
)

if [[ "${#RPMS[@]}" -eq 0 ]]; then
  echo "no built RPMs recorded for package: $PACKAGE" >&2
  exit 1
fi

for rpm in "${RPMS[@]}"; do
  if [[ ! -f "$rpm" ]]; then
    echo "built RPM missing: $rpm" >&2
    exit 1
  fi
done

python3 "$ROOT/scripts/export_smoke_test.py" "$PACKAGE" "$LOCAL_SMOKE_JSON"

ssh "${SSH_OPTS[@]}" "$REMOTE" "rm -rf '$STAGE_DIR' && mkdir -p '$STAGE_DIR'"
rsync -av -e "ssh ${SSH_OPTS[*]}" "${RPMS[@]}" "${REMOTE}:${STAGE_DIR}/"
rsync -av -e "ssh ${SSH_OPTS[*]}" "$ROOT/scripts/remote_smoke_publish.sh" "${REMOTE}:${REMOTE_HELPER}"
rsync -av -e "ssh ${SSH_OPTS[*]}" "$LOCAL_SMOKE_JSON" "${REMOTE}:${STAGE_DIR}/smoke-test.json"
ssh "${SSH_OPTS[@]}" "$REMOTE" "chmod 755 '$REMOTE_HELPER' && sudo '$REMOTE_HELPER' '$PACKAGE' '$STAGE_DIR'"
