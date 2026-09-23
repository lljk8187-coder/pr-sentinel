"""GitHub App JWT → installation token (mocked httpx)."""

from __future__ import annotations

from unittest.mock import MagicMock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pr_sentinel_github.auth import create_app_jwt, exchange_installation_token
from pr_sentinel_github.client import GitHubClient


def _rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode()


def test_create_app_jwt_roundtrip():
    import jwt

    pem = _rsa_pem()
    token = create_app_jwt("12345", pem, now=1_700_000_000)
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["iss"] == "12345"
    assert decoded["exp"] > decoded["iat"]


def test_exchange_installation_token_mocked():
    pem = _rsa_pem()

    class FakeResp:
        status_code = 201

        def raise_for_status(self):
            pass

        def json(self):
            return {"token": "ghs_test_installation_token"}

    http = MagicMock()
    http.post.return_value = FakeResp()

    tok = exchange_installation_token(
        app_id="99",
        private_key_pem=pem,
        installation_id=42,
        http_client=http,
    )
    assert tok == "ghs_test_installation_token"
    assert http.post.called
    args, kwargs = http.post.call_args
    assert "/app/installations/42/access_tokens" in args[0]
    assert "Authorization" in kwargs["headers"]


def test_client_uses_installation_token(monkeypatch):
    pem = _rsa_pem()

    def fake_exchange(**kwargs):
        return "ghs_from_app"

    monkeypatch.setattr(
        "pr_sentinel_github.client.exchange_installation_token", fake_exchange
    )

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return []

    class FakeHttp:
        def __init__(self):
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_headers = headers
            return FakeResp()

        def close(self):
            pass

    http = FakeHttp()
    client = GitHubClient(
        app_id="1",
        app_private_key=pem,
        installation_id=7,
        use_fixtures=False,
        http_client=http,
    )
    client.list_issue_comments("acme", "demo", 1)
    assert http.last_headers["Authorization"] == "Bearer ghs_from_app"
