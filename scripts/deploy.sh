#!/bin/bash
set -euo pipefail

REMOTE="${1:-cloud-user@repo.imhzj.com}"
ROOT_LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ssh -i /home/huazi/.ssh/id_ed25519 "$REMOTE" 'rm -rf /home/cloud-user/auto-rpm-builder && mkdir -p /home/cloud-user/auto-rpm-builder'
rsync -a --delete -e "ssh -i /home/huazi/.ssh/id_ed25519" "$ROOT_LOCAL/" "$REMOTE:/home/cloud-user/auto-rpm-builder/"

ssh -i /home/huazi/.ssh/id_ed25519 "$REMOTE" '
set -euo pipefail
sudo mkdir -p /opt/packager
sudo mkdir -p /opt/packager/state /opt/packager/work
sudo rsync -a --delete \
  --exclude state/ \
  --exclude work/ \
  /home/cloud-user/auto-rpm-builder/ /opt/packager/
sudo chown -R root:root /opt/packager
sudo chmod 755 /opt/packager/scripts/packager.py
sudo chmod 755 /opt/packager/scripts/remote_smoke_publish.sh
sudo chmod 755 /opt/packager/scripts/process_queue.py
sudo chmod 755 /opt/packager/scripts/webhook_server.py
sudo chmod 755 /opt/packager/scripts/register.py
sudo chmod 755 /opt/packager/scripts/snapshot_ghostty.py
sudo mkdir -p /srv/repos/custom/el10/x86_64/Packages
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/repos/custom(/.*)?" 2>/dev/null || sudo semanage fcontext -m -t httpd_sys_content_t "/srv/repos/custom(/.*)?"
sudo restorecon -RF /srv/repos/custom >/dev/null 2>&1 || true
'
