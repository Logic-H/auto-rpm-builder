#!/usr/bin/env python3
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_package_names(registry_dir: Path):
    names = []
    for path in sorted(registry_dir.glob("*.json")):
        with path.open() as f:
            data = json.load(f)
        if data.get("name"):
            names.append(data["name"])
    return names


def download_state(base_url: str, package: str, output_dir: Path):
    url = f"{base_url.rstrip('/')}/{package}.json"
    dest = output_dir / f"{package}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "auto-rpm-builder/0.1"})
    try:
        with urllib.request.urlopen(req) as resp:
            dest.write_bytes(resp.read())
            print(f"fetched {package} state from {url}")
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"state missing for {package}: {url}")
            return False
        raise


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: fetch_remote_state.py <base-url> <registry-dir> <output-dir>")

    base_url = sys.argv[1]
    registry_dir = Path(sys.argv[2]).resolve()
    output_dir = Path(sys.argv[3]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for package in load_package_names(registry_dir):
        download_state(base_url, package, output_dir)


if __name__ == "__main__":
    main()
