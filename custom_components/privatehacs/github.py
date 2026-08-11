"""GitHub REST API client for PrivateHACS."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import re
from typing import Any

from aiohttp import ClientResponse, ClientSession

from .const import GITHUB_API_URL, GITHUB_API_VERSION
from .models import GitHubAccount, GitHubRelease, GitHubRepository

_LOGGER = logging.getLogger(__name__)


class GitHubError(Exception):
    """Base error raised for GitHub API requests."""


class GitHubAuthenticationError(GitHubError):
    """The personal access token was rejected by GitHub."""


class GitHubNotFoundError(GitHubError):
    """The requested GitHub resource was not found or is inaccessible."""


@dataclass(frozen=True, slots=True)
class RepositoryQueryDiagnostics:
    """Non-sensitive results from the latest private repository lookup."""

    queried_at: str
    pages: int
    visible_repositories: int
    private_repositories: int
    oauth_scopes: str | None
    rate_limit_remaining: str | None
    error: str | None = None

    def as_dict(self) -> dict[str, bool | int | str | None]:
        """Return data suitable for logs and Home Assistant diagnostics."""
        return {
            "completed": self.error is None,
            "queried_at": self.queried_at,
            "pages": self.pages,
            "visible_repositories": self.visible_repositories,
            "private_repositories": self.private_repositories,
            "oauth_scopes": self.oauth_scopes,
            "rate_limit_remaining": self.rate_limit_remaining,
            "error": self.error,
        }


class GitHubClient:
    """Minimal GitHub REST client using Home Assistant's shared session."""

    def __init__(self, session: ClientSession, username: str, token: str) -> None:
        """Initialize the client without exposing token material."""
        self._session = session
        self.username = username
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        self._last_repository_query: RepositoryQueryDiagnostics | None = None

    @property
    def repository_query_diagnostics(self) -> dict[str, bool | int | str | None]:
        """Return only non-sensitive state from the latest repository lookup."""
        if self._last_repository_query is None:
            return {"completed": False, "error": "No repository query has run yet."}
        return self._last_repository_query.as_dict()

    async def async_validate(self) -> GitHubAccount:
        """Validate the configured account and token."""
        payload = await self._async_get_json("/user")
        account_id = payload.get("id")
        login = payload.get("login")
        if not isinstance(account_id, int) or not isinstance(login, str) or not login:
            raise GitHubError("GitHub returned an invalid user response.")
        return GitHubAccount(account_id=account_id, login=login)

    async def async_list_private_repositories(self) -> list[GitHubRepository]:
        """Return every private repository visible to the configured account."""
        repositories: list[GitHubRepository] = []
        url = f"{GITHUB_API_URL}/user/repos"
        params: dict[str, str] | None = {
            "affiliation": "owner,collaborator,organization_member",
            "per_page": "100",
            "sort": "updated",
            "direction": "desc",
        }

        pages = 0
        visible_repositories = 0
        oauth_scopes: str | None = None
        rate_limit_remaining: str | None = None
        try:
            while url:
                async with self._session.get(
                    url, params=params, headers=self._headers
                ) as response:
                    payload = await self._async_read_json(response)
                    next_link = response.links.get("next", {}).get("url")
                    oauth_scopes = response.headers.get("X-OAuth-Scopes")
                    rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
                params = None

                if not isinstance(payload, list):
                    raise GitHubError("GitHub returned an invalid repository list.")

                pages += 1
                visible_repositories += len(payload)
                for item in payload:
                    if isinstance(item, dict) and item.get("private") is True:
                        repositories.append(GitHubRepository.from_api(item))

                url = str(next_link) if next_link else ""
        except GitHubError as err:
            self._last_repository_query = RepositoryQueryDiagnostics(
                queried_at=datetime.now(UTC).isoformat(),
                pages=pages,
                visible_repositories=visible_repositories,
                private_repositories=len(repositories),
                oauth_scopes=oauth_scopes,
                rate_limit_remaining=rate_limit_remaining,
                error=str(err),
            )
            _LOGGER.warning(
                "GitHub repository lookup failed after %s page(s): %s", pages, err
            )
            raise

        self._last_repository_query = RepositoryQueryDiagnostics(
            queried_at=datetime.now(UTC).isoformat(),
            pages=pages,
            visible_repositories=visible_repositories,
            private_repositories=len(repositories),
            oauth_scopes=oauth_scopes,
            rate_limit_remaining=rate_limit_remaining,
        )
        _LOGGER.debug(
            "GitHub repository lookup completed: %s visible, %s private, %s page(s), "
            "rate limit remaining %s, OAuth scopes %s.",
            visible_repositories,
            len(repositories),
            pages,
            rate_limit_remaining,
            oauth_scopes,
        )
        if not repositories:
            _LOGGER.warning(
                "GitHub returned no private repositories. The configured PAT can see "
                "%s repository/repositories across %s page(s). Verify the PAT has "
                "access to the intended private repositories and organization SSO is authorized.",
                visible_repositories,
                pages,
            )

        return repositories

    async def async_get_repository(self, full_name: str) -> GitHubRepository:
        """Fetch one accessible private repository."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
            raise GitHubNotFoundError("Invalid GitHub repository name.")
        payload = await self._async_get_json(f"/repos/{full_name}")
        if payload.get("private") is not True:
            raise GitHubNotFoundError("Only private repositories can be installed.")
        return GitHubRepository.from_api(payload)

    async def async_get_commit_sha(self, full_name: str, branch: str) -> str:
        """Return the current SHA of a repository branch."""
        payload = await self._async_get_json(f"/repos/{full_name}/commits/{branch}")
        sha = payload.get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitHubError("GitHub returned an invalid commit response.")
        return sha

    async def async_get_latest_release(
        self, full_name: str
    ) -> GitHubRelease | None:
        """Return the latest published release, if the repository has one."""
        try:
            payload = await self._async_get_json(f"/repos/{full_name}/releases/latest")
        except GitHubNotFoundError:
            return None
        try:
            return GitHubRelease.from_api(payload)
        except ValueError as err:
            raise GitHubError(str(err)) from err

    async def async_get_integration_versions(
        self, full_name: str, ref: str
    ) -> dict[str, str | None]:
        """Return manifest versions under custom_components at a GitHub ref."""
        try:
            contents = await self._async_get_value(
                f"/repos/{full_name}/contents/custom_components", {"ref": ref}
            )
        except GitHubNotFoundError:
            return {}

        if not isinstance(contents, list):
            raise GitHubError("GitHub returned invalid custom component contents.")

        versions: dict[str, str | None] = {}
        for entry in contents:
            if (
                not isinstance(entry, dict)
                or entry.get("type") != "dir"
                or not isinstance(domain := entry.get("name"), str)
                or not re.fullmatch(r"[a-z0-9_]+", domain)
            ):
                continue

            try:
                manifest = await self._async_get_json(
                    f"/repos/{full_name}/contents/custom_components/{domain}/manifest.json",
                    {"ref": ref},
                )
                manifest = self._decode_manifest(manifest)
            except GitHubNotFoundError:
                continue

            if manifest.get("domain") != domain:
                continue
            version = manifest.get("version")
            versions[domain] = version if isinstance(version, str) else None

        return versions

    async def async_download_archive(self, full_name: str, ref: str) -> bytes:
        """Download a source archive without writing credentials to disk."""
        url = f"{GITHUB_API_URL}/repos/{full_name}/zipball/{ref}"
        async with self._session.get(url, headers=self._headers) as response:
            await self._async_raise_for_status(response)
            return await response.read()

    async def _async_get_json(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Request a JSON object from the GitHub API."""
        payload = await self._async_get_value(path, params)
        if not isinstance(payload, dict):
            raise GitHubError("GitHub returned an unexpected response.")
        return payload

    async def _async_get_value(
        self, path: str, params: dict[str, str] | None = None
    ) -> Any:
        """Request a JSON value from the GitHub API."""
        async with self._session.get(
            f"{GITHUB_API_URL}{path}", params=params, headers=self._headers
        ) as response:
            return await self._async_read_json(response)

    @staticmethod
    def _decode_manifest(payload: dict[str, Any]) -> dict[str, Any]:
        """Decode a base64 manifest response from GitHub's contents endpoint."""
        if payload.get("encoding") != "base64" or not isinstance(
            content := payload.get("content"), str
        ):
            raise GitHubError("GitHub returned an invalid manifest response.")
        try:
            manifest = json.loads(base64.b64decode(content).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as err:
            raise GitHubError("GitHub returned an invalid manifest file.") from err
        if not isinstance(manifest, dict):
            raise GitHubError("GitHub returned an invalid manifest file.")
        return manifest

    async def _async_read_json(self, response: ClientResponse) -> Any:
        """Read a JSON response after converting HTTP errors."""
        await self._async_raise_for_status(response)
        try:
            return await response.json(content_type=None)
        except ValueError as err:
            raise GitHubError("GitHub returned invalid JSON.") from err

    async def _async_raise_for_status(self, response: ClientResponse) -> None:
        """Map relevant GitHub HTTP errors to stable integration errors."""
        if response.status in (401, 403):
            raise GitHubAuthenticationError("GitHub authentication failed.")
        if response.status == 404:
            raise GitHubNotFoundError("GitHub repository was not found.")
        if response.status >= 400:
            raise GitHubError(f"GitHub returned HTTP {response.status}.")