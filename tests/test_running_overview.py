"""Which templates run right now - on project level (names, tasks) for sensors and dashboards."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .test_flow_and_entities import OK_LOG, eid, project_eid, setup, tick
from .test_parallel_guard import press


async def test_project_entities_name_the_running_templates(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    await setup(hass, make_entry)

    sensor = hass.states.get(project_eid(hass, "sensor", "running_tasks"))
    flag = hass.states.get(project_eid(hass, "binary_sensor", "project_running"))
    assert sensor.state == "0" and flag.state == "off"
    assert sensor.attributes["templates"] == [] and flag.attributes["templates"] == []

    await press(hass, "start", template_id=1)  # "docker-system aktualisieren"
    # a run started in Semaphore's own UI (cron, web interface) counts as well
    task = server.add_finished_task(2, status="running")
    task.pop("end")
    await tick(hass)

    sensor = hass.states.get(project_eid(hass, "sensor", "running_tasks"))
    flag = hass.states.get(project_eid(hass, "binary_sensor", "project_running"))
    assert sensor.state == "2"
    assert flag.state == "on"
    assert flag.attributes["templates"] == sensor.attributes["templates"]
    assert sensor.attributes["templates"] == ["docker-system aktualisieren", "Host-Update"]
    assert len(sensor.attributes["task_ids"]) == 2
    first = sensor.attributes["details"][0]
    assert first["template_id"] == 1 and first["status"] == "running"
    assert first["dry_run"] is False
    assert first["started"]  # ISO time of the start

    for task_id in sensor.attributes["task_ids"]:
        server.finish(task_id, "success", OK_LOG)
    await tick(hass)
    assert hass.states.get(project_eid(hass, "binary_sensor", "project_running")).state == "off"
    assert hass.states.get(project_eid(hass, "sensor", "running_tasks")).attributes["templates"] == []
    assert hass.states.get(eid(hass, "binary_sensor", 1, "running")).state == "off"
