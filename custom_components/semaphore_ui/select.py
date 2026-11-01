"""Drop-downs for enum survey variables."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .survey import TYPE_ENUM, SurveyVar
from .survey_entity import SemaphoreSurveyEntity, async_setup_survey_platform

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the drop-downs."""
    async_setup_survey_platform(
        hass,
        entry,
        async_add_entities,
        domain="select",
        wants=lambda var: var.type == TYPE_ENUM,
        factory=SemaphoreSurveyEnum,
    )


class SemaphoreSurveyEnum(SemaphoreSurveyEntity, SelectEntity):
    """Value of an ``enum`` survey variable (shown by its label)."""

    def __init__(
        self, coordinator: SemaphoreCoordinator, template_id: int, var: SurveyVar
    ) -> None:
        super().__init__(coordinator, template_id, var)
        self._current: str | None = None

    @property
    def options(self) -> list[str]:
        """Labels of the allowed values."""
        var = self.var
        return var.labels if var else []

    @property
    def current_option(self) -> str | None:
        """Selected label."""
        return self._current if self._current in self.options else None

    def _set_label(self, label: str | None) -> None:
        self._current = label
        var = self.var
        value = var.resolve(label) if var and label is not None else None
        self._remember(None if value is None else str(value))

    def _restore(self, state: str) -> None:
        if state in self.options:
            self._set_label(state)
        else:
            self._apply_default()

    def _apply_default(self) -> None:
        var = self.var
        label = var.label_of(var.default[0]) if var and var.default else None
        self._set_label(label)

    async def async_select_option(self, option: str) -> None:
        """Change the selection."""
        self._set_label(option)
        self.async_write_ha_state()
