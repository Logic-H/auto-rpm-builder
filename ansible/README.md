# Ansible Layout

## Purpose

This directory wraps the current auto RPM builder MVP into Ansible-managed deployment.

## Inventory

Edit [`inventory.ini`](/home/huazi/auto-rpm-builder/ansible/inventory.ini) if the repo builder host changes.

## Playbooks

- `playbooks/deploy_builder.yml`
  - installs system dependencies
  - deploys `/opt/packager`
  - installs nginx
  - installs the systemd timer unit but leaves it disabled by default
  - restores SELinux labels for the custom repo path

- `playbooks/sync_packages.yml`
  - runs `sync-one --force` for the package list in `group_vars/repo_builder.yml`

- `playbooks/install_client_repo.yml`
  - installs the generated repo file on client hosts

## Variables

Main variables are in [`group_vars/repo_builder.yml`](/home/huazi/auto-rpm-builder/ansible/group_vars/repo_builder.yml).

## Typical usage

```bash
ansible-galaxy collection install -r ansible/requirements.yml
ansible-playbook -i ansible/inventory.ini ansible/playbooks/deploy_builder.yml
ansible-playbook -i ansible/inventory.ini ansible/playbooks/sync_packages.yml
```

## Notes

- `state/` and `work/` are intentionally preserved on the remote host and are not deleted by deployment.
- This role assumes the control node can reach the repo builder over SSH.
- Local VPS builds are disabled by default through `packager_enable_local_builder: false`.
- The intended production path is GitHub Actions build -> remote `import-rpms` publish.
