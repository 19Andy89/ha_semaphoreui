"""No second start while a run of the template is queued or running (unless allowed)."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.semaphore_ui.const import CONF_ALLOW_PARALLEL, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from .test_flow_and_entities import OK_LOG, device_id_of, eid, setup, tick


def posts(server) -> list:
    """Task starts the fake server received."""
    return [r for r in server.requests if r[0] == "POST" and r[1].endswith("/tasks")]


async def press(hass: HomeAssistant, key: str, template_id: int = 1) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", template_id, key)}, blocking=True
    )


async def test_second_start_is_refused_while_running(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    await setup(hass, make_entry)

    await press(hass, "start")
    first = max(server.tasks)

    with pytest.raises(ServiceValidationError) as err:
        await press(hass, "start")
    assert err.value.translation_key == "already_running"
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_placeholders == {
        "template": "docker-system aktualisieren",
        "task_id": str(first),
    }
    # a dry run is a run as well
    with pytest.raises(ServiceValidationError):
        await press(hass, "dry_run")
    assert len(posts(server)) == 1  # nothing reached Semaphore

    running = hass.states.get(eid(hass, "binary_sensor", 1, "running"))
    assert running.state == "on"
    assert running.attributes["parallel_allowed"] is False
    assert running.attributes["task_ids"] == [first]

    # other templates are not affected
    await press(hass, "start", template_id=2)
    assert len(posts(server)) == 2

    # after the run has ended the template can be started again
    server.finish(first, "success", OK_LOG)
    await tick(hass)
    assert hass.states.get(eid(hass, "binary_sensor", 1, "running")).state == "off"
    await press(hass, "start")
    assert len(posts(server)) == 3


async def test_queued_run_counts_and_action_is_refused(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "waiting"  # Semaphore queues it
    await setup(hass, make_entry)
    await hass.services.async_call(
        DOMAIN, "run_template", {"device_id": device_id_of(hass, 1)}, blocking=True, return_response=True
    )
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "run_template", {"device_id": device_id_of(hass, 1), "wait": True},
            blocking=True, return_response=True,
        )
    assert err.value.translation_key == "already_running"
    assert len(posts(server)) == 1


async def test_run_started_in_semaphore_blocks_too(hass: HomeAssistant, fake, make_entry) -> None:
    """A run started in Semaphore's own UI is seen with the next poll."""
    server, _ = fake
    await setup(hass, make_entry)
    task = server.add_finished_task(1, status="running")
    task.pop("end")
    await tick(hass)
    with pytest.raises(ServiceValidationError):
        await press(hass, "start")
    assert posts(server) == []


async def test_stop_makes_start_possible_again(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    await setup(hass, make_entry)
    await press(hass, "start")
    with pytest.raises(ServiceValidationError):
        await press(hass, "start")
    await press(hass, "stop")
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "stopped"
    await press(hass, "start")
    assert len(posts(server)) == 2


async def test_two_clicks_at_once_start_only_one_run(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    entry = await setup(hass, make_entry)
    coordinator = entry.runtime_data
    results = await asyncio.gather(
        coordinator.async_run_template(1),
        coordinator.async_run_template(1),
        coordinator.async_run_template(1, dry_run=True),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, ServiceValidationError) for r in results) == 2
    assert len(posts(server)) == 1


async def test_option_allows_parallel_runs(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_PARALLEL: True})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await press(hass, "start")
    await press(hass, "start")
    await press(hass, "dry_run")
    assert len(posts(server)) == 3
    running = hass.states.get(eid(hass, "binary_sensor", 1, "running"))
    assert running.attributes["parallel_allowed"] is True
    assert len(running.attributes["task_ids"]) == 3


async def test_template_that_allows_parallel_tasks_is_not_blocked(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, _ = fake
    server.start_status = "running"
    server.templates[1]["allow_parallel_tasks"] = True  # "Allow parallel tasks" in Semaphore
    await setup(hass, make_entry)
    await press(hass, "start")
    await press(hass, "start")
    assert len(posts(server)) == 2
    assert hass.states.get(eid(hass, "binary_sensor", 1, "running")).attributes["parallel_allowed"] is True
    # the setting belongs to the template: template 2 is still protected
    await press(hass, "start", template_id=2)
    with pytest.raises(ServiceValidationError):
        await press(hass, "start", template_id=2)


async def test_options_flow_has_the_parallel_option(hass: HomeAssistant, fake, make_entry) -> None:
    entry = await setup(hass, make_entry)
    assert entry.runtime_data.allow_parallel is False  # default: protected

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert CONF_ALLOW_PARALLEL in {str(k) for k in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30, "check_for_updates": False, CONF_ALLOW_PARALLEL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_ALLOW_PARALLEL] is True
    assert entry.runtime_data.allow_parallel is True  # the entry was reloaded
