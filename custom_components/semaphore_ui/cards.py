"""Serves the dashboard cards that ship with the integration.

The cards (``custom:semaphore-ui-template-card`` and
``custom:semaphore-ui-project-card``) live in one JavaScript file. It is made
available under ``/semaphore_ui_static/`` and brought into the frontend in two
ways, so it is found even when one of them fails (browser cache of the start
page, YAML mode, ...):

1. ``frontend.add_extra_js_url`` - loaded together with the Home Assistant frontend.
2. A Lovelace *resource* (storage mode only) with the same URL - the same way
   other custom integrations and HACS cards are loaded. In YAML mode the
   resources are owned by the user's configuration, so nothing is changed there.

What happened is kept in ``hass.data`` and shown in the diagnostics.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import CARD_FILE, CARD_URL_BASE, DOMAIN

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"
CARDS_STATUS_KEY = f"{DOMAIN}_cards"

# values of ``status["resource"]``
RESOURCE_CREATED = "created"
RESOURCE_UPDATED = "updated"
RESOURCE_PRESENT = "present"
RESOURCE_YAML_MODE = "yaml_mode"
RESOURCE_NO_LOVELACE = "lovelace_not_loaded"
RESOURCE_ERROR = "error"


def cards_status(hass: HomeAssistant) -> dict[str, Any]:
    """What the registration of the cards did (for diagnostics)."""
    return hass.data.setdefault(
        CARDS_STATUS_KEY,
        {
            "file": None,
            "static_path": False,
            "extra_js_url": False,
            "resource": None,
            "url": None,
            "errors": [],
        },
    )


async def async_register_cards(hass: HomeAssistant) -> None:
    """Expose the card file and tell the frontend to load it (best effort)."""
    status = cards_status(hass)
    http = getattr(hass, "http", None)
    card = FRONTEND_DIR / CARD_FILE
    status["file"] = card.is_file()
    if http is None or not card.is_file():
        return  # no web server (e.g. in tests) - the integration works without the cards

    url = f"{CARD_URL_BASE}/{CARD_FILE}?v={int(card.stat().st_mtime)}"
    status["url"] = url
    try:
        from homeassistant.components.http import StaticPathConfig

        await http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(FRONTEND_DIR), cache_headers=False)]
        )
        status["static_path"] = True
    except (ImportError, KeyError, RuntimeError, ValueError) as err:
        _LOGGER.warning("Dashboard cards could not be served: %s", err)
        status["errors"].append(f"static_path: {err}")
        return

    try:
        from homeassistant.components.frontend import add_extra_js_url

        # the file's modification time as version: browsers fetch a new file after an update
        add_extra_js_url(hass, url)
        status["extra_js_url"] = True
    except (ImportError, KeyError, RuntimeError, ValueError) as err:
        _LOGGER.warning("Dashboard cards could not be added to the frontend: %s", err)
        status["errors"].append(f"extra_js_url: {err}")

    await async_ensure_resource(hass, url)
    if status["resource"] == RESOURCE_NO_LOVELACE:
        # Lovelace is not up yet (rare): try again when Home Assistant has started.
        from homeassistant.helpers.start import async_at_started

        async def _retry(_hass: HomeAssistant) -> None:
            await async_ensure_resource(hass, url)

        async_at_started(hass, _retry)


async def async_ensure_resource(hass: HomeAssistant, url: str) -> str:
    """Make sure the card file is a Lovelace resource (storage mode) with ``url``.

    Returns one of the ``RESOURCE_*`` values; it is also stored in the status.
    """
    status = cards_status(hass)
    result = await _async_ensure_resource(hass, url)
    status["resource"] = result
    return result


async def _async_ensure_resource(hass: HomeAssistant, url: str) -> str:
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
    except ImportError:
        return RESOURCE_NO_LOVELACE
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        return RESOURCE_NO_LOVELACE
    if getattr(lovelace, "resource_mode", "storage") == "yaml":
        # The user keeps the resources in configuration.yaml: do not touch them.
        return RESOURCE_YAML_MODE

    path = url.partition("?")[0]
    try:
        resources = lovelace.resources
        await resources.async_get_info()  # makes sure the collection is loaded
        existing = [
            item
            for item in resources.async_items()
            if str(item.get("url", "")).partition("?")[0] == path
        ]
        if not existing:
            await resources.async_create_item({"res_type": "module", "url": url})
            return RESOURCE_CREATED
        item = existing[0]
        if item.get("url") != url or item.get("type") != "module":
            await resources.async_update_item(
                item["id"], {"res_type": "module", "url": url}
            )
            return RESOURCE_UPDATED
        return RESOURCE_PRESENT
    except Exception as err:  # noqa: BLE001 - never block the start of the integration
        _LOGGER.warning("Dashboard resource for the cards could not be set: %s", err)
        cards_status(hass)["errors"].append(f"resource: {err}")
        return RESOURCE_ERROR
