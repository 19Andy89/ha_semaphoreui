"""0.3.0: care for the API token - show when it expires, replace it in time, replace a rejected one."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.semaphore_ui import tokens
from custom_components.semaphore_ui.const import (
    CONF_API_TOKEN,
    CONF_CLEAR_LOGIN,
    CONF_RENEW_PASSWORD,
    CONF_RENEW_TOKEN,
    CONF_RENEW_USER,
    CONF_TOKEN_DAYS,
    DEFAULT_NEW_TOKEN_DAYS,
    DOMAIN,
    ISSUE_TOKEN,
    ISSUE_TOKEN_EXPIRING,
    TOKEN_NAME,
    TOKEN_SCAN_INTERVAL,
)
from custom_components.semaphore_ui.diagnostics import async_get_config_entry_diagnostics
from custom_components.semaphore_ui.issues import issue_id

from .helpers import plain
from .fake_semaphore import TOKEN, FakeSemaphore
from .test_flow_and_entities import eid, setup, tick

DAY = timedelta(days=1)
LOGIN = {CONF_RENEW_USER: "andy", CONF_RENEW_PASSWORD: "secret"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def own_token(server: FakeSemaphore, *, left: float | None, lifetime: float = 90, **kwargs: Any) -> None:
    """The token of the integration: valid for ``lifetime`` days in total, ``left`` days are left."""
    server.add_token(
        TOKEN,
        name="Home Assistant",
        age=timedelta(days=lifetime - left) if left is not None else DAY * 30,
        expires_in=timedelta(days=left) if left is not None else None,
        **kwargs,
    )


def new_tokens(server: FakeSemaphore) -> list[tuple[str, dict[str, Any]]]:
    """Tokens that were created through the API (not the one the test started with)."""
    return [(t, r) for t, r in server.api_tokens.items() if t != TOKEN]


def token_sensor(hass: HomeAssistant, entry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_token_expires")
    assert entity_id, "no token sensor"
    return entity_id


def issue(hass: HomeAssistant, entry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(ISSUE_TOKEN_EXPIRING, entry.entry_id))


async def hour_later(hass: HomeAssistant, freezer) -> None:
    """The token check runs once an hour."""
    freezer.tick(timedelta(seconds=TOKEN_SCAN_INTERVAL + 60))
    await tick(hass, TOKEN_SCAN_INTERVAL + 60)


async def open_fix_flow(hass: HomeAssistant, entry, kind: str):
    assert await async_setup_component(hass, "repairs", {})
    manager = hass.data["repairs"]["flow_manager"]
    return manager, await manager.async_init(DOMAIN, context={"issue_id": issue_id(kind, entry.entry_id)})


# --------------------------------------------------------------------------- #
# The expiry is shown
# --------------------------------------------------------------------------- #
async def test_the_sensor_shows_when_the_token_ends(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    own_token(server, left=60)
    entry = await setup(hass, make_entry)

    state = hass.states.get(token_sensor(hass, entry))
    assert state is not None and state.attributes["device_class"] == "timestamp"
    ends = dt_util.parse_datetime(state.state)
    assert ends is not None and abs(ends - (dt_util.utcnow() + 60 * DAY)) < timedelta(minutes=2)
    assert state.attributes["token_name"] == "Home Assistant"
    assert state.attributes["never_expires"] is False
    assert state.attributes["auto_renew"] is True and state.attributes["renew_days_before"] == 7
    assert state.attributes["stored_login"] is False
    assert not new_tokens(server) and issue(hass, entry) is None  # plenty of time: nothing to do
    assert er.async_get(hass).async_get(state.entity_id).entity_category.value == "diagnostic"


async def test_a_token_without_an_end_is_left_alone(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    own_token(server, left=None)
    entry = await setup(hass, make_entry)
    state = hass.states.get(token_sensor(hass, entry))
    assert state.state == "unknown" and state.attributes["never_expires"] is True
    assert not new_tokens(server) and issue(hass, entry) is None


async def test_a_token_that_is_not_in_the_list_is_no_problem(hass: HomeAssistant, fake, make_entry) -> None:
    """Semaphore tells the 8 first characters only: an unknown one just shows nothing."""
    entry = await setup(hass, make_entry)  # the fake lists no tokens
    state = hass.states.get(token_sensor(hass, entry))
    assert state.state == "unknown" and state.attributes["token_found"] is False
    assert entry.state is ConfigEntryState.LOADED and issue(hass, entry) is None


@pytest.mark.parametrize("status", [403, 404, 405])
async def test_a_semaphore_that_does_not_list_tokens_is_fine(hass: HomeAssistant, fake, make_entry, status: int) -> None:
    server, _ = fake
    server.tokens_error = (status, "no")
    entry = await setup(hass, make_entry)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(token_sensor(hass, entry)).state == "unknown"
    assert issue(hass, entry) is None
    assert entry.runtime_data.token_coordinator.data.readable is False


async def test_a_server_error_while_listing_is_not_fatal(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.tokens_error = (500, "boom")
    entry = await setup(hass, make_entry)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state != "unavailable"  # the templates are fine
    assert hass.states.get(token_sensor(hass, entry)).state == "unavailable"


# --------------------------------------------------------------------------- #
# The token is replaced before it ends
# --------------------------------------------------------------------------- #
async def test_the_token_is_replaced_before_it_ends(hass: HomeAssistant, fake, make_entry, freezer) -> None:
    server, _ = fake
    own_token(server, left=5, lifetime=90)  # less than the 7 days
    entry = await setup(hass, make_entry)

    ((new_token, row),) = new_tokens(server)
    assert plain(hass, entry.data[CONF_API_TOKEN]) == new_token != TOKEN
    assert row["name"] == TOKEN_NAME
    assert abs((row["expires_at"] - row["created"]) - 90 * DAY) < timedelta(minutes=2)  # same lifetime as before
    assert server.api_tokens[TOKEN]["expired"] is False  # the old one is NOT deleted (it may be used elsewhere)
    assert entry.runtime_data.client.token == new_token
    state = hass.states.get(token_sensor(hass, entry))
    assert abs(dt_util.parse_datetime(state.state) - (dt_util.utcnow() + 90 * DAY)) < timedelta(minutes=2)
    assert state.attributes["last_renewed"] and state.attributes["renew_error"] is None
    assert issue(hass, entry) is None

    # everything goes on with the new token - also when the old one has run out
    freezer.tick(6 * DAY)
    await tick(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state != "unavailable"
    assert len(new_tokens(server)) == 1  # and it is not renewed again and again
    assert not [f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == SOURCE_REAUTH]


@pytest.mark.parametrize(
    ("lifetime", "left", "renewed"),
    [
        (90, 8, False),  # 7 days before the end is the limit
        (90, 6.5, True),
        (10, 6, False),  # a short token: at most half of its lifetime (5 days)
        (10, 4, True),
        (1, 0.6, False),
        (1, 0.4, True),
    ],
)
async def test_the_token_is_replaced_in_the_last_days(
    hass: HomeAssistant, fake, make_entry, lifetime: float, left: float, renewed: bool
) -> None:
    server, _ = fake
    own_token(server, left=left, lifetime=lifetime)
    await setup(hass, make_entry)
    assert bool(new_tokens(server)) is renewed


async def test_the_days_can_be_changed(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    own_token(server, left=20, lifetime=90)
    entry = make_entry({CONF_TOKEN_DAYS: 30})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(new_tokens(server)) == 1


async def test_a_token_that_works_again_after_the_check_is_not_replaced_twice(
    hass: HomeAssistant, fake, make_entry, freezer
) -> None:
    server, _ = fake
    own_token(server, left=5)
    await setup(hass, make_entry)
    for _ in range(3):
        await hour_later(hass, freezer)
    assert len(new_tokens(server)) == 1


# --------------------------------------------------------------------------- #
# Renewal switched off: a repair with "Fix"
# --------------------------------------------------------------------------- #
async def test_with_the_renewal_off_a_repair_replaces_the_token_on_request(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    own_token(server, left=5)
    entry = make_entry({CONF_RENEW_TOKEN: False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert not new_tokens(server)  # nothing happens by itself
    found = issue(hass, entry)
    assert found is not None and found.is_fixable and found.translation_key == "token_expiring"
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_placeholders["days"] == "5" and found.translation_placeholders["project"] == "Homelab"
    assert found.data == {"entry_id": entry.entry_id}

    manager, result = await open_fix_flow(hass, entry, ISSUE_TOKEN_EXPIRING)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "confirm"
    done = await manager.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert done["type"] is FlowResultType.CREATE_ENTRY
    ((new_token, _row),) = new_tokens(server)
    assert plain(hass, entry.data[CONF_API_TOKEN]) == new_token
    assert issue(hass, entry) is None
    assert hass.states.get(token_sensor(hass, entry)).attributes["last_renewed"]


async def test_the_repair_turns_red_when_the_end_has_come_and_goes_when_the_token_is_rejected(
    hass: HomeAssistant, fake, make_entry, freezer
) -> None:
    server, _ = fake
    own_token(server, left=2)
    entry = make_entry({CONF_RENEW_TOKEN: False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert issue(hass, entry) is not None

    freezer.tick(3 * DAY)  # the end is over: Semaphore rejects the token now
    await tick(hass)
    assert issue(hass, entry) is None  # "the token is rejected" replaces "it ends soon"
    rejected = ir.async_get(hass).async_get_issue(DOMAIN, issue_id(ISSUE_TOKEN, entry.entry_id))
    assert rejected is not None and rejected.is_fixable


async def test_the_fix_flow_needs_a_loaded_project(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    own_token(server, left=5)
    entry = make_entry({CONF_RENEW_TOKEN: False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager, result = await open_fix_flow(hass, entry, ISSUE_TOKEN_EXPIRING)
    await hass.config_entries.async_unload(entry.entry_id)
    again = await manager.async_configure(result["flow_id"], {})
    assert again["type"] is FlowResultType.ABORT and again["reason"] == "not_loaded"


async def test_removing_the_entry_removes_the_repair(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    own_token(server, left=5)
    entry = make_entry({CONF_RENEW_TOKEN: False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert issue(hass, entry) is not None
    await hass.config_entries.async_remove(entry.entry_id)
    assert not [i for d, i in ir.async_get(hass).issues if d == DOMAIN]


# --------------------------------------------------------------------------- #
# A renewal that does not work
# --------------------------------------------------------------------------- #
async def test_a_failed_renewal_is_reported_and_tried_again(hass: HomeAssistant, fake, make_entry, freezer) -> None:
    server, _ = fake
    own_token(server, left=3)
    server.tokens_create_error = (500, "database is locked")
    entry = await setup(hass, make_entry)

    assert entry.state is ConfigEntryState.LOADED and plain(hass, entry.data[CONF_API_TOKEN]) == TOKEN
    found = issue(hass, entry)
    assert found is not None and found.translation_key == "token_renew_failed"
    assert "500" in found.translation_placeholders["detail"]
    assert hass.states.get(token_sensor(hass, entry)).attributes["renew_error"]

    server.tokens_create_error = None
    await hour_later(hass, freezer)
    assert issue(hass, entry) is None
    assert len(new_tokens(server)) == 1
    assert hass.states.get(token_sensor(hass, entry)).attributes["renew_error"] is None


async def test_a_new_token_that_does_not_work_is_not_taken(hass: HomeAssistant, fake, make_entry, monkeypatch) -> None:
    """The new token is tried before the old one is dropped."""
    server, _ = fake
    own_token(server, left=3)

    original = FakeSemaphore._token_valid

    def reject_new_tokens(self: FakeSemaphore, bearer: str) -> bool:
        return original(self, bearer) and bearer == TOKEN

    monkeypatch.setattr(FakeSemaphore, "_token_valid", reject_new_tokens)
    entry = await setup(hass, make_entry)
    assert plain(hass, entry.data[CONF_API_TOKEN]) == TOKEN
    assert entry.runtime_data.client.token == TOKEN
    assert issue(hass, entry).translation_key == "token_renew_failed"


# --------------------------------------------------------------------------- #
# Stored login: a token that is already rejected is replaced
# --------------------------------------------------------------------------- #
async def test_a_rejected_token_is_replaced_by_the_stored_login(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.users["andy"] = "secret"
    own_token(server, left=1, expired=True)  # revoked / run out: Semaphore rejects it
    entry = make_entry(LOGIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    ((new_token, row),) = new_tokens(server)
    assert plain(hass, entry.data[CONF_API_TOKEN]) == new_token and row["name"] == TOKEN_NAME
    assert abs((row["expires_at"] - row["created"]) - DEFAULT_NEW_TOKEN_DAYS * DAY) < timedelta(minutes=2)
    kinds = [kind for kind, _path, _body in server.token_requests]
    assert kinds.count("LOGIN") == 1 and kinds.count("LOGOUT") == 1 and not server.sessions  # signed out again
    assert all("secret" not in str(body) for _k, _p, body in server.token_requests)  # the fake does not log the password
    assert hass.states.get(eid(hass, "sensor", 1, "status")).state != "unavailable"
    assert not [f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == SOURCE_REAUTH]
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(ISSUE_TOKEN, entry.entry_id)) is None


async def test_without_a_stored_login_everything_is_as_before(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.users["andy"] = "secret"
    own_token(server, left=1, expired=True)
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is not ConfigEntryState.LOADED  # the token is rejected -> re-authentication
    assert not [k for k, _p, _b in server.token_requests if k == "LOGIN"]


async def test_a_wrong_stored_login_is_not_tried_again_and_again(hass: HomeAssistant, fake, make_entry, freezer) -> None:
    server, _ = fake
    server.users["andy"] = "other-password"  # the stored password is wrong
    own_token(server, left=1, expired=True)
    entry = make_entry(LOGIN)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    logins = lambda: [k for k, _p, _b in server.token_requests if k == "LOGIN"]  # noqa: E731
    assert len(logins()) == 1
    assert entry.state is not ConfigEntryState.LOADED

    fresh = tokens._client_for(hass, entry, TOKEN)  # the client of the entry is gone with the failed setup
    assert await tokens.async_recover(hass, entry, fresh, TOKEN) is False
    assert len(logins()) == 1  # within ten minutes: no second attempt (a wrong password must not lock the account)
    freezer.tick(timedelta(seconds=tokens.RETRY_AFTER + 10))
    assert await tokens.async_recover(hass, entry, fresh, TOKEN) is False
    assert len(logins()) == 2


async def test_a_user_with_a_second_factor_is_told_so(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.users["andy"] = "secret"
    server.mfa_users.add("andy")
    own_token(server, left=1, expired=True)
    entry = make_entry(LOGIN)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is not ConfigEntryState.LOADED
    assert not new_tokens(server) and not server.sessions  # signed out again


# --------------------------------------------------------------------------- #
# The forms
# --------------------------------------------------------------------------- #
async def reauth_flow(hass: HomeAssistant, fake, make_entry):
    server, _ = fake
    server.users["andy"] = "secret"
    entry = await setup(hass, make_entry)
    server.token = "rotated"  # the token was replaced in Semaphore: the old one is rejected now
    await tick(hass)
    flow = next(f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == SOURCE_REAUTH)
    return server, entry, flow


async def test_reauth_with_a_login_creates_the_token(hass: HomeAssistant, fake, make_entry) -> None:
    server, entry, flow = await reauth_flow(hass, fake, make_entry)
    empty = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert empty["errors"] == {"base": "need_token_or_login"}
    bad = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USERNAME: "andy", CONF_PASSWORD: "wrong"}
    )
    assert bad["errors"] == {"base": "login_failed"}
    server.mfa_users.add("andy")
    mfa = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USERNAME: "andy", CONF_PASSWORD: "secret"}
    )
    assert mfa["errors"] == {"base": "mfa_required"}
    server.mfa_users.clear()
    server.token = "rotated"
    # the token created by the login has to work: the fake accepts tokens created through the API
    done = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USERNAME: "andy", CONF_PASSWORD: "secret"}
    )
    await hass.async_block_till_done()
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "reauth_successful"
    ((new_token, _row),) = new_tokens(server)
    assert plain(hass, entry.data[CONF_API_TOKEN]) == new_token
    assert entry.options.get(CONF_RENEW_USER) is None  # not kept without the tick
    assert not server.sessions


async def test_reauth_can_keep_the_login(hass: HomeAssistant, fake, make_entry) -> None:
    server, entry, flow = await reauth_flow(hass, fake, make_entry)
    done = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USERNAME: "andy", CONF_PASSWORD: "secret", tokens.STORE_LOGIN: True}
    )
    await hass.async_block_till_done()
    assert done["reason"] == "reauth_successful"
    assert entry.options[CONF_RENEW_USER] == "andy" and plain(hass, entry.options[CONF_RENEW_PASSWORD]) == "secret"


async def test_reauth_with_a_typed_token_still_works(hass: HomeAssistant, fake, make_entry) -> None:
    server, entry, flow = await reauth_flow(hass, fake, make_entry)
    done = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_API_TOKEN: "rotated"})
    await hass.async_block_till_done()
    assert done["reason"] == "reauth_successful" and plain(hass, entry.data[CONF_API_TOKEN]) == "rotated"
    assert not new_tokens(server)


async def test_the_repair_dialog_takes_a_login_too(hass: HomeAssistant, fake, make_entry) -> None:
    server, entry, _flow = await reauth_flow(hass, fake, make_entry)
    manager, result = await open_fix_flow(hass, entry, ISSUE_TOKEN)
    assert result["step_id"] == "init"
    bad = await manager.async_configure(result["flow_id"], {})
    assert bad["errors"] == {"base": "need_token_or_login"}
    done = await manager.async_configure(
        bad["flow_id"], {CONF_USERNAME: "andy", CONF_PASSWORD: "secret", tokens.STORE_LOGIN: True}
    )
    await hass.async_block_till_done()
    assert done["type"] is FlowResultType.CREATE_ENTRY
    ((new_token, _row),) = new_tokens(server)
    assert plain(hass, entry.data[CONF_API_TOKEN]) == new_token and entry.options[CONF_RENEW_USER] == "andy"
    assert entry.state is ConfigEntryState.LOADED


async def options_of(hass: HomeAssistant, entry, user_input: dict[str, Any] | None = None):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    if user_input is None:
        return result
    base = {
        CONF_SCAN_INTERVAL: 30,
        "check_for_updates": False,
        "allow_parallel_runs": False,
        CONF_RENEW_TOKEN: True,
        CONF_TOKEN_DAYS: 7,
        "templates": ["1", "2", "3"],
    }
    return await hass.config_entries.options.async_configure(result["flow_id"], {**base, **user_input})


async def test_the_options_keep_and_check_the_login(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    server.users["andy"] = "secret"
    server.mfa_users.add("boss")
    server.users["boss"] = "pw"
    entry = await setup(hass, make_entry)

    cases = [
        ({CONF_RENEW_USER: "andy"}, "login_incomplete"),  # no password and none stored
        ({CONF_RENEW_USER: "andy", CONF_RENEW_PASSWORD: "wrong"}, "login_failed"),
        ({CONF_RENEW_USER: "boss", CONF_RENEW_PASSWORD: "pw"}, "mfa_required"),
    ]
    for user_input, error in cases:
        result = await options_of(hass, entry, user_input)
        assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": error}, user_input
    assert not new_tokens(server) and not server.sessions  # a test only signs in and out, no token is made

    saved = await options_of(hass, entry, {CONF_RENEW_USER: "andy", CONF_RENEW_PASSWORD: "secret", CONF_TOKEN_DAYS: 14})
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_RENEW_USER] == "andy" and plain(hass, entry.options[CONF_RENEW_PASSWORD]) == "secret"
    assert entry.options[CONF_TOKEN_DAYS] == 14 and entry.options[CONF_RENEW_TOKEN] is True

    # empty password: the stored one stays (it is never shown again), nothing is tested again
    logins = len([k for k, _p, _b in server.token_requests if k == "LOGIN"])
    kept = await options_of(hass, entry, {CONF_RENEW_USER: "andy"})
    assert kept["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert plain(hass, entry.options[CONF_RENEW_PASSWORD]) == "secret"
    assert len([k for k, _p, _b in server.token_requests if k == "LOGIN"]) == logins

    # the form never shows the password and offers to remove the login
    form = await options_of(hass, entry)
    fields = {str(key) for key in form["data_schema"].schema}
    assert CONF_CLEAR_LOGIN in fields
    assert form["data_schema"]({}).get(CONF_RENEW_PASSWORD) is None

    cleared = await options_of(hass, entry, {CONF_CLEAR_LOGIN: True})
    assert cleared["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert CONF_RENEW_USER not in entry.options and CONF_RENEW_PASSWORD not in entry.options


async def test_the_options_say_so_when_semaphore_is_not_there(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    entry = await setup(hass, make_entry)
    server.raw_answer = (502, "Bad Gateway")
    result = await options_of(hass, entry, {CONF_RENEW_USER: "andy", CONF_RENEW_PASSWORD: "secret"})
    assert result["errors"] == {"base": "login_unreachable"}


# --------------------------------------------------------------------------- #
# Diagnostics, helpers, texts
# --------------------------------------------------------------------------- #
async def test_diagnostics_show_the_token_state_but_no_secret(hass: HomeAssistant, fake, make_entry) -> None:
    server, _ = fake
    own_token(server, left=60)
    entry = make_entry(LOGIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["token"]["listed"] is True and data["token"]["stored_login"] is True
    assert data["token"]["auto_renew"] is True and data["token"]["expires_at"]
    text = str(data)
    assert "secret" not in text and TOKEN not in text and "andy" not in text


def test_the_own_token_is_found_by_its_first_characters() -> None:
    rows = [{"id": "abcdefgh", "name": "a"}, {"id": "zzzzzzzz", "name": "z"}]
    assert tokens.find_own(rows, "ABCDEFGH-rest-of-the-token")["name"] == "a"
    assert tokens.find_own(rows, "other") is None
    assert tokens.find_own([{"id": "short"}], "shortcut") is None  # a short id is no prefix we can trust
    assert tokens.find_own([{"id": "short"}], "short")["id"] == "short"


@pytest.mark.parametrize("value", [None, "", "0001-01-01T00:00:00Z", "no date"])
def test_no_date_is_no_expiry(value: object) -> None:
    assert tokens.parse_time(value) is None
    assert tokens.data_from_row({"created": "2026-01-01T00:00:00Z", "expires_at": value}).expires_at is None


def test_the_lifetime_is_the_time_between_creation_and_end() -> None:
    row = {"created": "2026-01-01T00:00:00Z", "expires_at": "2026-04-01T00:00:00Z"}
    assert tokens.data_from_row(row).lifetime == timedelta(days=90)
    assert tokens.data_from_row({"created": "2026-01-01T00:00:00Z"}).lifetime is None
    assert tokens.data_from_row(None).found is False
