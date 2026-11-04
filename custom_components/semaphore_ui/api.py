"""Small async client for the Semaphore UI REST API.

Endpoints used (see https://semaphoreui.com/api-docs/):

* GET  /api/projects
* GET  /api/project/{id}
* GET  /api/project/{id}/templates      (each template contains ``last_task``)
* GET  /api/project/{id}/tasks/{task_id}
* GET  /api/project/{id}/tasks/{task_id}/output
* POST /api/project/{id}/tasks          (start a task)
* POST /api/project/{id}/tasks/{task_id}/stop
* GET  /api/user/tokens                 (expiry of the own token)
* POST /api/user/tokens                 (create a new token)
* POST /api/auth/login, /api/auth/logout (only to get a new token with user name and password)

Authentication: ``Authorization: Bearer <API token>``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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
    """Token rejected (HTTP 401). ``body`` is what the server said (e.g. ``TOTP_REQUIRED``)."""

    def __init__(self, message: str = "", body: str = "") -> None:
        super().__init__(message)
        self.body = body


class SemaphoreLoginError(SemaphoreError):
    """Signing in with user name and password did not work.

    ``reason``: ``invalid_auth`` (wrong login, or password login is switched off),
    ``mfa_required`` (a second factor is needed - not possible here) or ``unsupported``
    (the server answered in a way we do not understand).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
        session_cookie: str | None = None,
        cookie_sink: dict[str, str] | None = None,
    ) -> Any:
        """Send a request. With ``session_cookie`` the login session is used instead of the token."""
        url = f"{self.base_url}/api{path}"
        headers = {"Accept": "application/json"}
        if session_cookie is None:
            headers["Authorization"] = f"Bearer {self._token}"
        elif session_cookie:  # "" = neither token nor session (the login itself)
            headers["Cookie"] = f"semaphore={session_cookie}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, params=params, json=json_body
                ) as resp:
                    if cookie_sink is not None:
                        cookie_sink.update({k: m.value for k, m in resp.cookies.items()})
                    text = await resp.text()
                    if resp.status == 401:
                        raise SemaphoreAuthError(
                            "Token rejected (HTTP 401)", text.strip()[:100]
                        )
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

    @property
    def token(self) -> str:
        """The token that is used right now."""
        return self._token

    def set_token(self, token: str) -> None:
        """Use a new token from now on (all coordinators share this client)."""
        self._token = token

    async def get_tokens(
        self, *, session_cookie: str | None = None
    ) -> list[dict[str, Any]]:
        """Return the API tokens of the user (``id`` is shortened to the first 8 characters)."""
        return (
            await self._request("GET", "/user/tokens", session_cookie=session_cookie)
            or []
        )

    async def create_token(
        self,
        name: str,
        expires_at: datetime | None = None,
        *,
        session_cookie: str | None = None,
    ) -> dict[str, Any]:
        """Create a new API token; the answer carries the token itself as ``id``."""
        body: dict[str, Any] = {"name": name}
        if expires_at is not None:
            body["expires_at"] = expires_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            created = await self._request(
                "POST", "/user/tokens", json_body=body, session_cookie=session_cookie
            )
        except SemaphoreAuthError as err:
            if session_cookie is not None and err.body.upper().endswith("_REQUIRED"):
                raise SemaphoreLoginError("mfa_required") from err
            raise
        if not isinstance(created, dict) or not created.get("id"):
            raise SemaphoreApiError(0, "No token in the answer", kind="not_json")
        return created

    async def login(self, username: str, password: str) -> str:
        """Sign in with user name and password and return the session cookie."""
        sink: dict[str, str] = {}
        try:
            await self._request(
                "POST",
                "/auth/login",
                json_body={"auth": username, "password": password, "method": "password"},
                session_cookie="",
                cookie_sink=sink,
            )
        except SemaphoreAuthError as err:
            raise SemaphoreLoginError("invalid_auth") from err
        if not sink.get("semaphore"):
            raise SemaphoreLoginError("unsupported")
        return sink["semaphore"]

    async def logout(self, session_cookie: str) -> None:
        """End the login session (best effort)."""
        try:
            await self._request("POST", "/auth/logout", session_cookie=session_cookie)
        except SemaphoreError as err:
            _LOGGER.debug("Logout failed (ignored): %s", err)

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

    async def create_schedule(self, project_id: int, schedule: dict[str, Any]) -> dict[str, Any]:
        """Create a schedule (``template_id``, ``cron_format``, ``name``, ``active``); returns it with its new id."""
        body = {"project_id": project_id, **schedule}
        return await self._request("POST", f"/project/{project_id}/schedules", json_body=body) or {}

    async def update_schedule(
        self, project_id: int, schedule_id: int, schedule: dict[str, Any]
    ) -> None:
        """Replace a schedule. Semaphore expects the whole object (with ``id`` and ``project_id``), not just changes."""
        body = {**schedule, "id": schedule_id, "project_id": project_id}
        await self._request(
            "PUT", f"/project/{project_id}/schedules/{schedule_id}", json_body=body
        )

    async def delete_schedule(self, project_id: int, schedule_id: int) -> None:
        """Delete a schedule."""
        await self._request("DELETE", f"/project/{project_id}/schedules/{schedule_id}")

    def ws_connect(self) -> Any:
        """Open the live WebSocket (``/api/ws``); use as ``async with``."""
        parts = urlsplit(self.base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        url = urlunsplit((scheme, parts.netloc, f"{parts.path}/api/ws", "", ""))
        return self._session.ws_connect(
            url, headers={"Authorization": f"Bearer {self._token}"}, heartbeat=30
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
        build_task_id: int | None = None,
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
        if build_task_id is not None:
            # deploy template: the finished build task whose version is deployed
            body["build_task_id"] = build_task_id
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


async def async_docker_release_available(
    session: aiohttp.ClientSession, url_template: str, version: str
) -> bool | None:
    """Does the Docker image of ``version`` exist? ``None``: could not be found out.

    Tags are tried with and without a leading ``v``. Only a clear "not found" for all of
    them counts as ``False``; any other problem (no internet, rate limit) is ``None`` so that
    the update is shown as before.
    """
    unknown = False
    for tag in (f"v{version}", version):
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with session.get(url_template.format(tag=tag)) as resp:
                    if resp.status == 200:
                        return True
                    if resp.status != 404:
                        unknown = True
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug("Could not check the Docker tag %s: %s", tag, err)
            unknown = True
    return None if unknown else False


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
