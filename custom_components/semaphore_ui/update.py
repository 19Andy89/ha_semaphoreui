"""Update entity: installed vs. latest Semaphore version (read only)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    SemaphoreConfigEntry,
    SemaphoreCoordinator,
    SemaphoreVersionCoordinator,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the update entity."""
    coordinator = entry.runtime_data
    if coordinator.version_coordinator is not None:
        async_add_entities([SemaphoreUpdate(coordinator, coordinator.version_coordinator)])


class SemaphoreUpdate(CoordinatorEntity[SemaphoreVersionCoordinator], UpdateEntity):
    """Shows whether a newer Semaphore version exists (cannot install it)."""

    _attr_has_entity_name = True
    _attr_translation_key = "semaphore_update"
    _attr_title = "Semaphore UI"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SemaphoreCoordinator,
        version_coordinator: SemaphoreVersionCoordinator,
    ) -> None:
        super().__init__(version_coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_update"
        self._attr_device_info = coordinator.project_device_info()

    @property
    def installed_version(self) -> str | None:
        """Version of the running Semaphore."""
        return self.coordinator.data.installed if self.coordinator.data else None

    @property
    def latest_version(self) -> str | None:
        """Latest release (unknown if the check is off or failed)."""
        return self.coordinator.data.latest if self.coordinator.data else None

    @property
    def release_url(self) -> str | None:
        """Link to the release notes."""
        return self.coordinator.data.release_url if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The version as Semaphore reports it; a release that has no Docker image yet."""
        data = self.coordinator.data
        if data is None:
            return None
        attrs: dict[str, Any] = {}
        if data.installed_raw and data.installed_raw != data.installed:
            attrs["installed_version_reported"] = data.installed_raw
        if data.pending_release:
            # shown as "no update" until the image exists
            attrs["release_not_yet_in_docker"] = data.pending_release
        return attrs or None
