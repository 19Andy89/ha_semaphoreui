"""Care for the API token: when does it expire, replace it in time, replace a rejected one.

* The token check reads ``GET /api/user/tokens`` (once an hour) and finds the own token by
  the first 8 characters of its id (that is all the list shows). It reports the expiry as a
  sensor and, shortly before the end, replaces the token (``POST /api/user/tokens`` with the
  token itself - no password needed) with one of the same lifetime.
* The old token is **not** deleted: it may be in use elsewhere (a ``rest_command``, a script)
  and it expires on its own soon anyway.
* With a stored login (optional) a token that was already rejected is replaced as well:
  sign in, create a token, sign out. Nothing but the new token is kept from the session.

Nothing in here talks to another server than Semaphore.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import issues, secrets_store
from .api import (
    SemaphoreApiError,
    SemaphoreAuthError,
    SemaphoreClient,
    SemaphoreError,
    SemaphoreLoginError,
)
from .const import (
    CONF_API_TOKEN,
    CONF_PROJECT_ID,
    CONF_PROJECT_NAME,
    CONF_RENEW_PASSWORD,
    CONF_RENEW_TOKEN,
    CONF_RENEW_USER,
    CONF_TOKEN_DAYS,
    DEFAULT_NEW_TOKEN_DAYS,
    DEFAULT_TOKEN_DAYS,
    DOMAIN,
    ISSUE_TOKEN_EXPIRING,
    TOKEN_NAME,
    TOKEN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# A stored login that did not work is not tried again for this long (seconds):
# a wrong password must not lock the account of the user.
RETRY_AFTER = 600

_KEY = f"{DOMAIN}_token_care"

# Field of the "new token" forms: keep the login for replacing the token automatically later
STORE_LOGIN = "store_login"

# Issue keys (translation keys): the same issue id, the text depends on why it is shown
ISSUE_TEXT_OFF = "token_expiring"  # automatic renewal is switched off
ISSUE_TEXT_FAILED = "token_renew_failed"  # renewal failed


@dataclass
class TokenData:
    """What is known about the own token."""

    readable: bool = True  # False: this Semaphore does not list tokens
    found: bool = False  # the token is in the list
    name: str | None = None
    created: datetime | None = None
    expires_at: datetime | None = None  # None: never expires
    last_renewed: datetime | None = None
    renew_error: str | None = None

    @property
    def lifetime(self) -> timedelta | None:
        """How long the token is valid in total (``None``: forever or unknown)."""
        if self.expires_at is None or self.created is None:
            return None
        life = self.expires_at - self.created
        return life if life > timedelta(0) else None


def parse_time(value: Any) -> datetime | None:
    """RFC3339 text of Semaphore -> aware datetime (``None`` if empty or not a date)."""
    if not value:
        return None
    parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    # Go writes "0001-01-01T00:00:00Z" for "not set"
    return None if parsed.year <= 1 else parsed


def find_own(rows: list[dict[str, Any]], token: str) -> dict[str, Any] | None:
    """The list entry of the own token: its id is the start of the token."""
    token = token.lower()
    for row in rows:
        row_id = str(row.get("id") or "").lower()
        if row_id and token.startswith(row_id) and (len(row_id) >= 8 or token == row_id):
            return row
    return None


def data_from_row(row: dict[str, Any] | None) -> TokenData:
    """Token data from one entry of the list (or the answer to "create token")."""
    if row is None:
        return TokenData(found=False)
    return TokenData(
        found=True,
        name=row.get("name") or None,
        created=parse_time(row.get("created")),
        expires_at=parse_time(row.get("expires_at")),
    )


def _entry_lifetimes(hass: HomeAssistant) -> dict[str, timedelta | None]:
    return hass.data.setdefault(_KEY, {}).setdefault("lifetime", {})


def known_lifetime(hass: HomeAssistant, entry_id: str) -> timedelta | None:
    """Lifetime of the last token we saw (default for a new one when nothing is known)."""
    lifetimes = _entry_lifetimes(hass)
    if entry_id in lifetimes:
        return lifetimes[entry_id]
    return timedelta(days=DEFAULT_NEW_TOKEN_DAYS)


def stored_login(hass: HomeAssistant, entry: ConfigEntry) -> tuple[str, str] | None:
    """User name and password for replacing a rejected token (``None``: not stored)."""
    user = entry.options.get(CONF_RENEW_USER)
    password = secrets_store.unseal(hass, entry.options.get(CONF_RENEW_PASSWORD))
    return (str(user), str(password)) if user and password else None


def _client_for(hass: HomeAssistant, entry: ConfigEntry, token: str) -> SemaphoreClient:
    return SemaphoreClient(
        async_get_clientsession(hass, verify_ssl=entry.data[CONF_VERIFY_SSL]),
        entry.data[CONF_URL],
        token,
    )


async def _async_adopt(
    hass: HomeAssistant, entry: ConfigEntry, client: SemaphoreClient, new_token: str
) -> None:
    """Use ``new_token`` from now on - after it has proven that it works."""
    await _client_for(hass, entry, new_token).get_project(entry.data[CONF_PROJECT_ID])
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_API_TOKEN: secrets_store.seal(hass, new_token)}
    )
    client.set_token(new_token)


def _expiry(lifetime: timedelta | None) -> datetime | None:
    return dt_util.utcnow() + lifetime if lifetime else None


async def async_renew_with_token(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: SemaphoreClient,
    lifetime: timedelta | None,
) -> dict[str, Any]:
    """Create a new token with the current one and switch to it (the old one stays)."""
    created = await client.create_token(TOKEN_NAME, _expiry(lifetime))
    await _async_adopt(hass, entry, client, str(created["id"]))
    _LOGGER.info("The API token of %s was replaced by a new one", entry.title)
    return created


async def async_token_by_login(
    hass: HomeAssistant,
    entry: ConfigEntry,
    username: str,
    password: str,
    lifetime: timedelta | None,
) -> str:
    """Sign in, create a token for the integration, sign out. Returns the token.

    Raises :class:`SemaphoreLoginError` (wrong login, second factor) or another
    :class:`SemaphoreError` (not reachable, ...).
    """
    anonymous = _client_for(hass, entry, "")
    cookie = await anonymous.login(username, password)
    try:
        created = await anonymous.create_token(
            TOKEN_NAME, _expiry(lifetime), session_cookie=cookie
        )
    finally:
        await anonymous.logout(cookie)
    return str(created["id"])


async def async_test_login(
    hass: HomeAssistant, entry: ConfigEntry, username: str, password: str
) -> None:
    """Check a login (options dialog): sign in, read something, sign out. No token is created.

    Raises :class:`SemaphoreLoginError` (wrong login / second factor needed) or another
    :class:`SemaphoreError` (not reachable, ...).
    """
    anonymous = _client_for(hass, entry, "")
    cookie = await anonymous.login(username, password)
    try:
        await anonymous.get_tokens(session_cookie=cookie)
    except SemaphoreAuthError as err:
        raise SemaphoreLoginError(
            "mfa_required" if err.body.upper().endswith("_REQUIRED") else "invalid_auth"
        ) from err
    finally:
        await anonymous.logout(cookie)


async def async_recover(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: SemaphoreClient,
    failed_token: str,
) -> bool:
    """A request with ``failed_token`` was rejected: get a new token with the stored login.

    ``True`` when the client has a working new token now (also when another request did
    that a moment ago). ``False``: no login stored, it did not work, or it was tried
    recently with the same login.
    """
    if client.token != failed_token:
        return True  # somebody else was faster
    login = stored_login(hass, entry)
    if login is None:
        return False
    state = hass.data.setdefault(_KEY, {})
    lock: asyncio.Lock = state.setdefault("lock", {}).setdefault(entry.entry_id, asyncio.Lock())
    async with lock:
        if client.token != failed_token:
            return True
        attempts: dict[str, tuple[float, tuple[str, str]]] = state.setdefault("attempt", {})
        last = attempts.get(entry.entry_id)
        if last and last[1] == login and time.monotonic() - last[0] < RETRY_AFTER:
            return False
        attempts[entry.entry_id] = (time.monotonic(), login)
        try:
            token = await async_token_by_login(
                hass, entry, login[0], login[1], known_lifetime(hass, entry.entry_id)
            )
            await _async_adopt(hass, entry, client, token)
        except SemaphoreError as err:
            _LOGGER.warning(
                "The stored login could not get a new API token for %s: %s", entry.title, err
            )
            return False
        attempts.pop(entry.entry_id, None)
    _LOGGER.warning(
        "The API token of %s was rejected and replaced by a new one (stored login)", entry.title
    )
    return True


async def async_check_new_token(
    hass: HomeAssistant, entry: ConfigEntry, user_input: dict[str, Any]
) -> str:
    """The token of a "new token" form: typed in, or created by signing in. Checked.

    Raises :class:`SemaphoreLoginError` (``need_input`` when neither is given) or another
    :class:`SemaphoreError` when Semaphore does not accept it.
    """
    token = str(user_input.get(CONF_API_TOKEN) or "").strip()
    username = str(user_input.get(CONF_USERNAME) or "").strip()
    password = str(user_input.get(CONF_PASSWORD) or "")
    if not token and not (username and password):
        raise SemaphoreLoginError("need_input")
    if not token:
        token = await async_token_by_login(
            hass, entry, username, password, known_lifetime(hass, entry.entry_id)
        )
    await _client_for(hass, entry, token).get_project(entry.data[CONF_PROJECT_ID])
    return token


def options_with_login(
    hass: HomeAssistant, entry: ConfigEntry, user_input: dict[str, Any]
) -> dict[str, Any] | None:
    """The options with the typed login in them - if the user asked to keep it."""
    username = str(user_input.get(CONF_USERNAME) or "").strip()
    password = str(user_input.get(CONF_PASSWORD) or "")
    if not user_input.get(STORE_LOGIN) or not username or not password:
        return None
    return {
        **entry.options,
        CONF_RENEW_USER: username,
        CONF_RENEW_PASSWORD: secrets_store.seal(hass, password),
    }


def login_error_key(err: SemaphoreLoginError) -> str:
    """Error key of the forms for a failed sign-in."""
    return {
        "mfa_required": "mfa_required",
        "need_input": "need_token_or_login",
    }.get(err.reason, "login_failed")


def forget(hass: HomeAssistant, entry_id: str) -> None:
    """The entry was removed."""
    state = hass.data.get(_KEY)
    if state:
        for part in state.values():
            part.pop(entry_id, None)


class SemaphoreTokenCoordinator(DataUpdateCoordinator[TokenData]):
    """Reads the expiry of the own token and replaces the token before it runs out."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: SemaphoreClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} token {entry.title}",
            update_interval=timedelta(seconds=TOKEN_SCAN_INTERVAL),
        )
        self.client = client
        self.renew: bool = entry.options.get(CONF_RENEW_TOKEN, True)
        self.days: int = int(entry.options.get(CONF_TOKEN_DAYS, DEFAULT_TOKEN_DAYS))
        self.has_login: bool = stored_login(hass, entry) is not None
        self._last_renewed: datetime | None = None
        self._renew_error: str | None = None

    def _window(self, lifetime: timedelta | None) -> timedelta:
        """Replace / warn when less than this is left (never more than half the lifetime)."""
        window = timedelta(days=self.days)
        return min(window, lifetime / 2) if lifetime else window

    async def _async_list(self) -> list[dict[str, Any]]:
        failed = self.client.token
        try:
            return await self.client.get_tokens()
        except SemaphoreAuthError:
            if not await async_recover(self.hass, self.config_entry, self.client, failed):
                raise
            return await self.client.get_tokens()

    async def _async_update_data(self) -> TokenData:
        try:
            rows = await self._async_list()
        except SemaphoreAuthError as err:
            issues.report_token_rejected(self.hass, self.config_entry)
            raise ConfigEntryAuthFailed(str(err)) from err
        except SemaphoreApiError as err:
            if err.status in (403, 404, 405):  # a Semaphore that does not list tokens
                self._delete_issue()
                return TokenData(readable=False)
            raise UpdateFailed(str(err)) from err
        except SemaphoreError as err:
            raise UpdateFailed(str(err)) from err

        data = data_from_row(find_own(rows, self.client.token))
        _entry_lifetimes(self.hass)[self.config_entry.entry_id] = data.lifetime
        now = dt_util.utcnow()
        if (
            data.expires_at is not None
            and data.expires_at - now <= self._window(data.lifetime)
            and self.renew
        ):
            data = await self._async_try_renew(data)
        data.last_renewed = self._last_renewed
        data.renew_error = self._renew_error
        self._update_issue(data, now)
        return data

    async def _async_try_renew(self, data: TokenData) -> TokenData:
        try:
            created = await async_renew_with_token(
                self.hass, self.config_entry, self.client, data.lifetime
            )
        except SemaphoreError as err:
            _LOGGER.warning("The API token could not be replaced: %s", err)
            self._renew_error = str(err)
            return data
        self._renew_error = None
        self._last_renewed = dt_util.utcnow()
        return data_from_row(created)

    async def async_renew_now(self) -> None:
        """Replace the token now (the repair "token expires soon" calls this)."""
        life = self.data.lifetime if self.data and self.data.found else None
        if life is None:
            life = known_lifetime(self.hass, self.config_entry.entry_id)
        created = await async_renew_with_token(self.hass, self.config_entry, self.client, life)
        self._renew_error = None
        self._last_renewed = dt_util.utcnow()
        data = data_from_row(created)
        data.last_renewed = self._last_renewed
        _entry_lifetimes(self.hass)[self.config_entry.entry_id] = data.lifetime
        self.async_set_updated_data(data)
        self._update_issue(data, dt_util.utcnow())

    # ---- the repair "the token expires soon" ---------------------------- #
    def _issue_id(self) -> str:
        return issues.issue_id(ISSUE_TOKEN_EXPIRING, self.config_entry.entry_id)

    def _delete_issue(self) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id())

    def _update_issue(self, data: TokenData, now: datetime) -> None:
        """Show the repair while the end is near and nobody has replaced the token."""
        if data.expires_at is None or data.expires_at - now > self._window(data.lifetime):
            self._delete_issue()
            return
        entry = self.config_entry
        left = data.expires_at - now
        failed = bool(self.renew and data.renew_error)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(),
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR if left <= timedelta(0) else ir.IssueSeverity.WARNING,
            translation_key=ISSUE_TEXT_FAILED if failed else ISSUE_TEXT_OFF,
            translation_placeholders={
                "project": entry.data.get(CONF_PROJECT_NAME, ""),
                "url": entry.data.get(CONF_URL, ""),
                "days": str(max(0, math.ceil(left / timedelta(days=1)))),
                "when": dt_util.as_local(data.expires_at).strftime("%d.%m.%Y %H:%M"),
                "detail": data.renew_error or "",
            },
            data={"entry_id": entry.entry_id},
        )
