"""Fix flows of the repairs of the Semaphore UI integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SemaphoreApiError,
    SemaphoreAuthError,
    SemaphoreClient,
    SemaphoreConnectionError,
    SemaphoreError,
)
from .const import CONF_API_TOKEN, CONF_PROJECT_ID, DOMAIN, ISSUE_TOKEN

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
    """Enter a new API token right in the repair; it is checked before it is saved."""

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
        if user_input is not None and CONF_API_TOKEN in user_input:
            token = user_input[CONF_API_TOKEN].strip()
            client = SemaphoreClient(
                async_get_clientsession(self.hass, verify_ssl=entry.data[CONF_VERIFY_SSL]),
                entry.data[CONF_URL],
                token,
            )
            try:
                await client.get_project(entry.data[CONF_PROJECT_ID])
            except SemaphoreError as err:
                errors["base"] = _error_key(err)
                detail = str(err)
                _LOGGER.warning("New token not accepted (%s): %s", errors["base"], err)
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_API_TOKEN: token}
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
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): _TOKEN_SELECTOR}),
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
    """Create the fix flow of a fixable issue (only the rejected token is fixable)."""
    if issue_id.startswith(f"{ISSUE_TOKEN}_") and data and data.get("entry_id"):
        return TokenRepairFlow(str(data["entry_id"]))
    raise ValueError(f"No fix flow for the issue {issue_id}")
