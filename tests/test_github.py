"""Tests for GitHub catalog filtering and redacted diagnostics."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types


def _load_github_module():
    sys.modules.setdefault(
        "aiohttp", types.SimpleNamespace(ClientResponse=object, ClientSession=object)
    )
    root = Path(__file__).parents[1] / "custom_components" / "privatehacs"
    package_name = "privatehacs_github_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package

    for name in ("models", "github"):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}", root / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

    return sys.modules[f"{package_name}.github"]


github = _load_github_module()


class _Response:
    status = 200
    headers = {"X-OAuth-Scopes": "repo", "X-RateLimit-Remaining": "4999"}
    links: dict[str, object] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def json(self, content_type: object = None) -> list[dict[str, object]]:
        return [
            {
                "private": False,
                "full_name": "owner/public",
                "default_branch": "main",
                "html_url": "https://example.test/public",
            },
            {
                "private": True,
                "full_name": "owner/private",
                "default_branch": "main",
                "html_url": "https://example.test/private",
            },
        ]


class _Session:
    def __init__(self) -> None:
        self.params: dict[str, str] | None = None

    def get(
        self, _url: str, params: dict[str, str] | None = None, **_: object
    ) -> _Response:
        self.params = params
        return _Response()


def test_catalog_filters_private_repositories_and_redacts_diagnostics() -> None:
    """Catalog lookup does not rely on GitHub's visibility filter."""
    session = _Session()
    client = github.GitHubClient(session, "owner", "secret-token")

    repositories = asyncio.run(client.async_list_private_repositories())

    assert [repository.full_name for repository in repositories] == ["owner/private"]
    assert session.params is not None
    assert "visibility" not in session.params
    assert client.repository_query_diagnostics == {
        "completed": True,
        "queried_at": client.repository_query_diagnostics["queried_at"],
        "pages": 1,
        "visible_repositories": 2,
        "private_repositories": 1,
        "oauth_scopes": "repo",
        "rate_limit_remaining": "4999",
        "error": None,
    }
    assert "owner/private" not in str(client.repository_query_diagnostics)
    assert "secret-token" not in str(client.repository_query_diagnostics)