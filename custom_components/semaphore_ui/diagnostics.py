"""Diagnostics of the Semaphore UI integration (token and address are redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant

from .cards import cards_status
from .const import CONF_API_TOKEN
from .coordinator import SemaphoreConfigEntry
from .report import task_status

TO_REDACT = {CONF_API_TOKEN, CONF_URL, "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SemaphoreConfigEntry
) -> dict[str, Any]:
    """Return the state of the integration without secrets, task outputs or notes."""
    coordinator = entry.runtime_data
    version = coordinator.version_coordinator

    templates = []
    for template_id, template in sorted(coordinator.data.templates.items()):
        last = template.get("last_task") or {}
        action = coordinator.action_report(template_id)
        templates.append(
            {
                "id": template_id,
                "name": template.get("name"),
                "app": template.get("app"),
                "status": task_status(last) if last else "never_run",
                "last_task_id": last.get("id"),
                "active_task_ids": coordinator.active_task_ids(template_id),
                "ha_result": (
                    {
                        "needed": action["ha_result"]["needed"],
                        "updates": action["ha_result"]["updates"],
                        "reboot_required": action["ha_result"]["reboot_required"],
                        "hosts": list(action["ha_result"]["hosts"]),
                        "task_id": action["task_id"],
                    }
                    if action
                    else None
                ),
                "survey": [
                    {"name": var.name, "type": var.type, "required": var.required}
                    for var in coordinator.survey_vars(template_id)
                ],
            }
        )

    interval = coordinator.update_interval
    version_data = version.data if version is not None else None
    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "coordinator": {
                "last_update_success": coordinator.last_update_success,
                "update_interval_seconds": (
                    interval.total_seconds() if interval else None
                ),
                "running_tasks": coordinator.running_count,
                "templates_in_project": len(coordinator.data.all_templates),
                "excluded_templates": sorted(coordinator.excluded_templates),
                "templates": templates,
            },
            "frontend": dict(cards_status(hass)),
            "version": (
                {
                    "installed": version_data.installed,
                    "installed_reported": version_data.installed_raw,
                    "latest": version_data.latest,
                }
                if version_data is not None
                else None
            ),
        },
        TO_REDACT,
    )
