"""Integration tests against the fake Semaphore server."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.semaphore_ui import const
from custom_components.semaphore_ui.const import (
    CONF_API_TOKEN,
    CONF_PROJECT_ID,
    DOMAIN,
    EVENT_TASK_FINISHED,
    EVENT_TASK_STARTED,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .fake_semaphore import TOKEN

FAIL_LOG = """\
TASK [Neue Images ziehen] ******
fatal: [dockerhost]: FAILED! => {
    "changed": false,
    "msg": "pull access denied for foo"
}
PLAY RECAP ******
dockerhost                 : ok=0    changed=0    unreachable=0    failed=1    skipped=0    rescued=0    ignored=0
"""
OK_LOG = """\
TASK [Ergebnis anzeigen] ******
PLAY RECAP ******
dockerhost                 : ok=3    changed=1    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
"""


def eid(hass: HomeAssistant, platform: str, template_id: int, key: str) -> str:
    """Entity id from the registry via unique id (names depend on language)."""
    ent_reg = er.async_get(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_id = ent_reg.async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{template_id}_{key}"
    )
    assert entity_id, f"no entity for {platform} {template_id} {key}"
    return entity_id


async def setup(hass: HomeAssistant, make_entry) -> Any:
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def tick(hass: HomeAssistant, seconds: int = 60) -> None:
    """Fire the coordinator timer."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


# --------------------------------------------------------------------------- #
# Config flow
# --------------------------------------------------------------------------- #
async def test_config_flow_full(hass: HomeAssistant, fake) -> None:
    server, url = fake
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: url + "/", CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "project"
    options = result["data_schema"].schema[CONF_PROJECT_ID].config["options"]
    assert {o["label"] for o in options} == {"Homelab", "Other"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROJECT_ID: "1"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Semaphore – Homelab"
    assert result["data"][CONF_URL] == url
    assert result["data"][CONF_PROJECT_ID] == 1
    await hass.async_block_till_done()

    # second run of the flow for the same project -> abort
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROJECT_ID: "1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_config_flow_errors(hass: HomeAssistant, fake) -> None:
    server, url = fake
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: "nope", CONF_VERIFY_SSL: True}
    )
    assert bad["errors"] == {"base": "invalid_auth"}

    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "http://127.0.0.1:9", CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
    assert bad["errors"] == {"base": "connection_refused"}
    assert bad["description_placeholders"]["detail"] == "127.0.0.1:9"

    server.projects = []
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert bad["errors"] == {"base": "no_projects"}


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #
async def test_setup_creates_devices_and_entities(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.add_finished_task(1, "success", OK_LOG)
    server.add_finished_task(2, "error", FAIL_LOG, seconds=3)
    entry = await setup(hass, make_entry)
    assert entry.state is ConfigEntryState.LOADED

    # devices: project + 3 templates
    dev_reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    assert {d.name for d in devices} >= {
        "docker-system aktualisieren",
        "Host-Update",
        "Bash Job",
        "Semaphore – Homelab",
    }
    tpl_device = next(d for d in devices if d.name == "Host-Update")
    assert tpl_device.via_device_id is not None

    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "success"
    assert hass.states.get(eid(hass, "sensor", 2, "status")).state == "error"
    assert hass.states.get(eid(hass, "sensor", 3, "status")).state == "never_run"
    assert hass.states.get(eid(hass, "sensor", 1, "last_duration")).state == "72"
    assert hass.states.get(eid(hass, "sensor", 3, "last_started")).state == "unknown"
    assert hass.states.get(eid(hass, "binary_sensor", 2, "problem")).state == "on"
    assert hass.states.get(eid(hass, "binary_sensor", 1, "problem")).state == "off"
    assert hass.states.get(eid(hass, "binary_sensor", 1, "running")).state == "off"

    summary = hass.states.get(eid(hass, "sensor", 2, "summary"))
    assert "pull access denied" in summary.state
    assert summary.attributes["result"] == "failed"
    assert summary.attributes["error"]["host"] == "dockerhost"
    assert summary.attributes["duration_seconds"] == 3
    ok_summary = hass.states.get(eid(hass, "sensor", 1, "summary"))
    assert ok_summary.attributes["recap"][0]["changed"] == 1

    # bash templates have no dry run button; stop button is unavailable while idle
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("button", DOMAIN, f"{entry.entry_id}_3_dry_run") is None
    assert ent_reg.async_get_entity_id("button", DOMAIN, f"{entry.entry_id}_1_dry_run")
    assert hass.states.get(eid(hass, "button", 1, "stop")).state == "unavailable"
    # project device: running tasks counter
    assert hass.states.get("sensor.semaphore_homelab_running_tasks").state == "0"


async def test_start_button_and_finish_event(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    await setup(hass, make_entry)
    started = async_capture_events(hass, EVENT_TASK_STARTED)
    finished = async_capture_events(hass, EVENT_TASK_FINISHED)

    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 1, "start")}, blocking=True
    )
    await hass.async_block_till_done()

    post = [r for r in server.requests if r[0] == "POST"][-1]
    assert post[2] == {"template_id": 1}
    assert len(started) == 1 and started[0].data["result"] == "queued"
    assert hass.states.get(eid(hass, "binary_sensor", 1, "running")).state == "on"
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "waiting"
    assert hass.states.get(eid(hass, "button", 1, "stop")).state != "unavailable"
    assert not finished

    # Task finishes on the server; next poll reports it exactly once
    task_id = started[0].data["task_id"]
    server.finish(task_id, "success", OK_LOG, seconds=42)
    await tick(hass)
    assert len(finished) == 1
    data = finished[0].data
    assert data["task_id"] == task_id and data["result"] == "success"
    assert data["duration_seconds"] == 42 and data["duration"] == "42 s"
    assert data["recap"][0]["ok"] == 3
    assert data["title"].startswith("✅ docker-system aktualisieren")
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "success"
    assert hass.states.get(eid(hass, "binary_sensor", 1, "running")).state == "off"

    await tick(hass, 120)
    assert len(finished) == 1  # no duplicates


async def test_failure_event_contains_reason(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    await setup(hass, make_entry)
    finished = async_capture_events(hass, EVENT_TASK_FINISHED)

    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 2, "start")}, blocking=True
    )
    task_id = max(server.tasks)
    server.finish(task_id, "error", FAIL_LOG, seconds=3)
    await tick(hass)
    assert len(finished) == 1
    data = finished[0].data
    assert data["result"] == "failed" and data["success"] is False
    assert data["error"]["reason"] == "pull access denied for foo"
    assert data["error"]["failed_task"] == "Neue Images ziehen"
    assert "Fehler: pull access denied for foo" in data["text"] or "Error: pull" in data["text"]
    assert hass.states.get(eid(hass, "binary_sensor", 2, "problem")).state == "on"


async def test_dry_run_button_body(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    await setup(hass, make_entry)
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 1, "dry_run")}, blocking=True
    )
    post = [r for r in server.requests if r[0] == "POST"][-1]
    assert post[2]["dry_run"] is True and post[2]["params"] == {"dry_run": True}
    assert hass.states.get(eid(hass, "sensor", 1, "summary")).attributes["dry_run"] is True


async def test_stop_button(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.start_status = "running"
    await setup(hass, make_entry)
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 1, "start")}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 1, "stop")}, blocking=True
    )
    await hass.async_block_till_done()
    stop = [r for r in server.requests if r[1].endswith("/stop")]
    assert stop and stop[0][2] == {"force": False}
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "stopped"


# --------------------------------------------------------------------------- #
# Action
# --------------------------------------------------------------------------- #
def find_device(hass: HomeAssistant, ident: str):
    """Device of the (only) config entry by identifier."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return dr.async_get(hass).async_get_device_by_identifier((DOMAIN, ident), entry.entry_id)


def device_id_of(hass: HomeAssistant, template_id: int) -> str:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = find_device(hass, f"{entry.entry_id}_template_{template_id}")
    assert device
    return device.id


async def test_action_wait_returns_report(hass: HomeAssistant, fake, make_entry, monkeypatch) -> None:
    server, url = fake
    monkeypatch.setattr(const, "WAIT_POLL_SECONDS", 0.01)
    await setup(hass, make_entry)
    finished = async_capture_events(hass, EVENT_TASK_FINISHED)
    server.next_id = 500
    server.auto_finish[500] = (3, "success", OK_LOG)

    response = await hass.services.async_call(
        DOMAIN,
        "run_template",
        {"device_id": device_id_of(hass, 1), "wait": True, "message": "von HA"},
        blocking=True,
        return_response=True,
    )
    assert response["task_id"] == 500
    assert response["result"] == "success" and response["timed_out"] is False
    assert response["note"] == "von HA"
    assert response["recap"][0]["host"] == "dockerhost"
    assert response["text"] and response["title"]
    assert [r for r in server.requests if r[0] == "POST"][-1][2]["message"] == "von HA"
    # the coordinator reports the end as event as well (exactly once)
    assert len(finished) == 1


async def test_action_without_wait_and_errors(hass: HomeAssistant, fake, make_entry, monkeypatch) -> None:
    server, url = fake
    monkeypatch.setattr(const, "WAIT_POLL_SECONDS", 0.01)
    await setup(hass, make_entry)

    response = await hass.services.async_call(
        DOMAIN,
        "run_template",
        {"device_id": device_id_of(hass, 2), "dry_run": True, "limit": "dockerhost"},
        blocking=True,
        return_response=True,
    )
    assert response["result"] == "queued" and response["dry_run"] is True
    post = [r for r in server.requests if r[0] == "POST"][-1][2]
    assert post["limit"] == "dockerhost" and post["dry_run"] is True

    # raise_on_failure
    server.next_id = 700
    server.auto_finish[700] = (1, "error", FAIL_LOG)
    with pytest.raises(HomeAssistantError, match="pull access denied"):
        await hass.services.async_call(
            DOMAIN,
            "run_template",
            {"device_id": device_id_of(hass, 1), "wait": True, "raise_on_failure": True},
            blocking=True,
            return_response=True,
        )

    # project device / nothing selected
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    project_dev = find_device(hass, entry.entry_id)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "run_template", {"device_id": project_dev.id}, blocking=True, return_response=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "run_template", {}, blocking=True, return_response=True
        )

    # target by entity id works too
    response = await hass.services.async_call(
        DOMAIN,
        "run_template",
        {"entity_id": eid(hass, "sensor", 1, "status")},
        blocking=True,
        return_response=True,
    )
    assert response["template_id"] == 1


async def test_action_wait_timeout(hass: HomeAssistant, fake, make_entry, monkeypatch) -> None:
    server, url = fake
    monkeypatch.setattr(const, "WAIT_POLL_SECONDS", 0.05)
    server.start_status = "running"
    await setup(hass, make_entry)
    response = await hass.services.async_call(
        DOMAIN,
        "run_template",
        {"device_id": device_id_of(hass, 1), "wait": True, "timeout": 1},
        blocking=True,
        return_response=True,
    )
    assert response["timed_out"] is True and response["result"] == "running"


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #
async def test_new_template_and_stale_device(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)
    server.templates[4] = {"id": 4, "project_id": 1, "name": "Proxmox-Update", "app": "ansible"}
    del server.templates[3]
    await tick(hass)

    assert hass.states.get(eid(hass, "sensor", 4, "status")).state == "never_run"
    assert find_device(hass, f"{entry.entry_id}_template_4")
    assert find_device(hass, f"{entry.entry_id}_template_3") is None


async def test_task_displaced_by_newer_task_still_reported(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.start_status = "running"
    # two runs of one template at the same time need "Allow parallel tasks" in Semaphore
    server.templates[1]["allow_parallel_tasks"] = True
    await setup(hass, make_entry)
    finished = async_capture_events(hass, EVENT_TASK_FINISHED)
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 1, "start")}, blocking=True
    )
    first = max(server.tasks)
    # a second task starts and the first one ends before the next poll
    server.start_status = "running"
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 1, "start")}, blocking=True
    )
    server.finish(first, "success", OK_LOG)
    await tick(hass)
    assert [e.data["task_id"] for e in finished] == [first]


async def test_auth_error_triggers_reauth(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)
    server.token = "rotated"
    await tick(hass)
    assert entry.state is ConfigEntryState.LOADED  # reauth keeps entry loaded
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == SOURCE_REAUTH for f in flows)

    flow = next(f for f in flows if f["context"]["source"] == SOURCE_REAUTH)
    bad = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_API_TOKEN: "wrong"})
    assert bad["errors"] == {"base": "invalid_auth"}
    done = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_API_TOKEN: "rotated"})
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_API_TOKEN] == "rotated"
    assert entry.state is ConfigEntryState.LOADED


async def test_server_down_is_retried(hass: HomeAssistant, make_entry, fake) -> None:
    server, url = fake
    await server.close()  # nobody listens any more
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_flow_changes_interval(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval == timedelta(seconds=120)


async def test_unload(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_fallback_without_last_task_in_template_list(hass: HomeAssistant, fake, make_entry) -> None:
    """Older Semaphore versions: last tasks come from /tasks/last."""
    server, url = fake
    server.include_last_task = False
    server.add_finished_task(1, "success", OK_LOG, seconds=10)
    newest = server.add_finished_task(1, "error", FAIL_LOG, seconds=4)
    await setup(hass, make_entry)
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "error"
    attrs = hass.states.get(eid(hass, "sensor", 1, "summary")).attributes
    assert attrs["task_id"] == newest["id"] and attrs["duration_seconds"] == 4
    assert hass.states.get(eid(hass, "sensor", 2, "status")).state == "never_run"


# --------------------------------------------------------------------------- #
# Project device
# --------------------------------------------------------------------------- #
def project_eid(hass: HomeAssistant, platform: str, key: str) -> str:
    ent_reg = er.async_get(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"no project entity {platform} {key}"
    return entity_id


async def test_project_device_entities(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.add_finished_task(1, "success", OK_LOG, when=dt_util.utcnow() - timedelta(hours=3))
    failed = server.add_finished_task(
        2, "error", FAIL_LOG, seconds=3, when=dt_util.utcnow() - timedelta(hours=1)
    )
    await setup(hass, make_entry)

    assert hass.states.get(project_eid(hass, "binary_sensor", "connectivity")).state == "on"
    assert hass.states.get(project_eid(hass, "sensor", "template_count")).state == "3"
    count_attrs = hass.states.get(project_eid(hass, "sensor", "template_count")).attributes
    assert count_attrs["templates"] == ["Bash Job", "Host-Update", "docker-system aktualisieren"]

    # which template ran last, with which status
    assert hass.states.get(project_eid(hass, "sensor", "last_task_template")).state == "Host-Update"
    last_status = hass.states.get(project_eid(hass, "sensor", "last_task_status"))
    assert last_status.state == "error"
    assert last_status.attributes["task_id"] == failed["id"]
    assert last_status.attributes["error"]["reason"] == "pull access denied for foo"
    assert hass.states.get(project_eid(hass, "sensor", "last_task_started")).state != "unknown"

    # failed templates / problem
    assert hass.states.get(project_eid(hass, "sensor", "failed_templates")).state == "1"
    problem = hass.states.get(project_eid(hass, "binary_sensor", "project_problem"))
    assert problem.state == "on" and problem.attributes["templates"] == ["Host-Update"]
    assert hass.states.get(project_eid(hass, "sensor", "running_tasks")).state == "0"

    # update entity: installed 2.16.10 (v stripped) < latest 2.17.0
    update = hass.states.get(project_eid(hass, "update", "update"))
    assert update.state == "on"
    assert update.attributes["installed_version"] == "2.16.10"
    assert update.attributes["latest_version"] == "2.17.0"
    assert update.attributes["release_url"] == "https://example.test/release"
    # the Semaphore token must never be sent to GitHub
    github = [r for r in server.requests if r[0] == "GITHUB"]
    assert github and all(r[2] is None for r in github)


async def test_project_entities_follow_a_run_and_event_entity(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, url = fake
    await setup(hass, make_entry)
    tasks_event = project_eid(hass, "event", "tasks")
    assert hass.states.get(project_eid(hass, "sensor", "last_task_template")).state == "unknown"
    assert hass.states.get(project_eid(hass, "sensor", "last_task_status")).state == "never_run"

    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 1, "start")}, blocking=True
    )
    await hass.async_block_till_done()
    state = hass.states.get(tasks_event)
    assert state.attributes["event_type"] == "started"
    assert state.attributes["template"] == "docker-system aktualisieren"
    assert hass.states.get(project_eid(hass, "sensor", "running_tasks")).state == "1"
    assert hass.states.get(project_eid(hass, "sensor", "last_task_template")).state == (
        "docker-system aktualisieren"
    )
    assert hass.states.get(project_eid(hass, "sensor", "last_task_status")).state == "waiting"

    server.finish(max(server.tasks), "error", FAIL_LOG, seconds=9)
    await tick(hass)
    state = hass.states.get(tasks_event)
    assert state.attributes["event_type"] == "failed"
    assert state.attributes["title"].startswith("❌ docker-system aktualisieren")
    assert "pull access denied" in state.attributes["text"]
    assert state.attributes["duration_seconds"] == 9
    assert hass.states.get(project_eid(hass, "sensor", "running_tasks")).state == "0"
    assert hass.states.get(project_eid(hass, "binary_sensor", "project_problem")).state == "on"


async def test_connectivity_goes_off_while_other_entities_become_unavailable(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, url = fake
    await setup(hass, make_entry)
    await server.close()
    await tick(hass)
    connectivity = hass.states.get(project_eid(hass, "binary_sensor", "connectivity"))
    assert connectivity.state == "off" and connectivity.attributes["error"]
    assert connectivity.attributes["reason"] == "unreachable" and connectivity.attributes["detail"]
    assert connectivity.attributes["config_entry_id"]  # the cards link to the integration with it
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "unavailable"
    assert hass.states.get(project_eid(hass, "sensor", "template_count")).state == "unavailable"


async def test_connectivity_names_a_rejected_token_as_reason(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    server.token = "rotated"  # the token was removed / replaced in Semaphore
    await tick(hass)
    connectivity = hass.states.get(project_eid(hass, "binary_sensor", "connectivity"))
    assert connectivity.state == "off"
    assert connectivity.attributes["reason"] == "token_rejected"
    assert connectivity.attributes["config_entry_id"] == entry.entry_id


async def test_update_variants(hass: HomeAssistant, fake, make_entry) -> None:
    """Version reported by the server itself, and update check switched off."""
    server, url = fake
    server.info_update = {"tag_name": "v2.99.0", "html_url": "https://example.test/own"}
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"check_for_updates": False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    update = hass.states.get(project_eid(hass, "update", "update"))
    assert update.attributes["latest_version"] == "2.99.0"  # from /api/info, no GitHub call
    assert not [r for r in server.requests if r[0] == "GITHUB"]

    # same version -> "off"
    version_coordinator = entry.runtime_data.version_coordinator
    server.version = "2.99.0"
    await version_coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(project_eid(hass, "update", "update")).state == "off"

    # no info from the server and the check switched off -> latest version unknown
    server.info_update = None
    await version_coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(project_eid(hass, "update", "update")).attributes["latest_version"] is None
