#!/usr/bin/env python3
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT / "registry" / "packages"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: export_smoke_test.py <package> <output-path>")

    package = sys.argv[1]
    out_path = Path(sys.argv[2])
    pkg_path = REGISTRY_DIR / f"{package}.json"
    if not pkg_path.exists():
        raise SystemExit(f"package definition not found: {pkg_path}")

    with pkg_path.open() as f:
        pkg = json.load(f)

    test = pkg.get("test")
    if not test:
        raise SystemExit(f"package {package} has no test configuration")

    install = test.get("install") or [package]
    commands = test.get("commands") or []
    files = test.get("files") or []

    payload = {
        "package": package,
        "install": install,
        "files": files,
        "commands": commands,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
