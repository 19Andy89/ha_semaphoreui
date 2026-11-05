"""Sensor "Karte sichtbar": running, failed, something to do - and, with the option, 24 h after a run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.semaphore_ui.const import CONF_KEEP_RECENT
from homeassistant.core import HomeAssistant

from .test_flow_and_entities import eid
from .test_parallel_guard import press


async def _setup(hass: HomeAssistant, make_entry, options=None):
    entry = make_entry(options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_without_the_option_a_quiet_template_is_not_shown(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(1)
    await _setup(hass, make_entry)
    state = hass.states.get(eid(hass, "binary_sensor", 1, "show_card"))
    assert state.state == "off"
    assert state.attributes["reason"] is None


async def test_a_failed_template_is_shown(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(1, status="error")
    await _setup(hass, make_entry)
    state = hass.states.get(eid(hass, "binary_sensor", 1, "show_card"))
    assert (state.state, state.attributes["reason"]) == ("on", "error")


async def test_with_the_option_a_run_stays_visible_for_24_hours_until_marked_done(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, _ = fake
    server.add_finished_task(1, when=datetime.now(UTC) - timedelta(hours=2))
    server.add_finished_task(2, when=datetime.now(UTC) - timedelta(hours=30))
    await _setup(hass, make_entry, {CONF_KEEP_RECENT: True})

    fresh = hass.states.get(eid(hass, "binary_sensor", 1, "show_card"))
    assert (fresh.state, fresh.attributes["reason"]) == ("on", "recent")
    assert fresh.attributes["until"]
    assert hass.states.get(eid(hass, "binary_sensor", 2, "show_card")).state == "off"  # older than 24 h

    await press(hass, "dismiss")
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, "binary_sensor", 1, "show_card")).state == "off"


async def test_a_running_task_is_always_shown(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    await _setup(hass, make_entry)
    await press(hass, "start")
    state = hass.states.get(eid(hass, "binary_sensor", 1, "show_card"))
    assert (state.state, state.attributes["reason"]) == ("on", "running")
