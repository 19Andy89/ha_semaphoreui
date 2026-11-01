"""Number inputs for integer survey variables."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .survey import TYPE_INT, SurveyVar
from .survey_entity import SemaphoreSurveyEntity, async_setup_survey_platform

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the number inputs."""
    async_setup_survey_platform(
        hass,
        entry,
        async_add_entities,
        domain="number",
        wants=lambda var: var.type == TYPE_INT,
        factory=SemaphoreSurveyNumber,
    )


class SemaphoreSurveyNumber(SemaphoreSurveyEntity, NumberEntity):
    """Value of an ``int`` survey variable."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = -2147483648
    _attr_native_max_value = 2147483647
    _attr_native_step = 1

    def __init__(
        self, coordinator: SemaphoreCoordinator, template_id: int, var: SurveyVar
    ) -> None:
        super().__init__(coordinator, template_id, var)
        self._attr_native_value: float | None = None

    def _set(self, value: int | None) -> None:
        self._attr_native_value = value
        self._remember(None if value is None else str(value))

    def _restore(self, state: str) -> None:
        try:
            self._set(int(float(state)))
        except ValueError:
            self._apply_default()

    def _apply_default(self) -> None:
        var = self.var
        try:
            self._set(int(var.default[0]) if var and var.default else None)
        except ValueError:
            self._set(None)

    async def async_set_native_value(self, value: float) -> None:
        """Change the value."""
        self._set(int(value))
        self.async_write_ha_state()
