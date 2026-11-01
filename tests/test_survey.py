"""Survey variables: pure logic and the Home Assistant entities / action."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.semaphore_ui.const import DOMAIN, EVENT_TASK_FINISHED
from custom_components.semaphore_ui.survey import (
    SurveyError,
    build_survey_payload,
    parse_survey_vars,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events

from .fake_semaphore import FakeSemaphore
from .test_flow_and_entities import OK_LOG, eid, setup, tick

TEMPLATE = FakeSemaphore().survey_template


# --------------------------------------------------------------------------- #
# Pure logic
# --------------------------------------------------------------------------- #
def test_parse_survey_vars() -> None:
    variables = {v.name: v for v in parse_survey_vars(TEMPLATE)}
    assert list(variables) == ["target", "count", "stage", "tags", "token"]
    assert variables["target"].default == ("dockerhost",) and variables["target"].required
    assert variables["stage"].labels == ["Produktion", "Test"]
    assert variables["tags"].is_multi and variables["tags"].default == ("a",)
    assert variables["token"].is_secret
    assert parse_survey_vars({}) == []
    assert parse_survey_vars({"survey_vars": [{"title": "no name"}, "junk"]}) == []


def test_payload_defaults_and_coercion() -> None:
    variables = parse_survey_vars(TEMPLATE)
    env, secret = build_survey_payload(
        variables, {"stage": "Test", "count": 5.0, "token": "pw", "tags": "a, b"}
    )
    assert env == {"target": "dockerhost", "count": "5", "stage": "test", "tags": ["a", "b"]}
    assert secret == {"token": "pw"}

    # value given instead of label, list given for select, default for select
    env, _ = build_survey_payload(variables, {"stage": "prod", "token": "x", "tags": ["b"]})
    assert env["stage"] == "prod" and env["tags"] == ["b"]
    env, _ = build_survey_payload(variables, {"stage": "prod", "token": "x"})
    assert env["tags"] == ["a"]  # default of the select


def test_payload_errors() -> None:
    variables = parse_survey_vars(TEMPLATE)
    with pytest.raises(SurveyError) as err:
        build_survey_payload(variables, {})
    assert err.value.missing == ["stage", "token"]
    assert "token (secret: only via the action)" in str(err.value)

    with pytest.raises(SurveyError) as err:
        build_survey_payload(
            variables,
            {"stage": "nope", "token": "x", "count": "abc", "tags": ["zzz"], "typo": 1},
        )
    assert set(err.value.invalid) == {"stage", "count", "tags"}
    assert err.value.unknown == ["typo"]
    assert "known: target, count, stage, tags, token" in str(err.value)

    # booleans are no integers; negative integers are fine
    with pytest.raises(SurveyError):
        build_survey_payload(variables, {"stage": "prod", "token": "x", "count": True})
    env, _ = build_survey_payload(variables, {"stage": "prod", "token": "x", "count": -3})
    assert env["count"] == "-3"

    # no survey at all: everything passes through as "nothing to send"
    assert build_survey_payload([], None) == ({}, {})


# --------------------------------------------------------------------------- #
# Home Assistant
# --------------------------------------------------------------------------- #
def survey_eid(hass: HomeAssistant, platform: str, template_id: int, name: str) -> str | None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{template_id}_survey_{name}"
    )


def without_secret(template: dict) -> dict:
    template = deepcopy(template)
    template["survey_vars"] = [v for v in template["survey_vars"] if v["type"] != "secret"]
    return template


async def test_survey_entities_and_start_button(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.templates[4] = without_secret(server.survey_template)
    await setup(hass, make_entry)

    # string -> text (default), int -> number, enum -> select; multi select has none
    text_id = survey_eid(hass, "text", 4, "target")
    number_id = survey_eid(hass, "number", 4, "count")
    select_id = survey_eid(hass, "select", 4, "stage")
    assert text_id and number_id and select_id
    assert survey_eid(hass, "select", 4, "tags") is None
    assert hass.states.get(text_id).state == "dockerhost"
    assert hass.states.get(text_id).attributes["required"] is True
    assert hass.states.get(text_id).attributes["description"] == "Auf welchen Host"
    assert hass.states.get(number_id).state == "unknown"
    assert hass.states.get(select_id).state == "unknown"
    assert hass.states.get(select_id).attributes["options"] == ["Produktion", "Test"]
    assert hass.states.get(text_id).attributes["friendly_name"] == "Deploy Ziel-Host"
    assert er.async_get(hass).async_get(text_id).entity_category.value == "config"

    # a required enum without a value stops the start with a clear message
    with pytest.raises(ServiceValidationError, match="missing: stage"):
        await hass.services.async_call(
            "button", "press", {"entity_id": eid(hass, "button", 4, "start")}, blocking=True
        )
    assert not [r for r in server.requests if r[0] == "POST"]

    await hass.services.async_call("text", "set_value", {"entity_id": text_id, "value": "pi"}, blocking=True)
    await hass.services.async_call("number", "set_value", {"entity_id": number_id, "value": 5}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": select_id, "option": "Test"}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 4, "start")}, blocking=True
    )
    body = [r for r in server.requests if r[0] == "POST"][-1][2]
    assert json.loads(body["environment"]) == {
        "target": "pi",
        "count": "5",
        "stage": "test",
        "tags": ["a"],
    }
    assert "secret" not in body

    # the report shows the parameters the task was started with
    finished = async_capture_events(hass, EVENT_TASK_FINISHED)
    server.finish(max(server.tasks), "success", OK_LOG)
    await tick(hass)
    data = finished[0].data
    assert data["parameters"] == {"target": "pi", "count": "5", "stage": "test", "tags": ["a"]}
    assert "target=pi" in data["text"]


async def test_survey_values_are_restored(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.templates[4] = without_secret(server.survey_template)
    mock_restore_cache(
        hass,
        [
            State("text.deploy_ziel_host", "restored-host"),
            State("number.deploy_anzahl", "7.0"),
            State("select.deploy_stufe", "Produktion"),
        ],
    )
    await setup(hass, make_entry)
    assert hass.states.get("text.deploy_ziel_host").state == "restored-host"
    assert hass.states.get("number.deploy_anzahl").state == "7"
    assert hass.states.get("select.deploy_stufe").state == "Produktion"
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", 4, "start")}, blocking=True
    )
    body = json.loads([r for r in server.requests if r[0] == "POST"][-1][2]["environment"])
    assert body["target"] == "restored-host" and body["count"] == "7" and body["stage"] == "prod"


async def test_action_with_survey(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.templates[4] = deepcopy(server.survey_template)
    await setup(hass, make_entry)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_template_4"), entry.entry_id
    )

    response = await hass.services.async_call(
        DOMAIN,
        "run_template",
        {
            "device_id": device.id,
            "survey": {"stage": "Test", "token": "s3cret", "tags": ["a", "b"], "count": 3},
        },
        blocking=True,
        return_response=True,
    )
    body = [r for r in server.requests if r[0] == "POST"][-1][2]
    assert json.loads(body["environment"]) == {
        "target": "dockerhost",  # default of the template
        "count": "3",
        "stage": "test",
        "tags": ["a", "b"],
    }
    assert json.loads(body["secret"]) == {"token": "s3cret"}
    # secrets are never part of the report
    assert "s3cret" not in json.dumps(response)
    assert response["parameters"]["stage"] == "test"

    # button cannot supply the required secret -> clear message
    with pytest.raises(ServiceValidationError, match="secret: only via the action"):
        await hass.services.async_call(
            "button", "press", {"entity_id": eid(hass, "button", 4, "start")}, blocking=True
        )

    for survey, message in (
        ({"stage": "Test", "token": "x", "typo": 1}, "unknown: typo"),
        ({"stage": "Test", "token": "x", "count": "abc"}, "count"),
        ({"stage": "Gibts nicht", "token": "x"}, "stage"),
        ({}, "missing: stage, token"),
    ):
        with pytest.raises(ServiceValidationError, match=message):
            await hass.services.async_call(
                DOMAIN,
                "run_template",
                {"device_id": device.id, "survey": survey},
                blocking=True,
                return_response=True,
            )


async def test_survey_entities_follow_template_changes(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    server.templates[4] = without_secret(server.survey_template)
    await setup(hass, make_entry)
    assert survey_eid(hass, "number", 4, "count")

    # variable removed, new one added in Semaphore
    template = server.templates[4]
    template["survey_vars"] = [v for v in template["survey_vars"] if v["name"] != "count"]
    template["survey_vars"].append({"name": "reason", "title": "Grund", "type": "text"})
    await tick(hass)
    assert survey_eid(hass, "number", 4, "count") is None
    assert survey_eid(hass, "text", 4, "reason")
    assert hass.states.get("number.deploy_anzahl") is None

    # enum values changed -> options follow without a reload
    template["survey_vars"][1]["values"].append({"name": "Dev", "value": "dev"})
    await tick(hass, 120)
    assert "Dev" in hass.states.get(survey_eid(hass, "select", 4, "stage")).attributes["options"]
