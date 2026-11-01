"""Feedback of the first real installation: readable setup errors, version compare,
failure attributes of the problem sensors and the card resource."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp.client_reqrep import ConnectionKey
import pytest

from custom_components.semaphore_ui import cards, const
from custom_components.semaphore_ui.api import (
    SemaphoreApiError,
    SemaphoreAuthError,
    SemaphoreClient,
    SemaphoreConnectionError,
    classify_connection_error,
)
from custom_components.semaphore_ui.config_flow import _placeholders, describe_error
from custom_components.semaphore_ui.const import CONF_API_TOKEN, DOMAIN
from custom_components.semaphore_ui.coordinator import _clean_version
from custom_components.semaphore_ui.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from .fake_semaphore import TOKEN
from .test_flow_and_entities import (
    FAIL_LOG,
    OK_LOG,
    eid,
    project_eid,
    setup,
    tick,
)

KEY = ConnectionKey("semaphore.example.invalid", 3000, False, True, None, None, None, None)
URL = "http://semaphore.example.invalid:3000"
COMPONENT_DIR = Path(cards.__file__).parent


# --------------------------------------------------------------------------- #
# Setup errors: the dialog says what is wrong
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (aiohttp.ClientConnectorDNSError(KEY, socket.gaierror(-2, "Name or service not known")), "dns"),
        (aiohttp.ClientConnectorError(KEY, ConnectionRefusedError(111, "Connection refused")), "refused"),
        (aiohttp.ClientConnectorError(KEY, TimeoutError()), "timeout"),
        (aiohttp.ClientConnectorError(KEY, OSError(113, "No route to host")), "unreachable"),
        (aiohttp.ClientConnectorCertificateError(KEY, ssl.SSLCertVerificationError("self-signed certificate")), "ssl"),
        (aiohttp.ClientConnectorSSLError(KEY, ssl.SSLError("wrong version number")), "ssl"),
        (aiohttp.InvalidURL("http://bad:port"), "invalid_url"),
        (aiohttp.ServerDisconnectedError(), "disconnected"),
        (OSError(101, "Network is unreachable"), "unreachable"),
        (aiohttp.ClientError("boom"), "connection"),
    ],
)
def test_connection_errors_are_classified(error: BaseException, kind: str) -> None:
    result = classify_connection_error(error, URL)
    assert isinstance(result, SemaphoreConnectionError)
    assert result.kind == kind
    assert result.detail
    if kind in ("dns", "refused", "timeout", "unreachable") and isinstance(error, aiohttp.ClientConnectorError):
        assert result.host == "semaphore.example.invalid"


def test_describe_error_maps_every_case_to_a_dialog_text() -> None:
    def key(err, **kw):
        return describe_error(err, URL, **kw)[0]

    assert key(SemaphoreAuthError("x")) == "invalid_auth"
    assert key(SemaphoreConnectionError("d", kind="dns", host="h")) == "cannot_resolve"
    assert key(SemaphoreConnectionError("d", kind="refused")) == "connection_refused"
    assert key(SemaphoreConnectionError("d", kind="timeout")) == "timeout"
    assert key(SemaphoreConnectionError("d", kind="ssl")) == "ssl_error"
    assert key(SemaphoreConnectionError("d", kind="unreachable")) == "host_unreachable"
    assert key(SemaphoreConnectionError("d", kind="invalid_url")) == "invalid_url"
    assert key(SemaphoreConnectionError("d", kind="disconnected")) == "connection_lost"
    assert key(SemaphoreConnectionError("d")) == "cannot_connect"
    assert key(SemaphoreApiError(200, "Answer is not JSON: <html>", kind="not_json")) == "not_semaphore"
    assert key(SemaphoreApiError(404, "Not Found")) == "not_semaphore"
    assert key(SemaphoreApiError(404, "Not Found"), project_call=True) == "project_not_found"
    assert key(SemaphoreApiError(500, "boom")) == "http_error"
    assert key(ValueError("odd")) == "unknown"  # type: ignore[arg-type]


@pytest.mark.parametrize("language", ["de", "en"])
def test_every_error_text_exists_and_its_placeholders_are_filled(language: str) -> None:
    errors = json.loads((COMPONENT_DIR / "translations" / f"{language}.json").read_text())["config"]["error"]
    keys = {
        "cannot_connect", "cannot_resolve", "connection_refused", "timeout", "ssl_error",
        "host_unreachable", "connection_lost", "invalid_url", "not_semaphore", "http_error",
        "project_not_found", "invalid_auth", "no_projects", "unknown",
    }
    assert keys <= set(errors)
    values = _placeholders("http://x", host="h", detail="d", status="500")
    for key, text in errors.items():
        text.format(**values)  # raises KeyError for a placeholder the flow does not provide
        # the reason must be visible in the dialog, not "see the log"
        assert "log" not in text.lower(), key


async def test_flow_shows_dns_error_with_host(hass: HomeAssistant, fake, caplog) -> None:
    server, url = fake
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    dns = SemaphoreConnectionError("Name or service not known", kind="dns", host="semaphore.example.com")
    with patch.object(SemaphoreClient, "get_projects", AsyncMock(side_effect=dns)):
        bad = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: "https://semaphore.example.com", CONF_API_TOKEN: "secret-token-123", CONF_VERIFY_SSL: True},
        )
    assert bad["type"] is FlowResultType.FORM
    assert bad["errors"] == {"base": "cannot_resolve"}
    assert bad["description_placeholders"]["host"] == "semaphore.example.com"
    assert bad["description_placeholders"]["detail"] == "Name or service not known"
    assert "secret-token-123" not in caplog.text  # the token must never end up in a log line

    # the form is usable again: correct URL works
    ok = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert ok["step_id"] == "project"


async def test_flow_recognises_a_server_that_is_not_semaphore(hass: HomeAssistant, fake) -> None:
    server, url = fake
    server.raw_answer = (200, "<html><body>Welcome to nginx</body></html>")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert bad["errors"] == {"base": "not_semaphore"}
    assert bad["description_placeholders"]["status"] == "200"
    assert "nginx" in bad["description_placeholders"]["detail"]

    server.raw_answer = (503, "Service Unavailable")
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert bad["errors"] == {"base": "http_error"}
    assert bad["description_placeholders"]["status"] == "503"


async def test_reconfigure_and_reauth_show_the_reason_too(hass: HomeAssistant, fake, make_entry) -> None:
    server, url = fake
    entry = await setup(hass, make_entry)

    result = await entry.start_reconfigure_flow(hass)
    timeout = SemaphoreConnectionError("t", kind="timeout", host="semaphore.lan")
    with patch.object(SemaphoreClient, "get_project", AsyncMock(side_effect=timeout)):
        bad = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
        )
    assert bad["errors"] == {"base": "timeout"}
    assert bad["description_placeholders"]["host"] == "semaphore.lan"

    # project deleted in Semaphore: 404 of the project call is a "project not found"
    gone = SemaphoreApiError(404, "Not Found")
    with patch.object(SemaphoreClient, "get_project", AsyncMock(side_effect=gone)):
        bad = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: url, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
        )
    assert bad["errors"] == {"base": "project_not_found"}

    reauth = await entry.start_reauth_flow(hass)
    assert reauth["description_placeholders"]["url"] == url
    with patch.object(SemaphoreClient, "get_project", AsyncMock(side_effect=gone)):
        bad = await hass.config_entries.flow.async_configure(
            reauth["flow_id"], {CONF_API_TOKEN: "x"}
        )
    assert bad["errors"] == {"base": "project_not_found"}
    assert bad["description_placeholders"]["url"] == url


async def test_a_real_refused_connection_is_reported_as_such(hass: HomeAssistant, fake) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "127.0.0.1:9", CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},  # no scheme -> http
    )
    assert bad["errors"] == {"base": "connection_refused"}
    assert bad["description_placeholders"]["url"] == "http://127.0.0.1:9"


# --------------------------------------------------------------------------- #
# Versions: "2.19.17-f8cefe6-1792391878" is the same as "v2.19.17"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("2.19.17-f8cefe6-1792391878", "2.19.17"),
        ("v2.19.17", "2.19.17"),
        ("v2.19.17-f8cefe6-1792391878", "2.19.17"),
        ("2.19.17-f8cefe6", "2.19.17"),
        ("2.19.17-F8CEFE6-1792391878".lower(), "2.19.17"),
        ("2.19.17+build.5", "2.19.17"),
        ("2.16.0-beta1", "2.16.0-beta1"),  # real pre-release: kept
        ("v2.17.0-rc.2", "2.17.0-rc.2"),
        ("2.16.10", "2.16.10"),
        (" 2.16.10 \n", "2.16.10"),
        ("", None),
        (None, None),
    ],
)
def test_clean_version(raw: str | None, clean: str | None) -> None:
    assert _clean_version(raw) == clean


async def test_build_suffix_does_not_trigger_a_false_update(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.version = "2.19.17-f8cefe6-1792391878"
    server.latest_release = {"tag_name": "v2.19.17", "html_url": "https://example.test/r"}
    await setup(hass, make_entry)
    update = hass.states.get(project_eid(hass, "update", "update"))
    assert update.state == "off"
    assert update.attributes["installed_version"] == "2.19.17"
    assert update.attributes["latest_version"] == "2.19.17"
    # what the server really reports stays visible
    assert update.attributes["installed_version_reported"] == "2.19.17-f8cefe6-1792391878"


async def test_a_really_newer_release_is_still_reported(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.version = "2.19.17-f8cefe6-1792391878"
    server.latest_release = {"tag_name": "v2.20.0", "html_url": "https://example.test/r"}
    await setup(hass, make_entry)
    update = hass.states.get(project_eid(hass, "update", "update"))
    assert update.state == "on"
    assert update.attributes["latest_version"] == "2.20.0"


# --------------------------------------------------------------------------- #
# Problem sensors say which template failed, where and why
# --------------------------------------------------------------------------- #
async def test_problem_sensors_explain_the_failure(hass: HomeAssistant, fake, make_entry) -> None:
    """The case of the first real installation: a *newer* task of another template succeeded."""
    server, _ = fake
    server.add_finished_task(2, "error", FAIL_LOG, seconds=3)
    server.add_finished_task(1, "success", OK_LOG)  # most recent task of the project: success
    await setup(hass, make_entry)

    last_status = hass.states.get(project_eid(hass, "sensor", "last_task_status"))
    assert last_status.state == "success"

    problem = hass.states.get(project_eid(hass, "binary_sensor", "project_problem"))
    assert problem.state == "on"
    assert problem.attributes["templates"] == ["Host-Update"]
    assert problem.attributes["failed_count"] == 1
    (run,) = problem.attributes["failed_runs"]
    assert run["template"] == "Host-Update"
    assert run["template_id"] == 2
    assert run["reason"] == "pull access denied for foo"
    assert run["failed_task"] == "Neue Images ziehen"
    assert run["host"] == "dockerhost"
    assert run["task_id"] == server.last_task(2)["id"]
    assert run["url"].endswith(f"/project/1/templates/2?t={run['task_id']}")
    assert "Host-Update" in problem.attributes["explanation"]
    assert "pull access denied for foo" in problem.attributes["explanation"]
    assert "dockerhost" in problem.attributes["explanation"]

    count = hass.states.get(project_eid(hass, "sensor", "failed_templates"))
    assert count.state == "1"
    assert count.attributes["templates"] == ["Host-Update"]
    assert count.attributes["failed_runs"][0]["reason"] == "pull access denied for foo"
    assert "dockerhost" in count.attributes["explanation"]

    tpl_problem = hass.states.get(eid(hass, "binary_sensor", 2, "problem"))
    assert tpl_problem.state == "on"
    assert tpl_problem.attributes["reason"] == "pull access denied for foo"
    assert tpl_problem.attributes["failed_task"] == "Neue Images ziehen"
    assert tpl_problem.attributes["host"] == "dockerhost"
    assert tpl_problem.attributes["task_id"] == run["task_id"]
    ok_problem = hass.states.get(eid(hass, "binary_sensor", 1, "problem"))
    assert ok_problem.state == "off"
    assert "reason" not in ok_problem.attributes


async def test_failure_attributes_are_cleared_by_a_successful_run(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(2, "error", FAIL_LOG, seconds=3)
    await setup(hass, make_entry)
    assert hass.states.get(project_eid(hass, "binary_sensor", "project_problem")).state == "on"

    server.add_finished_task(2, "success", OK_LOG)
    await tick(hass)
    problem = hass.states.get(project_eid(hass, "binary_sensor", "project_problem"))
    assert problem.state == "off"
    assert problem.attributes["templates"] == []
    assert problem.attributes["failed_count"] == 0
    assert problem.attributes["explanation"] is None
    assert problem.attributes["failed_runs"] == []
    assert hass.states.get(project_eid(hass, "sensor", "failed_templates")).state == "0"
    assert "reason" not in hass.states.get(eid(hass, "binary_sensor", 2, "problem")).attributes


async def test_failure_without_a_readable_log_still_says_what_is_known(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    task = server.add_finished_task(2, "error", "", seconds=3)
    server.outputs[task["id"]] = []
    await setup(hass, make_entry)
    problem = hass.states.get(project_eid(hass, "binary_sensor", "project_problem"))
    assert problem.state == "on"
    (run,) = problem.attributes["failed_runs"]
    assert run["template"] == "Host-Update"
    assert run["reason"] is None
    assert "Host-Update" in problem.attributes["explanation"]
    assert problem.attributes["explanation"]  # tells that the reason is unknown / where to look


async def test_several_failed_templates_are_listed_sorted(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.add_finished_task(2, "error", FAIL_LOG, seconds=3)
    server.add_finished_task(1, "error", FAIL_LOG.replace("pull access denied for foo", "disk full"), seconds=3)
    await setup(hass, make_entry)
    problem = hass.states.get(project_eid(hass, "binary_sensor", "project_problem"))
    assert problem.attributes["templates"] == ["docker-system aktualisieren", "Host-Update"]
    assert problem.attributes["failed_count"] == 2
    assert [r["reason"] for r in problem.attributes["failed_runs"]] == ["disk full", "pull access denied for foo"]
    assert problem.attributes["explanation"].count("\n") == 1  # one line per template


# --------------------------------------------------------------------------- #
# Cards: served, loaded by the frontend AND registered as Lovelace resource
# --------------------------------------------------------------------------- #
@pytest.fixture
def web(hass: HomeAssistant):
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    hass.data[DATA_EXTRA_MODULE_URL] = set()
    hass.data.pop(cards.CARDS_STATUS_KEY, None)


async def _resources(hass: HomeAssistant):
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    collection = hass.data[LOVELACE_DATA].resources
    await collection.async_get_info()
    return collection


async def test_cards_are_also_registered_as_lovelace_resource(hass: HomeAssistant, web, hass_storage) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    collection = await _resources(hass)
    assert collection.async_items() == []

    await cards.async_register_cards(hass)

    (item,) = collection.async_items()
    assert item["type"] == "module"
    assert item["url"].startswith(f"{const.CARD_URL_BASE}/{const.CARD_FILE}?v=")
    status = cards.cards_status(hass)
    assert status["resource"] == cards.RESOURCE_CREATED
    assert status["static_path"] and status["extra_js_url"] and not status["errors"]
    assert item["url"] == status["url"] == next(iter(hass.data[DATA_EXTRA_MODULE_URL]))

    # restart: nothing is added twice
    await cards.async_register_cards(hass)
    assert len(collection.async_items()) == 1
    assert cards.cards_status(hass)["resource"] == cards.RESOURCE_PRESENT


async def test_resource_version_is_updated_after_an_update(hass: HomeAssistant, web, hass_storage) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    collection = await _resources(hass)
    old = await collection.async_create_item(
        {"res_type": "module", "url": f"{const.CARD_URL_BASE}/{const.CARD_FILE}?v=1"}
    )
    other = await collection.async_create_item({"res_type": "module", "url": "/hacsfiles/other-card.js"})

    await cards.async_register_cards(hass)

    items = {item["id"]: item for item in collection.async_items()}
    assert len(items) == 2
    assert items[old["id"]]["url"] == cards.cards_status(hass)["url"]
    assert items[other["id"]]["url"] == "/hacsfiles/other-card.js"  # foreign resources stay untouched
    assert cards.cards_status(hass)["resource"] == cards.RESOURCE_UPDATED


async def test_yaml_mode_resources_are_left_alone(hass: HomeAssistant, web) -> None:
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    resources = SimpleNamespace(
        async_get_info=AsyncMock(), async_items=lambda: [], async_create_item=AsyncMock()
    )
    hass.data[LOVELACE_DATA] = SimpleNamespace(resource_mode="yaml", resources=resources)
    await cards.async_register_cards(hass)
    resources.async_create_item.assert_not_awaited()
    assert cards.cards_status(hass)["resource"] == cards.RESOURCE_YAML_MODE
    assert cards.cards_status(hass)["extra_js_url"] is True  # the other way still works


async def test_resource_problems_never_break_the_integration(hass: HomeAssistant, web, caplog) -> None:
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    resources = SimpleNamespace(
        async_get_info=AsyncMock(side_effect=OSError("disk full")),
        async_items=lambda: [],
    )
    hass.data[LOVELACE_DATA] = SimpleNamespace(resource_mode="storage", resources=resources)
    await cards.async_register_cards(hass)
    status = cards.cards_status(hass)
    assert status["resource"] == cards.RESOURCE_ERROR
    assert any("disk full" in e for e in status["errors"])
    assert "could not be set" in caplog.text


async def test_without_lovelace_the_resource_is_tried_again_after_start(hass: HomeAssistant, web) -> None:
    with patch("homeassistant.helpers.start.async_at_started") as at_started:
        await cards.async_register_cards(hass)
    assert cards.cards_status(hass)["resource"] == cards.RESOURCE_NO_LOVELACE
    at_started.assert_called_once()


async def test_diagnostics_tell_how_the_cards_were_registered(hass: HomeAssistant, fake, make_entry) -> None:
    entry = await setup(hass, make_entry)
    data = await async_get_config_entry_diagnostics(hass, entry)
    frontend = data["frontend"]
    assert set(frontend) >= {"file", "static_path", "extra_js_url", "resource", "url", "errors"}
    assert frontend["file"] is True


def test_card_editor_offers_a_clear_choice_of_devices() -> None:
    source = (cards.FRONTEND_DIR / const.CARD_FILE).read_text(encoding="utf-8")
    # list "Project › Template" instead of the generic device picker
    assert "deviceOptions(" in source and "projectNameOf(" in source
    assert "selector: { select: { mode: \"dropdown\", options } }" in source
    assert "no_devices" in source and "help_device_t" in source
    manifest = json.loads((cards.FRONTEND_DIR.parent / "manifest.json").read_text(encoding="utf-8"))
    assert f'SEMAPHORE_CARD_VERSION = "{manifest["version"]}"' in source
