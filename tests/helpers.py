"""Small helpers for the tests."""

from __future__ import annotations

from custom_components.semaphore_ui.secrets_store import unseal
from homeassistant.core import HomeAssistant


def plain(hass: HomeAssistant, value: str | None) -> str | None:
    """A stored (encrypted) token or password as plain text."""
    return unseal(hass, value)
