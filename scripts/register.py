#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT / "registry" / "packages"


def parse_repo(url):
    parsed = urlparse(url)
    if parsed.netloc not in {"github.com", "www.github.com"}:
        raise SystemExit("only github.com URLs are supported in the MVP")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise SystemExit("expected a GitHub repository URL")
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def default_asset_patterns(name, mode):
    escaped = re.escape(name)
    if mode == "rpm":
        return [rf"{escaped}.*x86_64.*\.rpm$", rf".*x86_64.*\.rpm$"]
    if mode == "zip":
        return [rf"{escaped}.*x86_64.*\.zip$", rf".*x86_64.*\.zip$"]
    return [rf"{escaped}.*", r".*"]


def write_package(name, data):
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    path = REGISTRY_DIR / f"{name}.json"
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(path)


def cmd_github_release(args):
    repo = parse_repo(args.url)
    name = args.name or repo.split("/")[-1]
    mode = args.method

    if mode == "repack-rpm":
        asset_patterns = args.asset_pattern or default_asset_patterns(name, "rpm")
    else:
        asset_patterns = args.asset_pattern or default_asset_patterns(name, "zip")

    data = {
        "name": name,
        "enabled": args.enable,
        "source": {
            "type": "github-release",
            "repo": repo,
            "version_mode": "strip-v",
            "asset_patterns": asset_patterns,
        },
        "build": {
            "method": mode,
            "release": "1",
            "license": args.license,
            "summary": args.summary or name,
            "description": args.description or args.summary or name,
            "arch": "x86_64",
        },
    }

    if mode == "rpm-from-archive":
        data["build"]["files"] = []

    write_package(name, data)


def main():
    parser = argparse.ArgumentParser(description="Register package definitions for auto-rpm-builder")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("github-release", help="Register a package from a GitHub repository URL")
    p.add_argument("url", help="GitHub repository URL")
    p.add_argument("--name")
    p.add_argument("--method", choices=["repack-rpm", "rpm-from-archive"], default="repack-rpm")
    p.add_argument("--asset-pattern", action="append")
    p.add_argument("--summary")
    p.add_argument("--description")
    p.add_argument("--license", default="Unknown")
    p.add_argument("--enable", action="store_true")
    p.set_defaults(func=cmd_github_release)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
