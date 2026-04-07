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
./scripts/validate_registry.py
./scripts/register.py template
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
- `validate_registry.py`
  - validates all package definitions before the workflow starts

## GitHub Actions

Workflow file:

- `.github/workflows/build-and-publish-package.yml`

It can run in two modes:

- scheduled automatic polling every hour
- manual dispatch for one selected package

Automatic flow:

- detect upstream version changes for all enabled packages
- build changed packages in dependency order
- upload RPMs to a temporary directory on the repo host
- smoke-test each package inside a temporary `podman` EL10 container on the repo host
- publish only after the smoke test passes
- smoke-test behavior comes from each package definition in `registry/packages/*.json`

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
- Smoke tests run on the repo host but inside disposable `podman` containers, so
  the host stays clean while still validating a real `dnf install` path.
- New packages should define a `test` section with install targets, expected files,
  and smoke-test commands so the pipeline stays fully declarative.
- `registry/package-template.json` is the baseline template for new packages.
