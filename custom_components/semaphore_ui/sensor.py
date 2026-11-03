"""Sensors of the Semaphore UI integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import STATUS_OPTIONS
from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .entity import (
    SemaphoreProjectEntity,
    SemaphoreTemplateEntity,
    registered_template_ids,
)
from .report import (
    REPORT_KEYS,
    is_dry_run,
    task_duration,
    task_ended,
    task_started,
    task_status,
)
from .tokens import SemaphoreTokenCoordinator

PARALLEL_UPDATES = 0

PENDING_KEY = "pending_updates"
NEXT_RUN_KEY = "next_run"


@dataclass(frozen=True, kw_only=True)
class SemaphoreSensorDescription(SensorEntityDescription):
    """Description of a template sensor."""

    value_fn: Callable[[dict[str, Any] | None], StateType | datetime]


TEMPLATE_SENSORS: tuple[SemaphoreSensorDescription, ...] = (
    SemaphoreSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value_fn=task_status,
    ),
    SemaphoreSensorDescription(
        key="last_started",
        translation_key="last_started",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=task_started,
    ),
    SemaphoreSensorDescription(
        key="last_ended",
        translation_key="last_ended",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=task_ended,
    ),
    SemaphoreSensorDescription(
        key="last_duration",
        translation_key="last_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        value_fn=task_duration,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors and add sensors of templates created later."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SemaphoreRunningTasksSensor(coordinator),
            SemaphoreTemplateCountSensor(coordinator),
            SemaphoreFailedTemplatesSensor(coordinator),
            SemaphoreActionTemplatesSensor(coordinator),
            SemaphoreLastTaskTemplateSensor(coordinator),
            SemaphoreLastTaskStatusSensor(coordinator),
            SemaphoreLastTaskStartedSensor(coordinator),
            SemaphoreProjectNextRunSensor(coordinator),
        ]
    )

    if coordinator.token_coordinator is not None:
        async_add_entities(
            [SemaphoreTokenExpirySensor(coordinator, coordinator.token_coordinator)]
        )

    known: set[int] = set()

    def _add_new_templates() -> None:
        new_ids = set(coordinator.data.templates) - known
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[SensorEntity] = []
        for template_id in sorted(new_ids):
            entities.extend(
                SemaphoreTemplateSensor(coordinator, template_id, description)
                for description in TEMPLATE_SENSORS
            )
            entities.append(SemaphoreSummarySensor(coordinator, template_id))
            entities.append(SemaphoreLastSuccessSensor(coordinator, template_id))
        async_add_entities(entities)

    _add_new_templates()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_templates))

    # "Pending updates" exists for templates whose playbook reports HA_RESULT
    # (and, after a restart, for those that have the entity already).
    restored = registered_template_ids(hass, entry.entry_id, "sensor", PENDING_KEY)
    pending_known: set[int] = set()

    def _add_pending_sensors() -> None:
        wanted = (coordinator.action_template_ids() | restored) & set(
            coordinator.data.templates
        )
        new_ids = wanted - pending_known
        if not new_ids:
            return
        pending_known.update(new_ids)
        async_add_entities(
            SemaphorePendingUpdatesSensor(coordinator, template_id)
            for template_id in sorted(new_ids)
        )

    _add_pending_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_pending_sensors))

    # "Next run" exists for templates that have a schedule in Semaphore
    # (and, after a restart, for those that have the entity already).
    next_restored = registered_template_ids(hass, entry.entry_id, "sensor", NEXT_RUN_KEY)
    next_known: set[int] = set()

    def _add_next_run_sensors() -> None:
        wanted = (coordinator.schedule_template_ids() | next_restored) & set(
            coordinator.data.templates
        )
        new_ids = wanted - next_known
        if not new_ids:
            return
        next_known.update(new_ids)
        async_add_entities(
            SemaphoreNextRunSensor(coordinator, template_id)
            for template_id in sorted(new_ids)
        )

    _add_next_run_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_next_run_sensors))


class SemaphoreTokenExpirySensor(CoordinatorEntity[SemaphoreTokenCoordinator], SensorEntity):
    """Until when the API token of this integration is valid (unknown: it never expires)."""

    _attr_has_entity_name = True
    _attr_translation_key = "token_expires"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SemaphoreCoordinator,
        token_coordinator: SemaphoreTokenCoordinator,
    ) -> None:
        super().__init__(token_coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_token_expires"
        self._attr_device_info = coordinator.project_device_info()

    @property
    def native_value(self) -> datetime | None:
        """End of the validity (``None``: no expiry, or this Semaphore does not tell)."""
        data = self.coordinator.data
        return data.expires_at if data is not None and data.found else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Name, creation, renewal settings and the last renewal of the token."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "token_found": data.found,
            "token_name": data.name,
            "created": data.created.isoformat() if data.created else None,
            "never_expires": data.found and data.expires_at is None,
            "auto_renew": self.coordinator.renew,
            "renew_days_before": self.coordinator.days,
            "stored_login": self.coordinator.has_login,
            "last_renewed": data.last_renewed.isoformat() if data.last_renewed else None,
            "renew_error": data.renew_error,
        }


class SemaphoreRunningTasksSensor(SemaphoreProjectEntity, SensorEntity):
    """Number of tasks that are queued or running in the project."""

    _attr_translation_key = "running_tasks"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"details", "task_ids"})

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "running_tasks")

    @property
    def native_value(self) -> int:
        """Number of active tasks."""
        return self.coordinator.running_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which templates are queued or running (names, tasks, start)."""
        items = self.coordinator.running_items()
        return {
            "templates": [item["template"] for item in items],
            "task_ids": sorted({task for item in items for task in item["task_ids"]}),
            "details": items,
        }


class SemaphoreTemplateCountSensor(SemaphoreProjectEntity, SensorEntity):
    """Number of templates in the project."""

    _attr_translation_key = "template_count"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "template_count")

    @property
    def native_value(self) -> int:
        """Number of templates."""
        return len(self.coordinator.data.templates)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Names of the templates shown in Home Assistant and of those left out in the options."""
        data = self.coordinator.data
        return {
            "templates": sorted(
                t.get("name", str(t["id"])) for t in data.templates.values()
            ),
            "excluded": sorted(
                name for tid, name in data.all_templates.items() if tid not in data.templates
            ),
        }


class SemaphoreFailedTemplatesSensor(SemaphoreProjectEntity, SensorEntity):
    """Number of templates whose last run failed."""

    _attr_translation_key = "failed_templates"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"failed_runs"})

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "failed_templates")

    @property
    def native_value(self) -> int:
        """Number of failed templates."""
        return len(self.coordinator.failures())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which templates failed, where (step/host) and why."""
        infos = self.coordinator.failures()
        return {
            "templates": [info["template"] for info in infos],
            "explanation": self.coordinator.failure_explanation(infos),
            "failed_runs": infos,
        }


class SemaphoreActionTemplatesSensor(SemaphoreProjectEntity, SensorEntity):
    """Number of templates whose last run reported that something is to do."""

    _attr_translation_key = "action_templates"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"details", "explanation"})

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "action_templates")

    @property
    def native_value(self) -> int:
        """Number of templates with ``needed`` in their ``HA_RESULT``."""
        return len(self.coordinator.action_items())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which templates, how many updates, restart needed, hosts."""
        items = self.coordinator.action_items()
        return {
            "templates": [item["template"] for item in items],
            "explanation": self.coordinator.action_explanation(items),
            "details": items,
        }


class SemaphorePendingUpdatesSensor(SemaphoreTemplateEntity, SensorEntity):
    """Number of pending updates the last finished run reported (``HA_RESULT``)."""

    _attr_translation_key = PENDING_KEY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, PENDING_KEY)

    @property
    def native_value(self) -> int | None:
        """``updates`` of the last ``HA_RESULT`` (unknown if there is none)."""
        report = self.coordinator.action_report(self.template_id)
        return report["ha_result"]["updates"] if report else None


class SemaphoreProjectNextRunSensor(SemaphoreProjectEntity, SensorEntity):
    """When the next schedule of the project starts a task."""

    _attr_translation_key = "project_next_run"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = frozenset({"schedules"})

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "project_next_run")

    @property
    def native_value(self) -> datetime | None:
        """Start of the next scheduled run (unknown if no schedule is active)."""
        item = self.coordinator.next_scheduled()
        return dt_util.parse_datetime(item["next_run"]) if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which schedule runs next and all schedules of the project."""
        item = self.coordinator.next_scheduled()
        return {
            "schedule": item["name"] if item else None,
            "template": item["template"] if item else None,
            "timezone": self.coordinator.schedule_timezone,
            "schedules": self.coordinator.schedule_items(),
        }


class SemaphoreNextRunSensor(SemaphoreTemplateEntity, SensorEntity):
    """When the next schedule of the template starts a task."""

    _attr_translation_key = NEXT_RUN_KEY
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = frozenset({"schedules"})

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, NEXT_RUN_KEY)

    @property
    def native_value(self) -> datetime | None:
        """Start of the next scheduled run (unknown if no schedule is active)."""
        item = self.coordinator.next_scheduled(self.template_id)
        return dt_util.parse_datetime(item["next_run"]) if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The schedule that runs next and all schedules of the template."""
        item = self.coordinator.next_scheduled(self.template_id)
        return {
            "schedule": item["name"] if item else None,
            "timezone": self.coordinator.schedule_timezone,
            "schedules": self.coordinator.schedule_items(self.template_id),
        }


class SemaphoreLastSuccessSensor(SemaphoreTemplateEntity, SensorEntity):
    """When the template last ended successfully (a dry run counts, see ``dry_run``)."""

    _attr_translation_key = "last_success"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, "last_success")

    @property
    def native_value(self) -> datetime | None:
        """End of the newest successful task (unknown if there never was one)."""
        return task_ended(self.coordinator.last_success_task(self.template_id))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Which task it was."""
        task = self.coordinator.last_success_task(self.template_id)
        if task is None:
            return None
        return {
            "task_id": task.get("id"),
            "started": (task_started(task) or None) and task_started(task).isoformat(),
            "duration": task_duration(task),
            "dry_run": is_dry_run(task),
        }


class _SemaphoreLastTaskEntity(SemaphoreProjectEntity, SensorEntity):
    """Base for the sensors about the most recent task of the project."""

    # The report is large and changes with every task; keep it out of the recorder.
    _unrecorded_attributes = frozenset(REPORT_KEYS)

    @property
    def _last(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        return self.coordinator.last_task()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The report of that task (same content as the events)."""
        last = self._last
        if last is None:
            return None
        return self.coordinator.report_for(last[0]["id"])


class SemaphoreLastTaskTemplateSensor(_SemaphoreLastTaskEntity):
    """Name of the template that ran last."""

    _attr_translation_key = "last_task_template"

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "last_task_template")

    @property
    def native_value(self) -> str | None:
        """Template name."""
        last = self._last
        return last[0].get("name") if last else None


class SemaphoreLastTaskStatusSensor(_SemaphoreLastTaskEntity):
    """Status of the task that ran last (any template)."""

    _attr_translation_key = "last_task_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "last_task_status")

    @property
    def native_value(self) -> str:
        """Raw Semaphore status."""
        last = self._last
        return task_status(last[1]) if last else task_status(None)


class SemaphoreLastTaskStartedSensor(_SemaphoreLastTaskEntity):
    """When the task that ran last was started."""

    _attr_translation_key = "last_task_started"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        super().__init__(coordinator, "last_task_started")

    @property
    def native_value(self) -> datetime | None:
        """Start time."""
        last = self._last
        return task_started(last[1]) if last else None


class SemaphoreTemplateSensor(SemaphoreTemplateEntity, SensorEntity):
    """Status / start / end / duration of the last task of a template."""

    entity_description: SemaphoreSensorDescription

    def __init__(
        self,
        coordinator: SemaphoreCoordinator,
        template_id: int,
        description: SemaphoreSensorDescription,
    ) -> None:
        super().__init__(coordinator, template_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Value of the sensor."""
        return self.entity_description.value_fn(self.last_task)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """While a task runs and live updates are on: the Ansible step it is in."""
        if self.entity_description.key != "status":
            return None
        step = self.coordinator.current_step(self.template_id)
        if step is None:
            return None
        return {"current_step": step[1], "step_number": step[0]}


class SemaphoreSummarySensor(SemaphoreTemplateEntity, SensorEntity):
    """One-line summary; the attributes hold the complete report (JSON)."""

    _attr_translation_key = "summary"
    # The report is large and changes with every task; keep it out of the recorder.
    _unrecorded_attributes = frozenset(REPORT_KEYS)

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, "summary")

    @property
    def native_value(self) -> str:
        """Short text, e.g. ``✅ erfolgreich · 1 Min 12 s · 24.10. 14:03``."""
        return self.coordinator.report_for(self.template_id)["short"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The complete report of the last task."""
        return self.coordinator.report_for(self.template_id)
