# Auto RPM Builder

This project builds custom EL10 RPMs from `registry/packages/*.json` and publishes
them into the repository served from `repo.imhzj.com`.

## Current model

- GitHub Actions does the heavy build work on hosted runners.
- `chuncheon-vps` only stores RPMs, signs them, and serves the yum/dnf repo.
- Package definitions stay in `registry/packages/*.json`.

## Supported flows

- `github-release` + `rpm-from-archive`
- `github-release` + `repack-rpm`
- `git` + `rpmbuild-spec`

## Local commands

```bash
./scripts/packager.py list
./scripts/packager.py build-one daed --force
./scripts/packager.py sync-one daed --force
./scripts/packager.py import-rpms work/builds/daed/*/*.rpm
./scripts/publish_remote.sh daed
```

Command summary:

- `build-one`
  - builds locally and records `last_built_rpms`
  - does not publish or sign
- `sync-one`
  - builds locally, signs, and publishes to the current repo directory
- `import-rpms`
  - imports prebuilt RPMs into the current repo directory
  - removes old repo RPMs with the same RPM package names
  - signs RPMs and refreshes repodata

## GitHub Actions

Workflow file:

- `.github/workflows/build-and-publish-package.yml`

It builds a selected package on a GitHub-hosted runner and then uploads the RPMs
to the VPS, where `/opt/packager/scripts/packager.py import-rpms` publishes them.

Required GitHub repository secrets:

- `PACKAGER_REMOTE_HOST`
  - example: `repo.imhzj.com`
- `PACKAGER_REMOTE_USER`
  - example: `cloud-user`
- `PACKAGER_REMOTE_SSH_KEY`
  - private key that can SSH to the repo host and run `sudo /opt/packager/scripts/packager.py import-rpms`

## Notes

- The signing key stays on the VPS.
- GitHub runners never need the repo signing private key.
- For packages with local dependency chains such as `ghostty -> gtk4-layer-shell`,
  `build-one` can reuse dependency RPMs built earlier in the same run.
