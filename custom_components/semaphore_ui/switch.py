"""Switches of the Semaphore UI integration: one per schedule."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .entity import registered_template_ids

PARALLEL_UPDATES = 0

SCHEDULE_KEY = "schedule"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a switch for every schedule of the project (also for those created later)."""
    coordinator = entry.runtime_data
    known: set[int] = set()
    # unique ids are "<entry>_<schedule id>_schedule" - the helper reads the middle number
    registered = registered_template_ids(hass, entry.entry_id, "switch", SCHEDULE_KEY)

    def _sync() -> None:
        schedules = coordinator.data.schedules
        wanted = {
            sid
            for sid, item in schedules.items()
            if item.get("template_id") in coordinator.data.templates
        }
        new_ids = wanted - known
        if new_ids:
            known.update(new_ids)
            async_add_entities(
                SemaphoreScheduleSwitch(coordinator, sid) for sid in sorted(new_ids)
            )
        if coordinator.schedules_loaded:
            # schedules deleted in Semaphore: remove their switches as well
            registry = er.async_get(hass)
            for sid in (known | registered) - set(schedules):
                entity_id = registry.async_get_entity_id(
                    "switch", DOMAIN, f"{entry.entry_id}_{sid}_{SCHEDULE_KEY}"
                )
                if entity_id:
                    registry.async_remove(entity_id)
                known.discard(sid)
                registered.discard(sid)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class SemaphoreScheduleSwitch(CoordinatorEntity[SemaphoreCoordinator], SwitchEntity):
    """On if the schedule is active in Semaphore; switching changes only that flag."""

    _attr_has_entity_name = True
    _attr_translation_key = SCHEDULE_KEY
    _unrecorded_attributes = frozenset({"cron", "template", "type", "delete_after_run"})

    def __init__(self, coordinator: SemaphoreCoordinator, schedule_id: int) -> None:
        super().__init__(coordinator)
        self.schedule_id = schedule_id
        schedule = coordinator.data.schedules[schedule_id]
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{schedule_id}_{SCHEDULE_KEY}"
        )
        self._attr_translation_placeholders = {
            "name": str(schedule.get("name") or schedule_id)
        }
        # the schedule belongs to the device of its template
        self._attr_device_info = coordinator.template_device_info(schedule["template_id"])

    async def async_added_to_hass(self) -> None:
        """Let the sensors read the new entity id (the cards use it for the toggle)."""
        await super().async_added_to_hass()
        self.coordinator.async_update_listeners()

    @property
    def schedule(self) -> dict[str, Any] | None:
        """Current data of the schedule (``None`` if it was deleted in Semaphore)."""
        return self.coordinator.data.schedules.get(self.schedule_id)

    @property
    def available(self) -> bool:
        """Available while the schedule exists."""
        return super().available and self.schedule is not None

    @property
    def is_on(self) -> bool:
        """True if Semaphore runs the schedule."""
        schedule = self.schedule
        return bool(schedule and schedule.get("active"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Cron text, template and the next run."""
        schedule = self.schedule
        if schedule is None:
            return None
        upcoming = self.coordinator.next_run(schedule)
        return {
            "cron": schedule.get("cron_format") or "",
            "type": schedule.get("type") or "cron",
            "template": (self.coordinator.data.templates.get(schedule.get("template_id")) or {}).get("name"),
            "delete_after_run": bool(schedule.get("delete_after_run")),
            "next_run": upcoming.isoformat() if upcoming else None,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate the schedule."""
        await self.coordinator.async_set_schedule_active(self.schedule_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Deactivate the schedule."""
        await self.coordinator.async_set_schedule_active(self.schedule_id, False)
