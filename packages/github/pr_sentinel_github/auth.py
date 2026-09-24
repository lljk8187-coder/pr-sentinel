"""GitHub App JWT → installation access token exchange."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def create_app_jwt(app_id: str, private_key_pem: str, *, now: int | None = None) -> str:
    """Sign a short-lived JWT for GitHub App authentication (RS256)."""
    import jwt  # PyJWT

    issued_at = int(now if now is not None else time.time())
    # GitHub requires iat slightly in the past to allow clock skew
    payload = {
        "iat": issued_at - 60,
        "exp": issued_at + 9 * 60,  # max 10 minutes
        "iss": str(app_id),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def exchange_installation_token(
    *,
    app_id: str,
    private_key_pem: str,
    installation_id: int,
    http_client: httpx.Client | None = None,
) -> str:
    """POST /app/installations/{id}/access_tokens → token string."""
    token_jwt = create_app_jwt(app_id, private_key_pem)
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token_jwt}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pr-sentinel/0.10",
    }
    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
    owns = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        resp = client.post(url, headers=headers)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        access_token = data.get("token")
        if not access_token:
            raise RuntimeError("installation token response missing 'token'")
        logger.info("obtained installation access token for installation_id=%s", installation_id)
        return str(access_token)
    finally:
        if owns:
            client.close()
