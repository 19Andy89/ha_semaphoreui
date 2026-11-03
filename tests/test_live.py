"""Live updates over the WebSocket: current step while a task runs, fallback to polling."""

from __future__ import annotations

import asyncio

from custom_components.semaphore_ui.const import CONF_LIVE
from custom_components.semaphore_ui.live import parse_step
from homeassistant.core import HomeAssistant

from .test_flow_and_entities import eid, setup, tick
from .test_parallel_guard import press


def test_parse_step_reads_ansible_task_lines() -> None:
    assert parse_step("TASK [Paketlisten aktualisieren] ********") == "Paketlisten aktualisieren"
    assert parse_step("\x1b[0;32mTASK [Mit Farbe] ***\x1b[0m") == "Mit Farbe"
    assert parse_step("RUNNING HANDLER [restart ssh] ***") == "restart ssh"
    assert parse_step("PLAY [Host] ***") is None
    assert parse_step("ok: [proxmox]") is None
    assert parse_step("") is None


async def _wait(hass: HomeAssistant, predicate, *, tries: int = 60) -> bool:
    for _ in range(tries):
        await hass.async_block_till_done()
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_step_shown_while_running_and_connection_closed_afterwards(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, _ = fake
    server.start_status = "running"
    await setup(hass, make_entry)
    assert server.ws_connects == 0  # nothing runs: no connection

    await press(hass, "start", template_id=1)
    task_id = max(server.tasks)
    assert await _wait(hass, lambda: len(server.sockets) == 1)

    for name in ("Fakten sammeln", "Pakete installieren"):
        await server.broadcast(
            {"type": "log", "project_id": 1, "task_id": task_id, "output": f"TASK [{name}] ***"}
        )
    # a message of another project and noise are ignored
    await server.broadcast(
        {"type": "log", "project_id": 2, "task_id": task_id, "output": "TASK [fremd] ***"}
    )
    await server.broadcast(
        {"type": "log", "project_id": 1, "task_id": task_id, "output": "ok: [host]"}
    )
    status = eid(hass, "sensor", 1, "status")
    assert await _wait(
        hass, lambda: hass.states.get(status).attributes.get("current_step") == "Pakete installieren"
    )
    assert hass.states.get(status).attributes["step_number"] == 2
    assert hass.states.get(status).attributes["live"] is True

    server.finish(task_id, "success", "TASK [x] ***\nok")
    await server.broadcast(
        {"type": "update", "project_id": 1, "task_id": task_id, "template_id": 1, "status": "success"}
    )
    assert await _wait(hass, lambda: hass.states.get(status).state == "success")
    assert "current_step" not in hass.states.get(status).attributes
    assert await _wait(hass, lambda: not server.sockets)  # closed again


async def test_step_is_read_from_the_log_when_the_task_started_before_the_connection(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, _ = fake
    await setup(hass, make_entry)
    task = server.add_finished_task(1, status="running")
    task.pop("end")
    server.outputs[task["id"]] = [
        {"id": 1, "task_id": task["id"], "output": "PLAY [x] ***"},
        {"id": 2, "task_id": task["id"], "output": "TASK [Gathering Facts] ***"},
        {"id": 3, "task_id": task["id"], "output": "TASK [Update] ***"},
    ]
    await tick(hass)
    status = eid(hass, "sensor", 1, "status")
    assert await _wait(hass, lambda: hass.states.get(status).attributes.get("current_step") == "Update")
    assert hass.states.get(status).attributes["step_number"] == 2


async def test_no_websocket_when_live_updates_are_off(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    entry = make_entry({CONF_LIVE: False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await press(hass, "start", template_id=1)
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert server.ws_connects == 0
    status = eid(hass, "sensor", 1, "status")
    assert hass.states.get(status).state == "running"


async def test_polling_continues_when_the_server_has_no_websocket(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, _ = fake
    server.ws_enabled = False
    server.start_status = "running"
    await setup(hass, make_entry)
    await press(hass, "start", template_id=1)
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    task_id = max(server.tasks)
    server.finish(task_id, "success", "ok")
    await tick(hass)
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "success"
