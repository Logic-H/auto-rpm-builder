#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text())


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: finalize_detect.py <mode> [args...]")

    mode = sys.argv[1]
    if mode == "manual":
        if len(sys.argv) != 3:
            raise SystemExit("usage: finalize_detect.py manual <package>")
        package = sys.argv[2]
        payload = {
            "reason": "manual",
            "changed_names": [package],
            "has_updates": True,
        }
    elif mode == "push":
        if len(sys.argv) != 4:
            raise SystemExit("usage: finalize_detect.py push <update-json> <git-json>")
        update_data = load_json(sys.argv[2])
        git_data = load_json(sys.argv[3])
        names = sorted(set(update_data.get("changed_names", [])) | set(git_data.get("changed_names", [])))
        payload = {
            "reason": "push",
            "changed_names": names,
            "has_updates": bool(names),
            "upstream_changed_names": update_data.get("changed_names", []),
            "git_changed_names": git_data.get("changed_names", []),
        }
    elif mode == "scheduled":
        if len(sys.argv) != 3:
            raise SystemExit("usage: finalize_detect.py scheduled <update-json>")
        update_data = load_json(sys.argv[2])
        payload = {
            "reason": "scheduled",
            "changed_names": update_data.get("changed_names", []),
            "has_updates": update_data.get("has_updates", False),
        }
    else:
        raise SystemExit(f"unknown mode: {mode}")

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
