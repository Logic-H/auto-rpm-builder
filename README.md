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
- `url` + `repack-rpm`
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

## Add a package

Shortest path for a new package:

1. Copy [`registry/package-template.json`](/home/huazi/auto-rpm-builder/registry/package-template.json) to `registry/packages/<name>.json`.
2. Fill in `source`, `build`, and `test`.
3. Run `./scripts/validate_registry.py`.
4. If needed, test locally with `./scripts/packager.py build-one <name> --force`.
5. Commit to `main` or run the workflow manually for that package.

Practical rules:

- Keep the `test` section declarative and minimal.
- Prefer `test -e` over `test -x` unless the file is actually executable in the RPM payload.
- If the package ships its own RPM and install scripts are hostile to containers, use `test.dnf_args`, for example `--setopt=tsflags=noscripts`.
- If a package depends on another custom package, declare it in `requires`.

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

It can run in these modes:

- scheduled automatic polling every hour
- push-triggered incremental builds on `main`
- manual dispatch for one selected package

Automatic flow:

- detect upstream version changes for all enabled packages
- detect package definitions and packaging changes from Git on push
- merge both change sets and keep only affected packages
- build changed packages in dependency order
- upload a build bundle as a GitHub Actions artifact
- send a signed webhook to `repo.imhzj.com`
- let the VPS queue worker pull the artifact from GitHub
- smoke-test each package inside a temporary `podman` EL10 container on the repo host
- publish only after the smoke test passes
- smoke-test behavior comes from each package definition in `registry/packages/*.json`

Required GitHub repository secrets:

- `PACKAGER_WEBHOOK_SECRET`
  - shared HMAC secret used by GitHub Actions and the VPS webhook endpoint

## Notes

- The signing key stays on the VPS.
- GitHub runners never need the repo signing private key.
- GitHub runners also never need SSH access to the repo host.
- The VPS needs a GitHub token in `/etc/auto-rpm-builder.env` so it can download workflow artifacts.
- For packages with local dependency chains such as `ghostty -> gtk4-layer-shell`,
  `build-one` can reuse dependency RPMs built earlier in the same run.
- Smoke tests run on the repo host but inside disposable `podman` containers, so
  the host stays clean while still validating a real `dnf install` path.
- New packages should define a `test` section with install targets, expected files,
  and smoke-test commands so the pipeline stays fully declarative.
- `registry/package-template.json` is the baseline template for new packages.
- `schema_version: 1` is now required in every package definition.
- `test` also supports `dnf_args`, `env`, `pre_install_commands`, `unit_files`,
  and `post_install_commands` for more complex packages without changing the runner.
