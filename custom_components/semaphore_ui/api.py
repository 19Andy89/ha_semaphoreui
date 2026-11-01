"""Small async client for the Semaphore UI REST API.

Endpoints used (see https://semaphoreui.com/api-docs/):

* GET  /api/projects
* GET  /api/project/{id}
* GET  /api/project/{id}/templates      (each template contains ``last_task``)
* GET  /api/project/{id}/tasks/{task_id}
* GET  /api/project/{id}/tasks/{task_id}/output
* POST /api/project/{id}/tasks          (start a task)
* POST /api/project/{id}/tasks/{task_id}/stop

Authentication: ``Authorization: Bearer <API token>``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import ssl
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20


class SemaphoreError(Exception):
    """Base error of the Semaphore client."""


class SemaphoreConnectionError(SemaphoreError):
    """Server not reachable / timeout.

    ``kind`` tells *why* (used for readable messages in the setup dialog):
    ``dns``, ``refused``, ``timeout``, ``ssl``, ``unreachable``, ``disconnected``,
    ``invalid_url`` or ``connection`` (anything else). ``host`` is the host name
    of the failed request, ``detail`` the technical reason (never contains the token).
    """

    def __init__(
        self,
        detail: str,
        *,
        kind: str = "connection",
        host: str = "",
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind
        self.host = host


class SemaphoreAuthError(SemaphoreError):
    """Token rejected (HTTP 401)."""


class SemaphoreApiError(SemaphoreError):
    """The API answered with an error status.

    ``kind`` is ``http`` (error status) or ``not_json`` (the answer is not
    JSON, i.e. the address does not point to a Semaphore API).
    """

    def __init__(self, status: int, message: str, *, kind: str = "http") -> None:
        super().__init__(f"HTTP {status}: {message}" if message else f"HTTP {status}")
        self.status = status
        self.message = message
        self.kind = kind


def classify_connection_error(err: BaseException, url: str) -> SemaphoreConnectionError:
    """Turn an aiohttp/OS exception into a :class:`SemaphoreConnectionError`."""
    host = urlsplit(url).hostname or ""
    # SSL first: the SSL errors of aiohttp are also "connector errors" and even
    # ValueErrors (ClientConnectorCertificateError).
    if isinstance(err, (aiohttp.ClientSSLError, ssl.SSLError, aiohttp.ServerFingerprintMismatch)):
        reason = getattr(err, "os_error", None) or getattr(err, "certificate_error", None) or err
        return SemaphoreConnectionError(
            str(getattr(reason, "verify_message", None) or getattr(reason, "reason", None) or reason),
            kind="ssl",
            host=host,
        )
    if isinstance(err, (aiohttp.InvalidURL, ValueError)):
        return SemaphoreConnectionError(str(err) or url, kind="invalid_url", host=host)
    if isinstance(err, aiohttp.ClientConnectorError):
        os_error = err.os_error
        host = err.host or host
        if isinstance(os_error, socket.gaierror) or type(err).__name__ == "ClientConnectorDNSError":
            return SemaphoreConnectionError(
                getattr(os_error, "strerror", None) or str(os_error), kind="dns", host=host
            )
        if isinstance(os_error, ConnectionRefusedError):
            return SemaphoreConnectionError(
                f"{host}:{err.port}", kind="refused", host=host
            )
        if isinstance(os_error, (TimeoutError, asyncio.TimeoutError)):
            return SemaphoreConnectionError(f"{host}:{err.port}", kind="timeout", host=host)
        return SemaphoreConnectionError(
            getattr(os_error, "strerror", None) or str(os_error) or str(err),
            kind="unreachable",
            host=host,
        )
    if isinstance(err, OSError) and not isinstance(err, aiohttp.ClientError):
        return SemaphoreConnectionError(
            err.strerror or str(err), kind="unreachable", host=host
        )
    if isinstance(err, (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError)):
        return SemaphoreConnectionError(
            str(err) or type(err).__name__, kind="disconnected", host=host
        )
    return SemaphoreConnectionError(str(err) or type(err).__name__, host=host)


def normalize_base_url(url: str) -> str:
    """Return ``scheme://host[:port][/prefix]`` without trailing slash and ``/api``."""
    url = url.strip()
    if "://" not in url:
        url = f"http://{url}"
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


class SemaphoreClient:
    """Thin wrapper around the Semaphore REST API."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, token: str
    ) -> None:
        self._session = session
        self.base_url = normalize_base_url(base_url)
        self._token = token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}/api{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, params=params, json=json_body
                ) as resp:
                    if resp.status == 401:
                        raise SemaphoreAuthError("Token rejected (HTTP 401)")
                    text = await resp.text()
                    if resp.status >= 400:
                        raise SemaphoreApiError(resp.status, text.strip()[:300])
        except TimeoutError as err:
            raise SemaphoreConnectionError(
                f"Timeout talking to {url}",
                kind="timeout",
                host=urlsplit(url).hostname or "",
            ) from err
        except UnicodeDecodeError as err:
            raise SemaphoreApiError(
                0, "Answer is not text (binary data)", kind="not_json"
            ) from err
        except (aiohttp.ClientError, ValueError, OSError) as err:
            raise classify_connection_error(err, url) from err

        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError as err:
            raise SemaphoreApiError(
                resp.status,
                f"Answer is not JSON: {text.strip()[:120]}",
                kind="not_json",
            ) from err

    async def get_info(self) -> dict[str, Any]:
        """Return the system info (contains the Semaphore ``version``)."""
        return await self._request("GET", "/info") or {}

    async def get_projects(self) -> list[dict[str, Any]]:
        """Return all projects the token may see."""
        return await self._request("GET", "/projects") or []

    async def get_project(self, project_id: int) -> dict[str, Any]:
        """Return one project."""
        return await self._request("GET", f"/project/{project_id}")

    async def get_templates(self, project_id: int) -> list[dict[str, Any]]:
        """Return the templates of a project (including ``last_task``)."""
        return (
            await self._request(
                "GET",
                f"/project/{project_id}/templates",
                params={"sort": "name", "order": "asc"},
            )
            or []
        )

    async def get_last_tasks(self, project_id: int) -> list[dict[str, Any]]:
        """Return the most recent tasks of the project (max. 200)."""
        return (
            await self._request(
                "GET", f"/project/{project_id}/tasks/last", params={"count": 200}
            )
            or []
        )

    async def get_template_tasks(
        self, project_id: int, template_id: int, count: int = 100
    ) -> list[dict[str, Any]]:
        """Return the most recent tasks of one template (newest first)."""
        return (
            await self._request(
                "GET",
                f"/project/{project_id}/templates/{template_id}/tasks/last",
                params={"count": count},
            )
            or []
        )

    async def get_schedules(self, project_id: int) -> list[dict[str, Any]]:
        """Return the schedules of a project (cron or one-time, with ``tpl_name``)."""
        return await self._request("GET", f"/project/{project_id}/schedules") or []

    async def set_schedule_active(
        self, project_id: int, schedule_id: int, active: bool
    ) -> None:
        """Switch a schedule on or off (only the ``active`` flag, nothing else changes)."""
        await self._request(
            "PUT",
            f"/project/{project_id}/schedules/{schedule_id}/active",
            json_body={"active": active},
        )

    async def get_task(self, project_id: int, task_id: int) -> dict[str, Any]:
        """Return one task."""
        return await self._request("GET", f"/project/{project_id}/tasks/{task_id}")

    async def get_task_output(
        self, project_id: int, task_id: int
    ) -> list[dict[str, Any]]:
        """Return the log lines of a task."""
        rows = (
            await self._request("GET", f"/project/{project_id}/tasks/{task_id}/output")
            or []
        )
        # Keep the order the server gives (id/time ascending); be defensive anyway.
        if rows and all("id" in row for row in rows):
            rows = sorted(rows, key=lambda row: row["id"])
        return rows

    async def start_task(
        self,
        project_id: int,
        template_id: int,
        *,
        dry_run: bool = False,
        message: str | None = None,
        limit: str | None = None,
        environment: dict[str, Any] | None = None,
        secret: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start a task of a template and return the created task.

        ``environment`` / ``secret`` are the values of the survey variables
        (the API wants them as JSON *strings*, like the web UI sends them).
        """
        body: dict[str, Any] = {"template_id": template_id}
        if dry_run:
            # Older Semaphore versions read the top level flag, newer ones
            # (task ``params``) read it from ``params``. Sending both is safe.
            body["dry_run"] = True
            body["params"] = {"dry_run": True}
        if message:
            body["message"] = message
        if limit:
            body["limit"] = limit
        if environment:
            body["environment"] = json.dumps(environment, ensure_ascii=False)
        if secret:
            body["secret"] = json.dumps(secret, ensure_ascii=False)
        return await self._request(
            "POST", f"/project/{project_id}/tasks", json_body=body
        )

    async def stop_task(
        self, project_id: int, task_id: int, *, force: bool = False
    ) -> None:
        """Stop a running task."""
        await self._request(
            "POST",
            f"/project/{project_id}/tasks/{task_id}/stop",
            json_body={"force": force},
        )


async def async_get_latest_release(
    session: aiohttp.ClientSession, url: str
) -> tuple[str, str | None] | None:
    """Return ``(tag_name, html_url)`` of the latest GitHub release.

    Uses its own request on purpose: the Semaphore API token must never be
    sent to another server. Any problem simply returns ``None``.
    """
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(
                url, headers={"Accept": "application/vnd.github+json"}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug("Could not check for a new Semaphore release: %s", err)
        return None
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    return str(data["tag_name"]), data.get("html_url")
