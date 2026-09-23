"""GitHub REST client — App (prod placeholder) / PAT fallback / fixtures."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Minimal GitHub client for PR files + issue comments.

    Auth priority (M1):
      1. GitHub App ID + private key + installation_id (JWT exchange **placeholder**)
      2. GITHUB_TOKEN / PAT (local / fallback)
      3. USE_FIXTURES=true → local JSON, no network

    When App creds are set but exchange is not wired, callers should use
    fixtures or a PAT until M2 completes real App auth.
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
        max_pages: int = 5,
        per_page: int = 100,
        max_files: int = 300,
    ):
        self.token = token
        self.app_id = app_id
        self.app_private_key = app_private_key
        self.installation_id = installation_id
        self.use_fixtures = use_fixtures
        self.fixtures_dir = Path(fixtures_dir)
        self.max_pages = max_pages
        self.per_page = per_page
        self.max_files = max_files
        self._http = http_client
        self._owns_http = http_client is None
        self.calls: list[dict[str, Any]] = []
        self.truncated: bool = False

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

    @property
    def _has_app_creds(self) -> bool:
        return bool(self.app_id and self.app_private_key)

    @property
    def _should_use_fixtures(self) -> bool:
        if self.use_fixtures:
            return True
        # No real auth available → fixtures
        if not self.token and not self._has_app_creds:
            return True
        return False

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-sentinel/0.1",
        }
        # Prod path (placeholder): App installation token
        if self._has_app_creds and self.installation_id and not self.token:
            # M1: JWT → installation access token NOT implemented.
            logger.warning(
                "GitHub App placeholder auth (installation_id=%s); "
                "real JWT exchange is M2 — use GITHUB_TOKEN or USE_FIXTURES",
                self.installation_id,
            )
            headers["Authorization"] = f"Bearer app-placeholder-{self.installation_id}"
            return headers
        # Local / fallback: PAT or fine-grained token
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            return headers
        return headers

    def _fixture(self, name: str) -> Any:
        path = self.fixtures_dir / name
        if not path.exists():
            raise FileNotFoundError(f"fixture not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """GET /repos/{owner}/{repo}/pulls/{n}/files with pagination + truncation."""
        if self._should_use_fixtures:
            logger.info("list_pr_files via fixtures (%s/%s#%s)", owner, repo, pr_number)
            data = self._fixture("pr_files.json")
            self.calls.append(
                {
                    "method": "GET",
                    "path": f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
                    "fixture": True,
                }
            )
            truncated = data[: self.max_files]
            self.truncated = len(data) > self.max_files
            return truncated

        http = self._ensure_http()
        headers = self._auth_headers()
        all_files: list[dict[str, Any]] = []
        self.truncated = False

        for page in range(1, self.max_pages + 1):
            url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"
            params = {"per_page": self.per_page, "page": page}
            resp = http.get(url, headers=headers, params=params)
            self.calls.append({"method": "GET", "path": url, "page": page, "status": resp.status_code})
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list):
                break
            all_files.extend(batch)
            if len(all_files) >= self.max_files:
                self.truncated = True
                all_files = all_files[: self.max_files]
                break
            if len(batch) < self.per_page:
                break
            if page == self.max_pages and len(batch) == self.per_page:
                self.truncated = True

        return all_files

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, Any]]:
        if self._should_use_fixtures:
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
        if self._should_use_fixtures:
            logger.info("create_issue_comment mocked (fixture mode)")
            result = {
                "id": 9001,
                "body": body,
                "html_url": f"https://github.com/{owner}/{repo}/issues/{issue_number}#comment-9001",
            }
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
        if self._should_use_fixtures:
            logger.info("update_issue_comment mocked (fixture mode) id=%s", comment_id)
            result = {"id": comment_id, "body": body}
            self.calls.append({"method": "PATCH", "path": path, "body": body, "fixture": True, "result": result})
            return result

        url = f"{GITHUB_API}{path}"
        resp = self._ensure_http().patch(url, headers=self._auth_headers(), json={"body": body})
        self.calls.append({"method": "PATCH", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()
