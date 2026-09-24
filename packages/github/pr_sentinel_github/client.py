"""GitHub REST client — App JWT / PAT / fixtures."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .auth import exchange_installation_token

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Minimal GitHub client for PR files + issue comments + config contents.

    Auth priority:
      1. GitHub App ID + private key + installation_id → JWT → installation token
      2. GITHUB_TOKEN / PAT (local / fallback)
      3. use_fixtures=True → local JSON, no network

    Missing credentials no longer imply fixtures: live mode must fail-fast via
    ``validate_live_auth`` / ``build_client`` when USE_FIXTURES=false.
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
        self._installation_token: str | None = None
        self._installation_token_for: int | None = None
        # Fixture-mode store for inline review comments (upsert tests).
        self._pull_review_comments: list[dict[str, Any]] = []

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
        # M18: never treat missing auth as fixtures — callers must set use_fixtures
        # explicitly (or go through build_client / validate_live_auth in live mode).
        return bool(self.use_fixtures)

    def _resolve_bearer(self) -> str | None:
        """Prefer explicit PAT; else exchange App installation token."""
        if self.token:
            return self.token
        if self._has_app_creds and self.installation_id:
            if (
                self._installation_token
                and self._installation_token_for == self.installation_id
            ):
                return self._installation_token
            token = exchange_installation_token(
                app_id=self.app_id,
                private_key_pem=self.app_private_key,
                installation_id=int(self.installation_id),
                http_client=self._ensure_http(),
            )
            self._installation_token = token
            self._installation_token_for = int(self.installation_id)
            return token
        return None

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-sentinel/1.5",
        }
        bearer = self._resolve_bearer()
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return headers

    def _fixture(self, name: str) -> Any:
        path = self.fixtures_dir / name
        if not path.exists():
            raise FileNotFoundError(f"fixture not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        """GET /repos/{owner}/{repo} — used for default_branch."""
        if self._should_use_fixtures:
            path = self.fixtures_dir / "repo.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {"default_branch": "main", "full_name": f"{owner}/{repo}"}
            self.calls.append(
                {
                    "method": "GET",
                    "path": f"/repos/{owner}/{repo}",
                    "fixture": True,
                }
            )
            return data

        url = f"{GITHUB_API}/repos/{owner}/{repo}"
        resp = self._ensure_http().get(url, headers=self._auth_headers())
        self.calls.append({"method": "GET", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

    def get_default_branch(self, owner: str, repo: str) -> str:
        info = self.get_repo(owner, repo)
        return str(info.get("default_branch") or "main")

    def get_file_contents(
        self, owner: str, repo: str, path: str, *, ref: str
    ) -> str | None:
        """GET /repos/{owner}/{repo}/contents/{path}?ref=…

        Returns decoded UTF-8 text, or None if 404 / missing.
        """
        if self._should_use_fixtures:
            # Prefer local fixture file named after basename
            local = self.fixtures_dir / Path(path).name
            alt = self.fixtures_dir / path.lstrip("/")
            # also pr-sentinel.yml without leading dot
            candidates = [
                self.fixtures_dir / "pr-sentinel.yml",
                self.fixtures_dir / ".pr-sentinel.yml",
                local,
                alt,
            ]
            for c in candidates:
                if c.exists() and c.is_file():
                    self.calls.append(
                        {
                            "method": "GET",
                            "path": f"/repos/{owner}/{repo}/contents/{path}",
                            "ref": ref,
                            "fixture": True,
                        }
                    )
                    return c.read_text(encoding="utf-8")
            self.calls.append(
                {
                    "method": "GET",
                    "path": f"/repos/{owner}/{repo}/contents/{path}",
                    "ref": ref,
                    "fixture": True,
                    "status": 404,
                }
            )
            return None

        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        resp = self._ensure_http().get(
            url, headers=self._auth_headers(), params={"ref": ref}
        )
        self.calls.append(
            {"method": "GET", "path": url, "ref": ref, "status": resp.status_code}
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return None  # directory
        content = data.get("content")
        encoding = data.get("encoding")
        if content and encoding == "base64":
            raw = base64.b64decode(content.replace("\n", ""))
            return raw.decode("utf-8")
        if isinstance(content, str):
            return content
        # raw download_url fallback
        download = data.get("download_url")
        if download:
            r2 = self._ensure_http().get(download, headers=self._auth_headers())
            r2.raise_for_status()
            return r2.text
        return None

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

    def delete_issue_comment(self, owner: str, repo: str, comment_id: int) -> None:
        path = f"/repos/{owner}/{repo}/issues/comments/{comment_id}"
        if self._should_use_fixtures:
            logger.info("delete_issue_comment mocked (fixture mode) id=%s", comment_id)
            self.calls.append({"method": "DELETE", "path": path, "fixture": True})
            return

        url = f"{GITHUB_API}{path}"
        resp = self._ensure_http().delete(url, headers=self._auth_headers())
        self.calls.append({"method": "DELETE", "path": url, "status": resp.status_code})
        resp.raise_for_status()

    def create_check_run(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        head_sha: str,
        status: str = "queued",
        conclusion: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /repos/{owner}/{repo}/check-runs"""
        path = f"/repos/{owner}/{repo}/check-runs"
        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }
        if conclusion is not None:
            payload["conclusion"] = conclusion
        if output is not None:
            payload["output"] = output

        if self._should_use_fixtures:
            result = {
                "id": 8001,
                "name": name,
                "head_sha": head_sha,
                "status": status,
                "conclusion": conclusion,
                "output": output,
                "html_url": f"https://github.com/{owner}/{repo}/runs/8001",
            }
            self.calls.append(
                {
                    "method": "POST",
                    "path": path,
                    "payload": payload,
                    "fixture": True,
                    "result": result,
                }
            )
            return result

        url = f"{GITHUB_API}{path}"
        resp = self._ensure_http().post(url, headers=self._auth_headers(), json=payload)
        self.calls.append({"method": "POST", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

    def update_check_run(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        *,
        status: str | None = None,
        conclusion: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """PATCH /repos/{owner}/{repo}/check-runs/{check_run_id}"""
        path = f"/repos/{owner}/{repo}/check-runs/{check_run_id}"
        payload: dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if conclusion is not None:
            payload["conclusion"] = conclusion
        if output is not None:
            payload["output"] = output

        if self._should_use_fixtures:
            result = {
                "id": check_run_id,
                "status": status,
                "conclusion": conclusion,
                "output": output,
            }
            self.calls.append(
                {
                    "method": "PATCH",
                    "path": path,
                    "payload": payload,
                    "fixture": True,
                    "result": result,
                }
            )
            return result

        url = f"{GITHUB_API}{path}"
        resp = self._ensure_http().patch(url, headers=self._auth_headers(), json=payload)
        self.calls.append({"method": "PATCH", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

    def create_pull_review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        side: str = "RIGHT",
    ) -> dict[str, Any]:
        """POST /repos/{owner}/{repo}/pulls/{pr_number}/comments (inline review)."""
        api_path = f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        payload: dict[str, Any] = {
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
            "side": side,
        }

        if self._should_use_fixtures:
            n = len(self._pull_review_comments)
            cid = 7001 + n
            result = {
                "id": cid,
                "body": body,
                "path": path,
                "line": line,
                "commit_id": commit_id,
                "side": side,
                "pull_request_url": f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                "html_url": f"https://github.com/{owner}/{repo}/pull/{pr_number}#discussion_r{cid}",
            }
            self._pull_review_comments.append(dict(result))
            self.calls.append(
                {
                    "method": "POST",
                    "path": api_path,
                    "payload": payload,
                    "body": body,
                    "fixture": True,
                    "result": result,
                }
            )
            return result

        url = f"{GITHUB_API}{api_path}"
        resp = self._ensure_http().post(url, headers=self._auth_headers(), json=payload)
        self.calls.append({"method": "POST", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

    def list_pull_review_comments(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        """GET /repos/{owner}/{repo}/pulls/{pr_number}/comments"""
        api_path = f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        if self._should_use_fixtures:
            # Prefer in-memory POSTed/PATCHed comments so upsert tests work offline.
            data = [dict(c) for c in self._pull_review_comments]
            fixture_file = self.fixtures_dir / "pull_review_comments.json"
            if not data and fixture_file.exists():
                data = json.loads(fixture_file.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            self.calls.append(
                {
                    "method": "GET",
                    "path": api_path,
                    "fixture": True,
                    "count": len(data),
                }
            )
            return data

        http = self._ensure_http()
        headers = self._auth_headers()
        all_comments: list[dict[str, Any]] = []
        for page in range(1, self.max_pages + 1):
            url = f"{GITHUB_API}{api_path}"
            params = {"per_page": self.per_page, "page": page}
            resp = http.get(url, headers=headers, params=params)
            self.calls.append(
                {"method": "GET", "path": url, "page": page, "status": resp.status_code}
            )
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list):
                break
            all_comments.extend(batch)
            if len(batch) < self.per_page:
                break
        return all_comments

    def update_pull_review_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        *,
        body: str,
    ) -> dict[str, Any]:
        """PATCH /repos/{owner}/{repo}/pulls/comments/{comment_id} — body only."""
        api_path = f"/repos/{owner}/{repo}/pulls/comments/{comment_id}"
        payload = {"body": body}

        if self._should_use_fixtures:
            result: dict[str, Any] | None = None
            for stored in self._pull_review_comments:
                if int(stored.get("id", -1)) == int(comment_id):
                    stored["body"] = body
                    result = dict(stored)
                    break
            if result is None:
                result = {"id": comment_id, "body": body}
                self._pull_review_comments.append(dict(result))
            self.calls.append(
                {
                    "method": "PATCH",
                    "path": api_path,
                    "payload": payload,
                    "body": body,
                    "fixture": True,
                    "result": result,
                }
            )
            return result

        url = f"{GITHUB_API}{api_path}"
        resp = self._ensure_http().patch(
            url, headers=self._auth_headers(), json=payload
        )
        self.calls.append({"method": "PATCH", "path": url, "status": resp.status_code})
        resp.raise_for_status()
        return resp.json()

