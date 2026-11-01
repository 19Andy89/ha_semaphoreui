"""A tiny fake Semaphore UI server for the tests (only the endpoints we use)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

TOKEN = "good-token"


def iso(dt: datetime) -> str:
    """Go-like RFC3339 timestamp."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class FakeSemaphore:
    """In-memory Semaphore with a project, templates and tasks."""

    def __init__(self) -> None:
        self.token = TOKEN
        self.projects = [{"id": 1, "name": "Homelab"}, {"id": 2, "name": "Other"}]
        self.templates: dict[int, dict[str, Any]] = {
            1: {"id": 1, "project_id": 1, "name": "docker-system aktualisieren", "app": "ansible"},
            2: {"id": 2, "project_id": 1, "name": "Host-Update", "app": "ansible"},
            3: {"id": 3, "project_id": 1, "name": "Bash Job", "app": "bash"},
        }
        self.tasks: dict[int, dict[str, Any]] = {}
        self.outputs: dict[int, list[dict[str, Any]]] = {}
        self.next_id = 100
        self.requests: list[tuple[str, str, Any]] = []
        self.get_task_calls: dict[int, int] = {}
        # task_id -> (after N get_task calls, status, output text); auto finish helper
        self.auto_finish: dict[int, tuple[int, str, str]] = {}
        self.server: TestServer | None = None
        self.start_status = "waiting"
        self.include_last_task = True
        self.survey_template = {
            "id": 4,
            "project_id": 1,
            "name": "Deploy",
            "app": "ansible",
            "survey_vars": [
                {"name": "target", "title": "Ziel-Host", "type": "", "required": True,
                 "default_value": "dockerhost", "description": "Auf welchen Host"},
                {"name": "count", "title": "Anzahl", "type": "int", "required": False},
                {"name": "stage", "title": "Stufe", "type": "enum", "required": True,
                 "values": [{"name": "Produktion", "value": "prod"}, {"name": "Test", "value": "test"}]},
                {"name": "tags", "title": "Tags", "type": "select",
                 "values": [{"name": "A", "value": "a"}, {"name": "B", "value": "b"}],
                 "default_value": ["a"]},
                {"name": "token", "title": "Token", "type": "secret", "required": True},
            ],
        }
        self.version = "v2.16.10"
        self.latest_release = {"tag_name": "v2.17.0", "html_url": "https://example.test/release"}
        self.info_update: dict[str, Any] | None = None
        # (status, body): answer every API call with this instead (HTML page, 404, ...)
        self.raw_answer: tuple[int, str] | None = None
        # the next N reads of a task log answer with an error (slow/broken server)
        self.fail_output = 0
        # schedules like Semaphore returns them; time zone of the schedules (/api/info)
        self.schedules: dict[int, dict[str, Any]] = {}
        self.schedule_timezone: str | None = "UTC"
        # (status, text): answer the schedule calls with this (404 = Semaphore without schedules, 500 ...)
        self.schedules_error: tuple[int, str] | None = None
        # seconds the writing calls (start a task, switch a schedule) take: lets a test see the busy state
        self.write_delay = 0.0

    # ---- helpers for the tests ----------------------------------------- #
    def add_finished_task(
        self,
        template_id: int,
        status: str = "success",
        output: str = "",
        *,
        seconds: int = 72,
        when: datetime | None = None,
        user: str = "Andreas",
    ) -> dict[str, Any]:
        start = when or (datetime.now(UTC) - timedelta(hours=1))
        task_id = self.next_id
        self.next_id += 1
        task = {
            "id": task_id,
            "template_id": template_id,
            "project_id": 1,
            "status": status,
            "created": iso(start),
            "start": iso(start),
            "end": iso(start + timedelta(seconds=seconds)),
            "user_name": user,
            "tpl_alias": self.templates[template_id]["name"],
            "message": "",
            "params": {},
        }
        self.tasks[task_id] = task
        self.set_output(task_id, output)
        return task

    def set_output(self, task_id: int, text: str) -> None:
        self.outputs[task_id] = [
            {"id": i + 1, "task_id": task_id, "time": iso(datetime.now(UTC)), "output": line}
            for i, line in enumerate(text.splitlines())
        ]

    def finish(self, task_id: int, status: str, output: str, seconds: int = 42) -> None:
        task = self.tasks[task_id]
        start = datetime.fromisoformat(task["created"].replace("Z", "+00:00"))
        task["status"] = status
        task["start"] = iso(start)
        task["end"] = iso(start + timedelta(seconds=seconds))
        self.set_output(task_id, output)

    def add_schedule(
        self,
        template_id: int,
        cron: str = "0 2 * * *",
        *,
        name: str = "nightly",
        active: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        """A schedule as the Semaphore API returns it."""
        schedule_id = max(self.schedules, default=0) + 1
        schedule = {
            "id": schedule_id,
            "project_id": 1,
            "template_id": template_id,
            "cron_format": cron,
            "name": name,
            "active": active,
            "type": "",
            "delete_after_run": False,
            "repository_id": None,
            "tpl_name": self.templates[template_id]["name"],
            **extra,
        }
        self.schedules[schedule_id] = schedule
        return schedule

    def last_task(self, template_id: int) -> dict[str, Any] | None:
        tasks = [t for t in self.tasks.values() if t["template_id"] == template_id]
        return max(tasks, key=lambda t: t["id"]) if tasks else None

    # ---- HTTP ------------------------------------------------------------ #
    def _check(self, request: web.Request) -> web.Response | None:
        if self.raw_answer is not None:
            return web.Response(status=self.raw_answer[0], text=self.raw_answer[1])
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return web.Response(status=401, text="Unauthorized")
        return None

    async def _body(self, request: web.Request) -> Any:
        return await request.json() if request.can_read_body else None

    def make_app(self) -> web.Application:
        routes = web.RouteTableDef()

        @routes.get("/api/info")
        async def info(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            body: dict[str, Any] = {"version": self.version}
            if self.schedule_timezone:
                body["schedule_timezone"] = self.schedule_timezone
            if self.info_update:
                body["update"] = self.info_update
            return web.json_response(body)

        @routes.get("/github/latest")
        async def github(request: web.Request) -> web.Response:
            # must never receive the Semaphore token
            self.requests.append(("GITHUB", request.path, request.headers.get("Authorization")))
            return web.json_response(self.latest_release)

        @routes.get("/api/projects")
        async def projects(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            return web.json_response(self.projects)

        @routes.get("/api/project/{pid}")
        async def project(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            pid = int(request.match_info["pid"])
            for proj in self.projects:
                if proj["id"] == pid:
                    return web.json_response(proj)
            return web.Response(status=404, text="Not Found")

        @routes.get("/api/project/{pid}/templates")
        async def templates(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            self.requests.append(("GET", request.path, dict(request.query)))
            out = []
            for tpl in self.templates.values():
                item = dict(tpl)
                last = self.last_task(tpl["id"])
                if last and self.include_last_task:
                    item["last_task"] = dict(last)
                out.append(item)
            return web.json_response(out)

        @routes.get("/api/project/{pid}/templates/{tpl}/tasks/last")
        async def template_tasks(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            self.requests.append(("GET", request.path, dict(request.query)))
            tid = int(request.match_info["tpl"])
            count = int(request.query.get("count", 100))
            found = sorted(
                (t for t in self.tasks.values() if t["template_id"] == tid),
                key=lambda t: t["id"],
                reverse=True,
            )
            return web.json_response(found[:count])

        @routes.get("/api/project/{pid}/schedules")
        async def get_schedules(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            if self.schedules_error is not None:
                return web.Response(status=self.schedules_error[0], text=self.schedules_error[1])
            self.requests.append(("GET", request.path, None))
            return web.json_response(list(self.schedules.values()))

        @routes.put("/api/project/{pid}/schedules/{sid}/active")
        async def set_schedule_active(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            body = await self._body(request)
            self.requests.append(("PUT", request.path, body))
            if self.write_delay:
                await asyncio.sleep(self.write_delay)
            if self.schedules_error is not None:
                return web.Response(status=self.schedules_error[0], text=self.schedules_error[1])
            schedule = self.schedules.get(int(request.match_info["sid"]))
            if schedule is None:
                return web.Response(status=404, text="Not Found")
            if not isinstance(body, dict) or set(body) != {"active"} or not isinstance(body["active"], bool):
                return web.json_response({"error": "bad body"}, status=400)
            schedule["active"] = body["active"]
            return web.Response(status=204)

        @routes.get("/api/project/{pid}/tasks/last")
        async def last_tasks(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            return web.json_response(list(self.tasks.values()))

        @routes.post("/api/project/{pid}/tasks")
        async def start(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            body = await self._body(request)
            self.requests.append(("POST", request.path, body))
            if self.write_delay:
                await asyncio.sleep(self.write_delay)
            tpl_id = body["template_id"]
            if tpl_id not in self.templates:
                return web.Response(status=400, text="template not found")
            task_id = self.next_id
            self.next_id += 1
            task = {
                "id": task_id,
                "template_id": tpl_id,
                "project_id": 1,
                "status": self.start_status,
                "created": iso(datetime.now(UTC)),
                "message": body.get("message", ""),
                "params": body.get("params", {}),
                "user_name": "Andreas",
                "environment": body.get("environment", ""),
            }
            self.tasks[task_id] = task
            return web.json_response(task, status=201)

        @routes.get("/api/project/{pid}/tasks/{tid}")
        async def get_task(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            task_id = int(request.match_info["tid"])
            task = self.tasks.get(task_id)
            if task is None:
                return web.Response(status=404, text="Not Found")
            self.get_task_calls[task_id] = self.get_task_calls.get(task_id, 0) + 1
            auto = self.auto_finish.get(task_id)
            if auto and self.get_task_calls[task_id] >= auto[0] and task["status"] not in (
                "success",
                "error",
                "stopped",
            ):
                self.finish(task_id, auto[1], auto[2])
            return web.json_response(task)

        @routes.get("/api/project/{pid}/tasks/{tid}/output")
        async def output(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            if self.fail_output > 0:
                self.fail_output -= 1
                return web.Response(status=500, text="boom")
            return web.json_response(self.outputs.get(int(request.match_info["tid"]), []))

        @routes.post("/api/project/{pid}/tasks/{tid}/stop")
        async def stop(request: web.Request) -> web.Response:
            if (resp := self._check(request)) is not None:
                return resp
            task_id = int(request.match_info["tid"])
            self.requests.append(("POST", request.path, await self._body(request)))
            self.finish(task_id, "stopped", "stopped by user", seconds=5)
            return web.Response(status=204)

        app = web.Application()
        app.add_routes(routes)
        return app

    async def start_server(self) -> str:
        self.server = TestServer(self.make_app(), host="127.0.0.1")
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    async def close(self) -> None:
        if self.server:
            await self.server.close()
