"""Config flow of the Semaphore UI integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import secrets_store, tokens
from .api import (
    REQUEST_TIMEOUT,
    SemaphoreApiError,
    SemaphoreAuthError,
    SemaphoreClient,
    SemaphoreConnectionError,
    SemaphoreError,
    SemaphoreLoginError,
    normalize_base_url,
)
from .const import (
    CONF_ALLOW_PARALLEL,
    CONF_LIVE,
    CONF_API_TOKEN,
    CONF_CHECK_UPDATES,
    CONF_CLEAR_LOGIN,
    CONF_EXCLUDED_TEMPLATES,
    CONF_PROJECT_ID,
    CONF_PROJECT_NAME,
    CONF_RENEW_PASSWORD,
    CONF_RENEW_TOKEN,
    CONF_RENEW_USER,
    CONF_TEMPLATES,
    CONF_TOKEN_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOKEN_DAYS,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MAX_TOKEN_DAYS,
    MIN_SCAN_INTERVAL,
    MIN_TOKEN_DAYS,
)

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        type=selector.TextSelectorType.PASSWORD, autocomplete="off"
    )
)


_CONNECTION_ERRORS = {
    "dns": "cannot_resolve",
    "refused": "connection_refused",
    "timeout": "timeout",
    "ssl": "ssl_error",
    "unreachable": "host_unreachable",
    "invalid_url": "invalid_url",
    "disconnected": "connection_lost",
}


def _placeholders(url: str = "", **extra: str) -> dict[str, str]:
    """Values the error texts in the translations may use."""
    values = {
        "url": url,
        "host": "",
        "detail": "",
        "status": "",
        "seconds": str(REQUEST_TIMEOUT),
        "url_example": "https://semaphore.example.com",
        "ip_example": "http://192.168.1.10:3000",
    }
    values.update(extra)
    return values


def describe_error(
    err: SemaphoreError, url: str, *, project_call: bool = False
) -> tuple[str, dict[str, str]]:
    """Return ``(error key, placeholders)`` so the dialog can say *what* failed.

    ``project_call`` is True when a single project was requested (re-auth,
    reconfigure): HTTP 404 then means "this project does not exist (any more)".
    """
    if isinstance(err, SemaphoreAuthError):
        return "invalid_auth", _placeholders(url)
    if isinstance(err, SemaphoreConnectionError):
        return _CONNECTION_ERRORS.get(err.kind, "cannot_connect"), _placeholders(
            url, host=err.host, detail=err.detail
        )
    if isinstance(err, SemaphoreApiError):
        placeholders = _placeholders(
            url, status=str(err.status or "–"), detail=err.message or ""
        )
        if err.kind == "not_json":
            return "not_semaphore", placeholders
        if err.status == 404:
            return ("project_not_found" if project_call else "not_semaphore"), placeholders
        return "http_error", placeholders
    return "unknown", _placeholders(url, detail=str(err))


class SemaphoreConfigFlow(ConfigFlow, domain=DOMAIN):
    """Step 1: URL + token, step 2: choose the project."""

    VERSION = 1

    def __init__(self) -> None:
        self._url: str = ""
        self._token: str = ""
        self._verify_ssl: bool = True
        self._projects: list[dict[str, Any]] = []

    def _client(self, url: str, token: str, verify_ssl: bool) -> SemaphoreClient:
        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        return SemaphoreClient(session, url, token)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for URL and API token."""
        errors: dict[str, str] = {}
        placeholders = _placeholders()
        if user_input is not None:
            url = normalize_base_url(user_input[CONF_URL])
            token = user_input[CONF_API_TOKEN].strip()
            verify_ssl = user_input[CONF_VERIFY_SSL]
            placeholders = _placeholders(url)
            try:
                projects = await self._client(url, token, verify_ssl).get_projects()
            except SemaphoreError as err:
                errors["base"], placeholders = describe_error(err, url)
                _LOGGER.warning("Semaphore setup failed (%s): %s", errors["base"], err)
            else:
                if not projects:
                    errors["base"] = "no_projects"
                else:
                    self._url, self._token, self._verify_ssl = url, token, verify_ssl
                    self._projects = projects
                    return await self.async_step_project()

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_URL, default=defaults.get(CONF_URL, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Required(
                        CONF_API_TOKEN, default=defaults.get(CONF_API_TOKEN, "")
                    ): TOKEN_SELECTOR,
                    vol.Required(
                        CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, True)
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_project(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose one of the projects read from the API."""
        await secrets_store.async_load_key(self.hass)
        if user_input is not None:
            project_id = int(user_input[CONF_PROJECT_ID])
            project = next(p for p in self._projects if p["id"] == project_id)
            await self.async_set_unique_id(f"{self._url}#{project_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Semaphore – {project['name']}",
                data={
                    CONF_URL: self._url,
                    CONF_API_TOKEN: secrets_store.seal(self.hass, self._token),
                    CONF_VERIFY_SSL: self._verify_ssl,
                    CONF_PROJECT_ID: project_id,
                    CONF_PROJECT_NAME: project["name"],
                },
            )

        options = [
            selector.SelectOptionDict(value=str(p["id"]), label=p["name"])
            for p in sorted(self._projects, key=lambda p: p["name"].lower())
        ]
        return self.async_show_form(
            step_id="project",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROJECT_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    # ---- re-authentication: new token when the old one is invalid ------- #
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API token - or for a login that creates one."""
        await secrets_store.async_load_key(self.hass)
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        placeholders = _placeholders(entry.data[CONF_URL])
        if user_input is not None:
            try:
                token = await tokens.async_check_new_token(self.hass, entry, user_input)
            except SemaphoreLoginError as err:
                errors["base"] = tokens.login_error_key(err)
            except SemaphoreError as err:
                errors["base"], placeholders = describe_error(
                    err, entry.data[CONF_URL], project_call=True
                )
                _LOGGER.warning("Semaphore re-auth failed (%s): %s", errors["base"], err)
            else:
                options = tokens.options_with_login(self.hass, entry, user_input)
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_API_TOKEN: secrets_store.seal(self.hass, token)},
                    **({"options": options} if options is not None else {}),
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_TOKEN): TOKEN_SELECTOR,
                    vol.Optional(CONF_USERNAME): selector.TextSelector(),
                    vol.Optional(CONF_PASSWORD): TOKEN_SELECTOR,
                    vol.Optional(tokens.STORE_LOGIN, default=False): selector.BooleanSelector(),
                }
            ),
            description_placeholders=placeholders,
            errors=errors,
        )

    # ---- reconfigure: new URL / token / SSL setting for the same project -- #
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change URL, token or SSL check without losing devices and history."""
        await secrets_store.async_load_key(self.hass)
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders = _placeholders(entry.data[CONF_URL])
        if user_input is not None:
            url = normalize_base_url(user_input[CONF_URL])
            # left empty: keep the stored token (it is never shown in the form)
            token = (user_input.get(CONF_API_TOKEN) or "").strip() or (
                secrets_store.unseal(self.hass, entry.data[CONF_API_TOKEN]) or ""
            )
            verify_ssl = user_input[CONF_VERIFY_SSL]
            placeholders = _placeholders(url)
            try:
                await self._client(url, token, verify_ssl).get_project(
                    entry.data[CONF_PROJECT_ID]
                )
            except SemaphoreError as err:
                errors["base"], placeholders = describe_error(
                    err, url, project_call=True
                )
                _LOGGER.warning(
                    "Semaphore reconfigure failed (%s): %s", errors["base"], err
                )
            else:
                unique_id = f"{url}#{entry.data[CONF_PROJECT_ID]}"
                other = self.hass.config_entries.async_entry_for_domain_unique_id(
                    DOMAIN, unique_id
                )
                if other is not None and other.entry_id != entry.entry_id:
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    data_updates={
                        CONF_URL: url,
                        CONF_API_TOKEN: secrets_store.seal(self.hass, token),
                        CONF_VERIFY_SSL: verify_ssl,
                    },
                )

        current = user_input or entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_URL, default=current.get(CONF_URL, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Optional(CONF_API_TOKEN): TOKEN_SELECTOR,
                    vol.Required(
                        CONF_VERIFY_SSL, default=current.get(CONF_VERIFY_SSL, True)
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> SemaphoreOptionsFlow:
        """Options: polling interval, update check, parallel runs."""
        return SemaphoreOptionsFlow()


class SemaphoreOptionsFlow(OptionsFlowWithReload):
    """Polling interval, update check, parallel runs, token care and which templates are shown.

    The entry is reloaded when the options change.
    """

    async def _async_login_option(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, Any]:
        """The stored login after this form: ``{}`` (none) or the user name and password.

        A typed login is tried first; an empty password keeps the stored one (it is never
        shown again), ``clear_login`` removes it.
        """
        stored = tokens.stored_login(self.hass, self.config_entry)
        if user_input.get(CONF_CLEAR_LOGIN):
            return {}
        user = str(user_input.get(CONF_RENEW_USER) or "").strip()
        password = str(user_input.get(CONF_RENEW_PASSWORD) or "")
        if not user and not password:
            return (
                {
                    CONF_RENEW_USER: stored[0],
                    CONF_RENEW_PASSWORD: secrets_store.seal(self.hass, stored[1]),
                }
                if stored
                else {}
            )
        if not user or (not password and not (stored and stored[0] == user)):
            errors["base"] = "login_incomplete"
            return {}
        if not password and stored:
            return {
                CONF_RENEW_USER: stored[0],
                CONF_RENEW_PASSWORD: secrets_store.seal(self.hass, stored[1]),
            }
        try:
            await tokens.async_test_login(self.hass, self.config_entry, user, password)
        except SemaphoreLoginError as err:
            errors["base"] = tokens.login_error_key(err)
            return {}
        except SemaphoreError as err:
            _LOGGER.warning("The login could not be tested: %s", err)
            errors["base"] = "login_unreachable"
            return {}
        return {
            CONF_RENEW_USER: user,
            CONF_RENEW_PASSWORD: secrets_store.seal(self.hass, password),
        }

    def _known_templates(self) -> dict[int, str]:
        """All templates of the project (id -> name) as of the last poll.

        Empty while the entry is not loaded (Semaphore down, token rejected): the
        selection is then not offered and the saved choice stays as it is.
        """
        coordinator = getattr(self.config_entry, "runtime_data", None)
        data = getattr(coordinator, "data", None)
        return dict(data.all_templates) if data is not None else {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the options."""
        await secrets_store.async_load_key(self.hass)
        options = self.config_entry.options
        templates = self._known_templates()
        excluded = {int(tid) for tid in options.get(CONF_EXCLUDED_TEMPLATES, [])}
        errors: dict[str, str] = {}

        if user_input is not None:
            saved: dict[str, Any] = {
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                CONF_CHECK_UPDATES: user_input[CONF_CHECK_UPDATES],
                CONF_ALLOW_PARALLEL: user_input[CONF_ALLOW_PARALLEL],
                CONF_LIVE: user_input[CONF_LIVE],
                CONF_RENEW_TOKEN: user_input[CONF_RENEW_TOKEN],
                CONF_TOKEN_DAYS: int(user_input[CONF_TOKEN_DAYS]),
            }
            saved.update(await self._async_login_option(user_input, errors))
            if templates:
                shown = {int(tid) for tid in user_input.get(CONF_TEMPLATES, [])}
                if not shown & set(templates):
                    errors["base"] = "no_templates"
                else:
                    # only templates that exist can be excluded; new ones show up as usual
                    saved[CONF_EXCLUDED_TEMPLATES] = sorted(set(templates) - shown)
            elif excluded:
                saved[CONF_EXCLUDED_TEMPLATES] = sorted(excluded)  # not offered: keep it
            if not errors:
                return self.async_create_entry(data=saved)
            options = dict(saved)  # show what was typed
            if user_input.get(CONF_RENEW_USER):
                options[CONF_RENEW_USER] = user_input[CONF_RENEW_USER]
            excluded = set(templates) - {
                int(tid) for tid in user_input.get(CONF_TEMPLATES, [])
            }

        current = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        check_updates = options.get(CONF_CHECK_UPDATES, True)
        allow_parallel = options.get(CONF_ALLOW_PARALLEL, False)
        stored = tokens.stored_login(self.hass, self.config_entry)
        schema: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=current): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=5,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_CHECK_UPDATES, default=check_updates
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_ALLOW_PARALLEL, default=allow_parallel
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_LIVE, default=options.get(CONF_LIVE, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RENEW_TOKEN, default=options.get(CONF_RENEW_TOKEN, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_TOKEN_DAYS, default=options.get(CONF_TOKEN_DAYS, DEFAULT_TOKEN_DAYS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_TOKEN_DAYS,
                    max=MAX_TOKEN_DAYS,
                    step=1,
                    unit_of_measurement="d",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_RENEW_USER,
                description={"suggested_value": options.get(CONF_RENEW_USER)},
            ): selector.TextSelector(),
            vol.Optional(CONF_RENEW_PASSWORD): TOKEN_SELECTOR,
        }
        if stored:
            schema[vol.Optional(CONF_CLEAR_LOGIN, default=False)] = selector.BooleanSelector()
        if templates:
            names = list(templates.values())
            choices = [
                selector.SelectOptionDict(
                    value=str(tid),
                    # the same name twice: tell them apart by the id
                    label=name if names.count(name) == 1 else f"{name} (#{tid})",
                )
                for tid, name in sorted(
                    templates.items(), key=lambda item: item[1].lower()
                )
            ]
            schema[
                vol.Required(
                    CONF_TEMPLATES,
                    default=[str(tid) for tid in templates if tid not in excluded],
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=choices,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
