"""Fix flows of the repairs of the Semaphore UI integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from . import tokens
from .api import (
    SemaphoreApiError,
    SemaphoreAuthError,
    SemaphoreConnectionError,
    SemaphoreError,
    SemaphoreLoginError,
)
from .const import CONF_API_TOKEN, DOMAIN, ISSUE_TOKEN, ISSUE_TOKEN_EXPIRING

_LOGGER = logging.getLogger(__name__)

_TOKEN_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        type=selector.TextSelectorType.PASSWORD, autocomplete="off"
    )
)


def _error_key(err: SemaphoreError) -> str:
    """Short reason for the form (the long texts are those of the setup dialog)."""
    if isinstance(err, SemaphoreAuthError):
        return "invalid_auth"
    if isinstance(err, SemaphoreApiError) and err.status in (403, 404):
        return "project_not_found"
    if isinstance(err, (SemaphoreConnectionError, SemaphoreApiError)):
        return "cannot_connect"
    return "unknown"


class TokenRepairFlow(RepairsFlow):
    """Enter a new API token - or a login that creates one - right in the repair.

    The token is checked before it is saved. The login is only kept (as an option) when
    the box is ticked; otherwise only the new token is stored.
    """

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Ask for the new token."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_missing")
        errors: dict[str, str] = {}
        detail = ""
        # Home Assistant opens the first step with ``{"issue_id": ...}`` as input
        # (compatibility for custom integrations): only a token means "submitted".
        if user_input is not None and (
            {CONF_API_TOKEN, CONF_USERNAME, tokens.STORE_LOGIN} & user_input.keys()
        ):
            try:
                token = await tokens.async_check_new_token(self.hass, entry, user_input)
            except SemaphoreLoginError as err:
                errors["base"] = tokens.login_error_key(err)
            except SemaphoreError as err:
                errors["base"] = _error_key(err)
                detail = str(err)
                _LOGGER.warning("New token not accepted (%s): %s", errors["base"], err)
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_API_TOKEN: token},
                    options=tokens.options_with_login(entry, user_input) or entry.options,
                )
                # the open "re-authenticate" notification is obsolete now
                for flow in self.hass.config_entries.flow.async_progress_by_handler(
                    DOMAIN,
                    match_context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
                ):
                    self.hass.config_entries.flow.async_abort(flow["flow_id"])
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_TOKEN): _TOKEN_SELECTOR,
                    vol.Optional(CONF_USERNAME): selector.TextSelector(),
                    vol.Optional(CONF_PASSWORD): _TOKEN_SELECTOR,
                    vol.Optional(tokens.STORE_LOGIN, default=False): selector.BooleanSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "project": entry.data.get("project_name", ""),
                "url": entry.data[CONF_URL],
                "detail": detail,
            },
        )


class TokenRenewFlow(RepairsFlow):
    """"The token expires soon": replace it now (with the token itself)."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Home Assistant opens the first step with the issue id: go on to the question."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Ask once, then create the new token."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        coordinator = getattr(entry, "runtime_data", None)
        token_check = getattr(coordinator, "token_coordinator", None)
        if entry is None or token_check is None:
            return self.async_abort(reason="not_loaded")
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            try:
                await token_check.async_renew_now()
            except SemaphoreError as err:
                errors["base"] = "renew_failed"
                detail = str(err)
                _LOGGER.warning("The API token could not be replaced: %s", err)
            else:
                return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "project": entry.data.get("project_name", ""),
                "url": entry.data[CONF_URL],
                "detail": detail,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow of a fixable issue (rejected token, token expires soon)."""
    if issue_id.startswith(f"{ISSUE_TOKEN}_") and data and data.get("entry_id"):
        return TokenRepairFlow(str(data["entry_id"]))
    if issue_id.startswith(f"{ISSUE_TOKEN_EXPIRING}_") and data and data.get("entry_id"):
        return TokenRenewFlow(str(data["entry_id"]))
    raise ValueError(f"No fix flow for the issue {issue_id}")
