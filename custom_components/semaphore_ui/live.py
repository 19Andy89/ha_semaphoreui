"""Live updates: follow the running task over Semaphore's WebSocket (``/api/ws``).

The connection is only open while a task is queued or running (the polling of the
coordinator notices that) and is held by Home Assistant, not by a browser. It adds
two things on top of polling: status changes arrive at once and the Ansible step
that is running right now is known. If the WebSocket is not available or breaks,
nothing is lost: polling keeps working exactly as before.

Messages (verified against Semaphore 2.19)::

    {"type": "update", "project_id": 1, "task_id": 90, "template_id": 5, "status": "running", ...}
    {"type": "log", "project_id": 1, "task_id": 90, "output": "TASK [Install] ***", "time": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp

from .api import SemaphoreError

if TYPE_CHECKING:
    from .coordinator import SemaphoreCoordinator

_LOGGER = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_STEP = re.compile(r"^(?:TASK|RUNNING HANDLER) \[(.+?)\]")
_FIRST_DELAY = 2
_MAX_DELAY = 60


def parse_step(line: str) -> str | None:
    """Name of the Ansible step a log line announces (``TASK [name] ****``), else None."""
    match = _STEP.match(_ANSI.sub("", line or "").strip())
    return match.group(1).strip() if match else None


class LiveStream:
    """Holds the WebSocket while tasks are active and keeps the current step per task."""

    def __init__(self, coordinator: SemaphoreCoordinator) -> None:
        self._coordinator = coordinator
        self._task: asyncio.Task[None] | None = None
        self._unsupported = False
        # task_id -> (step number, step name)
        self.steps: dict[int, tuple[int, str]] = {}
        # task_id -> last (status, end) seen, so repeated messages cause no refresh
        self._seen: dict[int, tuple[Any, Any]] = {}

    @property
    def connected(self) -> bool:
        """True while the connection loop runs."""
        return self._task is not None and not self._task.done()

    def sync(self, active: bool) -> None:
        """Open the connection while something is active, close it otherwise."""
        if not self._coordinator.live_enabled or self._unsupported:
            active = False
        if active and not self.connected:
            # A plain task (closed in stop()/async_shutdown): it lives as long as a task
            # runs and must not hold up Home Assistant's "wait for background tasks".
            self._task = self._coordinator.hass.loop.create_task(
                self._run(), name=f"semaphore_ui live {self._coordinator.project_id}"
            )
        elif not active and self._task is not None:
            self.stop()
        if not active:
            self.steps.clear()
            self._seen.clear()
        else:
            for task_id in set(self.steps) - set(self._coordinator._active):  # noqa: SLF001
                self.steps.pop(task_id, None)
                self._seen.pop(task_id, None)

    def stop(self) -> None:
        """Close the connection."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def step_for(self, template_id: int) -> tuple[int, str] | None:
        """The step of the newest active task of a template (number, name)."""
        for task_id in sorted(self._coordinator.active_task_ids(template_id), reverse=True):
            if task_id in self.steps:
                return self.steps[task_id]
        return None

    # ------------------------------------------------------------------ #
    async def _run(self) -> None:
        delay = _FIRST_DELAY
        while True:
            try:
                async with self._coordinator.client.ws_connect() as ws:
                    delay = _FIRST_DELAY
                    _LOGGER.debug("Live connection to %s open", self._coordinator.base_url)
                    await self._catch_up()
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except asyncio.CancelledError:
                raise
            except aiohttp.WSServerHandshakeError as err:
                if err.status in (401, 403, 404, 405):
                    # An older Semaphore or a proxy without WebSocket: stay with polling.
                    _LOGGER.info(
                        "Live updates are not available (HTTP %s); polling is used instead",
                        err.status,
                    )
                    self._unsupported = True
                    return
                _LOGGER.debug("Live connection refused: %s", err)
            except (aiohttp.ClientError, SemaphoreError, OSError, TimeoutError) as err:
                _LOGGER.debug("Live connection lost: %s", err)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_DELAY)

    async def _catch_up(self) -> None:
        """A task that started before the connection was open: read the step from its log."""
        coordinator = self._coordinator
        for task_id in list(coordinator._active):  # noqa: SLF001
            if task_id in self.steps:
                continue
            try:
                rows = await coordinator.client.get_task_output(coordinator.project_id, task_id)
            except SemaphoreError:
                continue
            number = 0
            name = None
            for row in rows:
                step = parse_step(str(row.get("output", "")))
                if step:
                    number += 1
                    name = step
            if name:
                self.steps[task_id] = (number, name)
        coordinator.async_update_listeners()

    def _handle(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict) or msg.get("project_id") != self._coordinator.project_id:
            return
        task_id = msg.get("task_id")
        if not isinstance(task_id, int):
            return
        kind = msg.get("type")
        if kind == "log":
            if task_id not in self._coordinator._active:  # noqa: SLF001
                return
            step = parse_step(str(msg.get("output", "")))
            if step:
                number = self.steps.get(task_id, (0, ""))[0] + 1
                self.steps[task_id] = (number, step)
                self._coordinator.async_update_listeners()
        elif kind == "update":
            seen = (msg.get("status"), msg.get("end"))
            if self._seen.get(task_id) == seen:
                return
            self._seen[task_id] = seen
            # The coordinator does the bookkeeping (events, reports); only hurry it up.
            self._coordinator.hass.async_create_task(self._coordinator.async_request_refresh())

