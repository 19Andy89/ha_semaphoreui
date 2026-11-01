"""0.2.1: which templates are shown in Home Assistant (option "Templates")."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.semaphore_ui.const import (
    CONF_EXCLUDED_TEMPLATES,
    CONF_TEMPLATES,
    DOMAIN,
)
from custom_components.semaphore_ui.coordinator import template_identifier
from custom_components.semaphore_ui.diagnostics import async_get_config_entry_diagnostics

from .test_flow_and_entities import project_eid, setup, tick
from .test_schedules import switch_ids


def template_devices(hass: HomeAssistant, entry) -> set[int]:
    """Template ids that have a device."""
    registry = dr.async_get(hass)
    return {
        tid
        for tid in (1, 2, 3, 4, 7)
        if registry.async_get_device_by_identifier(template_identifier(entry.entry_id, tid), entry.entry_id)
    }


def field(result, key: str):
    """The marker of a form field (to read its default)."""
    return next(marker for marker in result["data_schema"].schema if marker.schema == key)


async def save_templates(hass: HomeAssistant, entry, shown: list[str], **more):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TEMPLATES: shown, **more}
    )
    await hass.async_block_till_done()
    return result


async def test_options_list_every_template_and_all_are_ticked_at_first(hass: HomeAssistant, fake, make_entry) -> None:
    entry = await setup(hass, make_entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    options = result["data_schema"].schema[CONF_TEMPLATES].config["options"]
    assert [o["label"] for o in options] == ["Bash Job", "docker-system aktualisieren", "Host-Update"]  # sorted by name
    assert sorted(field(result, CONF_TEMPLATES).default()) == ["1", "2", "3"]  # nothing excluded yet


async def test_unticked_templates_get_no_devices_and_come_back_when_ticked(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="host nightly")
    server.add_schedule(3, name="bash nightly")
    entry = await setup(hass, make_entry)
    assert template_devices(hass, entry) == {1, 2, 3}
    assert len(switch_ids(hass)) == 2

    result = await save_templates(hass, entry, ["1", "2"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXCLUDED_TEMPLATES] == [3]
    assert entry.state is ConfigEntryState.LOADED
    # no device, no entity, no schedule switch for "Bash Job" - and nothing is left behind in the registries
    assert template_devices(hass, entry) == {1, 2}
    registry = er.async_get(hass)
    assert not [e for e in er.async_entries_for_config_entry(registry, entry.entry_id) if e.unique_id.startswith(f"{entry.entry_id}_3_")]
    assert len(switch_ids(hass)) == 1
    # the project knows what it shows and what it leaves out
    count = hass.states.get(project_eid(hass, "sensor", "template_count"))
    assert count.state == "2"
    assert count.attributes["templates"] == ["Host-Update", "docker-system aktualisieren"]
    assert count.attributes["excluded"] == ["Bash Job"]
    # the schedule of the left-out template is not the "next scheduled run" of the project
    schedules = hass.states.get(project_eid(hass, "sensor", "project_next_run")).attributes["schedules"]
    assert [s["name"] for s in schedules] == ["host nightly"]

    # the dialog shows the choice again: 3 is not ticked
    again = await hass.config_entries.options.async_init(entry.entry_id)
    assert sorted(field(again, CONF_TEMPLATES).default()) == ["1", "2"]
    hass.config_entries.options.async_abort(again["flow_id"])

    await save_templates(hass, entry, ["1", "2", "3"])
    assert entry.options[CONF_EXCLUDED_TEMPLATES] == []
    assert template_devices(hass, entry) == {1, 2, 3}
    assert len(switch_ids(hass)) == 2
    assert hass.states.get(project_eid(hass, "sensor", "template_count")).state == "3"


async def test_new_templates_of_semaphore_still_show_up(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    await save_templates(hass, entry, ["1"])  # only docker-system
    assert template_devices(hass, entry) == {1}

    server.templates[7] = {"id": 7, "project_id": 1, "name": "Neu", "app": "ansible"}
    await tick(hass)
    assert template_devices(hass, entry) == {1, 7}  # not excluded: it appears as usual
    assert entry.options[CONF_EXCLUDED_TEMPLATES] == [2, 3]


async def test_at_least_one_template_must_stay_ticked(hass: HomeAssistant, fake, make_entry) -> None:
    entry = await setup(hass, make_entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    bad = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_TEMPLATES: []})
    assert bad["type"] is FlowResultType.FORM
    assert bad["errors"] == {"base": "no_templates"}
    assert field(bad, CONF_TEMPLATES).default() == []  # shows what was typed
    good = await hass.config_entries.options.async_configure(bad["flow_id"], {CONF_TEMPLATES: ["2"]})
    assert good["type"] is FlowResultType.CREATE_ENTRY
    assert good["data"][CONF_EXCLUDED_TEMPLATES] == [1, 3]


async def test_other_options_do_not_lose_the_choice_and_ids_that_are_gone_are_dropped(hass: HomeAssistant, fake, make_entry) -> None:
    entry = make_entry({CONF_EXCLUDED_TEMPLATES: [3, 99]})  # 99: deleted in Semaphore long ago
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert template_devices(hass, entry) == {1, 2}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert sorted(field(result, CONF_TEMPLATES).default()) == ["1", "2"]
    # "send the form as shown": interval changed, choice untouched
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 90})
    await hass.async_block_till_done()
    assert result["data"]["scan_interval"] == 90
    assert result["data"][CONF_EXCLUDED_TEMPLATES] == [3]  # 99 does not exist any more
    assert template_devices(hass, entry) == {1, 2}


async def test_without_a_connection_the_choice_is_not_offered_and_stays(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.raw_answer = (500, "boom")  # Semaphore is down while Home Assistant starts
    entry = make_entry({CONF_EXCLUDED_TEMPLATES: [3]})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert CONF_TEMPLATES not in {marker.schema for marker in result["data_schema"].schema}
    saved = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 45})
    assert saved["data"]["scan_interval"] == 45
    assert saved["data"][CONF_EXCLUDED_TEMPLATES] == [3]  # the choice is not lost


async def test_two_templates_with_the_same_name_are_told_apart(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.templates[7] = {"id": 7, "project_id": 1, "name": "Host-Update", "app": "ansible"}
    entry = await setup(hass, make_entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    labels = [o["label"] for o in result["data_schema"].schema[CONF_TEMPLATES].config["options"]]
    assert "Host-Update (#2)" in labels and "Host-Update (#7)" in labels
    assert "Bash Job" in labels  # unique names stay as they are


async def test_diagnostics_tell_what_is_left_out(hass: HomeAssistant, fake, make_entry) -> None:
    entry = await setup(hass, make_entry)
    await save_templates(hass, entry, ["1", "2"])
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["coordinator"]["templates_in_project"] == 3
    assert diagnostics["coordinator"]["excluded_templates"] == [3]
    assert [t["id"] for t in diagnostics["coordinator"]["templates"]] == [1, 2]
