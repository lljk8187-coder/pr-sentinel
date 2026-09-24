"""M18: Live mode (USE_FIXTURES=false) fail-fast — no silent fixtures fallback."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from common.settings import (
    LiveAuthError,
    Settings,
    resolve_app_private_key,
    validate_live_auth,
)
from pr_sentinel_github.client import GitHubClient

ROOT = Path(__file__).resolve().parents[1]


def _load_worker_main():
    path = ROOT / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main_m18", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    for pth in (ROOT, ROOT / "packages", ROOT / "packages" / "github"):
        sp = str(pth)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def worker_mod():
    return _load_worker_main()


def test_validate_live_auth_noop_when_fixtures():
    s = Settings(
        use_fixtures=True,
        github_token="",
        github_app_id="",
        github_app_private_key="",
    )
    validate_live_auth(s)  # must not raise


def test_validate_live_auth_fails_when_live_and_empty():
    s = Settings(
        use_fixtures=False,
        github_token="",
        github_app_id="",
        github_app_private_key="",
        github_app_private_key_path="",
    )
    with pytest.raises(LiveAuthError, match="USE_FIXTURES=false"):
        validate_live_auth(s)


def test_validate_live_auth_accepts_pat():
    s = Settings(use_fixtures=False, github_token="ghp_test_token")
    validate_live_auth(s)


def test_validate_live_auth_accepts_app_inline_key():
    s = Settings(
        use_fixtures=False,
        github_app_id="123",
        github_app_private_key="-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
    )
    validate_live_auth(s)


def test_validate_live_auth_accepts_app_key_path(tmp_path: Path):
    pem = tmp_path / "app.pem"
    pem.write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")
    s = Settings(
        use_fixtures=False,
        github_app_id="99",
        github_app_private_key="",
        github_app_private_key_path=str(pem),
    )
    validate_live_auth(s)
    assert "BEGIN" in resolve_app_private_key(s)


def test_validate_live_auth_bad_key_path(tmp_path: Path):
    s = Settings(
        use_fixtures=False,
        github_token="",
        github_app_id="99",
        github_app_private_key="",
        github_app_private_key_path=str(tmp_path / "missing.pem"),
    )
    with pytest.raises(LiveAuthError, match="PRIVATE_KEY_PATH"):
        validate_live_auth(s)


def test_client_should_use_fixtures_only_when_flag_set():
    """Missing auth must NOT imply fixtures (M18)."""
    c = GitHubClient(use_fixtures=False, token="", app_id="", app_private_key="")
    assert c._should_use_fixtures is False  # noqa: SLF001

    c2 = GitHubClient(use_fixtures=True)
    assert c2._should_use_fixtures is True  # noqa: SLF001


def test_build_client_fail_fast_live_empty(worker_mod):
    s = Settings(
        use_fixtures=False,
        github_token="",
        github_app_id="",
        github_app_private_key="",
    )
    with pytest.raises(LiveAuthError):
        worker_mod.build_client(s)


def test_build_client_fixtures_still_work(worker_mod, fixtures_dir: Path):
    s = Settings(
        use_fixtures=True,
        github_token="",
        github_app_id="",
        github_app_private_key="",
        fixtures_dir=str(fixtures_dir),
    )
    client = worker_mod.build_client(s)
    try:
        assert client.use_fixtures is True
        assert client._should_use_fixtures is True  # noqa: SLF001
        files = client.list_pr_files("acme", "demo", 1)
        assert isinstance(files, list)
        assert len(files) >= 1
    finally:
        client.close()


def test_build_client_live_with_token_keeps_fixtures_false(worker_mod):
    s = Settings(use_fixtures=False, github_token="ghp_live")
    client = worker_mod.build_client(s)
    try:
        assert client.use_fixtures is False
        assert client._should_use_fixtures is False  # noqa: SLF001
        assert client.token == "ghp_live"
    finally:
        client.close()


def test_on_startup_fail_fast(worker_mod, monkeypatch):
    live_empty = Settings(
        use_fixtures=False,
        github_token="",
        github_app_id="",
        github_app_private_key="",
        github_app_private_key_path="",
    )
    monkeypatch.setattr(worker_mod, "get_settings", lambda: live_empty)

    with pytest.raises(LiveAuthError):
        asyncio.run(worker_mod.on_startup({}))


def test_on_startup_ok_with_fixtures(worker_mod, monkeypatch):
    s = Settings(use_fixtures=True)
    monkeypatch.setattr(worker_mod, "get_settings", lambda: s)
    ctx: dict = {}
    asyncio.run(worker_mod.on_startup(ctx))
    assert ctx["settings"] is s
