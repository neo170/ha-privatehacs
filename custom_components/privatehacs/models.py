"""Data models used by PrivateHACS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GitHubAccount:
    """A GitHub account authenticated by a personal access token."""

    account_id: int
    login: str


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    """A private GitHub repository that can contain integrations."""

    full_name: str
    description: str | None
    default_branch: str
    html_url: str
    updated_at: str | None
    archived: bool

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> GitHubRepository:
        """Build a repository model from the GitHub REST response."""
        full_name = payload.get("full_name")
        default_branch = payload.get("default_branch")
        html_url = payload.get("html_url")
        if not all(isinstance(value, str) and value for value in (
            full_name,
            default_branch,
            html_url,
        )):
            raise ValueError("GitHub returned a repository without required metadata.")

        description = payload.get("description")
        updated_at = payload.get("updated_at")
        return cls(
            full_name=full_name,
            description=description if isinstance(description, str) else None,
            default_branch=default_branch,
            html_url=html_url,
            updated_at=updated_at if isinstance(updated_at, str) else None,
            archived=bool(payload.get("archived")),
        )


@dataclass(frozen=True, slots=True)
class InstalledRepository:
    """The local record of an integration repository installed by PrivateHACS."""

    full_name: str
    default_branch: str
    commit_sha: str
    domains: tuple[str, ...]
    installed_at: str

    def as_dict(self) -> dict[str, Any]:
        """Serialize the record for Home Assistant storage."""
        return {
            "full_name": self.full_name,
            "default_branch": self.default_branch,
            "commit_sha": self.commit_sha,
            "domains": list(self.domains),
            "installed_at": self.installed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InstalledRepository:
        """Deserialize a validated record from Home Assistant storage."""
        full_name = payload.get("full_name")
        default_branch = payload.get("default_branch")
        commit_sha = payload.get("commit_sha")
        installed_at = payload.get("installed_at")
        domains = payload.get("domains")
        if not all(isinstance(value, str) and value for value in (
            full_name,
            default_branch,
            commit_sha,
            installed_at,
        )) or not isinstance(domains, list) or not all(
            isinstance(domain, str) and domain for domain in domains
        ):
            raise ValueError("Invalid installed repository record.")

        return cls(
            full_name=full_name,
            default_branch=default_branch,
            commit_sha=commit_sha,
            domains=tuple(domains),
            installed_at=installed_at,
        )