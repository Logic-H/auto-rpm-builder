#!/usr/bin/env python3
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT / "registry" / "packages"


def fail(path, message):
    raise SystemExit(f"{path}: {message}")


def require(obj, key, expected_type, path):
    if key not in obj:
        fail(path, f"missing key: {key}")
    value = obj[key]
    if not isinstance(value, expected_type):
        fail(path, f"{key} must be {expected_type.__name__}")
    return value


def require_nonempty_string(value, path, label):
    if not isinstance(value, str) or not value.strip():
        fail(path, f"{label} must be a non-empty string")


def require_string_list(value, path, label, allow_empty=True):
    if not isinstance(value, list):
        fail(path, f"{label} must be a list")
    if not allow_empty and not value:
        fail(path, f"{label} must not be empty")
    for item in value:
        require_nonempty_string(item, path, f"{label} item")


def validate_test_section(data, path):
    test = require(data, "test", dict, path)
    install = require(test, "install", list, path)
    files = require(test, "files", list, path)
    commands = require(test, "commands", list, path)

    require_string_list(install, path, "test.install", allow_empty=False)
    require_string_list(files, path, "test.files")
    require_string_list(commands, path, "test.commands")

    for item in files:
        if not item.startswith("/"):
            fail(path, f"test.files item must be absolute: {item}")


def validate_package(path):
    with path.open() as f:
        data = json.load(f)

    require_nonempty_string(require(data, "name", str, path), path, "name")
    require(data, "enabled", bool, path)

    source = require(data, "source", dict, path)
    require_nonempty_string(require(source, "type", str, path), path, "source.type")

    build = require(data, "build", dict, path)
    require_nonempty_string(require(build, "method", str, path), path, "build.method")

    validate_test_section(data, path)


def main():
    package_paths = sorted(REGISTRY_DIR.glob("*.json"))
    if not package_paths:
        raise SystemExit(f"no package definitions found in {REGISTRY_DIR}")

    for path in package_paths:
        validate_package(path)

    print(f"validated {len(package_paths)} package definitions")


if __name__ == "__main__":
    main()
