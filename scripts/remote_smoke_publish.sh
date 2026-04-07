#!/bin/bash
set -euo pipefail

PACKAGE="${1:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
STAGE_DIR="${2:?usage: remote_smoke_publish.sh <package> <stage_dir>}"
CONTAINER_NAME="trilby-smoke-${PACKAGE}-$$"
IMAGE="${PACKAGER_SMOKE_IMAGE:-registry.access.redhat.com/ubi10/ubi:latest}"
REPO_URL="${PACKAGER_PUBLIC_REPO_URL:-http://repo.imhzj.com/custom/el10/x86_64/}"

cleanup() {
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf "$STAGE_DIR/.smoke-repo"
}
trap cleanup EXIT

if [[ ! -d "$STAGE_DIR" ]]; then
  echo "stage dir not found: $STAGE_DIR" >&2
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

podman run --name "$CONTAINER_NAME" --rm --cgroups=disabled \
  -v "$STAGE_DIR/.smoke-repo:/repo:Z,ro" \
  -v "$STAGE_DIR/.smoke-repo/local-smoke.repo:/etc/yum.repos.d/local-smoke.repo:Z,ro" \
  "$IMAGE" \
  bash -lc "
    set -euo pipefail
    dnf -y makecache --disablerepo='*' --enablerepo=local-smoke,trilby-live
    case '$PACKAGE' in
      ghostty)
        dnf -y install --disablerepo='*' --enablerepo=local-smoke,trilby-live ghostty
        test -x /usr/bin/ghostty
        test -f /usr/share/applications/com.mitchellh.ghostty.desktop
        grep -q '^Exec=/usr/bin/ghostty' /usr/share/applications/com.mitchellh.ghostty.desktop
        ;;
      gtk4-layer-shell)
        dnf -y install --disablerepo='*' --enablerepo=local-smoke,trilby-live gtk4-layer-shell gtk4-layer-shell-devel
        test -e /usr/lib64/libgtk4-layer-shell.so.0
        test -e /usr/lib64/pkgconfig/gtk4-layer-shell-0.pc
        ;;
      dae)
        dnf -y install --disablerepo='*' --enablerepo=local-smoke,trilby-live dae
        /usr/bin/dae --help >/dev/null
        test -f /usr/lib/systemd/system/dae.service
        ;;
      daed)
        dnf -y install --disablerepo='*' --enablerepo=local-smoke,trilby-live daed
        /usr/bin/daed --help >/dev/null
        test -f /usr/lib/systemd/system/daed.service
        test -f /usr/share/applications/daed.desktop
        ;;
      *)
        echo \"unsupported smoke-test package: $PACKAGE\" >&2
        exit 1
        ;;
    esac
  "

python3 /opt/packager/scripts/packager.py import-rpms "$STAGE_DIR"/*.rpm
