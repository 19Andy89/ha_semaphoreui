"""Semaphore UI integration: control Ansible/Terraform/... templates from Home Assistant."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    CONF_URL,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from . import issues
from .api import SemaphoreClient
from .cards import async_register_cards
from .const import CONF_API_TOKEN, DEFAULT_WAIT_TIMEOUT, DOMAIN
from .coordinator import (
    TEMPLATE_IDENTIFIER_RE,
    SemaphoreConfigEntry,
    SemaphoreCoordinator,
    SemaphoreVersionCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.UPDATE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_RUN_TEMPLATE = "run_template"
SERVICE_RUN_TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional("dry_run", default=False): cv.boolean,
        vol.Optional("wait", default=False): cv.boolean,
        vol.Optional("timeout", default=DEFAULT_WAIT_TIMEOUT): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=86400)
        ),
        vol.Optional("message"): cv.string,
        vol.Optional("limit"): cv.string,
        vol.Optional("survey"): dict,
        vol.Optional("raise_on_failure", default=False): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the action ``semaphore_ui.run_template`` and the dashboard cards."""

    def _resolve(call: ServiceCall) -> list[tuple[SemaphoreCoordinator, int]]:
        """Find (coordinator, template id) for the targeted devices/entities."""
        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)
        device_ids = set(call.data.get(ATTR_DEVICE_ID, []))
        for entity_id in call.data.get(ATTR_ENTITY_ID, []):
            entity = ent_reg.async_get(entity_id)
            if entity is None or entity.device_id is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_a_template",
                )
            device_ids.add(entity.device_id)

        found: list[tuple[SemaphoreCoordinator, int]] = []
        for device_id in device_ids:
            device = dev_reg.async_get(device_id)
            match = None
            if device is not None:
                for domain, identifier in device.identifiers:
                    if domain == DOMAIN and (
                        match := TEMPLATE_IDENTIFIER_RE.match(identifier)
                    ):
                        break
            if match is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_a_template",
                )
            entry = hass.config_entries.async_get_entry(match["entry"])
            if entry is None or entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="entry_not_loaded",
                )
            found.append((entry.runtime_data, int(match["tid"])))
        return found

    async def _async_run_template(call: ServiceCall) -> ServiceResponse:
        targets = _resolve(call)
        if len(targets) != 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="exactly_one_template",
            )
        coordinator, template_id = targets[0]
        return await coordinator.async_run_template(
            template_id,
            dry_run=call.data["dry_run"],
            message=call.data.get("message"),
            limit=call.data.get("limit"),
            survey=call.data.get("survey"),
            wait=call.data["wait"],
            timeout=call.data["timeout"],
            raise_on_failure=call.data["raise_on_failure"],
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_TEMPLATE,
        _async_run_template,
        schema=SERVICE_RUN_TEMPLATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    await async_register_cards(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SemaphoreConfigEntry) -> bool:
    """Set up one Semaphore project."""
    session = async_get_clientsession(hass, verify_ssl=entry.data[CONF_VERIFY_SSL])
    client = SemaphoreClient(session, entry.data[CONF_URL], entry.data[CONF_API_TOKEN])
    coordinator = SemaphoreCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.register_project_device()

    # Version / update info: a failure here must never block the setup.
    coordinator.version_coordinator = SemaphoreVersionCoordinator(hass, entry, client)
    await coordinator.version_coordinator.async_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SemaphoreConfigEntry) -> bool:
    """Unload a project."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: SemaphoreConfigEntry) -> None:
    """The project was removed: its repairs are obsolete."""
    issues.clear(hass, entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SemaphoreConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting the device of a template that no longer exists in Semaphore."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return False
    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == entry.entry_id:
            return False  # the project device
        match = TEMPLATE_IDENTIFIER_RE.match(identifier)
        if (
            match
            and match["entry"] == entry.entry_id
            and int(match["tid"]) in coordinator.data.templates
        ):
            return False  # the template is still there
    return True
