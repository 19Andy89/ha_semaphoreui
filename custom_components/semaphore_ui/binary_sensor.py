"""Binary sensors of the Semaphore UI integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATUS_ACTIVE
from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .entity import (
    SemaphoreProjectEntity,
    SemaphoreTemplateEntity,
    registered_template_ids,
)
from .report import ha_result_text, task_status

PARALLEL_UPDATES = 0

RUNNING = BinarySensorEntityDescription(
    key="running",
    translation_key="running",
    device_class=BinarySensorDeviceClass.RUNNING,
)
PROBLEM = BinarySensorEntityDescription(
    key="problem",
    translation_key="problem",
    device_class=BinarySensorDeviceClass.PROBLEM,
)
NEEDS_ACTION = BinarySensorEntityDescription(
    key="needs_action",
    translation_key="needs_action",
)
CONNECTIVITY = BinarySensorEntityDescription(
    key="connectivity",
    translation_key="connectivity",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)
PROJECT_PROBLEM = BinarySensorEntityDescription(
    key="project_problem",
    translation_key="project_problem",
    device_class=BinarySensorDeviceClass.PROBLEM,
)
PROJECT_RUNNING = BinarySensorEntityDescription(
    key="project_running",
    translation_key="project_running",
    device_class=BinarySensorDeviceClass.RUNNING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors and add those of templates created later."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SemaphoreConnectivitySensor(coordinator),
            SemaphoreProjectProblemSensor(coordinator),
            SemaphoreProjectRunningSensor(coordinator),
        ]
    )
    known: set[int] = set()

    def _add_new_templates() -> None:
        new_ids = set(coordinator.data.templates) - known
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[BinarySensorEntity] = []
        for template_id in sorted(new_ids):
            entities.append(SemaphoreRunningSensor(coordinator, template_id))
            entities.append(SemaphoreProblemSensor(coordinator, template_id))
        async_add_entities(entities)

    _add_new_templates()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_templates))

    # "Needs action" exists for templates whose playbook reports HA_RESULT
    # (and, after a restart, for those that have the entity already).
    restored = registered_template_ids(
        hass, entry.entry_id, "binary_sensor", NEEDS_ACTION.key
    )
    action_known: set[int] = set()

    def _add_action_sensors() -> None:
        wanted = (coordinator.action_template_ids() | restored) & set(
            coordinator.data.templates
        )
        new_ids = wanted - action_known
        if not new_ids:
            return
        action_known.update(new_ids)
        async_add_entities(
            SemaphoreNeedsActionSensor(coordinator, template_id)
            for template_id in sorted(new_ids)
        )

    _add_action_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_action_sensors))


class SemaphoreRunningSensor(SemaphoreTemplateEntity, BinarySensorEntity):
    """On while a task of the template is queued or running."""

    entity_description = RUNNING

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, RUNNING.key)

    @property
    def is_on(self) -> bool:
        """True if a task is active."""
        return bool(
            task_status(self.last_task) in STATUS_ACTIVE
            or self.coordinator.active_task_ids(self.template_id)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which tasks are open and whether a second start is allowed (used by the card)."""
        return {
            "task_ids": self.coordinator.open_task_ids(self.template_id),
            "parallel_allowed": self.coordinator.parallel_allowed(self.template_id),
        }


class SemaphoreProblemSensor(SemaphoreTemplateEntity, BinarySensorEntity):
    """On if the last task ended with an error."""

    entity_description = PROBLEM

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, PROBLEM.key)

    @property
    def is_on(self) -> bool:
        """True if the last task failed."""
        return task_status(self.last_task) == "error"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Why the last run failed (only while the problem exists)."""
        info = self.coordinator.failure_for(self.template_id)
        if info is None:
            return None
        return {
            "reason": info["reason"],
            "failed_task": info["failed_task"],
            "host": info["host"],
            "task_id": info["task_id"],
            "finished": info["ended"],
            "dry_run": info["dry_run"],
            "url": info["url"],
            "explanation": self.coordinator.failure_explanation([info]),
        }


class SemaphoreNeedsActionSensor(SemaphoreTemplateEntity, BinarySensorEntity):
    """On if the last finished run reported that there is something to do.

    The playbook prints ``HA_RESULT {"updates": 3, "reboot_required": false}``;
    unknown while the last finished run reported nothing.
    """

    entity_description = NEEDS_ACTION
    _unrecorded_attributes = frozenset(
        {"hosts", "packages", "notes", "explanation", "task_id", "url", "checked_local"}
    )

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, NEEDS_ACTION.key)

    @property
    def is_on(self) -> bool | None:
        """True if updates are pending or a restart is required."""
        report = self.coordinator.action_report(self.template_id)
        return report["ha_result"]["needed"] if report else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """What was reported, by which run and when."""
        report = self.coordinator.action_report(self.template_id)
        if report is None:
            return None
        result = report["ha_result"]
        return {
            "updates": result["updates"],
            "reboot_required": result["reboot_required"],
            "explanation": ha_result_text(result, self.coordinator.hass.config.language),
            "hosts": result["hosts"],
            "packages": result["packages"],
            "notes": result.get("notes", []),
            "checked": report["ended"],
            "checked_local": report["ended_local"],
            "dry_run": report["dry_run"],
            "task_id": report["task_id"],
            "url": report["url"],
        }


class SemaphoreConnectivitySensor(SemaphoreProjectEntity, BinarySensorEntity):
    """Is the Semaphore API reachable (stays available while it is not)."""

    entity_description = CONNECTIVITY

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, CONNECTIVITY.key)

    @property
    def available(self) -> bool:
        """Always available - "off" is the information."""
        return True

    @property
    def is_on(self) -> bool:
        """True if the last poll worked."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Reason of the last failed poll."""
        error = self.coordinator.last_exception
        return {"error": str(error) if error and not self.is_on else None}


class SemaphoreProjectProblemSensor(SemaphoreProjectEntity, BinarySensorEntity):
    """On if at least one template ended its last run with an error."""

    entity_description = PROJECT_PROBLEM
    _unrecorded_attributes = frozenset({"failed_runs"})

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, PROJECT_PROBLEM.key)

    @property
    def is_on(self) -> bool:
        """True if a template failed."""
        return bool(self.coordinator.failed_template_names())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which templates failed, where (step/host) and why."""
        infos = self.coordinator.failures()
        return {
            "templates": [info["template"] for info in infos],
            "failed_count": len(infos),
            "explanation": self.coordinator.failure_explanation(infos),
            "failed_runs": infos,
        }


class SemaphoreProjectRunningSensor(SemaphoreProjectEntity, BinarySensorEntity):
    """On while at least one template of the project is queued or running."""

    entity_description = PROJECT_RUNNING
    _unrecorded_attributes = frozenset({"details", "task_ids"})

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, PROJECT_RUNNING.key)

    @property
    def is_on(self) -> bool:
        """True if a task is queued or running (also one started in Semaphore itself)."""
        return bool(self.coordinator.running_items())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which templates run (names, tasks, start)."""
        items = self.coordinator.running_items()
        return {
            "templates": [item["template"] for item in items],
            "task_ids": sorted({task for item in items for task in item["task_ids"]}),
            "details": items,
        }
