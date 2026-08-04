"""GitHub REST API client for PrivateHACS."""

from __future__ import annotations

import re
from typing import Any

from aiohttp import ClientResponse, ClientSession

from .const import GITHUB_API_URL, GITHUB_API_VERSION
from .models import GitHubAccount, GitHubRepository


class GitHubError(Exception):
    """Base error raised for GitHub API requests."""


class GitHubAuthenticationError(GitHubError):
    """The personal access token was rejected by GitHub."""


class GitHubNotFoundError(GitHubError):
    """The requested GitHub resource was not found or is inaccessible."""


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
            "visibility": "private",
            "affiliation": "owner,collaborator,organization_member",
            "per_page": "100",
            "sort": "updated",
            "direction": "desc",
        }

        while url:
            async with self._session.get(
                url, params=params, headers=self._headers
            ) as response:
                payload = await self._async_read_json(response)
                next_link = response.links.get("next", {}).get("url")
            params = None

            if not isinstance(payload, list):
                raise GitHubError("GitHub returned an invalid repository list.")

            for item in payload:
                if isinstance(item, dict) and item.get("private") is True:
                    repositories.append(GitHubRepository.from_api(item))

            url = str(next_link) if next_link else ""

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

    async def async_download_archive(self, full_name: str, ref: str) -> bytes:
        """Download a source archive without writing credentials to disk."""
        url = f"{GITHUB_API_URL}/repos/{full_name}/zipball/{ref}"
        async with self._session.get(url, headers=self._headers) as response:
            await self._async_raise_for_status(response)
            return await response.read()

    async def _async_get_json(self, path: str) -> dict[str, Any]:
        """Request a JSON object from the GitHub API."""
        async with self._session.get(
            f"{GITHUB_API_URL}{path}", headers=self._headers
        ) as response:
            payload = await self._async_read_json(response)
        if not isinstance(payload, dict):
            raise GitHubError("GitHub returned an unexpected response.")
        return payload

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