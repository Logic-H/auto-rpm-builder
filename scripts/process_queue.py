#!/usr/bin/env python3
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
QUEUE_ROOT = Path(os.environ.get("PACKAGER_QUEUE_DIR", "/opt/packager/queue"))
PENDING_DIR = QUEUE_ROOT / "pending"
PROCESSING_DIR = QUEUE_ROOT / "processing"
DONE_DIR = QUEUE_ROOT / "done"
FAILED_DIR = QUEUE_ROOT / "failed"
LOCK_PATH = QUEUE_ROOT / ".lock"
GITHUB_API_URL = os.environ.get("PACKAGER_GITHUB_API_URL", "https://api.github.com")
GITHUB_TOKEN = os.environ.get("PACKAGER_GITHUB_TOKEN", "")
PUBLIC_STATE_DIR = Path(os.environ.get("PACKAGER_PUBLIC_STATE_DIR", "/srv/repos/custom/state"))
REMOTE_SCRIPT = ROOT / "scripts" / "remote_smoke_publish.sh"
PACKAGER_SCRIPT = ROOT / "scripts" / "packager.py"
STATE_DIR = ROOT / "state"
REPO_PACKAGES_DIR = Path(os.environ.get("PACKAGER_REPO_DIR", "/srv/repos/custom/el10/x86_64")) / "Packages"


def ensure_dirs():
    for path in (PENDING_DIR, PROCESSING_DIR, DONE_DIR, FAILED_DIR, PUBLIC_STATE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def request_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "User-Agent": "auto-rpm-builder/0.1",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def download_file(url: str, dest: Path):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "User-Agent": "auto-rpm-builder/0.1",
        },
    )
    with urllib.request.urlopen(req) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)


def find_artifact_id(repository: str, run_id: str, artifact_name: str):
    data = request_json(f"{GITHUB_API_URL}/repos/{repository}/actions/runs/{run_id}/artifacts")
    for artifact in data.get("artifacts", []):
        if artifact.get("name") == artifact_name and not artifact.get("expired", False):
            return artifact["id"]
    raise RuntimeError(f"artifact {artifact_name} not found for run {run_id}")


def extract_artifact(repository: str, run_id: str, artifact_name: str, dest_dir: Path):
    artifact_id = find_artifact_id(repository, run_id, artifact_name)
    zip_path = dest_dir / "artifact.zip"
    download_file(f"{GITHUB_API_URL}/repos/{repository}/actions/artifacts/{artifact_id}/zip", zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    bundle_root = dest_dir / "bundle"
    return bundle_root if bundle_root.exists() else dest_dir


def run(cmd):
    subprocess.run(cmd, check=True, text=True)


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def find_stage_dir(bundle_root: Path, package: str):
    direct = bundle_root / package
    if direct.exists():
        return direct
    for candidate in bundle_root.rglob("smoke-test.json"):
        if candidate.parent.name == package:
            return candidate.parent
    raise RuntimeError(f"stage dir not found for package {package}")


def collect_published_paths(stage_dir: Path):
    published = []
    for rpm in sorted(stage_dir.glob("*.rpm")):
        dest = REPO_PACKAGES_DIR / rpm.name
        if dest.exists():
            published.append(str(dest))
    return published


def sync_public_state():
    PUBLIC_STATE_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(STATE_DIR.glob("*.json")):
        shutil.copy2(path, PUBLIC_STATE_DIR / path.name)


def process_request(request_path: Path):
    payload = load_json(request_path)
    packages = payload["packages"]
    with tempfile.TemporaryDirectory(prefix="packager-artifact-") as tempdir:
        bundle_root = extract_artifact(
            payload["repository"],
            str(payload["run_id"]),
            payload["artifact_name"],
            Path(tempdir),
        )
        for package in packages:
            stage_dir = find_stage_dir(bundle_root, package)
            state_data = load_json(stage_dir / "state.json")
            run([str(REMOTE_SCRIPT), package, str(stage_dir)])
            state_path = STATE_DIR / f"{package}.json"
            existing = load_json(state_path) if state_path.exists() else {}
            existing.update(state_data)
            existing["last_published_rpms"] = collect_published_paths(stage_dir)
            existing["last_published_at"] = int(time.time())
            save_json(state_path, existing)
    sync_public_state()


def process_all():
    ensure_dirs()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("queue processor already running")
            return
        for request_path in sorted(PENDING_DIR.glob("*.json")):
            processing_path = PROCESSING_DIR / request_path.name
            request_path.replace(processing_path)
            try:
                process_request(processing_path)
            except Exception:
                failed_path = FAILED_DIR / processing_path.name
                processing_path.replace(failed_path)
                raise
            else:
                done_path = DONE_DIR / processing_path.name
                processing_path.replace(done_path)


def main():
    if not GITHUB_TOKEN:
        raise SystemExit("PACKAGER_GITHUB_TOKEN is not configured")
    process_all()


if __name__ == "__main__":
    main()
