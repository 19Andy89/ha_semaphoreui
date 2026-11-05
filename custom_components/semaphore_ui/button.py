"""Buttons of the Semaphore UI integration (start, dry run, stop)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DRY_RUN_APPS
from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .entity import SemaphoreTemplateEntity

PARALLEL_UPDATES = 1

START = ButtonEntityDescription(key="start", translation_key="start")
DRY_RUN = ButtonEntityDescription(key="dry_run", translation_key="dry_run")
STOP = ButtonEntityDescription(key="stop", translation_key="stop")
DISMISS = ButtonEntityDescription(key="dismiss", translation_key="dismiss")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons and add those of templates created later."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    def _add_new_templates() -> None:
        new_ids = set(coordinator.data.templates) - known
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[ButtonEntity] = []
        for template_id in sorted(new_ids):
            template = coordinator.data.templates[template_id]
            entities.append(SemaphoreStartButton(coordinator, template_id, dry_run=False))
            if (template.get("app") or "") in DRY_RUN_APPS:
                entities.append(
                    SemaphoreStartButton(coordinator, template_id, dry_run=True)
                )
            entities.append(SemaphoreStopButton(coordinator, template_id))
            entities.append(SemaphoreDismissButton(coordinator, template_id))
        async_add_entities(entities)

    _add_new_templates()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_templates))


class SemaphoreStartButton(SemaphoreTemplateEntity, ButtonEntity):
    """Starts a task of the template (optionally as dry run)."""

    def __init__(
        self, coordinator: SemaphoreCoordinator, template_id: int, *, dry_run: bool
    ) -> None:
        description = DRY_RUN if dry_run else START
        super().__init__(coordinator, template_id, description.key)
        self.entity_description = description
        self._dry_run = dry_run

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Survey variables without an input entity (secrets, multi-selects): the card asks for them in a dialog."""
        extra = [
            {
                "name": var.name,
                "title": var.title,
                "kind": "secret" if var.is_secret else "multi",
                "required": var.required,
                "description": var.description or None,
                "options": var.labels if var.is_multi else None,
                # a default of a secret is never handed to the browser
                "default": None if var.is_secret else [var.label_of(d) or d for d in var.default],
            }
            for var in self.coordinator.survey_vars(self.template_id)
            if var.is_secret or var.is_multi
        ]
        return {"survey_dialog": extra} if extra else None

    async def async_press(self) -> None:
        """Start the task."""
        await self.coordinator.async_run_template(
            self.template_id,
            dry_run=self._dry_run,
            survey=self.coordinator.survey_values(self.template_id),
        )


class SemaphoreStopButton(SemaphoreTemplateEntity, ButtonEntity):
    """Stops the running task of the template."""

    entity_description = STOP

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, STOP.key)

    @property
    def available(self) -> bool:
        """Only available while a task is active."""
        return super().available and bool(
            self.coordinator.active_task_ids(self.template_id)
        )

    async def async_press(self) -> None:
        """Stop the task."""
        await self.coordinator.async_stop_template(self.template_id)


class SemaphoreDismissButton(SemaphoreTemplateEntity, ButtonEntity):
    """Marks the last finished run as done: the project card hides the template (if it shows recent runs)."""

    entity_description = DISMISS

    def __init__(self, coordinator: SemaphoreCoordinator, template_id: int) -> None:
        super().__init__(coordinator, template_id, DISMISS.key)

    @property
    def available(self) -> bool:
        """Not while a task is active: only a finished run can be marked as done."""
        return super().available and not self.coordinator.active_task_ids(self.template_id)

    async def async_press(self) -> None:
        """Hide the template until its next run."""
        await self.coordinator.async_dismiss_template(self.template_id)
