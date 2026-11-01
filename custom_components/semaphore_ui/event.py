"""Event entity: one event per started/finished task of the project."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES
from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .entity import SemaphoreProjectEntity
from .report import REPORT_KEYS

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entity."""
    async_add_entities([SemaphoreTaskEvent(entry.runtime_data)])


class SemaphoreTaskEvent(SemaphoreProjectEntity, EventEntity):
    """Fires ``started`` / ``success`` / ``failed`` / ``stopped``.

    The attributes of the entity hold the complete report of the task, so an
    automation with the trigger "event received" can use ``title`` and ``text``
    for a push message.
    """

    _attr_translation_key = "tasks"
    _attr_event_types = EVENT_TYPES
    _unrecorded_attributes = frozenset(REPORT_KEYS)

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "tasks")

    async def async_added_to_hass(self) -> None:
        """Listen to the task events of the coordinator."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_task_listener(self._on_task))

    @callback
    def _on_task(self, event_type: str, report: dict[str, Any]) -> None:
        if event_type not in EVENT_TYPES:
            return
        self._trigger_event(event_type, report)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Polling does not change the last event."""
        self.async_write_ha_state()
