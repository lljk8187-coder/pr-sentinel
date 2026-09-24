#!/usr/bin/env python3
"""Live preflight (M35): static checks before real GitHub App / PR traffic.

Stdlib only — no JWT, no GitHub API writes, no installation token exchange.

Exit codes:
  0  no FAIL (PASS and optional WARN only)
  1  one or more FAIL (config not ready for live)

Usage:
  # Prefer exporting vars or sourcing .env first; script also loads ./.env if present
  # (does not override existing env).
  python scripts/preflight_live.py
  # optional:
  #   PREFLIGHT_HEALTH_URL=http://127.0.0.1:8000/health
  #   PREFLIGHT_SKIP_HEALTH=1
  #   PREFLIGHT_DOTENV=/path/to/.env
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines; does not override existing environ."""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"WARN  cannot read dotenv {path}: {exc}")
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        os.environ[key] = val


def _truthy(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _mask_present(label: str, value: str, *, kind: str = "secret") -> str:
    if not value:
        return f"{label}=<empty>"
    if kind == "pem":
        has_begin = "BEGIN" in value and "PRIVATE KEY" in value
        return f"{label}=set (chars={len(value)}, looks_like_pem={has_begin})"
    if kind == "path":
        return f"{label}={value}"
    # token / generic — never echo full value
    return f"{label}=set (chars={len(value)}, prefix={value[:4]!r}…)"


def _check_health(url: str) -> tuple[str, str]:
    """Return (level, message) level in PASS|WARN|FAIL."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")[:200]
    except urllib.error.HTTPError as e:
        return "WARN", f"GET {url} → HTTP {e.code} (api up but unhealthy?)"
    except urllib.error.URLError as e:
        return "WARN", f"GET {url} unreachable ({e.reason}) — start api/compose before live PR"
    except Exception as e:  # noqa: BLE001 — preflight must not crash
        return "WARN", f"GET {url} failed: {type(e).__name__}: {e}"
    if 200 <= status < 300:
        return "PASS", f"GET {url} → HTTP {status} ok ({body!r})"
    return "WARN", f"GET {url} → HTTP {status} ({body!r})"


def main() -> int:
    dotenv = Path(os.environ.get("PREFLIGHT_DOTENV") or (ROOT / ".env"))
    _load_dotenv(dotenv)

    results: list[tuple[str, str]] = []

    # --- USE_FIXTURES ---
    raw_fix = os.environ.get("USE_FIXTURES", "")
    if raw_fix == "":
        results.append(
            (
                "WARN",
                "USE_FIXTURES unset (compose/settings often default true) — "
                "for live set USE_FIXTURES=false",
            )
        )
    elif _truthy("USE_FIXTURES"):
        results.append(
            (
                "FAIL",
                "USE_FIXTURES=true — fixtures mode will not hit real GitHub; "
                "set USE_FIXTURES=false for live",
            )
        )
    else:
        results.append(("PASS", f"USE_FIXTURES={raw_fix!r} (live)"))

    # --- credentials: App or PAT ---
    app_id = os.environ.get("GITHUB_APP_ID", "").strip()
    pem_inline = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").strip()
    pem_path_raw = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH", "").strip()
    pat = os.environ.get("GITHUB_TOKEN", "").strip()

    app_ok = False
    if app_id and (pem_inline or pem_path_raw):
        if pem_path_raw:
            pem_path = Path(pem_path_raw)
            # Also try host-relative to repo root
            if not pem_path.is_file() and not pem_path.is_absolute():
                alt = ROOT / pem_path_raw
                if alt.is_file():
                    pem_path = alt
            if not pem_path.is_file():
                results.append(
                    (
                        "FAIL",
                        f"GITHUB_APP_PRIVATE_KEY_PATH not a readable file: {pem_path_raw!r}",
                    )
                )
            elif not os.access(pem_path, os.R_OK):
                results.append(("FAIL", f"PEM path not readable: {pem_path}"))
            else:
                try:
                    pem_text = pem_path.read_text(encoding="utf-8")
                except OSError as exc:
                    results.append(("FAIL", f"cannot read PEM {pem_path}: {exc}"))
                else:
                    results.append(
                        (
                            "PASS",
                            f"App creds via PATH: GITHUB_APP_ID={app_id!r}; "
                            f"{_mask_present('PEM_FILE', pem_text, kind='pem')} path={pem_path}",
                        )
                    )
                    app_ok = True
        else:
            results.append(
                (
                    "PASS",
                    f"App creds via env: GITHUB_APP_ID={app_id!r}; "
                    f"{_mask_present('GITHUB_APP_PRIVATE_KEY', pem_inline, kind='pem')}",
                )
            )
            app_ok = True
    elif app_id and not pem_inline and not pem_path_raw:
        results.append(
            (
                "FAIL",
                f"GITHUB_APP_ID={app_id!r} set but missing "
                "GITHUB_APP_PRIVATE_KEY and GITHUB_APP_PRIVATE_KEY_PATH",
            )
        )
    elif (pem_inline or pem_path_raw) and not app_id:
        results.append(
            (
                "FAIL",
                "PEM configured but GITHUB_APP_ID empty",
            )
        )

    pat_ok = bool(pat)
    if pat_ok:
        results.append(("PASS", _mask_present("GITHUB_TOKEN", pat, kind="token")))

    if not app_ok and not pat_ok:
        results.append(
            (
                "FAIL",
                "no live auth: need GITHUB_APP_ID+(PRIVATE_KEY|PATH) or GITHUB_TOKEN",
            )
        )

    # --- webhook secret (soft) ---
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "").strip()
    if not secret:
        results.append(
            (
                "WARN",
                "GITHUB_WEBHOOK_SECRET empty — HMAC will fail unless WEBHOOK_SKIP_VERIFY=true",
            )
        )
    else:
        results.append(("PASS", _mask_present("GITHUB_WEBHOOK_SECRET", secret)))

    if _truthy("WEBHOOK_SKIP_VERIFY") or _truthy("ALLOW_INSECURE_WEBHOOKS"):
        results.append(
            (
                "WARN",
                "WEBHOOK_SKIP_VERIFY/ALLOW_INSECURE_WEBHOOKS enabled — do not use with public smee",
            )
        )

    # --- optional /health ---
    if _truthy("PREFLIGHT_SKIP_HEALTH"):
        results.append(("WARN", "PREFLIGHT_SKIP_HEALTH=1 — skipped /health probe"))
    else:
        health_url = os.environ.get(
            "PREFLIGHT_HEALTH_URL", "http://127.0.0.1:8000/health"
        )
        level, msg = _check_health(health_url)
        results.append((level, msg))

    fails = 0
    warns = 0
    for level, msg in results:
        print(f"{level:4}  {msg}")
        if level == "FAIL":
            fails += 1
        elif level == "WARN":
            warns += 1

    print("---")
    print(
        f"summary: FAIL={fails} WARN={warns} PASS={sum(1 for l, _ in results if l == 'PASS')}"
    )
    print(
        "exit: 0 if no FAIL (WARN ok); 1 if any FAIL. "
        "No GitHub API / JWT calls were made."
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
