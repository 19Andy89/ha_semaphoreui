"""Deploy templates need a finished build (build_task_id); build templates start as they are."""

from __future__ import annotations

import pytest

from custom_components.semaphore_ui.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .test_flow_and_entities import eid, setup
from .test_parallel_guard import press


def _add_build_and_deploy(server) -> tuple[dict, dict]:
    server.templates[10] = {
        "id": 10, "project_id": 1, "name": "App bauen", "app": "ansible", "type": "build"
    }
    server.templates[11] = {
        "id": 11, "project_id": 1, "name": "App ausrollen", "app": "ansible",
        "type": "deploy", "build_template_id": 10,
    }
    return server.templates[10], server.templates[11]


def _build(server, version: str | None, status: str = "success") -> int:
    task = server.add_finished_task(10, status=status)
    if version:
        task["version"] = version
    return task["id"]


def _started_body(server, template_id: int) -> dict:
    bodies = [b for m, p, b in server.requests if m == "POST" and p.endswith("/tasks") and b.get("template_id") == template_id]
    return bodies[-1]


async def test_a_deploy_takes_the_newest_successful_build(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    _add_build_and_deploy(server)
    _build(server, "1.0.1")
    newest_ok = _build(server, "1.0.2")
    _build(server, "1.0.3", status="error")  # a failed build is never deployed
    _build(server, None)  # without a version neither
    await setup(hass, make_entry)

    await press(hass, "start", template_id=11)
    assert _started_body(server, 11)["build_task_id"] == newest_ok


async def test_a_build_version_picks_that_build(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    _add_build_and_deploy(server)
    older = _build(server, "1.0.1")
    _build(server, "1.0.2")
    await setup(hass, make_entry)

    await hass.services.async_call(
        DOMAIN, "run_template",
        {"entity_id": eid(hass, "button", 11, "start"), "build_version": "1.0.1"},
        blocking=True,
    )
    assert _started_body(server, 11)["build_task_id"] == older


async def test_a_build_task_id_is_passed_on(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    _add_build_and_deploy(server)
    await setup(hass, make_entry)
    await hass.services.async_call(
        DOMAIN, "run_template",
        {"entity_id": eid(hass, "button", 11, "start"), "build_task_id": 4242},
        blocking=True,
    )
    assert _started_body(server, 11)["build_task_id"] == 4242


async def test_unknown_version_and_missing_builds_are_explained(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    _add_build_and_deploy(server)
    await setup(hass, make_entry)
    with pytest.raises(ServiceValidationError) as err:
        await press(hass, "start", template_id=11)  # no build at all yet
    assert err.value.translation_key == "no_build_available"

    _build(server, "1.0.1")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "run_template",
            {"entity_id": eid(hass, "button", 11, "start"), "build_version": "9.9.9"},
            blocking=True,
        )
    assert err.value.translation_key == "build_not_found"
    assert not [b for m, p, b in server.requests if m == "POST" and p.endswith("/tasks")]


async def test_build_and_ordinary_templates_start_without_build_task(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.start_status = "running"
    _add_build_and_deploy(server)
    await setup(hass, make_entry)
    await press(hass, "start", template_id=10)  # the build gets its version from Semaphore
    assert "build_task_id" not in _started_body(server, 10)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "run_template",
            {"entity_id": eid(hass, "button", 1, "start"), "build_version": "1.0.1"},
            blocking=True,
        )
    assert err.value.translation_key == "build_not_applicable"
