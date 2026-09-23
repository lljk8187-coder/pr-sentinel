"""GitHub REST client with fixture / token / app-placeholder auth."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

COMMENT_MARKER_PREFIX = "<!-- pr-sentinel:"
GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Minimal GitHub client for PR files + issue comments.

    Auth priority:
      1. GITHUB_TOKEN (Bearer)
      2. App ID + private key + installation_id (placeholder; falls back to fixtures)
      3. USE_FIXTURES=true → local JSON, no network
    """

    def __init__(
        self,
        *,
        token: str = "",
        app_id: str = "",
        app_private_key: str = "",
        installation_id: int | None = None,
        use_fixtures: bool = False,
        fixtures_dir: str | Path = "tests/fixtures",
        http_client: httpx.Client | None = None,
    ):
        self.token = token
        self.app_id = app_id
        self.app_private_key = app_private_key
        self.installation_id = installation_id
        self.use_fixtures = use_fixtures
        self.fixtures_dir = Path(fixtures_dir)
        self._http = http_client
        self._owns_http = http_client is None
        # Captured HTTP calls in fixture / mock mode for tests
        self.calls: list[dict[str, Any]] = []

    def _ensure_http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=30.0)
            self._owns_http = True
        return self._http

    def close(self) -> None:
        if self._owns_http and self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-sentinel/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            return headers
        if self.app_id and self.app_private_key and self.installation_id:
            # M1 placeholder: real JWT + installation token exchange not wired.
            # Callers should set USE_FIXTURES=true until App auth is implemented.
            logger.warning(
                "GitHub App credentials present but M1 uses placeholder; "
                "prefer GITHUB_TOKEN or USE_FIXTURES=true"
            )
            headers["Authorization"] = f"Bearer app-placeholder-{self.installation_id}"
            return headers
        return headers

    def _fixture(self, name: str) -> Any:
        path = self.fixtures_dir / name
        if not path.exists():
            raise FileNotFoundError(f"fixture not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        if self.use_fixtures or (not self.token and not (self.app_id and self.app_private_key)):
            logger.info("list_pr_files via fixtures (%s/%s#%s)", owner, repo, pr_number)
            data = self._fixture("pr_files.json")
            self.calls.append({"method": "GET", "path": f"/repos/{owner}/{repo}/pulls/{pr_number}/files", "fixture": True})
            return data

        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        resp = self._ensure_http().get(url, headers=self._auth_headers(), params={"per_page": 100})
        self.calls.append({"method": "GET", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, Any]]:
        if self.use_fixtures or (not self.token and not (self.app_id and self.app_private_key)):
            data = self._fixture("issue_comments.json")
            self.calls.append(
                {
                    "method": "GET",
                    "path": f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                    "fixture": True,
                }
            )
            return data

        url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        resp = self._ensure_http().get(url, headers=self._auth_headers(), params={"per_page": 100})
        self.calls.append({"method": "GET", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

    def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        path = f"/repos/{owner}/{repo}/issues/{issue_number}/comments"
        if self.use_fixtures or (not self.token and not (self.app_id and self.app_private_key)):
            logger.info("create_issue_comment mocked (fixture mode)")
            result = {"id": 9001, "body": body, "html_url": f"https://github.com/{owner}/{repo}/issues/{issue_number}#comment-9001"}
            self.calls.append({"method": "POST", "path": path, "body": body, "fixture": True, "result": result})
            return result

        url = f"{GITHUB_API}{path}"
        resp = self._ensure_http().post(url, headers=self._auth_headers(), json={"body": body})
        self.calls.append({"method": "POST", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

    def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        path = f"/repos/{owner}/{repo}/issues/comments/{comment_id}"
        if self.use_fixtures or (not self.token and not (self.app_id and self.app_private_key)):
            logger.info("update_issue_comment mocked (fixture mode) id=%s", comment_id)
            result = {"id": comment_id, "body": body}
            self.calls.append({"method": "PATCH", "path": path, "body": body, "fixture": True, "result": result})
            return result

        url = f"{GITHUB_API}{path}"
        resp = self._ensure_http().patch(url, headers=self._auth_headers(), json={"body": body})
        self.calls.append({"method": "PATCH", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()


def marker_for_sha(head_sha: str) -> str:
    return f"{COMMENT_MARKER_PREFIX}{head_sha} -->"
