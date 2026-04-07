#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import subprocess
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


QUEUE_PENDING_DIR = Path(os.environ.get("PACKAGER_QUEUE_PENDING_DIR", "/opt/packager/queue/pending"))
WEBHOOK_SECRET = os.environ.get("PACKAGER_WEBHOOK_SECRET", "")
WEBHOOK_HOST = os.environ.get("PACKAGER_WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = int(os.environ.get("PACKAGER_WEBHOOK_PORT", "9876"))
QUEUE_SERVICE = os.environ.get("PACKAGER_QUEUE_SERVICE", "auto-rpm-builder-queue.service")


def verify_signature(body: bytes, provided: str) -> bool:
    if not WEBHOOK_SECRET:
        return False
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided or "")


def enqueue_payload(payload):
    QUEUE_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    queue_name = f"{int(time.time())}-{uuid.uuid4().hex}.json"
    queue_path = QUEUE_PENDING_DIR / queue_name
    queue_path.write_text(json.dumps(payload, indent=2) + "\n")
    return queue_path


class Handler(BaseHTTPRequestHandler):
    server_version = "TrilbyWebhook/0.1"

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path != "/hooks/packager":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        signature = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(body, signature):
            self.send_error(HTTPStatus.FORBIDDEN, "invalid signature")
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid json")
            return

        required = ["repository", "run_id", "artifact_name", "packages", "sha", "ref"]
        missing = [key for key in required if key not in payload]
        if missing:
            self.send_error(HTTPStatus.BAD_REQUEST, f"missing keys: {', '.join(missing)}")
            return

        queue_path = enqueue_payload(payload)
        subprocess.run(["systemctl", "start", QUEUE_SERVICE], check=False)
        response = {"queued": str(queue_path)}
        encoded = (json.dumps(response) + "\n").encode("utf-8")
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main():
    server = ThreadingHTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
