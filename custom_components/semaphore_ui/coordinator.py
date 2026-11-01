"""DataUpdateCoordinator of the Semaphore UI integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import re
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import const, issues
from .api import (
    SemaphoreApiError,
    SemaphoreAuthError,
    SemaphoreClient,
    SemaphoreConnectionError,
    SemaphoreError,
    async_get_latest_release,
)
from .const import (
    ACTIVE_SCAN_INTERVAL,
    CONF_ALLOW_PARALLEL,
    CONF_CHECK_UPDATES,
    CONF_EXCLUDED_TEMPLATES,
    CONF_PROJECT_ID,
    CONF_PROJECT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_TASK_FINISHED,
    EVENT_TASK_STARTED,
    GITHUB_LATEST_URL,
    ISSUE_PROJECT,
    ISSUE_UNREACHABLE,
    MANUFACTURER,
    MODEL_PROJECT,
    MODEL_TEMPLATE,
    STATUS_ACTIVE,
    STATUS_FINISHED,
    VERSION_SCAN_INTERVAL,
)
from .report import (
    build_report,
    failure_info,
    failure_text,
    ha_result_text,
    is_dry_run,
    task_started,
    task_status,
)
from .schedule import load_timezone, next_run_of
from .survey import SurveyError, SurveyVar, build_survey_payload, parse_survey_vars

_LOGGER = logging.getLogger(__name__)

type SemaphoreConfigEntry = ConfigEntry[SemaphoreCoordinator]

TEMPLATE_IDENTIFIER_RE = re.compile(r"^(?P<entry>[^_]+)_template_(?P<tid>\d+)$")

# How often the log of a finished task is read again after reading it failed
# (Semaphore sometimes answers slowly; the log carries the failure reason and HA_RESULT).
MAX_LOG_ATTEMPTS = 5

# Newer Home Assistant versions replace ``via_device`` by ``via_device_id``.
_HAS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


@dataclass
class SemaphoreData:
    """Data of one update: the templates (with ``last_task``) and the schedules of the project.

    ``templates`` holds only the templates that are shown in Home Assistant; ``all_templates``
    (id -> name) holds every template of the project, also those excluded in the options.
    """

    templates: dict[int, dict[str, Any]] = field(default_factory=dict)
    schedules: dict[int, dict[str, Any]] = field(default_factory=dict)
    all_templates: dict[int, str] = field(default_factory=dict)


def template_identifier(entry_id: str, template_id: int) -> tuple[str, str]:
    """Device identifier of a template."""
    return (DOMAIN, f"{entry_id}_template_{template_id}")


class SemaphoreCoordinator(DataUpdateCoordinator[SemaphoreData]):
    """Polls the templates of one Semaphore project and fires task events."""

    config_entry: SemaphoreConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SemaphoreConfigEntry,
        client: SemaphoreClient,
    ) -> None:
        self._base_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=self._base_interval,
        )
        self.client = client
        self.project_id: int = entry.data[CONF_PROJECT_ID]
        self.project_name: str = entry.data[CONF_PROJECT_NAME]
        self.base_url: str = client.base_url
        self.project_device_id: str | None = None
        self.version_coordinator: SemaphoreVersionCoordinator | None = None
        # a template may be started while one of its runs is queued/running
        self.allow_parallel: bool = entry.options.get(CONF_ALLOW_PARALLEL, False)
        # templates that get no devices/entities (option "Templates")
        self.excluded_templates: set[int] = {
            int(tid) for tid in entry.options.get(CONF_EXCLUDED_TEMPLATES, [])
        }
        # template_id -> lock around "check that nothing runs" + "start" (double clicks)
        self._start_locks: dict[int, asyncio.Lock] = {}
        self._task_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        # template_id -> {survey variable -> value of the input entity}
        self._survey_values: dict[int, dict[str, Any]] = {}
        # task_id -> template_id of tasks we have seen running
        self._active: dict[int, int] = {}
        # task ids whose end was already handled
        self._reported: set[int] = set()
        # template_id -> report of the last finished task (including log analysis)
        self._reports: dict[int, dict[str, Any]] = {}
        # task_id -> number of failed attempts to read its log
        self._log_failed: dict[int, int] = {}
        # template_id -> newest successful task (None: none found in the history)
        self._last_success: dict[int, dict[str, Any] | None] = {}
        # template_id -> id of the last task for which the history was read
        self._success_checked: dict[int, int] = {}
        # True once the schedules were read successfully (a failed read keeps the old ones)
        self.schedules_loaded = False
        self._first_done = False

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    @property
    def running_count(self) -> int:
        """Number of tasks currently queued or running."""
        return len(self._active)

    def active_task_ids(self, template_id: int) -> list[int]:
        """Active task ids of a template."""
        return [tid for tid, tpl in self._active.items() if tpl == template_id]

    def open_task_ids(self, template_id: int) -> list[int]:
        """Tasks of a template that are queued or running (seen by us or by the last poll)."""
        ids = set(self.active_task_ids(template_id))
        last = (self.data.templates.get(template_id) or {}).get("last_task") or {}
        if last.get("status") in STATUS_ACTIVE and "id" in last:
            ids.add(last["id"])
        return sorted(ids)

    def running_items(self) -> list[dict[str, Any]]:
        """Templates with a queued or running task, sorted by name (for the project entities)."""
        items: list[dict[str, Any]] = []
        for tid, template in self.data.templates.items():
            ids = self.open_task_ids(tid)
            if not ids:
                continue
            last = template.get("last_task") or {}
            current = last if last.get("id") in ids else {}
            started = task_started(current) if current else None
            items.append(
                {
                    "template": template.get("name") or f"#{tid}",
                    "template_id": tid,
                    "task_ids": ids,
                    "status": task_status(current) if current else "running",
                    "dry_run": is_dry_run(current) if current else False,
                    "started": started.isoformat() if started else None,
                }
            )
        return sorted(items, key=lambda item: str(item["template"]).lower())

    def parallel_allowed(self, template_id: int) -> bool:
        """May the template be started while a run of it is queued or running?

        By default not: Semaphore would queue the second run and execute it after the
        first one (or run both at once with "Allow parallel tasks"). It is allowed if
        the option of the integration is on or the template itself allows parallel
        tasks in Semaphore.
        """
        template = self.data.templates.get(template_id) or {}
        return self.allow_parallel or bool(template.get("allow_parallel_tasks"))

    def _ensure_not_running(self, template_id: int, template: dict[str, Any]) -> None:
        """Refuse a second start while a run of the template is queued or running."""
        if self.parallel_allowed(template_id):
            return
        open_ids = self.open_task_ids(template_id)
        if open_ids:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="already_running",
                translation_placeholders={
                    "template": template.get("name", str(template_id)),
                    "task_id": str(open_ids[0]),
                },
            )

    # ---- survey variables ---------------------------------------------- #
    def survey_vars(self, template_id: int) -> list[SurveyVar]:
        """Survey variables of a template."""
        template = self.data.templates.get(template_id) if self.data else None
        return parse_survey_vars(template) if template else []

    def survey_values(self, template_id: int) -> dict[str, Any]:
        """Values currently set in the input entities of a template."""
        return dict(self._survey_values.get(template_id, {}))

    def set_survey_value(self, template_id: int, name: str, value: Any) -> None:
        """Remember the value of an input entity (``None`` = not set)."""
        values = self._survey_values.setdefault(template_id, {})
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value

    # ---- events -------------------------------------------------------- #
    def async_add_task_listener(
        self, listener: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Call ``listener(event_type, report)`` for every started/finished task."""
        self._task_listeners.append(listener)

        def _remove() -> None:
            self._task_listeners.remove(listener)

        return _remove

    def _emit(self, started: bool, report: dict[str, Any]) -> None:
        """Fire the bus event and notify the ``Tasks`` event entity."""
        self.hass.bus.async_fire(
            EVENT_TASK_STARTED if started else EVENT_TASK_FINISHED, report
        )
        event_type = "started" if started else report["result"]
        for listener in list(self._task_listeners):
            listener(event_type, report)

    # ---- project level values ------------------------------------------ #
    def last_task(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """(template, task) of the most recent task of the whole project."""
        best: tuple[dict[str, Any], dict[str, Any]] | None = None
        for template in self.data.templates.values():
            task = template.get("last_task")
            if task and "id" in task and (best is None or task["id"] > best[1]["id"]):
                best = (template, task)
        return best

    def failed_template_names(self) -> list[str]:
        """Templates whose last run ended with an error."""
        return sorted(
            template.get("name", str(template["id"]))
            for template in self.data.templates.values()
            if (template.get("last_task") or {}).get("status") == "error"
        )

    def failure_for(self, template_id: int) -> dict[str, Any] | None:
        """Why/where the last run of a template failed (``None`` if it did not)."""
        template = self.data.templates.get(template_id)
        if template is None or task_status(template.get("last_task")) != "error":
            return None
        return failure_info(self.report_for(template_id))

    def failures(self) -> list[dict[str, Any]]:
        """Details of every template whose last run failed (sorted by name)."""
        found = [
            info
            for template_id in self.data.templates
            if (info := self.failure_for(template_id)) is not None
        ]
        return sorted(found, key=lambda info: str(info["template"]).lower())

    def failure_explanation(self, infos: list[dict[str, Any]] | None = None) -> str | None:
        """Readable text for the attributes (one line per failed template)."""
        infos = self.failures() if infos is None else infos
        if not infos:
            return None
        return "\n".join(failure_text(info, self._lang) for info in infos)

    # ---- "something to do" (HA_RESULT of the last finished run) -------------- #
    def action_report(self, template_id: int) -> dict[str, Any] | None:
        """Report of the last finished run of a template if it printed ``HA_RESULT``.

        Only the last *finished* run counts: while a new run is queued or running
        the previous result stays; a finished run without the marker (or a log that
        could not be read) makes the result unknown.
        """
        if template_id not in self.data.templates:
            return None
        report = self._reports.get(template_id)
        return report if report and report.get("ha_result") else None

    def action_template_ids(self) -> set[int]:
        """Templates whose last finished run reported ``HA_RESULT``."""
        return {tid for tid in self.data.templates if self.action_report(tid)}

    def action_items(self) -> list[dict[str, Any]]:
        """Templates that need action according to ``HA_RESULT`` (sorted by name)."""
        items: list[dict[str, Any]] = []
        for tid, template in self.data.templates.items():
            report = self.action_report(tid)
            if report is None or not report["ha_result"]["needed"]:
                continue
            result = report["ha_result"]
            items.append(
                {
                    "template": template.get("name") or report["template"],
                    "template_id": tid,
                    "updates": result["updates"],
                    "reboot_required": result["reboot_required"],
                    "hosts": [
                        host for host, info in result["hosts"].items() if info["needed"]
                    ],
                    "notes": result.get("notes", []),
                    "dry_run": report["dry_run"],
                    "checked": report["ended"],
                    "checked_local": report["ended_local"],
                    "task_id": report["task_id"],
                    "text": ha_result_text(result, self._lang),
                }
            )
        return sorted(items, key=lambda item: str(item["template"]).lower())

    def action_explanation(self, items: list[dict[str, Any]] | None = None) -> str | None:
        """Readable text for the attributes (one line per template)."""
        items = self.action_items() if items is None else items
        if not items:
            return None
        return "\n".join(f"{item['template']}: {item['text']}" for item in items)

    # ------------------------------------------------------------------ #
    # Schedules and "last success"
    # ------------------------------------------------------------------ #
    def last_success_task(self, template_id: int) -> dict[str, Any] | None:
        """Newest successful task of the template (``None`` if there is none)."""
        return self._last_success.get(template_id)

    @property
    def schedule_timezone(self) -> str:
        """Time zone Semaphore evaluates its schedules in (``/api/info``, default UTC)."""
        version = self.version_coordinator
        zone = version.data.schedule_timezone if version and version.data else None
        return zone or "UTC"

    def schedule_entity_id(self, schedule_id: int) -> str | None:
        """Entity id of the switch of a schedule (for the cards)."""
        return er.async_get(self.hass).async_get_entity_id(
            "switch", DOMAIN, f"{self.config_entry.entry_id}_{schedule_id}_schedule"
        )

    def schedule_template_ids(self) -> set[int]:
        """Templates that have at least one schedule."""
        return {
            item["template_id"]
            for item in self.data.schedules.values()
            if item.get("template_id") in self.data.templates
        }

    def next_run(self, schedule: dict[str, Any]) -> datetime | None:
        """Next run of one schedule (``None``: off, not predictable or invalid)."""
        return next_run_of(
            schedule, dt_util.utcnow(), load_timezone(self.schedule_timezone)
        )

    def schedule_items(self, template_id: int | None = None) -> list[dict[str, Any]]:
        """The schedules for entities and cards (sorted: template, name)."""
        items: list[dict[str, Any]] = []
        for schedule in self.data.schedules.values():
            tid = schedule.get("template_id")
            template = self.data.templates.get(tid)
            if template is None or (template_id is not None and tid != template_id):
                continue
            upcoming = self.next_run(schedule)
            items.append(
                {
                    "id": schedule["id"],
                    "name": schedule.get("name") or f"#{schedule['id']}",
                    "template": template.get("name"),
                    "template_id": tid,
                    "cron": schedule.get("cron_format") or "",
                    "type": schedule.get("type") or "cron",
                    "run_at": schedule.get("run_at"),
                    "active": bool(schedule.get("active")),
                    "next_run": upcoming.isoformat() if upcoming else None,
                    "delete_after_run": bool(schedule.get("delete_after_run")),
                    "repository_id": schedule.get("repository_id"),
                    "entity_id": self.schedule_entity_id(schedule["id"]),
                }
            )
        items.sort(key=lambda i: ((i["template"] or "").lower(), i["name"].lower(), i["id"]))
        return items

    def next_scheduled(self, template_id: int | None = None) -> dict[str, Any] | None:
        """The schedule that runs next (of one template or of the whole project)."""
        coming = [i for i in self.schedule_items(template_id) if i["next_run"]]
        return min(coming, key=lambda i: i["next_run"]) if coming else None

    async def async_set_schedule_active(self, schedule_id: int, active: bool) -> None:
        """Switch a schedule on or off in Semaphore."""
        schedule = self.data.schedules.get(schedule_id)
        if schedule is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="schedule_not_found",
                translation_placeholders={"schedule_id": str(schedule_id)},
            )
        try:
            await self.client.set_schedule_active(self.project_id, schedule_id, active)
        except SemaphoreAuthError as err:
            raise self._auth_failed_in_action(err) from err
        except SemaphoreError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="schedule_failed",
                translation_placeholders={
                    "schedule": str(schedule.get("name") or schedule_id),
                    "error": str(err),
                },
            ) from err
        schedule["active"] = active  # show it at once, the next poll confirms it
        self.async_update_listeners()
        await self.async_request_refresh()

    @property
    def _lang(self) -> str:
        return self.hass.config.language

    def _auth_failed(self, err: SemaphoreAuthError) -> ConfigEntryAuthFailed:
        """The token was rejected: show the repair and let Home Assistant ask for a new one."""
        issues.report_token_rejected(self.hass, self.config_entry)
        return ConfigEntryAuthFailed(str(err))

    def _auth_failed_in_action(self, err: SemaphoreAuthError) -> HomeAssistantError:
        """Same for a button/switch/action: reauth, repair and a readable message."""
        issues.report_token_rejected(self.hass, self.config_entry)
        self.config_entry.async_start_reauth(self.hass)
        return HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        )

    def project_device_info(self) -> DeviceInfo:
        """Device of the project."""
        entry_id = self.config_entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=f"Semaphore – {self.project_name}",
            manufacturer=MANUFACTURER,
            model=MODEL_PROJECT,
            configuration_url=f"{self.base_url}/project/{self.project_id}",
        )

    def register_project_device(self) -> None:
        """Create the project device up front (parent of all template devices)."""
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            **self.project_device_info(),
        )
        self.project_device_id = device.id

    def template_device_info(self, template_id: int) -> DeviceInfo:
        """Device of a template (below the project device)."""
        template = (self.data.templates.get(template_id) if self.data else None) or {}
        info = DeviceInfo(
            identifiers={template_identifier(self.config_entry.entry_id, template_id)},
            name=template.get("name") or f"Template {template_id}",
            manufacturer=MANUFACTURER,
            model=MODEL_TEMPLATE,
            model_id=template.get("app") or "ansible",
            configuration_url=(
                f"{self.base_url}/project/{self.project_id}/templates/{template_id}"
            ),
        )
        if _HAS_VIA_DEVICE_ID and self.project_device_id:
            info["via_device_id"] = self.project_device_id
        elif not _HAS_VIA_DEVICE_ID:  # older Home Assistant
            info["via_device"] = (DOMAIN, self.config_entry.entry_id)  # type: ignore[typeddict-unknown-key]
        return info

    def _report(
        self,
        template: dict[str, Any],
        task: dict[str, Any] | None,
        output: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return build_report(
            project_id=self.project_id,
            project_name=self.project_name,
            template=template,
            task=task,
            output=output,
            base_url=self.base_url,
            lang=self._lang,
            tz=dt_util.get_default_time_zone(),
        )

    def report_for(self, template_id: int) -> dict[str, Any]:
        """Report of the last task of a template (cached one if it has the log)."""
        template = self.data.templates.get(template_id, {"id": template_id})
        last_task = template.get("last_task")
        cached = self._reports.get(template_id)
        if (
            cached
            and last_task
            and cached["task_id"] == last_task.get("id")
            and cached["status"] == last_task.get("status")
        ):
            return cached
        return self._report(template, last_task)

    async def _async_make_report(
        self, template: dict[str, Any], task: dict[str, Any]
    ) -> dict[str, Any]:
        """Report including the log analysis (failure reason, recap)."""
        output = None
        if task.get("status") in STATUS_FINISHED:
            try:
                output = await self.client.get_task_output(
                    self.project_id, task["id"]
                )
            except SemaphoreError as err:
                _LOGGER.debug("Could not read the log of task %s: %s", task["id"], err)
                self._log_failed[task["id"]] = self._log_failed.get(task["id"], 0) + 1
            else:
                self._log_failed.pop(task["id"], None)
        return self._report(template, task, output)

    async def _async_retry_unread_logs(
        self, templates: dict[int, dict[str, Any]], skip: set[int]
    ) -> None:
        """Read the log again of last tasks whose log could not be read before."""
        retry = []
        for template in templates.values():
            last = template.get("last_task") or {}
            task_id = last.get("id")
            if (
                task_id in self._log_failed
                and task_id not in skip
                and last.get("status") in STATUS_FINISHED
                and self._log_failed[task_id] < MAX_LOG_ATTEMPTS
            ):
                retry.append((template, last))
        # forget tasks that are no longer the last task of a template
        current = {(tpl.get("last_task") or {}).get("id") for tpl in templates.values()}
        self._log_failed = {k: v for k, v in self._log_failed.items() if k in current}
        if not retry:
            return
        semaphore = asyncio.Semaphore(5)

        async def build(template: dict[str, Any], task: dict[str, Any]):
            async with semaphore:
                return await self._async_make_report(template, task)

        reports = await asyncio.gather(*(build(tpl, task) for tpl, task in retry))
        for (template, task), report in zip(retry, reports, strict=True):
            if task["id"] not in self._log_failed:  # it worked this time
                self._reports[template["id"]] = report

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> SemaphoreData:
        try:
            raw = await self.client.get_templates(self.project_id)
        except SemaphoreAuthError as err:
            raise self._auth_failed(err) from err
        except SemaphoreApiError as err:
            if err.status in (403, 404):
                issues.report_failure(
                    self.hass,
                    self.config_entry,
                    ISSUE_PROJECT,
                    f"HTTP {err.status}",
                )
                raise UpdateFailed(
                    f"Project {self.project_id} not found: {err}"
                ) from err
            issues.report_failure(
                self.hass, self.config_entry, ISSUE_UNREACHABLE, str(err)
            )
            raise UpdateFailed(str(err)) from err
        except SemaphoreConnectionError as err:
            issues.report_failure(
                self.hass, self.config_entry, ISSUE_UNREACHABLE, str(err)
            )
            raise UpdateFailed(f"Semaphore not reachable: {err}") from err
        issues.report_ok(self.hass, self.config_entry)

        all_templates = {
            tpl["id"]: tpl.get("name") or f"#{tpl['id']}" for tpl in raw
        }
        templates = {
            tpl["id"]: tpl for tpl in raw if tpl["id"] not in self.excluded_templates
        }
        try:
            if templates and not any("last_task" in tpl for tpl in templates.values()):
                # Semaphore version without ``last_task`` in the template list:
                # take the newest task of every template from the task list.
                self._attach_last_tasks(
                    templates, await self.client.get_last_tasks(self.project_id)
                )
            await self._async_process_tasks(templates)
        except ConfigEntryAuthFailed:
            raise
        except SemaphoreError as err:
            # Task bookkeeping must never make the whole update fail.
            _LOGGER.debug("Task bookkeeping failed: %s", err)

        # Poll faster while something is running
        self.update_interval = (
            timedelta(seconds=ACTIVE_SCAN_INTERVAL)
            if self._active
            else self._base_interval
        )
        await self._async_update_last_success(templates)
        schedules = await self._async_read_schedules()
        self._remove_stale_devices(templates)
        self._first_done = True
        return SemaphoreData(
            templates=templates, schedules=schedules, all_templates=all_templates
        )

    async def _async_read_schedules(self) -> dict[int, dict[str, Any]]:
        """Schedules of the project; a failed read keeps the previous ones."""
        previous = self.data.schedules if self.data else {}
        try:
            raw = await self.client.get_schedules(self.project_id)
        except SemaphoreAuthError as err:
            raise self._auth_failed(err) from err
        except SemaphoreApiError as err:
            if err.status in (403, 404):
                # no permission / a Semaphore without schedules: there are none to show
                self.schedules_loaded = True
                return {}
            _LOGGER.debug("Reading the schedules failed: %s", err)
            return previous
        except SemaphoreError as err:
            _LOGGER.debug("Reading the schedules failed: %s", err)
            return previous
        self.schedules_loaded = True
        return {
            item["id"]: item
            for item in raw
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }

    async def _async_update_last_success(
        self, templates: dict[int, dict[str, Any]]
    ) -> None:
        """Remember the newest successful task of every template.

        A template whose last task succeeded needs no extra request. If the last task
        failed (or was stopped) the history of that template is read once per new last
        task - so after a restart the "last success" of a failing template is found too.
        """
        wanted: list[int] = []
        for tid, template in templates.items():
            last = template.get("last_task")
            if not last or "id" not in last:
                continue
            if last.get("status") == "success":
                self._last_success[tid] = last
                self._success_checked[tid] = last["id"]
            elif self._success_checked.get(tid) != last["id"]:
                wanted.append(tid)
        for tid in [t for t in self._last_success if t not in templates]:
            self._last_success.pop(tid, None)
            self._success_checked.pop(tid, None)
        if not wanted:
            return
        semaphore = asyncio.Semaphore(5)

        async def read(tid: int) -> None:
            async with semaphore:
                try:
                    history = await self.client.get_template_tasks(self.project_id, tid)
                except SemaphoreAuthError as err:
                    raise self._auth_failed(err) from err
                except SemaphoreError as err:
                    _LOGGER.debug("History of template %s not readable: %s", tid, err)
                    return
            wins = [
                task
                for task in history
                if isinstance(task, dict) and task.get("status") == "success"
            ]
            self._last_success[tid] = max(wins, key=lambda t: t["id"]) if wins else None
            self._success_checked[tid] = templates[tid]["last_task"]["id"]

        await asyncio.gather(*(read(tid) for tid in wanted))

    @staticmethod
    def _attach_last_tasks(
        templates: dict[int, dict[str, Any]], tasks: list[dict[str, Any]]
    ) -> None:
        newest: dict[int, dict[str, Any]] = {}
        for task in tasks:
            tid = task.get("template_id")
            if tid in templates and task.get("id", 0) > newest.get(tid, {}).get("id", 0):
                newest[tid] = task
        for tid, task in newest.items():
            templates[tid]["last_task"] = task

    async def _async_process_tasks(self, templates: dict[int, dict[str, Any]]) -> None:
        """Detect started/finished tasks and fire the events."""
        first = not self._first_done
        # (template, task, fire_finished_event)
        finished: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        started: list[tuple[dict[str, Any], dict[str, Any]]] = []

        for tid, template in templates.items():
            task = template.get("last_task")
            if not task or "id" not in task:
                continue
            status = task.get("status")
            task_id = task["id"]
            if status in STATUS_ACTIVE:
                if task_id not in self._active:
                    self._active[task_id] = tid
                    if not first:
                        started.append((template, task))
            elif status in STATUS_FINISHED:
                was_active = self._active.pop(task_id, None) is not None
                if task_id not in self._reported:
                    self._reported.add(task_id)
                    # At HA start-up old results are only used as baseline.
                    finished.append((template, task, was_active or not first))

        # Tasks we watched that are no longer the last task of their template
        for task_id, tid in list(self._active.items()):
            template = templates.get(tid)
            if template is None:
                del self._active[task_id]
                continue
            if (template.get("last_task") or {}).get("id") == task_id:
                continue
            try:
                task = await self.client.get_task(self.project_id, task_id)
            except SemaphoreApiError as err:
                if err.status == 404:
                    del self._active[task_id]
                continue
            if task and task.get("status") in STATUS_FINISHED:
                del self._active[task_id]
                if task_id not in self._reported:
                    self._reported.add(task_id)
                    finished.append((template, task, True))

        for template, task in started:
            self._emit(True, self._report(template, task))

        if finished:
            semaphore = asyncio.Semaphore(5)

            async def build(template: dict[str, Any], task: dict[str, Any]):
                async with semaphore:
                    return await self._async_make_report(template, task)

            reports = await asyncio.gather(
                *(build(tpl, task) for tpl, task, _ in finished)
            )
            for (template, task, fire), report in zip(finished, reports, strict=True):
                last = template.get("last_task") or {}
                if last.get("id") == task["id"]:
                    self._reports[template["id"]] = report
                if fire:
                    self._emit(False, report)

        await self._async_retry_unread_logs(
            templates, {task["id"] for _, task, _ in finished}
        )

    def _remove_stale_devices(self, templates: dict[int, dict[str, Any]]) -> None:
        """Remove devices of templates that no longer exist in Semaphore."""
        registry = dr.async_get(self.hass)
        entry_id = self.config_entry.entry_id
        for device in dr.async_entries_for_config_entry(registry, entry_id):
            for domain, identifier in device.identifiers:
                if domain != DOMAIN:
                    continue
                match = TEMPLATE_IDENTIFIER_RE.match(identifier)
                if (
                    match
                    and match["entry"] == entry_id
                    and int(match["tid"]) not in templates
                ):
                    registry.async_remove_device(device.id)
                    break

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    async def async_run_template(
        self,
        template_id: int,
        *,
        dry_run: bool = False,
        message: str | None = None,
        limit: str | None = None,
        survey: dict[str, Any] | None = None,
        wait: bool = False,
        timeout: float = const.DEFAULT_WAIT_TIMEOUT,
        raise_on_failure: bool = False,
    ) -> dict[str, Any]:
        """Start a template, optionally wait for the end, return the report."""
        template = self.data.templates.get(template_id)
        if template is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="template_not_found",
                translation_placeholders={"template_id": str(template_id)},
            )
        try:
            environment, secret = build_survey_payload(
                parse_survey_vars(template), survey
            )
        except SurveyError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="survey_invalid",
                translation_placeholders={
                    "template": template.get("name", str(template_id)),
                    "details": str(err),
                },
            ) from err
        # The check and the start are one step: two quick clicks (or an automation and
        # a click) must not both pass the check before the first run is registered.
        async with self._start_locks.setdefault(template_id, asyncio.Lock()):
            self._ensure_not_running(template_id, template)
            try:
                task = await self.client.start_task(
                    self.project_id,
                    template_id,
                    dry_run=dry_run,
                    message=message,
                    limit=limit,
                    environment=environment,
                    secret=secret,
                )
            except SemaphoreAuthError as err:
                raise self._auth_failed_in_action(err) from err
            except SemaphoreError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="start_failed",
                    translation_placeholders={
                        "template": template.get("name", str(template_id)),
                        "error": str(err),
                    },
                ) from err

            task_id = task["id"]
            self._active[task_id] = template_id
        self.update_interval = timedelta(seconds=ACTIVE_SCAN_INTERVAL)
        self._emit(True, self._report(template, task))

        timed_out = False
        if wait:
            task, timed_out = await self._async_wait_for_task(task_id, timeout)
            report = await self._async_make_report(template, task)
        else:
            report = self._report(template, task)
        report["timed_out"] = timed_out

        # Let the entities (and the finished event) catch up.
        await self.async_refresh()

        if raise_on_failure and report["result"] == "failed":
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="task_failed",
                translation_placeholders={
                    "template": report["template"],
                    "reason": (report["error"] or {}).get("reason", report["status"]),
                },
            )
        return report

    async def _async_wait_for_task(
        self, task_id: int, timeout: float
    ) -> tuple[dict[str, Any], bool]:
        """Poll a task until it is finished. Returns (task, timed_out)."""
        deadline = time.monotonic() + timeout
        task: dict[str, Any] = {"id": task_id, "status": "waiting"}
        while True:
            try:
                task = await self.client.get_task(self.project_id, task_id)
            except SemaphoreAuthError as err:
                raise self._auth_failed(err) from err
            except SemaphoreError as err:
                _LOGGER.debug("Polling task %s failed: %s", task_id, err)
            else:
                if task.get("status") in STATUS_FINISHED:
                    return task, False
            if time.monotonic() >= deadline:
                return task, True
            await asyncio.sleep(const.WAIT_POLL_SECONDS)

    async def async_stop_template(self, template_id: int) -> None:
        """Stop the active task(s) of a template."""
        task_ids = self.active_task_ids(template_id)
        if not task_ids:
            return
        for task_id in task_ids:
            try:
                await self.client.stop_task(self.project_id, task_id)
            except SemaphoreError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="stop_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
        await self.async_request_refresh()


@dataclass
class SemaphoreVersionData:
    """Installed and latest Semaphore version.

    ``installed_raw`` is what the server reported (e.g. ``2.19.17-f8cefe6-1792391878``
    for Docker builds); ``installed`` is the comparable release number (``2.19.17``).
    """

    installed: str | None
    latest: str | None
    release_url: str | None
    installed_raw: str | None = None
    schedule_timezone: str | None = None


# Docker/CI builds append "-<commit sha>[-<unix time>]" to the release number;
# SemVer "+build" metadata is dropped as well. Pre-release names (beta1, rc.2)
# are kept - they are real versions.
_BUILD_SUFFIX = re.compile(r"(?:-[0-9a-f]{7,40}(?:-\d{6,})?|\+.*)$")


def _clean_version(version: str | None) -> str | None:
    """Return the plain release number (without ``v`` and without build suffix)."""
    if not version:
        return None
    cleaned = str(version).strip().removeprefix("v")
    cleaned = _BUILD_SUFFIX.sub("", cleaned)
    return cleaned or None


class SemaphoreVersionCoordinator(DataUpdateCoordinator[SemaphoreVersionData]):
    """Reads the Semaphore version rarely and (optionally) the latest release."""

    config_entry: SemaphoreConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SemaphoreConfigEntry,
        client: SemaphoreClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} version {entry.title}",
            update_interval=timedelta(seconds=VERSION_SCAN_INTERVAL),
        )
        self.client = client
        self.check_updates: bool = entry.options.get(CONF_CHECK_UPDATES, True)

    async def _async_update_data(self) -> SemaphoreVersionData:
        try:
            info = await self.client.get_info()
        except SemaphoreAuthError as err:
            issues.report_token_rejected(self.hass, self.config_entry)
            raise ConfigEntryAuthFailed(str(err)) from err
        except SemaphoreError as err:
            raise UpdateFailed(str(err)) from err

        raw_version = info.get("version")
        installed = _clean_version(raw_version)
        latest: str | None = None
        release_url: str | None = None
        # Older Semaphore versions report an available update themselves.
        update = info.get("update")
        if isinstance(update, dict) and update.get("tag_name"):
            latest = _clean_version(update["tag_name"])
            release_url = update.get("html_url")
        elif self.check_updates:
            release = await async_get_latest_release(
                async_get_clientsession(self.hass), GITHUB_LATEST_URL
            )
            if release:
                latest = _clean_version(release[0])
                release_url = release[1]
        return SemaphoreVersionData(
            installed,
            latest,
            release_url,
            str(raw_version).strip() if raw_version else None,
            info.get("schedule_timezone") or None,
        )
