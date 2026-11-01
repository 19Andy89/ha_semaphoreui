"""Text inputs for string / multi line survey variables."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .survey import TYPE_STRING, TYPE_TEXT, SurveyVar
from .survey_entity import SemaphoreSurveyEntity, async_setup_survey_platform

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the text inputs."""
    async_setup_survey_platform(
        hass,
        entry,
        async_add_entities,
        domain="text",
        wants=lambda var: var.type in (TYPE_STRING, TYPE_TEXT),
        factory=SemaphoreSurveyText,
    )


class SemaphoreSurveyText(SemaphoreSurveyEntity, TextEntity):
    """Value of a string survey variable."""

    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 255

    def __init__(
        self, coordinator: SemaphoreCoordinator, template_id: int, var: SurveyVar
    ) -> None:
        super().__init__(coordinator, template_id, var)
        self._attr_native_value: str | None = None

    def _restore(self, state: str) -> None:
        self._attr_native_value = state
        self._remember(state or None)

    def _apply_default(self) -> None:
        var = self.var
        value = var.default[0] if var and var.default else None
        self._attr_native_value = value
        self._remember(value)

    async def async_set_value(self, value: str) -> None:
        """Change the value."""
        self._attr_native_value = value
        self._remember(value or None)
        self.async_write_ha_state()
