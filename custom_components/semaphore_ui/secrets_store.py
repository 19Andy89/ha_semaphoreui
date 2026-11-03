"""Keep the API token and the stored login out of ``core.config_entries`` as plain text.

Home Assistant has no secret store for integrations: everything in a config entry lies in
``.storage/core.config_entries`` as readable text (that is true for the official integrations as
well). This module encrypts the token and the optional password (Fernet, AES-128-CBC + HMAC)
with a random key that lives in its own file, ``.storage/semaphore_ui.key`` (only readable by the
Home Assistant user). What that protects against: the config file alone (shared by mistake,
posted in a forum, a partial copy) no longer gives away access. What it does *not* protect
against: someone who gets the whole ``.storage`` folder or a full backup with the key in it,
because the key has to be readable for Home Assistant itself. Encrypted backups are the real
protection there.
"""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

PREFIX = "enc1:"
_KEY = "semaphore_ui_cipher"
_STORE_VERSION = 1
_STORE_NAME = "semaphore_ui.key"


async def async_load_key(hass: HomeAssistant) -> None:
    """Load the key (or create it on first use) and keep it for :func:`seal`/:func:`unseal`."""
    if hass.data.get(_KEY) is not None:
        return
    store: Store[dict[str, str]] = Store(hass, _STORE_VERSION, _STORE_NAME, private=True)
    data = await store.async_load()
    key = (data or {}).get("key")
    if not key:
        key = Fernet.generate_key().decode()
        await store.async_save({"key": key})
        _LOGGER.debug("Created a new key for the stored credentials")
    hass.data[_KEY] = Fernet(key.encode())


def is_sealed(value: object) -> bool:
    """True if ``value`` is an encrypted string of this module."""
    return isinstance(value, str) and value.startswith(PREFIX)


def seal(hass: HomeAssistant, value: str) -> str:
    """Encrypt ``value`` (a value that is already encrypted stays as it is)."""
    if is_sealed(value):
        return value
    cipher: Fernet | None = hass.data.get(_KEY)
    if cipher is None:  # the key is loaded in async_setup; never write plain text silently
        raise RuntimeError("key for the credentials not loaded")
    return PREFIX + cipher.encrypt(value.encode()).decode()


def unseal(hass: HomeAssistant, value: str | None) -> str | None:
    """Decrypt ``value``. Plain text (an entry from before 0.15) comes back unchanged.

    ``None``: the value is encrypted but cannot be read (the key file is missing or does not
    belong to it) - the caller asks for a new token.
    """
    if not value:
        return value
    if not is_sealed(value):
        return value
    cipher: Fernet | None = hass.data.get(_KEY)
    if cipher is None:
        return None
    try:
        return cipher.decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        return None
