#!/usr/bin/env python3
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parent.parent
REGISTRY_DIR = ROOT / "registry" / "packages"
STATE_DIR = ROOT / "state"
WORK_DIR = ROOT / "work"
REPO_DIR = Path(os.environ.get("PACKAGER_REPO_DIR", "/srv/repos/custom/el10/x86_64"))
REPO_PACKAGES_DIR = REPO_DIR / "Packages"
REPO_ROOT_DIR = REPO_DIR.parent.parent
GPG_HOME = Path(os.environ.get("PACKAGER_GPG_HOME", "/opt/packager/gnupg"))
GPG_KEY_NAME = os.environ.get("PACKAGER_GPG_KEY_NAME", "Huazi EL10 Repo <repo@imhzj.com>")
GPG_PRIMARY_KEY_ID = os.environ.get(
    "PACKAGER_GPG_PRIMARY_KEY_ID",
    "6FD5AADC6FAD40C229A4E4B0E3A41A4F89311F85!",
)
GPG_PUBLIC_KEY_PATH = Path(
    os.environ.get("PACKAGER_GPG_PUBLIC_KEY_PATH", str(REPO_ROOT_DIR / "RPM-GPG-KEY-huazi-el10"))
)


def run(cmd, **kwargs):
    kwargs.setdefault("check", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **kwargs)


def ensure_dirs():
    for path in (STATE_DIR, WORK_DIR, WORK_DIR / "builds", REPO_PACKAGES_DIR, GPG_HOME):
        path.mkdir(parents=True, exist_ok=True)
    os.chmod(GPG_HOME, 0o700)


def load_package(name):
    path = REGISTRY_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"package definition not found: {path}")
    with path.open() as f:
        data = json.load(f)
    data["_path"] = str(path)
    return data


def iter_packages():
    for path in sorted(REGISTRY_DIR.glob("*.json")):
        with path.open() as f:
            data = json.load(f)
        data["_path"] = str(path)
        yield data


def state_path(name):
    return STATE_DIR / f"{name}.json"


def load_state(name):
    path = state_path(name)
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def save_state(name, data):
    path = state_path(name)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def merge_state(name, updates):
    state = load_state(name)
    state.update(updates)
    save_state(name, state)


def github_api_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "auto-rpm-builder/0.1"
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def normalize_version(tag, mode):
    if mode == "strip-v":
        return tag[1:] if tag.startswith("v") else tag
    return tag


def select_asset(assets, patterns):
    for pattern in patterns:
        regex = re.compile(pattern)
        for asset in assets:
            if regex.search(asset["name"]):
                return asset
    raise RuntimeError(f"no asset matched patterns: {patterns}")


def git_stdout(args, cwd=None):
    return run(["git", *args], cwd=cwd, capture_output=True).stdout.strip()


def download_file(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "auto-rpm-builder/0.1"})
    with urllib.request.urlopen(req) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)


def fetch_latest_source(pkg):
    source = pkg["source"]
    if source["type"] == "github-release":
        repo = source["repo"]
        release = github_api_json(f"https://api.github.com/repos/{repo}/releases/latest")
        version = normalize_version(release["tag_name"], source.get("version_mode", "raw"))
        build_id = release["tag_name"]
        asset_patterns = source.get("asset_patterns", [])
        asset = None
        if asset_patterns:
            asset = select_asset(release.get("assets", []), asset_patterns)

        source_dir = WORK_DIR / "sources" / pkg["name"] / version
        asset_path = None
        if asset:
            asset_path = source_dir / asset["name"]
            if not asset_path.exists():
                download_file(asset["browser_download_url"], asset_path)

        return {
            "version": version,
            "build_id": build_id,
            "release_tag": release["tag_name"],
            "asset_name": asset["name"] if asset else release["tag_name"],
            "asset_url": asset["browser_download_url"] if asset else f"https://github.com/{repo}/releases/tag/{release['tag_name']}",
            "asset_path": asset_path,
        }

    if source["type"] == "local-file":
        asset_path = Path(source["path"])
        if not asset_path.exists():
            raise RuntimeError(f"local source file not found: {asset_path}")
        version = source["version"]
        return {
            "version": version,
            "build_id": source.get("build_id", version),
            "release_tag": source.get("release_tag", version),
            "asset_name": asset_path.name,
            "asset_url": str(asset_path),
            "asset_path": asset_path,
        }

    if source["type"] == "git":
        repo_url = source["repo"]
        checkout_dir = WORK_DIR / "sources" / pkg["name"] / "git-checkout"
        if checkout_dir.exists():
            shutil.rmtree(checkout_dir)

        clone_cmd = ["git", "clone", "--depth", "1"]
        ref = source.get("ref")
        if ref:
            clone_cmd.extend(["--branch", ref])
        clone_cmd.extend([repo_url, str(checkout_dir)])
        run(clone_cmd)

        revision = git_stdout(["rev-parse", "HEAD"], cwd=checkout_dir)
        return {
            "version": revision[:12],
            "build_id": revision,
            "release_tag": revision,
            "asset_name": checkout_dir.name,
            "asset_url": repo_url,
            "asset_path": checkout_dir,
            "checkout_dir": checkout_dir,
        }

    raise RuntimeError(f"unsupported source type: {source['type']}")


def rpmspec_query(spec_path, fmt, topdir=None):
    cmd = ["rpmspec", "-q", "--srpm", "--qf", fmt]
    if topdir:
        cmd.extend(["--define", f"_topdir {topdir}"])
    cmd.append(str(spec_path))
    return run(cmd, capture_output=True).stdout.strip()


def clone_tree(src, dest):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True)


def gpg_run(args, **kwargs):
    return run(["gpg", "--homedir", str(GPG_HOME), "--batch", "--yes", *args], **kwargs)


def ensure_signing_key():
    keys = gpg_run(["--list-secret-keys", "--with-colons", GPG_KEY_NAME], check=False, capture_output=True)
    if keys.returncode != 0 or "sec:" not in keys.stdout:
        batch = f"""%no-protection
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: {GPG_KEY_NAME.split(' <', 1)[0]}
Name-Email: {GPG_KEY_NAME.split('<', 1)[1].rstrip('>') if '<' in GPG_KEY_NAME else 'repo@imhzj.com'}
Expire-Date: 0
%commit
"""
        gpg_run(["--generate-key"], input=batch)

    GPG_PUBLIC_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GPG_PUBLIC_KEY_PATH.open("w") as f:
        gpg_run(["--armor", "--export", GPG_KEY_NAME], stdout=f)


def sign_rpm(rpm_path):
    run(
        [
            "rpmsign",
            "--addsign",
            "--define",
            f"_gpg_name {GPG_KEY_NAME}",
            "--define",
            f"_gpg_path {GPG_HOME}",
            "--define",
            "__gpg /usr/bin/gpg",
            str(rpm_path),
        ]
    )


def sign_repo_metadata():
    repomd = REPO_DIR / "repodata" / "repomd.xml"
    if not repomd.exists():
        raise RuntimeError(f"repomd.xml not found: {repomd}")
    asc_path = repomd.with_suffix(".xml.asc")
    gpg_run(
        [
            "--armor",
            "--local-user",
            GPG_PRIMARY_KEY_ID,
            "--detach-sign",
            "--output",
            str(asc_path),
            str(repomd),
        ]
    )


def sign_repo_packages(rpm_paths):
    ensure_signing_key()
    for rpm_path in rpm_paths:
        sign_rpm(rpm_path)


def stage_archive_files(archive_path, file_rules, extracted_dir, stage_root):
    for rule in file_rules:
        src = extracted_dir / rule["src"]
        if not src.exists():
            raise RuntimeError(f"missing source path in archive: {src}")
        dest_rel = rule["dest"].lstrip("/")
        dest = stage_root / dest_rel
        if src.is_dir() or rule.get("kind") == "tree":
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest, symlinks=True)
            if rule.get("mode"):
                for root, dirs, files in os.walk(dest):
                    for dirname in dirs:
                        os.chmod(Path(root) / dirname, 0o755)
                    for filename in files:
                        os.chmod(Path(root) / filename, int(rule["mode"], 8))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest, follow_symlinks=False)
        os.chmod(dest, int(rule.get("mode", "0644"), 8))


def make_source_tarball(name, version, stage_root, out_path):
    payload_root = stage_root.parent / f"{name}-{version}"
    if payload_root.exists():
        shutil.rmtree(payload_root)
    shutil.copytree(stage_root, payload_root)
    with tarfile.open(out_path, "w:gz") as tar:
        tar.add(payload_root, arcname=payload_root.name)


def generate_spec(pkg, version):
    build = pkg["build"]
    name = pkg["name"]
    release = build.get("release", "1")
    summary = build["summary"]
    license_name = build["license"]
    description = build.get("description", summary)
    arch = build.get("arch", "x86_64")

    file_lines = []
    for rule in build["files"]:
        mode = int(rule.get("mode", "0644"), 8)
        owner = "root"
        group = "root"
        file_lines.append(
            f"%attr({mode:04o},{owner},{group}) {rule['dest']}"
        )

    preamble = ["%global debug_package %{nil}"]
    if build.get("disable_check_rpaths"):
        preamble.append("%global __brp_check_rpaths %{nil}")

    spec = f"""{chr(10).join(preamble)}

Name:           {name}
Version:        {version}
Release:        {release}%{{?dist}}
Summary:        {summary}
License:        {license_name}
BuildArch:      {arch}
Source0:        %{{name}}-%{{version}}.tar.gz

%description
{description}

%prep
%autosetup -n %{{name}}-%{{version}}

%build

%install
mkdir -p %{{buildroot}}
cp -a * %{{buildroot}}/

%files
{chr(10).join(file_lines)}

%changelog
* Mon Apr 06 2026 Auto RPM Builder <root@localhost> - {version}-{release}
- Automated build
"""
    return spec


def build_rpm_from_archive(pkg, source_info):
    build = pkg["build"]
    if build["method"] != "rpm-from-archive":
        raise RuntimeError(f"unsupported build method: {build['method']}")

    with tempfile.TemporaryDirectory(prefix=f"packager-{pkg['name']}-") as tempdir:
        temp = Path(tempdir)
        extract_root = temp / "extract"
        stage_root = temp / "stage"
        extract_root.mkdir()
        stage_root.mkdir()

        asset_name = source_info["asset_path"].name
        if asset_name.endswith(".zip"):
            with zipfile.ZipFile(source_info["asset_path"]) as zf:
                zf.extractall(extract_root)
        elif asset_name.endswith(".tar.gz") or asset_name.endswith(".tgz"):
            with tarfile.open(source_info["asset_path"], "r:gz") as tf:
                tf.extractall(extract_root)
        else:
            raise RuntimeError(f"unsupported archive type: {source_info['asset_path'].name}")

        stage_archive_files(source_info["asset_path"], build["files"], extract_root, stage_root)

        rpmbuild_root = temp / "rpmbuild"
        for subdir in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
            (rpmbuild_root / subdir).mkdir(parents=True, exist_ok=True)

        source_tarball = rpmbuild_root / "SOURCES" / f"{pkg['name']}-{source_info['version']}.tar.gz"
        spec_path = rpmbuild_root / "SPECS" / f"{pkg['name']}.spec"
        make_source_tarball(pkg["name"], source_info["version"], stage_root, source_tarball)
        spec_path.write_text(generate_spec(pkg, source_info["version"]))

        run(
            [
                "rpmbuild",
                "-bb",
                "--define",
                f"_topdir {rpmbuild_root}",
                str(spec_path),
            ]
        )

        rpm_dir = rpmbuild_root / "RPMS" / build.get("arch", "x86_64")
        rpms = sorted(rpm_dir.glob("*.rpm"))
        if not rpms:
            raise RuntimeError(f"no RPM produced in {rpm_dir}")
        persistent_rpm = WORK_DIR / "builds" / pkg["name"] / source_info["version"] / rpms[-1].name
        persistent_rpm.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rpms[-1], persistent_rpm)
        return [persistent_rpm]


def repack_rpm(pkg, source_info):
    asset_path = source_info["asset_path"]
    if asset_path.suffix != ".rpm":
        raise RuntimeError(f"expected RPM asset, got: {asset_path.name}")
    return [asset_path]


def install_local_repo_build_dependencies(rpms):
    if not rpms:
        return
    run(["dnf", "-y", "install", *[str(rpm) for rpm in rpms]])


def rpm_query(rpm_path, fmt):
    return run(["rpm", "-qp", "--qf", fmt, str(rpm_path)], capture_output=True).stdout.strip()


def rpm_name(rpm_path):
    return rpm_query(rpm_path, "%{NAME}\n")


def select_built_rpms(pkg, rpm_paths):
    build = pkg["build"]
    include = build.get("publish_include_patterns")
    exclude = build.get(
        "publish_exclude_patterns",
        [r"-debuginfo-", r"-debugsource-", r"\.src\.rpm$"],
    )
    selected = []
    for rpm_path in rpm_paths:
        name = rpm_path.name
        if include and not any(re.search(pattern, name) for pattern in include):
            continue
        if any(re.search(pattern, name) for pattern in exclude):
            continue
        selected.append(rpm_path)
    if not selected:
        raise RuntimeError(f"no RPM matched publish rules for {pkg['name']}")
    return selected


def build_rpms_from_spec(pkg, source_info):
    build = pkg["build"]
    if source_info.get("checkout_dir") is None:
        raise RuntimeError("rpmbuild-spec requires a git source checkout")

    with tempfile.TemporaryDirectory(prefix=f"packager-spec-{pkg['name']}-") as tempdir:
        temp = Path(tempdir)
        rpmbuild_root = temp / "rpmbuild"
        for subdir in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
            (rpmbuild_root / subdir).mkdir(parents=True, exist_ok=True)

        repo_root = source_info["checkout_dir"]
        spec_relpath = build["spec_path"]
        spec_src = repo_root / spec_relpath
        if not spec_src.exists():
            raise RuntimeError(f"spec file not found: {spec_src}")

        spec_override = build.get("spec_override")
        if spec_override:
            override_path = (ROOT / spec_override).resolve()
            if not override_path.exists():
                raise RuntimeError(f"spec override file not found: {override_path}")
            spec_src = override_path

        spec_dest = rpmbuild_root / "SPECS" / Path(spec_src).name
        shutil.copy2(spec_src, spec_dest)

        for extra_spec in build.get("extra_specs", []):
            extra_src = repo_root / extra_spec
            if not extra_src.exists():
                raise RuntimeError(f"extra spec file not found: {extra_src}")
            shutil.copy2(extra_src, rpmbuild_root / "SPECS" / Path(extra_spec).name)

        for extra_source in build.get("extra_sources", []):
            extra_src = (ROOT / extra_source).resolve()
            if not extra_src.exists():
                raise RuntimeError(f"extra source file not found: {extra_src}")
            dest = rpmbuild_root / "SOURCES" / Path(extra_source).name
            if extra_src.is_dir():
                clone_tree(extra_src, dest)
            else:
                shutil.copy2(extra_src, dest)

        for item in build.get("source_overrides", []):
            src = repo_root / item["src"]
            dest = rpmbuild_root / item["dest"].lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                clone_tree(src, dest)
            else:
                shutil.copy2(src, dest)

        version = rpmspec_query(spec_dest, "%{VERSION}\n", topdir=rpmbuild_root)
        release = rpmspec_query(spec_dest, "%{RELEASE}\n", topdir=rpmbuild_root)

        for dep_name in build.get("install_from_repo", []):
            dep_state = load_state(dep_name)
            dep_paths = dep_state.get("last_published_rpms") or dep_state.get("last_built_rpms", [])
            dep_rpms = [Path(path) for path in dep_paths]
            missing = [path for path in dep_rpms if not path.exists()]
            if missing:
                raise RuntimeError(f"missing published dependency RPMs for {dep_name}: {missing}")
            install_local_repo_build_dependencies(dep_rpms)

        run(["spectool", "-g", "-R", "--define", f"_topdir {rpmbuild_root}", str(spec_dest)])
        run(["dnf", "-y", "builddep", str(spec_dest)])

        run(
            [
                "rpmbuild",
                "-ba",
                "--define",
                f"_topdir {rpmbuild_root}",
                str(spec_dest),
            ]
        )

        rpm_paths = sorted((rpmbuild_root / "RPMS").glob("*/*.rpm"))
        selected = select_built_rpms(pkg, rpm_paths)
        persistent_dir = WORK_DIR / "builds" / pkg["name"] / f"{version}-{release}"
        persistent_dir.mkdir(parents=True, exist_ok=True)
        persistent_rpms = []
        for rpm_path in selected:
            persistent_path = persistent_dir / rpm_path.name
            shutil.copy2(rpm_path, persistent_path)
            persistent_rpms.append(persistent_path)

        source_info["version"] = version
        source_info["spec_release"] = release
        return persistent_rpms


def publish_rpms(rpm_paths):
    REPO_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    published = []
    for rpm_path in rpm_paths:
        dest = REPO_PACKAGES_DIR / rpm_path.name
        shutil.copy2(rpm_path, dest)
        published.append(dest)
    sign_repo_packages(published)
    run(["createrepo_c", "--update", str(REPO_DIR)])
    sign_repo_metadata()
    restorecon = shutil.which("restorecon")
    if restorecon:
        run([restorecon, "-RF", str(REPO_DIR)])
    return published


def prune_repo_rpms_by_name(package_names):
    if not package_names:
        return []
    removed = []
    for repo_rpm in sorted(REPO_PACKAGES_DIR.glob("*.rpm")):
        try:
            name = rpm_name(repo_rpm)
        except subprocess.CalledProcessError:
            continue
        if name in package_names:
            repo_rpm.unlink()
            removed.append(repo_rpm)
    return removed


def import_rpms(rpm_paths):
    ensure_dirs()
    normalized = [Path(path).resolve() for path in rpm_paths]
    missing = [path for path in normalized if not path.exists()]
    if missing:
        raise RuntimeError(f"missing RPMs for import: {', '.join(str(path) for path in missing)}")
    package_names = sorted({rpm_name(path) for path in normalized})
    prune_repo_rpms_by_name(package_names)
    return publish_rpms(normalized)


def build_package(pkg, force=False, synced=None):
    if synced is None:
        synced = set()
    ensure_dirs()
    if not pkg.get("enabled", False):
        print(f"skip {pkg['name']}: disabled")
        return None
    if pkg["name"] in synced:
        return None

    for dep_name in pkg.get("requires", []):
        dep_pkg = load_package(dep_name)
        build_package(dep_pkg, force=force, synced=synced)

    state = load_state(pkg["name"])
    source_info = fetch_latest_source(pkg)
    build_id = source_info.get("build_id", source_info["version"])

    if not force and state.get("last_build_id") == build_id and state.get("last_built_rpms"):
        print(f"skip {pkg['name']}: already built {state.get('last_build_version', source_info['version'])}")
        synced.add(pkg["name"])
        return {
            "pkg": pkg,
            "source_info": source_info,
            "built_rpms": [Path(path) for path in state.get("last_built_rpms", [])],
        }

    method = pkg["build"]["method"]
    if method == "rpm-from-archive":
        built_rpms = build_rpm_from_archive(pkg, source_info)
    elif method == "repack-rpm":
        built_rpms = repack_rpm(pkg, source_info)
    elif method == "rpmbuild-spec":
        built_rpms = build_rpms_from_spec(pkg, source_info)
    else:
        raise RuntimeError(f"unsupported build method: {method}")

    state_updates = {
        "last_asset_name": source_info["asset_name"],
        "last_asset_url": source_info["asset_url"],
        "last_build_id": build_id,
        "last_build_version": source_info["version"],
        "last_release_tag": source_info["release_tag"],
        "last_built_rpms": [str(path) for path in built_rpms],
    }
    if source_info.get("spec_release"):
        state_updates["last_spec_release"] = source_info["spec_release"]
    merge_state(pkg["name"], state_updates)
    synced.add(pkg["name"])
    print(f"built {pkg['name']} {source_info['version']}: {', '.join(str(path) for path in built_rpms)}")
    return {
        "pkg": pkg,
        "source_info": source_info,
        "built_rpms": built_rpms,
    }


def sync_package(pkg, force=False, synced=None):
    result = build_package(pkg, force=force, synced=synced)
    if result is None:
        return
    published = publish_rpms(result["built_rpms"])
    merge_state(pkg["name"], {"last_published_rpms": [str(path) for path in published]})
    print(
        f"published {pkg['name']} {result['source_info']['version']}: "
        f"{', '.join(str(path) for path in published)}"
    )


def cmd_list(_args):
    for pkg in iter_packages():
        status = "enabled" if pkg.get("enabled", False) else "disabled"
        print(f"{pkg['name']}\t{status}\t{pkg['_path']}")


def cmd_sync_one(args):
    pkg = load_package(args.name)
    sync_package(pkg, force=args.force)


def cmd_build_one(args):
    pkg = load_package(args.name)
    build_package(pkg, force=args.force)


def cmd_sync_all(args):
    for pkg in iter_packages():
        sync_package(pkg, force=args.force)


def cmd_import_rpms(args):
    rpm_paths = []
    for pattern in args.rpms:
        matched = [Path(path) for path in sorted(glob.glob(pattern))]
        if matched:
            rpm_paths.extend(matched)
        else:
            rpm_paths.append(Path(pattern))
    published = import_rpms(rpm_paths)
    print(f"imported {len(published)} RPMs: {', '.join(str(path) for path in published)}")


def cmd_sign_repo(_args):
    ensure_dirs()
    rpm_paths = sorted(REPO_PACKAGES_DIR.glob("*.rpm"))
    if not rpm_paths:
        print(f"no RPMs found in {REPO_PACKAGES_DIR}")
        return
    sign_repo_packages(rpm_paths)
    run(["createrepo_c", "--update", str(REPO_DIR)])
    sign_repo_metadata()
    print(f"signed {len(rpm_paths)} RPMs and repository metadata")


def main():
    parser = argparse.ArgumentParser(description="Auto RPM Builder MVP")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List package definitions")
    p_list.set_defaults(func=cmd_list)

    p_sync_one = sub.add_parser("sync-one", help="Build and publish one package")
    p_sync_one.add_argument("name")
    p_sync_one.add_argument("--force", action="store_true")
    p_sync_one.set_defaults(func=cmd_sync_one)

    p_build_one = sub.add_parser("build-one", help="Build one package without publishing")
    p_build_one.add_argument("name")
    p_build_one.add_argument("--force", action="store_true")
    p_build_one.set_defaults(func=cmd_build_one)

    p_sync_all = sub.add_parser("sync-all", help="Build and publish all enabled packages")
    p_sync_all.add_argument("--force", action="store_true")
    p_sync_all.set_defaults(func=cmd_sync_all)

    p_import = sub.add_parser("import-rpms", help="Import prebuilt RPMs into the repository")
    p_import.add_argument("rpms", nargs="+", help="RPM paths or glob patterns")
    p_import.set_defaults(func=cmd_import_rpms)

    p_sign_repo = sub.add_parser("sign-repo", help="Sign all published RPMs and repodata")
    p_sign_repo.set_defaults(func=cmd_sign_repo)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
