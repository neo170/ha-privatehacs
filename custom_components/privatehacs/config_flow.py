"""Config flow for PrivateHACS."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .const import CONF_GITHUB_TOKEN, CONF_GITHUB_USERNAME, DOMAIN, NAME
from .github import GitHubAuthenticationError, GitHubClient, GitHubError


async def validate_input(hass: HomeAssistant, data: dict[str, str]) -> tuple[int, str]:
    """Validate GitHub credentials and return the authenticated account identity."""
    account = await GitHubClient(
        async_get_clientsession(hass),
        data[CONF_GITHUB_USERNAME],
        data[CONF_GITHUB_TOKEN],
    ).async_validate()
    return account.account_id, account.login


class PrivateHacsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure PrivateHACS with a GitHub account and PAT."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial configuration step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                account_id, login = await validate_input(self.hass, user_input)
            except GitHubAuthenticationError:
                errors["base"] = "invalid_auth"
            except GitHubError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(str(account_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{NAME} ({login})",
                    data={
                        CONF_GITHUB_USERNAME: user_input[CONF_GITHUB_USERNAME],
                        CONF_GITHUB_TOKEN: user_input[CONF_GITHUB_TOKEN],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GITHUB_USERNAME): str,
                    vol.Required(CONF_GITHUB_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                }
            ),
            errors=errors,
        )