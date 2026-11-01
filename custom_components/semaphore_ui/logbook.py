"""Logbook entries for the task events of Semaphore UI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_TASK_FINISHED, EVENT_TASK_STARTED


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[Event[Any]], dict[str, str]]], None
    ],
) -> None:
    """Describe ``semaphore_ui_task_started`` / ``..._finished`` in the logbook."""

    @callback
    def _describe(event: Event[Any]) -> dict[str, str]:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: f"Semaphore – {data.get('template', '?')}",
            # "short" is the ready-made one-liner of the report (language of HA)
            LOGBOOK_ENTRY_MESSAGE: data.get("short") or data.get("title") or "",
        }

    async_describe_event(DOMAIN, EVENT_TASK_STARTED, _describe)
    async_describe_event(DOMAIN, EVENT_TASK_FINISHED, _describe)
