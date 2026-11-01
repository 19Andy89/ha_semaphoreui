"""Base entities of the Semaphore UI integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SemaphoreCoordinator


def registered_template_ids(
    hass: HomeAssistant, entry_id: str, domain: str, key: str
) -> set[int]:
    """Templates that already have the entity ``key`` in the entity registry.

    Entities that exist only for some templates (e.g. "needs action") are created
    when the first result shows up; after a restart they are restored from here, even
    if the last run did not report anything.
    """
    prefix, suffix = f"{entry_id}_", f"_{key}"
    found: set[int] = set()
    for entity in er.async_entries_for_config_entry(er.async_get(hass), entry_id):
        unique_id = entity.unique_id
        if (
            entity.domain == domain
            and unique_id.startswith(prefix)
            and unique_id.endswith(suffix)
        ):
            middle = unique_id[len(prefix) : len(unique_id) - len(suffix)]
            if middle.isdigit():
                found.add(int(middle))
    return found


class SemaphoreProjectEntity(CoordinatorEntity[SemaphoreCoordinator]):
    """Entity that belongs to the project device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SemaphoreCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = coordinator.project_device_info()


class SemaphoreTemplateEntity(CoordinatorEntity[SemaphoreCoordinator]):
    """Entity that belongs to the device of one template."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SemaphoreCoordinator, template_id: int, key: str
    ) -> None:
        super().__init__(coordinator)
        self.template_id = template_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{template_id}_{key}"
        )
        self._attr_device_info: DeviceInfo = coordinator.template_device_info(
            template_id
        )

    @property
    def template(self) -> dict[str, Any] | None:
        """Current data of the template (``None`` if it was deleted)."""
        return self.coordinator.data.templates.get(self.template_id)

    @property
    def last_task(self) -> dict[str, Any] | None:
        """Last task of the template."""
        template = self.template
        return template.get("last_task") if template else None

    @property
    def available(self) -> bool:
        """Available while the template exists."""
        return super().available and self.template is not None
