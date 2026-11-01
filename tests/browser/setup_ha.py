"""Richtet ein frisch gestartetes Test-Home-Assistant für den Browser-Test ein.

* meldet den Benutzer ``tester`` an und speichert die Tokens in ``<E2E_DIR>/token.json``
* legt die Integration für die Projekte „Homelab“ und „Testlab“ über den Config-Flow an (Abfrage-Intervall 10 s)
* legt das Dashboard ``dashboard-sem-test`` an: Projekt-Karte und vier Template-Karten von „Homelab“ sowie
  Projekt- und Template-Karte von „Testlab“ (gleiche Template-Namen in beiden Projekten); dazu die Ansichten „Benötigt“
  und „Versionen“

Umgebungsvariablen: ``E2E_DIR`` (Arbeitsordner), ``HA_URL``, ``FAKE_URL``.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

import aiohttp

HA_URL = os.environ.get("HA_URL", "http://127.0.0.1:8123")
FAKE_URL = os.environ.get("FAKE_URL", "http://127.0.0.1:13000")
E2E_DIR = Path(os.environ.get("E2E_DIR", "."))
DASHBOARD = "dashboard-sem-test"


def post(path: str, data: dict, token: str | None = None, *, form: bool = False) -> dict:
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(HA_URL + path, body, headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return json.load(response)


def login() -> dict:
    client_id = HA_URL + "/"
    flow = post(
        "/auth/login_flow",
        {"client_id": client_id, "handler": ["homeassistant", None], "redirect_uri": client_id + "?auth_callback=1"},
    )
    result = post(
        "/auth/login_flow/" + flow["flow_id"],
        {"client_id": client_id, "username": "tester", "password": "testpass123"},
    )
    return post(
        "/auth/token",
        {"client_id": client_id, "grant_type": "authorization_code", "code": result["result"]},
        form=True,
    )


def create_entry(token: str, project_id: str) -> str:
    flow = post("/api/config/config_entries/flow", {"handler": "semaphore_ui"}, token)
    flow = post(
        "/api/config/config_entries/flow/" + flow["flow_id"],
        {"url": FAKE_URL, "api_token": "good-token", "verify_ssl": False},
        token,
    )
    done = post("/api/config/config_entries/flow/" + flow["flow_id"], {"project_id": project_id}, token)
    assert done["type"] == "create_entry", done
    entry_id = done["result"]["entry_id"]
    options = post("/api/config/config_entries/options/flow", {"handler": entry_id}, token)
    done = post(
        "/api/config/config_entries/options/flow/" + options["flow_id"],
        {"scan_interval": 10, "check_for_updates": False},
        token,
    )
    assert done["type"] == "create_entry", done
    return entry_id


async def build_dashboard(token: str) -> None:
    async with aiohttp.ClientSession() as session, session.ws_connect(HA_URL + "/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        counter = 0

        async def call(message: dict) -> dict:
            nonlocal counter
            counter += 1
            await ws.send_json({"id": counter, **message})
            while True:
                reply = await ws.receive_json()
                if reply.get("id") == counter:
                    assert reply.get("success"), reply
                    return reply

        # wait until all devices exist (2 projects x 5 templates + 2 project devices)
        for _ in range(60):
            devices = (await call({"type": "config/device_registry/list"}))["result"]
            mine = [d for d in devices if any(i[0] == "semaphore_ui" for i in d["identifiers"])]
            if len([d for d in mine if d["model"] == "Template"]) >= 10:
                break
            await asyncio.sleep(1)
        projects = {d["name"]: d["id"] for d in mine if d["model"] == "Project"}
        project = projects["Semaphore – Homelab"]
        testlab = projects["Semaphore – Testlab"]
        templates = {d["name"]: d["id"] for d in mine if d["model"] == "Template" and d["via_device_id"] == project}
        testlab_templates = {d["name"]: d["id"] for d in mine if d["model"] == "Template" and d["via_device_id"] == testlab}

        # Update-Entität des Projekts „Homelab“ (steht im Test für die HACS-Entität der Integration)
        registry = (await call({"type": "config/entity_registry/list"}))["result"]
        update_entity = next(e["entity_id"] for e in registry if e["device_id"] == project and e["entity_id"].startswith("update."))

        def tcard(name: str, **extra: object) -> dict:
            return {"type": "custom:semaphore-ui-template-card", "device_id": templates[name], **extra}

        await call(
            {
                "type": "lovelace/dashboards/create",
                "url_path": DASHBOARD,
                "title": "Sem Test",
                "icon": "mdi:cog",
                "show_in_sidebar": True,
                "require_admin": False,
                "allow_single_word": True,
            }
        )
        config = {
            "views": [
                {
                    "title": "Semaphore",
                    "type": "sections",
                    "max_columns": 3,
                    "sections": [
                        {"type": "grid", "cards": [{"type": "custom:semaphore-ui-project-card", "device_id": project}]},
                        {"type": "grid", "cards": [tcard("Host-Update"), tcard("docker-system aktualisieren", confirm_start=True)]},
                        {"type": "grid", "cards": [tcard("Proxmox Snapshot HAOS"), tcard("Deploy")]},
                        {
                            "type": "grid",
                            "cards": [
                                {"type": "custom:semaphore-ui-project-card", "device_id": testlab},
                                {"type": "custom:semaphore-ui-template-card", "device_id": testlab_templates["Host-Update"]},
                            ],
                        },
                    ],
                },
                {
                    # nur das, was gerade gebraucht wird (Handlungsbedarf, Fehler, läuft)
                    "title": "Benötigt",
                    "type": "sections",
                    "max_columns": 2,
                    "sections": [
                        {
                            "type": "grid",
                            "cards": [
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "only_needed": True},
                                tcard("docker-system aktualisieren"),
                            ],
                        },
                    ],
                },
                {
                    # Versionsanzeige der Projekt-Karte (Semaphore / Integration / HACS-Hinweis)
                    "title": "Versionen",
                    "type": "sections",
                    "max_columns": 2,
                    "sections": [
                        {
                            "type": "grid",
                            "cards": [
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "A Standard"},
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "B Nur Integration", "show_version": False, "show_integration_version": True},
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "C Beides mit HACS", "show_integration_version": True, "hacs_update_entity": update_entity},
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "D Ohne Version", "show_version": False},
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "E Nur Deploy", "templates": [templates["Deploy"]]},
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "F Beide Versionen", "show_integration_version": True},
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "G Ohne Zeitpläne", "show_schedules": False},
                                {"type": "custom:semaphore-ui-project-card", "device_id": project, "name": "Homelab", "show_integration_version": True},
                                tcard("docker-system aktualisieren"),
                            ],
                        },
                    ],
                },
            ]
        }
        await call({"type": "lovelace/config/save", "url_path": DASHBOARD, "config": config})


def main() -> None:
    E2E_DIR.mkdir(parents=True, exist_ok=True)
    tokens = login()
    tokens.update(hassUrl=HA_URL, clientId=HA_URL + "/", expires=int(time.time() * 1000) + tokens["expires_in"] * 1000)
    (E2E_DIR / "token.json").write_text(json.dumps(tokens))
    create_entry(tokens["access_token"], "1")  # Homelab
    create_entry(tokens["access_token"], "2")  # Testlab
    asyncio.run(build_dashboard(tokens["access_token"]))
    print("Home Assistant eingerichtet:", f"{HA_URL}/{DASHBOARD}/0")


if __name__ == "__main__":
    main()
