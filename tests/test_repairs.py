"""0.2.1: Repairs - problems the user has to fix show up under Settings -> Repairs."""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path

import pytest

from homeassistant.config_entries import ConfigEntryState, SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.semaphore_ui.const import (
    CONF_API_TOKEN,
    DOMAIN,
    ISSUE_PROJECT,
    ISSUE_TOKEN,
    ISSUE_UNREACHABLE,
    REPAIR_AFTER,
)
from custom_components.semaphore_ui.issues import issue_id

from .test_flow_and_entities import eid, setup, tick
from .test_schedules import switch_id

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "semaphore_ui"
LONGER_THAN_THE_LIMIT = timedelta(seconds=REPAIR_AFTER + 60)


def issue(hass: HomeAssistant, kind: str, entry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(kind, entry.entry_id))


def all_issues(hass: HomeAssistant) -> list[str]:
    return sorted(i for d, i in ir.async_get(hass).issues if d == DOMAIN)


async def open_fix_flow(hass: HomeAssistant, entry, kind: str = ISSUE_TOKEN):
    assert await async_setup_component(hass, "repairs", {})
    manager = hass.data["repairs"]["flow_manager"]
    return manager, await manager.async_init(
        DOMAIN, context={"issue_id": issue_id(kind, entry.entry_id)}
    )


# --------------------------------------------------------------------------- #
# Token rejected: reported at once, fixable in the repair dialog
# --------------------------------------------------------------------------- #
async def test_a_rejected_token_is_reported_at_once_and_fixed_in_the_dialog(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    assert all_issues(hass) == []

    server.token = "rotated"  # the token was replaced in Semaphore
    await tick(hass)
    found = issue(hass, ISSUE_TOKEN, entry)
    assert found is not None and found.is_fixable
    assert found.severity is ir.IssueSeverity.ERROR
    assert found.translation_key == "token_rejected"
    assert found.translation_placeholders["project"] == "Homelab"
    assert found.data == {"entry_id": entry.entry_id}
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "unavailable"
    reauth = [f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == SOURCE_REAUTH]
    assert len(reauth) == 1  # Home Assistant asks for the token in its own way, too

    manager, result = await open_fix_flow(hass, entry)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "init"
    bad = await manager.async_configure(result["flow_id"], {CONF_API_TOKEN: "still-wrong"})
    assert bad["type"] is FlowResultType.FORM and bad["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_API_TOKEN] != "still-wrong"  # a token that does not work is not saved
    assert issue(hass, ISSUE_TOKEN, entry) is not None

    done = await manager.async_configure(bad["flow_id"], {CONF_API_TOKEN: "  rotated "})
    await hass.async_block_till_done()
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_API_TOKEN] == "rotated"  # trimmed
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state != "unavailable"
    assert all_issues(hass) == []
    # the "re-authenticate" request is obsolete, too
    assert not [f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == SOURCE_REAUTH]


async def test_a_token_without_access_to_the_project_is_explained(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    server.token = "rotated"
    await tick(hass)
    manager, result = await open_fix_flow(hass, entry)
    server.projects = [{"id": 2, "name": "Other"}]  # the new token may not see project 1
    bad = await manager.async_configure(result["flow_id"], {CONF_API_TOKEN: "rotated"})
    assert bad["errors"] == {"base": "project_not_found"}


async def test_the_fix_flow_survives_a_removed_entry(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    server.token = "rotated"
    await tick(hass)
    manager, result = await open_fix_flow(hass, entry)
    await hass.config_entries.async_remove(entry.entry_id)
    again = await manager.async_configure(result["flow_id"], {CONF_API_TOKEN: "x"})
    assert again["type"] is FlowResultType.ABORT and again["reason"] == "entry_missing"


async def test_a_rejected_token_in_an_action_is_reported_and_readable(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_schedule(2, name="nightly")
    entry = await setup(hass, make_entry)
    server.token = "rotated"
    for domain, service, target in (
        ("button", "press", eid(hass, "button", 2, "start")),
        ("switch", "turn_off", switch_id(hass, 1)),
    ):
        with pytest.raises(HomeAssistantError) as raised:
            await hass.services.async_call(domain, service, {"entity_id": target}, blocking=True)
        assert raised.value.translation_key == "auth_failed"  # a message, not a stack trace
        assert issue(hass, ISSUE_TOKEN, entry) is not None
        ir.async_delete_issue(hass, DOMAIN, issue_id(ISSUE_TOKEN, entry.entry_id))


# --------------------------------------------------------------------------- #
# Semaphore does not answer / project gone: only after a longer outage
# --------------------------------------------------------------------------- #
async def test_an_outage_is_reported_after_ten_minutes_and_disappears_with_it(hass: HomeAssistant, fake, make_entry, freezer) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)

    server.raw_answer = (502, "Bad Gateway")  # e.g. the reverse proxy: Semaphore is restarting
    freezer.tick(timedelta(seconds=60))
    await tick(hass)
    freezer.tick(timedelta(minutes=5))
    await tick(hass)
    assert all_issues(hass) == []  # a restart of Semaphore is not worth a repair

    freezer.tick(timedelta(minutes=6))
    await tick(hass)
    found = issue(hass, ISSUE_UNREACHABLE, entry)
    assert found is not None and not found.is_fixable
    assert found.severity is ir.IssueSeverity.WARNING
    assert "502" in found.translation_placeholders["detail"]
    assert found.translation_placeholders["url"] == url
    assert found.translation_placeholders["since"]  # when it started
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state == "unavailable"

    server.raw_answer = None  # Semaphore is back
    freezer.tick(timedelta(seconds=60))
    await tick(hass)
    assert all_issues(hass) == []
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state != "unavailable"


async def test_a_short_outage_leaves_no_repair_behind(hass: HomeAssistant, fake, make_entry, freezer) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    server.raw_answer = (500, "boom")
    freezer.tick(timedelta(minutes=8))
    await tick(hass)
    server.raw_answer = None
    freezer.tick(timedelta(minutes=8))  # 16 minutes after the start, but the outage was interrupted
    await tick(hass)
    server.raw_answer = (500, "boom")
    freezer.tick(timedelta(minutes=2))
    await tick(hass)  # a new series: 2 minutes old
    assert all_issues(hass) == []
    assert entry.state is ConfigEntryState.LOADED


async def test_a_vanished_project_is_reported_as_such(hass: HomeAssistant, fake, make_entry, freezer) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    server.raw_answer = (404, "Not Found")
    freezer.tick(LONGER_THAN_THE_LIMIT)
    await tick(hass)
    freezer.tick(LONGER_THAN_THE_LIMIT)
    await tick(hass)
    found = issue(hass, ISSUE_PROJECT, entry)
    assert found is not None and not found.is_fixable
    assert found.severity is ir.IssueSeverity.ERROR
    assert found.translation_placeholders["detail"] == "HTTP 404"
    assert issue(hass, ISSUE_UNREACHABLE, entry) is None

    # 403: the token may not see the project - the same repair
    server.raw_answer = (403, "Forbidden")
    freezer.tick(timedelta(seconds=60))
    await tick(hass)
    assert issue(hass, ISSUE_PROJECT, entry).translation_placeholders["detail"] == "HTTP 403"

    # another kind of problem replaces the first one (and starts counting again)
    server.raw_answer = (503, "unavailable")
    freezer.tick(timedelta(seconds=60))
    await tick(hass)
    assert issue(hass, ISSUE_PROJECT, entry) is None and issue(hass, ISSUE_UNREACHABLE, entry) is None
    freezer.tick(LONGER_THAN_THE_LIMIT)
    await tick(hass)
    assert issue(hass, ISSUE_UNREACHABLE, entry) is not None


async def test_the_outage_is_counted_across_setup_retries(hass: HomeAssistant, fake, make_entry, freezer) -> None:
    """While Semaphore is down at start-up Home Assistant retries the setup with a new coordinator each time."""
    server, _ = fake
    server.raw_answer = (502, "Bad Gateway")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert all_issues(hass) == []

    freezer.tick(LONGER_THAN_THE_LIMIT)
    await hass.config_entries.async_reload(entry.entry_id)  # the next attempt
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert issue(hass, ISSUE_UNREACHABLE, entry) is not None

    server.raw_answer = None
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert all_issues(hass) == []


async def test_removing_the_project_removes_its_repairs(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    server.token = "rotated"
    await tick(hass)
    assert issue(hass, ISSUE_TOKEN, entry) is not None
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert all_issues(hass) == []


async def test_a_problem_of_one_project_does_not_touch_another(hass: HomeAssistant, fake, make_entry) -> None:
    first = await setup(hass, make_entry)
    ir.async_create_issue(
        hass, DOMAIN, issue_id(ISSUE_TOKEN, "some-other-entry"), is_fixable=True,
        severity=ir.IssueSeverity.ERROR, translation_key=ISSUE_TOKEN,
    )
    await tick(hass)  # a successful poll of the first entry
    assert issue_id(ISSUE_TOKEN, "some-other-entry") in all_issues(hass)  # not its business
    assert first.state is ConfigEntryState.LOADED


# --------------------------------------------------------------------------- #
# Texts
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["de", "en"])
def test_every_repair_has_a_title_and_texts_with_known_placeholders(language: str) -> None:
    texts = json.loads((COMPONENT_DIR / "translations" / f"{language}.json").read_text())
    issues = texts["issues"]
    assert set(issues) == {ISSUE_TOKEN, ISSUE_UNREACHABLE, ISSUE_PROJECT}
    values = {"project": "P", "url": "U", "detail": "D", "since": "S"}
    for key, item in issues.items():
        assert item["title"] and item["description"], key
        item["description"].format(**values)  # KeyError = a placeholder nobody fills in
    flow = issues[ISSUE_TOKEN]["fix_flow"]
    assert flow["step"]["init"]["data"]["api_token"]
    flow["step"]["init"]["description"].format(**values)
    assert set(flow["error"]) >= {"invalid_auth", "project_not_found", "cannot_connect", "unknown"}
    for text in [*flow["error"].values(), *flow["abort"].values()]:
        text.format(**values)
    # the options dialog
    options = texts["options"]
    assert options["step"]["init"]["data"]["templates"] and options["step"]["init"]["data_description"]["templates"]
    assert options["error"]["no_templates"]
