"""Schedules of Semaphore in Home Assistant: switch, next run, "last success"."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.semaphore_ui.const import DOMAIN

from .test_flow_and_entities import FAIL_LOG, OK_LOG, eid, project_eid, setup, tick

THURSDAY_EVENING = "2026-10-29 22:10:00+00:00"


def switch_id(hass: HomeAssistant, schedule_id: int) -> str:
    """Entity id of the switch of a schedule (from the registry via its unique id)."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_{schedule_id}_schedule"
    )
    assert entity_id, f"no switch for schedule {schedule_id}"
    return entity_id


def switch_ids(hass: HomeAssistant) -> list[str]:
    return [e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), hass.config_entries.async_entries(DOMAIN)[0].entry_id) if e.domain == "switch"]


async def test_switch_per_schedule_changes_only_the_active_flag(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, "0 2 * * *", name="linux update checks", active=False)
    server.add_schedule(1, "0 6 * * MON-FRI", name="docker nightly")
    await setup(hass, make_entry)

    off, on = hass.states.get(switch_id(hass, 1)), hass.states.get(switch_id(hass, 2))
    assert off.state == "off" and on.state == "on"
    assert off.attributes["cron"] == "0 2 * * *"
    assert off.attributes["template"] == "Host-Update"
    assert "linux update checks" in off.attributes["friendly_name"]
    # the switch sits on the device of its template
    device = er.async_get(hass).async_get(switch_id(hass, 1)).device_id
    assert device == er.async_get(hass).async_get(eid(hass, "sensor", 2, "status")).device_id

    await hass.services.async_call("switch", "turn_on", {"entity_id": switch_id(hass, 1)}, blocking=True)
    await hass.async_block_till_done()
    puts = [r for r in server.requests if r[0] == "PUT"]
    assert puts == [("PUT", "/api/project/1/schedules/1/active", {"active": True})]  # nothing else is sent
    assert server.schedules[1]["active"] is True
    assert hass.states.get(switch_id(hass, 1)).state == "on"

    await hass.services.async_call("switch", "turn_off", {"entity_id": switch_id(hass, 2)}, blocking=True)
    await hass.async_block_till_done()
    assert server.schedules[2]["active"] is False
    assert hass.states.get(switch_id(hass, 2)).state == "off"


async def test_a_failing_switch_call_says_why_and_keeps_the_state(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="nightly", active=False)
    await setup(hass, make_entry)

    server.schedules_error = (500, "database is locked")
    with pytest.raises(HomeAssistantError, match="nightly.*database is locked"):
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch_id(hass, 1)}, blocking=True)
    assert hass.states.get(switch_id(hass, 1)).state == "off"


@pytest.mark.freeze_time(THURSDAY_EVENING)
async def test_next_run_sensors(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, "0 2 * * *", name="linux update checks", active=False)
    server.add_schedule(1, "0 6 * * MON-FRI", name="docker nightly")
    server.add_schedule(1, "30 4 * * *", name="second", active=False)
    await setup(hass, make_entry)

    # template 1: only the active schedule counts; template 2: all off -> unknown
    one = hass.states.get(eid(hass, "sensor", 1, "next_run"))
    assert one.state == "2026-10-30T06:00:00+00:00"
    assert one.attributes["schedule"] == "docker nightly"
    assert [s["name"] for s in one.attributes["schedules"]] == ["docker nightly", "second"]
    assert hass.states.get(eid(hass, "sensor", 2, "next_run")).state == "unknown"
    # no schedule -> no entity at all
    with pytest.raises(AssertionError):
        eid(hass, "sensor", 3, "next_run")

    project = hass.states.get(project_eid(hass, "sensor", "project_next_run"))
    assert project.state == "2026-10-30T06:00:00+00:00"
    assert project.attributes["template"] == "docker-system aktualisieren"
    assert project.attributes["timezone"] == "UTC"
    listed = {s["name"]: s for s in project.attributes["schedules"]}
    assert set(listed) == {"linux update checks", "docker nightly", "second"}
    assert listed["linux update checks"]["next_run"] is None
    assert listed["linux update checks"]["entity_id"] == switch_id(hass, 1)  # the card needs it

    # switching on makes the earlier schedule the next one
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch_id(hass, 1)}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, "sensor", 2, "next_run")).state == "2026-10-30T02:00:00+00:00"
    assert hass.states.get(project_eid(hass, "sensor", "project_next_run")).state == "2026-10-30T02:00:00+00:00"


@pytest.mark.freeze_time(THURSDAY_EVENING)
async def test_the_time_zone_of_semaphore_is_used(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.schedule_timezone = "Europe/Berlin"
    server.add_schedule(2, "0 2 * * *")
    await setup(hass, make_entry)
    # 02:00 in Berlin (UTC+1 since Oct 25) is 01:00 UTC
    assert hass.states.get(eid(hass, "sensor", 2, "next_run")).state == "2026-10-30T01:00:00+00:00"
    assert hass.states.get(eid(hass, "sensor", 2, "next_run")).attributes["timezone"] == "Europe/Berlin"


@pytest.mark.freeze_time(THURSDAY_EVENING)
async def test_without_a_reported_time_zone_utc_is_assumed(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.schedule_timezone = None  # older Semaphore
    server.add_schedule(2, "0 2 * * *")
    await setup(hass, make_entry)
    assert hass.states.get(eid(hass, "sensor", 2, "next_run")).state == "2026-10-30T02:00:00+00:00"


@pytest.mark.freeze_time(THURSDAY_EVENING)
async def test_one_time_and_odd_schedules_do_not_break_anything(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, "", name="once", type="run_at", run_at="2026-11-05T08:30:00Z")
    server.add_schedule(2, "@every 10m", name="timer")
    server.add_schedule(2, "not a cron", name="broken")
    server.add_schedule(3, "0 5 * * *", name="bash nightly", delete_after_run=True)
    await setup(hass, make_entry)

    assert hass.states.get(eid(hass, "sensor", 2, "next_run")).state == "2026-11-05T08:30:00+00:00"
    assert hass.states.get(eid(hass, "sensor", 3, "next_run")).state == "2026-10-30T05:00:00+00:00"
    states = {s.attributes["cron"]: s for s in map(hass.states.get, switch_ids(hass))}
    assert states["@every 10m"].attributes["next_run"] is None
    assert states["not a cron"].attributes["next_run"] is None  # a wrong expression does not crash
    assert states[""].attributes["type"] == "run_at"
    assert hass.states.get(switch_id(hass, 4)).attributes["delete_after_run"] is True


async def test_semaphore_without_schedules(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.schedules_error = (404, "404 page not found")
    await setup(hass, make_entry)
    assert switch_ids(hass) == []
    assert hass.states.get(project_eid(hass, "sensor", "project_next_run")).state == "unknown"
    assert hass.states.get(project_eid(hass, "sensor", "project_next_run")).attributes["schedules"] == []
    # the rest works as before
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "never_run"


async def test_schedules_that_cannot_be_read_keep_the_last_state(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="nightly")
    await setup(hass, make_entry)
    assert hass.states.get(switch_id(hass, 1)).state == "on"

    server.schedules_error = (500, "boom")
    await tick(hass)
    assert hass.states.get(switch_id(hass, 1)).state == "on"  # not unavailable because of one failed read
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state != "unavailable"


async def test_schedule_changes_and_deletion_in_semaphore(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="nightly")
    await setup(hass, make_entry)
    first = switch_id(hass, 1)

    server.schedules[1]["active"] = False  # switched off in Semaphore's own UI
    server.add_schedule(1, "0 5 * * *", name="new one")  # created there
    await tick(hass)
    assert hass.states.get(first).state == "off"
    assert hass.states.get(switch_id(hass, 2)).state == "on"
    assert hass.states.get(eid(hass, "sensor", 1, "next_run")) is not None

    del server.schedules[1]  # deleted there
    await tick(hass)
    registry = er.async_get(hass)
    assert registry.async_get(first) is None  # the switch is gone, not "unavailable" for ever
    assert hass.states.get(first) is None
    assert hass.states.get(switch_id(hass, 2)).state == "on"


async def test_switches_come_back_after_a_restart(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="nightly")
    entry = await setup(hass, make_entry)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(switch_id(hass, 1)).state == "on"
    assert len(switch_ids(hass)) == 1


# ------------------------------------------------------------------ last success
def end_of(task: dict) -> str:
    ended = datetime.fromisoformat(task["end"].replace("Z", "+00:00")).astimezone(UTC)
    return ended.replace(microsecond=0).isoformat()  # Home Assistant drops the fraction of a second


async def test_last_success_of_a_template_whose_last_run_failed(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    now = datetime.now(UTC)
    server.add_finished_task(2, "success", OK_LOG, when=now - timedelta(days=3))
    good = server.add_finished_task(2, "success", OK_LOG, when=now - timedelta(days=2))
    good["params"] = {"dry_run": True}
    server.add_finished_task(2, "error", FAIL_LOG, when=now - timedelta(hours=1))
    server.add_finished_task(1, "error", FAIL_LOG, when=now - timedelta(hours=2))  # never succeeded
    ok_last = server.add_finished_task(3, "success", OK_LOG, when=now - timedelta(minutes=30))
    await setup(hass, make_entry)

    state = hass.states.get(eid(hass, "sensor", 2, "last_success"))
    assert state.state == end_of(good)  # the newest success, not the one three days ago
    assert state.attributes["task_id"] == good["id"]
    assert state.attributes["dry_run"] is True
    assert hass.states.get(eid(hass, "sensor", 1, "last_success")).state == "unknown"
    assert hass.states.get(eid(hass, "sensor", 3, "last_success")).state == end_of(ok_last)

    history = [r[1] for r in server.requests if "/tasks/last" in r[1] and "/templates/" in r[1]]
    # only templates whose last run did not succeed need a look into the history
    assert sorted(history) == ["/api/project/1/templates/1/tasks/last", "/api/project/1/templates/2/tasks/last"]


async def test_the_history_is_read_once_per_new_last_run(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    now = datetime.now(UTC)
    server.add_finished_task(2, "success", OK_LOG, when=now - timedelta(days=1))
    server.add_finished_task(2, "error", FAIL_LOG, when=now - timedelta(hours=2))
    await setup(hass, make_entry)

    def history_calls() -> int:
        return len([r for r in server.requests if r[1].endswith("/templates/2/tasks/last")])

    assert history_calls() == 1
    await tick(hass)
    await tick(hass)
    assert history_calls() == 1  # nothing new -> no request

    again = server.add_finished_task(2, "error", FAIL_LOG, when=now - timedelta(minutes=5))
    await tick(hass)
    assert history_calls() == 2  # a new last run: look again
    assert hass.states.get(eid(hass, "sensor", 2, "last_success")).attributes["task_id"] < again["id"]

    fixed = server.add_finished_task(2, "success", OK_LOG, when=now)
    await tick(hass)
    assert history_calls() == 2  # a success is taken from the template data directly
    assert hass.states.get(eid(hass, "sensor", 2, "last_success")).attributes["task_id"] == fixed["id"]


async def test_a_run_that_is_still_running_keeps_the_last_success(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    now = datetime.now(UTC)
    good = server.add_finished_task(2, "success", OK_LOG, when=now - timedelta(days=1))
    running = server.add_finished_task(2, "running", "", when=now - timedelta(seconds=30))
    running.pop("end")
    await setup(hass, make_entry)
    assert hass.states.get(eid(hass, "sensor", 2, "last_success")).attributes["task_id"] == good["id"]

    server.finish(running["id"], "error", FAIL_LOG)
    await tick(hass)
    # the same task ended: it did not succeed, the earlier success stays
    assert hass.states.get(eid(hass, "sensor", 2, "last_success")).attributes["task_id"] == good["id"]
    assert len([r for r in server.requests if r[1].endswith("/templates/2/tasks/last")]) == 1


# --- create / change / delete schedules (actions) ---------------------------------------------------------------

from homeassistant.exceptions import ServiceValidationError  # noqa: E402

from .test_flow_and_entities import device_id_of  # noqa: E402


async def test_create_schedule_for_a_template(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    await setup(hass, make_entry)
    assert switch_ids(hass) == []

    response = await hass.services.async_call(
        DOMAIN,
        "create_schedule",
        {"device_id": device_id_of(hass, 2), "cron": " 0 3 * * 1 ", "name": "Montags"},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()

    assert response == {"schedule_id": 1, "name": "Montags"}
    posts = [r for r in server.requests if r[0] == "POST" and r[1].endswith("/schedules")]
    assert posts == [
        (
            "POST",
            "/api/project/1/schedules",
            {
                "project_id": 1,
                "template_id": 2,
                "cron_format": "0 3 * * 1",
                "name": "Montags",
                "active": True,
                "type": "",
                "delete_after_run": False,
            },
        )
    ]
    # the new schedule gets its switch (on the device of the template) with the next poll
    state = hass.states.get(switch_id(hass, 1))
    assert state.state == "on" and state.attributes["cron"] == "0 3 * * 1"


async def test_create_schedule_rejects_bad_cron_before_asking_semaphore(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    await setup(hass, make_entry)
    with pytest.raises(ServiceValidationError, match="kein gültiger Cron-Text|not a valid cron"):
        await hass.services.async_call(
            DOMAIN, "create_schedule", {"device_id": device_id_of(hass, 2), "cron": "every day"}, blocking=True
        )
    assert not [r for r in server.requests if r[0] == "POST" and r[1].endswith("/schedules")]
    assert server.schedules == {}


async def test_update_schedule_sends_the_whole_object(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, "0 2 * * *", name="nightly")
    await setup(hass, make_entry)

    await hass.services.async_call(
        DOMAIN,
        "update_schedule",
        {"entity_id": switch_id(hass, 1), "cron": "30 4 * * *", "template_id": 1, "name": "Morgens"},
        blocking=True,
    )
    await hass.async_block_till_done()

    put = [r for r in server.requests if r[0] == "PUT" and r[1] == "/api/project/1/schedules/1"]
    assert len(put) == 1
    body = put[0][2]
    assert body["id"] == 1 and body["project_id"] == 1  # Semaphore wants these in the body
    assert (body["cron_format"], body["template_id"], body["name"], body["active"]) == ("30 4 * * *", 1, "Morgens", True)
    assert "tpl_name" not in body
    state = hass.states.get(switch_id(hass, 1))
    assert state.attributes["cron"] == "30 4 * * *" and state.attributes["template"] == "docker-system aktualisieren"


async def test_update_schedule_checks_input(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="nightly")
    await setup(hass, make_entry)
    for data in ({"cron": "61 * * * *"}, {"template_id": 99}):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "update_schedule", {"entity_id": switch_id(hass, 1), **data}, blocking=True
            )
    assert not [r for r in server.requests if r[0] == "PUT"]
    # not the switch of a schedule
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "update_schedule", {"entity_id": eid(hass, "sensor", 2, "status"), "cron": "0 1 * * *"}, blocking=True
        )


async def test_delete_schedule_removes_switch_and_reports_errors(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="nightly")
    server.add_schedule(1, name="weekly")
    await setup(hass, make_entry)

    server.schedules_error = (500, "database is locked")
    with pytest.raises(HomeAssistantError, match="nightly.*database is locked"):
        await hass.services.async_call(DOMAIN, "delete_schedule", {"entity_id": switch_id(hass, 1)}, blocking=True)
    assert 1 in server.schedules

    server.schedules_error = None
    await hass.services.async_call(DOMAIN, "delete_schedule", {"entity_id": switch_id(hass, 1)}, blocking=True)
    await hass.async_block_till_done()
    assert list(server.schedules) == [2]
    assert er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{hass.config_entries.async_entries(DOMAIN)[0].entry_id}_1_schedule") is None
    assert len(switch_ids(hass)) == 1


async def test_create_one_time_schedule(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    await setup(hass, make_entry)

    await hass.services.async_call(
        DOMAIN,
        "create_schedule",
        {"device_id": device_id_of(hass, 2), "run_at": "2026-11-05T09:30:00+01:00", "delete_after_run": True, "name": "Einmal"},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()

    post = [r for r in server.requests if r[0] == "POST" and r[1].endswith("/schedules")][-1][2]
    assert post["type"] == "run_at" and post["run_at"] == "2026-11-05T08:30:00Z"  # sent as UTC
    assert post["cron_format"] == "" and post["delete_after_run"] is True
    state = hass.states.get(switch_id(hass, 1))
    assert state.attributes["type"] == "run_at" and state.attributes["delete_after_run"] is True


@pytest.mark.parametrize("data", [{}, {"cron": "0 1 * * *", "run_at": "2026-11-05T09:30:00+01:00"}])
async def test_create_needs_exactly_one_of_cron_and_run_at(hass: HomeAssistant, fake, make_entry, data) -> None:
    server, _ = fake
    await setup(hass, make_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "create_schedule", {"device_id": device_id_of(hass, 2), **data}, blocking=True)
    assert server.schedules == {}


async def test_update_turns_a_cron_schedule_into_a_one_time_one_and_back(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, "0 2 * * *", name="nightly")
    await setup(hass, make_entry)
    entity = switch_id(hass, 1)

    await hass.services.async_call(DOMAIN, "update_schedule", {"entity_id": entity, "run_at": "2026-11-05T08:30:00Z"}, blocking=True)
    await hass.async_block_till_done()
    assert (server.schedules[1]["type"], server.schedules[1]["run_at"], server.schedules[1]["cron_format"]) == ("run_at", "2026-11-05T08:30:00Z", "")

    await hass.services.async_call(DOMAIN, "update_schedule", {"entity_id": entity, "cron": "5 5 * * *"}, blocking=True)
    await hass.async_block_till_done()
    assert (server.schedules[1]["type"], server.schedules[1]["cron_format"]) == ("", "5 5 * * *")
