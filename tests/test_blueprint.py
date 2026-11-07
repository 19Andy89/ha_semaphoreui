"""The automation blueprint that ships with the repository (``blueprints/``)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

BLUEPRINT = Path(__file__).parents[1] / "blueprints" / "automation" / "ha_semaphoreui" / "notify_task_result.yaml"


class _Loader(yaml.SafeLoader):
    """Home Assistant's YAML knows ``!input``; for the test it is a marker."""


_Loader.add_constructor("!input", lambda loader, node: {"__input__": loader.construct_scalar(node)})


def _load() -> dict:
    return yaml.load(BLUEPRINT.read_text(encoding="utf-8"), _Loader)  # noqa: S506 - own file, own loader


def test_blueprint_is_complete() -> None:
    data = _load()
    blueprint = data["blueprint"]
    assert blueprint["domain"] == "automation"
    # Home Assistant knows only these keys under "blueprint" ("min_version" belongs under "homeassistant")
    assert set(blueprint) <= {"name", "description", "domain", "author", "source_url", "homeassistant", "input"}
    assert set(blueprint["homeassistant"]) == {"min_version"}
    assert blueprint["source_url"].endswith("blueprints/automation/ha_semaphoreui/notify_task_result.yaml")
    inputs = set(blueprint["input"])
    # every !input points to an input that exists
    used = {
        value["__input__"]
        for section in ("variables", "actions")
        for value in _walk(data[section])
        if isinstance(value, dict) and "__input__" in value
    }
    assert used <= inputs
    assert data["triggers"][0]["event_type"] == "semaphore_ui_task_finished"


def _walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _event(result: str = "success", *, needed: bool | None = None, dry_run: bool = False, template: str = "docker") -> dict:
    ha_result = None if needed is None else {"needed": needed}
    return {"event": {"data": {"result": result, "ha_result": ha_result, "dry_run": dry_run, "template": template}}}


@pytest.mark.parametrize(
    ("when", "event", "include_dry_runs", "only", "expected"),
    [
        ("failed", _event("failed"), True, [], True),
        ("failed", _event("success", needed=True), True, [], False),
        ("failed", _event("success"), True, [], False),
        ("problems", _event("success", needed=True), True, [], True),
        ("problems", _event("success", needed=False), True, [], False),
        ("problems", _event("success"), True, [], False),
        ("problems", _event("failed"), True, [], True),
        ("all", _event("success"), True, [], True),
        ("all", _event("stopped"), True, [], True),
        ("failed", _event("stopped"), True, [], False),
        ("problems", _event("stopped"), True, [], False),
        ("all", _event("success", dry_run=True), False, [], False),
        ("all", _event("success", dry_run=True), True, [], True),
        ("all", _event("failed", template="proxmox"), True, ["docker"], False),
        ("all", _event("failed", template="docker"), True, ["docker"], True),
    ],
)
async def test_condition(hass: HomeAssistant, when, event, include_dry_runs, only, expected) -> None:
    condition = _load()["conditions"][0]["value_template"]
    variables = {"when": when, "include_dry_runs": include_dry_runs, "only_templates": only, "trigger": event}
    assert Template(condition, hass).async_render(variables) is expected
