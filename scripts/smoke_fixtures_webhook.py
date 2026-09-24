#!/usr/bin/env python3
"""Local fixtures smoke: POST a signed pull_request webhook (no real GitHub App).

Default acceptance path (M19):
  USE_FIXTURES=true + HMAC webhook → 202 → /console shows job from Postgres.

Zero new deps — stdlib only (hmac / hashlib / json / urllib / uuid).

Usage:
  export GITHUB_WEBHOOK_SECRET=dev-secret   # must match API (.env / compose)
  python scripts/smoke_fixtures_webhook.py
  # optional:
  #   SMOKE_URL=http://127.0.0.1:8000/webhooks/github
  #   SMOKE_DELIVERY_ID=<unique>   # reuse same id → duplicate 200
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import uuid
import urllib.error
import urllib.request


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def main() -> int:
    url = os.environ.get("SMOKE_URL", "http://127.0.0.1:8000/webhooks/github")
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "dev-secret")
    delivery = os.environ.get("SMOKE_DELIVERY_ID") or f"smoke-{uuid.uuid4()}"

    payload = {
        "action": "opened",
        "number": 7,
        "pull_request": {
            "number": 7,
            "html_url": "https://github.com/acme/demo/pull/7",
            "head": {"sha": "deadbeefcafebabe000011112222333344445555"},
        },
        "repository": {
            "full_name": "acme/demo",
            "name": "demo",
            "owner": {"login": "acme"},
        },
        "installation": {"id": 12345},
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": _sign(body, secret),
        "User-Agent": "pr-sentinel-smoke/0.1",
    }

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {status}\n{raw}", file=sys.stderr)
        print(
            "Hint: 401 → GITHUB_WEBHOOK_SECRET mismatch; "
            "connection error → is api up on :8000?",
            file=sys.stderr,
        )
        return 1
    except urllib.error.URLError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        print("Is the API listening? e.g. docker compose … up  or uvicorn on :8000", file=sys.stderr)
        return 1

    print(f"HTTP {status}")
    print(raw)
    print(f"delivery_id={delivery}")
    if status == 202:
        print("OK — check http://127.0.0.1:8000/console (job from Postgres)")
        return 0
    if status == 200:
        print("Duplicate delivery (already recorded) — use a new SMOKE_DELIVERY_ID")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
