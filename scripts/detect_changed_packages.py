#!/usr/bin/env python3
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT / "registry" / "packages"


def enabled_packages():
    names = []
    for path in sorted(REGISTRY_DIR.glob("*.json")):
        with path.open() as f:
            data = json.load(f)
        if data.get("enabled", False):
            names.append(data["name"])
    return sorted(names)


def package_from_path(path_str):
    path = Path(path_str)
    parts = path.parts

    if len(parts) >= 3 and parts[0] == "registry" and parts[1] == "packages" and path.suffix == ".json":
        return path.stem

    if len(parts) >= 2 and parts[0] == "packaging":
        return parts[1]

    return None


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: detect_changed_packages.py <event-json>")

    event_path = Path(sys.argv[1])
    with event_path.open() as f:
        event = json.load(f)

    changed_files = []
    for commit in event.get("commits", []):
        changed_files.extend(commit.get("added", []))
        changed_files.extend(commit.get("modified", []))
        changed_files.extend(commit.get("removed", []))
    changed_files = sorted(set(changed_files))

    all_enabled = enabled_packages()
    affected = set()
    rebuild_all = False

    for changed_file in changed_files:
        package_name = package_from_path(changed_file)
        if package_name:
            affected.add(package_name)
            continue

        if changed_file.startswith(".github/workflows/"):
            rebuild_all = True
            continue
        if changed_file.startswith("scripts/"):
            rebuild_all = True
            continue

    if rebuild_all:
        affected.update(all_enabled)

    payload = {
        "changed_files": changed_files,
        "changed_names": sorted(name for name in affected if name in all_enabled),
        "rebuild_all": rebuild_all,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
