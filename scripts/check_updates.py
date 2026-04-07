#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import packager  # noqa: E402


def dependency_order(names):
    ordered = []
    visiting = set()
    visited = set()

    def visit(name):
        if name in visited:
            return
        if name in visiting:
            raise RuntimeError(f"dependency cycle detected at {name}")
        visiting.add(name)
        pkg = packager.load_package(name)
        for dep in pkg.get("requires", []):
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in names:
        visit(name)
    return ordered


def packages_to_check(requested):
    if requested:
        names = []
        for name in requested:
            pkg = packager.load_package(name)
            if pkg.get("enabled", False):
                names.append(name)
        return dependency_order(names)

    names = [pkg["name"] for pkg in packager.iter_packages() if pkg.get("enabled", False)]
    return dependency_order(names)


def main():
    requested = sys.argv[1:]
    packages = []
    for name in packages_to_check(requested):
        pkg = packager.load_package(name)
        state = packager.load_state(name)
        source_info = packager.fetch_latest_source(pkg)
        build_id = source_info.get("build_id", source_info["version"])
        current = {
            "name": name,
            "version": source_info["version"],
            "build_id": build_id,
            "current_build_id": state.get("last_build_id", ""),
            "changed": state.get("last_build_id") != build_id,
        }
        packages.append(current)

    changed = [item for item in packages if item["changed"]]
    payload = {
        "packages": packages,
        "changed": changed,
        "changed_names": [item["name"] for item in changed],
        "has_updates": bool(changed),
    }

    print(json.dumps(payload, indent=2))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"has_updates={'true' if payload['has_updates'] else 'false'}\n")
            f.write(f"changed_names={json.dumps(payload['changed_names'])}\n")


if __name__ == "__main__":
    main()
