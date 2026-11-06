"""A finished run can be marked as done (project card hides it); the mark survives a restart."""

from __future__ import annotations

from custom_components.semaphore_ui.const import DOMAIN
from homeassistant.core import HomeAssistant

from .test_flow_and_entities import eid, setup
from .test_parallel_guard import press


async def test_dismiss_marks_the_run_and_survives_a_reload(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(1)
    entry = await setup(hass, make_entry)
    status = eid(hass, "sensor", 1, "status")
    assert "dismissed_at" not in hass.states.get(status).attributes

    await press(hass, "dismiss")
    marked = hass.states.get(status).attributes["dismissed_at"]
    assert marked
    # other templates stay untouched
    assert "dismissed_at" not in hass.states.get(eid(hass, "sensor", 2, "status")).attributes

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(status).attributes["dismissed_at"] == marked


async def test_dismiss_is_not_possible_while_a_task_runs(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    await setup(hass, make_entry)
    await press(hass, "start")
    assert hass.states.get(eid(hass, "button", 1, "dismiss")).state == "unavailable"


async def test_removing_the_project_deletes_the_marks(hass: HomeAssistant, fake, make_entry) -> None:
    from homeassistant.helpers.storage import Store

    server, _ = fake
    server.add_finished_task(1)
    entry = await setup(hass, make_entry)
    await press(hass, "dismiss")
    name = f"{DOMAIN}.dismissed_{entry.entry_id}"
    assert await Store(hass, 1, name).async_load()
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await Store(hass, 1, name).async_load() is None
