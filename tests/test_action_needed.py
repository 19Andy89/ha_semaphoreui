"""Entities for "something to do": the playbook prints ``HA_RESULT {...}``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.semaphore_ui.const import DOMAIN, EVENT_TASK_FINISHED
from custom_components.semaphore_ui.diagnostics import async_get_config_entry_diagnostics
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .test_flow_and_entities import OK_LOG, FAIL_LOG, eid, setup, tick

FIXTURES = Path(__file__).parent / "fixtures"
PENDING = (FIXTURES / "check_yaml.log").read_text(encoding="utf-8")  # 2 hosts x 2 updates
CLEAN = """\
TASK [Ergebnis fuer Home Assistant melden] *****
ok: [adguard] =>
    msg: 'HA_RESULT {"updates": 0, "reboot_required": false}'
PLAY RECAP *****
adguard                    : ok=1    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
"""
HOST_UPDATE = 2
OTHER = 1


def exists(hass: HomeAssistant, platform: str, template_id: int, key: str) -> bool:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return (
        er.async_get(hass).async_get_entity_id(
            platform, DOMAIN, f"{entry.entry_id}_{template_id}_{key}"
        )
        is not None
    )


def project_sensor(hass: HomeAssistant) -> Any:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_action_templates"
    )
    assert entity_id
    return hass.states.get(entity_id)


async def test_entities_only_for_templates_that_report(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)["params"] = {"dry_run": True}
    server.add_finished_task(OTHER, "success", OK_LOG)
    await setup(hass, make_entry)

    assert exists(hass, "binary_sensor", HOST_UPDATE, "needs_action")
    assert exists(hass, "sensor", HOST_UPDATE, "pending_updates")
    for template_id in (OTHER, 3):  # no marker / never run
        assert not exists(hass, "binary_sensor", template_id, "needs_action")
        assert not exists(hass, "sensor", template_id, "pending_updates")

    needs = hass.states.get(eid(hass, "binary_sensor", HOST_UPDATE, "needs_action"))
    assert needs.state == "on"
    assert needs.attributes["updates"] == 4
    assert needs.attributes["reboot_required"] is False
    assert needs.attributes["dry_run"] is True
    assert needs.attributes["explanation"] == "Pending updates: 4"
    assert set(needs.attributes["hosts"]) == {"adguard", "dockerhost"}
    assert needs.attributes["packages"] == ["libssl3", "openssl"]
    assert needs.attributes["checked_local"]
    assert needs.attributes["url"].endswith(f"/templates/{HOST_UPDATE}?t={needs.attributes['task_id']}")
    assert hass.states.get(eid(hass, "sensor", HOST_UPDATE, "pending_updates")).state == "4"

    project = project_sensor(hass)
    assert project.state == "1"
    assert project.attributes["templates"] == ["Host-Update"]
    assert project.attributes["explanation"] == "Host-Update: Pending updates: 4"
    assert project.attributes["details"][0]["hosts"] == ["adguard", "dockerhost"]
    assert project.attributes["details"][0]["template_id"] == HOST_UPDATE


async def test_clean_result_turns_it_off(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)
    await setup(hass, make_entry)
    entity = eid(hass, "binary_sensor", HOST_UPDATE, "needs_action")
    assert hass.states.get(entity).state == "on"

    server.add_finished_task(HOST_UPDATE, "success", CLEAN)
    await tick(hass)
    assert hass.states.get(entity).state == "off"
    assert hass.states.get(eid(hass, "sensor", HOST_UPDATE, "pending_updates")).state == "0"
    assert project_sensor(hass).state == "0"
    assert project_sensor(hass).attributes["templates"] == []
    assert project_sensor(hass).attributes["explanation"] is None


async def test_reboot_alone_needs_action(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(
        HOST_UPDATE,
        "success",
        "ok: [pve] =>\n    msg: 'HA_RESULT {\"updates\": 0, \"reboot_required\": true}'\n",
    )
    await setup(hass, make_entry)
    needs = hass.states.get(eid(hass, "binary_sensor", HOST_UPDATE, "needs_action"))
    assert needs.state == "on"
    assert needs.attributes["explanation"] == "Reboot required"
    assert project_sensor(hass).attributes["details"][0]["reboot_required"] is True


async def test_result_stays_while_a_new_run_is_active(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)
    await setup(hass, make_entry)
    entity = eid(hass, "binary_sensor", HOST_UPDATE, "needs_action")

    running = server.add_finished_task(HOST_UPDATE, "running", "")
    running.pop("end")
    await tick(hass)
    assert hass.states.get(entity).state == "on"  # the previous result still counts
    assert project_sensor(hass).state == "1"

    server.finish(running["id"], "success", CLEAN)
    await tick(hass)
    assert hass.states.get(entity).state == "off"


async def test_run_without_marker_makes_it_unknown(hass: HomeAssistant, fake, make_entry) -> None:
    """The last finished run decides: no marker (or a failed run) = unknown, entity stays."""
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)
    entry = await setup(hass, make_entry)
    entity = eid(hass, "binary_sensor", HOST_UPDATE, "needs_action")
    assert hass.states.get(entity).state == "on"

    server.add_finished_task(HOST_UPDATE, "error", FAIL_LOG)
    await tick(hass)
    state = hass.states.get(entity)
    assert state.state == "unknown"
    assert "updates" not in state.attributes
    assert hass.states.get(eid(hass, "sensor", HOST_UPDATE, "pending_updates")).state == "unknown"
    assert project_sensor(hass).state == "0"

    # after a restart the entity is restored even though nothing reports now
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert exists(hass, "binary_sensor", HOST_UPDATE, "needs_action")
    assert exists(hass, "sensor", HOST_UPDATE, "pending_updates")
    assert hass.states.get(eid(hass, "binary_sensor", HOST_UPDATE, "needs_action")).state == "unknown"


async def test_entities_appear_when_a_playbook_starts_reporting(
    hass: HomeAssistant, fake, make_entry
) -> None:
    server, _ = fake
    server.add_finished_task(OTHER, "success", OK_LOG)
    await setup(hass, make_entry)
    assert not exists(hass, "binary_sensor", OTHER, "needs_action")

    server.add_finished_task(OTHER, "success", PENDING)
    await tick(hass)
    assert exists(hass, "binary_sensor", OTHER, "needs_action")
    assert hass.states.get(eid(hass, "binary_sensor", OTHER, "needs_action")).state == "on"
    assert project_sensor(hass).attributes["templates"] == ["docker-system aktualisieren"]


async def test_unreadable_log_is_read_again(hass: HomeAssistant, fake, make_entry) -> None:
    """A slow server must not hide the result for good."""
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)
    server.fail_output = 1  # the first read of the log at start-up fails
    await setup(hass, make_entry)
    assert not exists(hass, "binary_sensor", HOST_UPDATE, "needs_action")

    await tick(hass)  # second attempt works
    entity = eid(hass, "binary_sensor", HOST_UPDATE, "needs_action")
    assert hass.states.get(entity).state == "on"
    assert hass.states.get(eid(hass, "sensor", HOST_UPDATE, "pending_updates")).state == "4"


async def test_log_retry_gives_up(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)
    server.fail_output = 1000
    entry = await setup(hass, make_entry)
    coordinator = entry.runtime_data
    for _ in range(8):
        await tick(hass)
    task_id = server.last_task(HOST_UPDATE)["id"]
    left = 1000 - server.fail_output
    assert coordinator._log_failed[task_id] == 5  # noqa: SLF001 - MAX_LOG_ATTEMPTS
    assert left == 5  # no more requests after that
    assert not exists(hass, "binary_sensor", HOST_UPDATE, "needs_action")


async def test_finished_event_carries_the_result(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    await setup(hass, make_entry)
    events = async_capture_events(hass, EVENT_TASK_FINISHED)
    task = server.add_finished_task(HOST_UPDATE, "success", PENDING)
    task["params"] = {"dry_run": True}
    await tick(hass)
    assert len(events) == 1
    result = events[0].data["ha_result"]
    assert result["needed"] is True and result["updates"] == 4
    assert "Pending updates: 4" in events[0].data["text"]
    # the dry run report is also the attribute of the summary sensor
    summary = hass.states.get(eid(hass, "sensor", HOST_UPDATE, "summary"))
    assert summary.attributes["ha_result"]["updates"] == 4


async def test_diagnostics_show_the_result(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)
    entry = await setup(hass, make_entry)
    assert entry.state is ConfigEntryState.LOADED
    data = await async_get_config_entry_diagnostics(hass, entry)
    by_id = {t["id"]: t for t in data["coordinator"]["templates"]}
    assert by_id[HOST_UPDATE]["ha_result"]["needed"] is True
    assert by_id[HOST_UPDATE]["ha_result"]["hosts"] == ["adguard", "dockerhost"]
    assert by_id[OTHER]["ha_result"] is None
    assert "libssl3" not in str(data)  # package names are not part of the diagnostics


async def test_deleted_template_loses_its_entities(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", PENDING)
    await setup(hass, make_entry)
    assert project_sensor(hass).state == "1"
    del server.templates[HOST_UPDATE]
    await tick(hass)
    assert project_sensor(hass).state == "0"


async def test_texts_follow_the_language(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    hass.config.language = "de"
    server.add_finished_task(
        HOST_UPDATE,
        "success",
        "ok: [pve] =>\n    msg: 'HA_RESULT {\"updates\": 3, \"reboot_required\": true}'\n",
    )
    await setup(hass, make_entry)
    needs = hass.states.get(eid(hass, "binary_sensor", HOST_UPDATE, "needs_action"))
    assert needs.attributes["explanation"] == "Offene Updates: 3 · Neustart nötig"
    assert needs.name == "Host-Update Handlungsbedarf"
    assert project_sensor(hass).name == "Semaphore – Homelab Templates mit Handlungsbedarf"


NOTES = (FIXTURES / "notes_yaml.log").read_text(encoding="utf-8")


async def test_notes_end_up_in_the_attributes(hass: HomeAssistant, fake, make_entry) -> None:
    """A hint alone (e.g. "Debian 13 is out") is shown, but is no action."""
    server, _ = fake
    server.add_finished_task(HOST_UPDATE, "success", NOTES)
    await setup(hass, make_entry)

    needs = hass.states.get(eid(hass, "binary_sensor", HOST_UPDATE, "needs_action"))
    assert needs.state == "off"
    notes = needs.attributes["notes"]
    assert [n["host"] for n in notes] == ["adguard", "dockerhost"]
    assert "Distributionsupgrade prüfen" in notes[0]["text"]
    assert project_sensor(hass).state == "0"
