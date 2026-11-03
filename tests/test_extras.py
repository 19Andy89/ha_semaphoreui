"""Reconfigure flow, diagnostics, logbook, device removal and the dashboard cards."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.semaphore_ui import (
    async_remove_config_entry_device,
    cards,
    const,
)
from custom_components.semaphore_ui.const import (
    CONF_API_TOKEN,
    DOMAIN,
    EVENT_TASK_FINISHED,
    EVENT_TASK_STARTED,
)
from custom_components.semaphore_ui.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.semaphore_ui.logbook import async_describe_events
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from .helpers import plain
from .fake_semaphore import TOKEN
from .test_flow_and_entities import find_device, setup

# --------------------------------------------------------------------------- #
# Reconfigure
# --------------------------------------------------------------------------- #


async def test_reconfigure_changes_token_and_ssl(
    hass: HomeAssistant, fake, make_entry, caplog: pytest.LogCaptureFixture
) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)
    server.token = "rotated"

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: url, CONF_API_TOKEN: "wrong", CONF_VERIFY_SSL: True},
    )
    assert bad["errors"] == {"base": "invalid_auth"}

    done = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: url + "/", CONF_API_TOKEN: "rotated", CONF_VERIFY_SSL: False},
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert plain(hass, entry.data[CONF_API_TOKEN]) == "rotated"
    assert entry.data[CONF_URL] == url  # trailing slash removed
    assert entry.data[CONF_VERIFY_SSL] is False
    assert entry.state is ConfigEntryState.LOADED
    # HA 2026.12 turns this into an error: no manual update listener together with
    # async_update_reload_and_abort
    assert "update listener" not in caplog.text


async def test_reconfigure_unreachable(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)
    result = await entry.start_reconfigure_flow(hass)
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "http://127.0.0.1:1", CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
    assert bad["errors"] == {"base": "connection_refused"}
    assert bad["description_placeholders"]["host"] == "127.0.0.1"


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #


async def test_diagnostics_hides_token_and_address(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, url = fake
    server.add_finished_task(2, "error", "fatal: [h]: FAILED! => {}")
    entry = await setup(hass, make_entry)

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert data["entry"]["data"][CONF_API_TOKEN] == "**REDACTED**"
    assert data["entry"]["data"][CONF_URL] == "**REDACTED**"
    assert TOKEN not in str(data)
    assert url not in str(data)
    names = {t["name"]: t for t in data["coordinator"]["templates"]}
    assert names["Host-Update"]["status"] == "error"
    assert names["Bash Job"]["status"] == "never_run"
    assert data["version"]["installed"] == "2.16.10"
    assert data["coordinator"]["update_interval_seconds"] == const.DEFAULT_SCAN_INTERVAL


# --------------------------------------------------------------------------- #
# Logbook
# --------------------------------------------------------------------------- #


async def test_logbook_describes_task_events(hass: HomeAssistant) -> None:
    registered: dict[tuple[str, str], object] = {}

    def _register(domain: str, event_type: str, describe) -> None:
        registered[(domain, event_type)] = describe

    async_describe_events(hass, _register)
    assert (DOMAIN, EVENT_TASK_STARTED) in registered
    assert (DOMAIN, EVENT_TASK_FINISHED) in registered

    event = Event(
        EVENT_TASK_FINISHED,
        {"template": "Host-Update", "short": "❌ Fehler · 18 s", "title": "x"},
    )
    entry = registered[(DOMAIN, EVENT_TASK_FINISHED)](event)
    assert entry[LOGBOOK_ENTRY_NAME] == "Semaphore – Host-Update"
    assert entry[LOGBOOK_ENTRY_MESSAGE] == "❌ Fehler · 18 s"

    # a report without "short" falls back to the title
    entry = registered[(DOMAIN, EVENT_TASK_STARTED)](
        Event(EVENT_TASK_STARTED, {"template": "T", "title": "Gestartet"})
    )
    assert entry[LOGBOOK_ENTRY_MESSAGE] == "Gestartet"


# --------------------------------------------------------------------------- #
# Removing devices
# --------------------------------------------------------------------------- #


async def test_only_devices_of_missing_templates_can_be_removed(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)

    project = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert project is not None
    assert await async_remove_config_entry_device(hass, entry, project) is False

    template = find_device(hass, f"{entry.entry_id}_template_1")
    assert await async_remove_config_entry_device(hass, entry, template) is False

    ghost = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_template_99")},
        name="Gone",
    )
    assert await async_remove_config_entry_device(hass, entry, ghost) is True


# --------------------------------------------------------------------------- #
# Dashboard cards
# --------------------------------------------------------------------------- #


async def test_cards_are_served_and_loaded_by_the_frontend(hass: HomeAssistant) -> None:
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    hass.data[DATA_EXTRA_MODULE_URL] = set()

    await cards.async_register_cards(hass)

    hass.http.async_register_static_paths.assert_awaited_once()
    (config,) = hass.http.async_register_static_paths.await_args.args[0]
    assert config.url_path == const.CARD_URL_BASE
    assert (Path(config.path) / const.CARD_FILE).is_file()
    (url,) = hass.data[DATA_EXTRA_MODULE_URL]
    assert url.startswith(f"{const.CARD_URL_BASE}/{const.CARD_FILE}?v=")


async def test_cards_without_web_server_or_frontend_do_not_break(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    # no web server at all (like in these tests normally)
    await cards.async_register_cards(hass)

    # web server but the frontend integration is not loaded
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    hass.data.pop(DATA_EXTRA_MODULE_URL, None)
    await cards.async_register_cards(hass)
    assert "could not be added to the frontend" in caplog.text
    assert cards.cards_status(hass)["errors"]


def test_card_file_is_valid_javascript_and_registers_both_cards() -> None:
    source = (cards.FRONTEND_DIR / const.CARD_FILE).read_text(encoding="utf-8")
    for name in ("semaphore-ui-template-card", "semaphore-ui-project-card"):
        assert f'"{name}"' in source
    assert "window.customCards" in source
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed - syntax check skipped")
    result = subprocess.run(  # noqa: S603
        [node, "--check", str(cards.FRONTEND_DIR / const.CARD_FILE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
