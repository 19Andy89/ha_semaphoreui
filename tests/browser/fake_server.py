"""Eigenständiger Semaphore-Nachbau für den Browser-Test der Dashboard-Karten.

Startet ``tests/fake_semaphore.py`` als normalen Server (Standard: Port 13000) mit Beispieldaten
und ein paar Steuer-Endpunkten unter ``/ctl/...``, damit ``check_cards.py`` prüfen kann,
was die Karten an Semaphore geschickt haben.

    python tests/browser/fake_server.py [PORT]

Token: ``good-token``. Beispieldaten: ein Testlauf mit drei Hosts (HA_RESULT, 5 Updates, Neustart, Hinweis), ein fehlgeschlagenes (mit älterem Erfolg) und ein laufendes Template,
Semaphore 2.19.17 mit Zeitzone Europe/Berlin und drei Zeitplänen (zwei bei „Host-Update“, einer bei „docker-system“),
ein Template ohne Lauf und ein Template mit Survey-Variablen (``Deploy``).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.fake_semaphore import FakeSemaphore, iso  # noqa: E402

FAIL_OUT = """TASK [Update apt cache] ********************************************************
fatal: [dockerhost]: FAILED! => {"changed": false, "msg": "Failed to lock apt for exclusive operation"}
PLAY RECAP *********************************************************************
dockerhost                 : ok=2    changed=0    unreachable=0    failed=1    skipped=0    rescued=0    ignored=0"""
OK_OUT = "PLAY RECAP\ndockerhost : ok=5 changed=1 unreachable=0 failed=0"
# Testlauf mit drei Hosts (HA_RESULT): dockerhost 3 Updates + Neustart, pialert 2 Updates, adguard nichts, aber ein Hinweis
PENDING_OUT = """TASK [Ergebnis fuer Home Assistant melden] *************************************
ok: [dockerhost] =>
    msg: 'HA_RESULT {"updates": 7, "reboot_required": true, "packages": ["libssl3", "openssl", "curl", "docker-ce", "docker-ce-cli", "containerd.io", "linux-image-6.12.48+deb13-amd64"]}'
ok: [pialert] =>
    msg: 'HA_RESULT {"updates": 2, "reboot_required": false, "packages": ["curl", "bash"]}'
ok: [adguard] =>
    msg: 'HA_RESULT {"updates": 0, "reboot_required": false, "notes": "Debian 13 (trixie) ist verfügbar"}'
PLAY RECAP *********************************************************************
dockerhost                 : ok=2    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
pialert                    : ok=2    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
adguard                    : ok=2    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0"""


def build() -> FakeSemaphore:
    """Fake with sample data (see module docstring)."""
    fake = FakeSemaphore()
    fake.projects[1]["name"] = "Testlab"  # second project: the cards must tell the two apart
    fake.templates[4] = fake.survey_template
    fake.templates[5] = {
        "id": 5,
        "project_id": 1,
        "name": "Proxmox Snapshot HAOS",
        "app": "ansible",
    }
    now = datetime.now(UTC)
    # an older success of "Host-Update": its last run failed, so "last success" has something to show
    fake.add_finished_task(2, "success", OK_OUT, seconds=95, when=now - timedelta(days=2, hours=3))
    pending = fake.add_finished_task(1, "success", PENDING_OUT, seconds=134, when=now - timedelta(hours=3))
    pending["params"] = {"dry_run": True}
    fake.add_finished_task(2, "error", FAIL_OUT, seconds=18, when=now - timedelta(minutes=25))
    running = fake.add_finished_task(5, "running", "", seconds=0, when=now - timedelta(seconds=95))
    running.pop("end", None)
    fake.version = "v2.19.17"
    fake.info_update = {"tag_name": "v2.20.2"}  # deterministic "update available"
    # schedules (the real Semaphore evaluates them in this time zone, default UTC)
    fake.schedule_timezone = "Europe/Berlin"
    fake.add_schedule(2, "0 2 * * *", name="linux update checks")
    fake.add_schedule(2, "30 3 * * 0", name="Sonntag voller Lauf", active=False)
    fake.add_schedule(1, "0 4 * * 1", name="Dockhand wöchentlich")
    # the token of the integration: 90 days valid, 60 left (Semaphore >= 2.18.2 lists its expiry)
    fake.add_token("good-token", name="Home Assistant", age=timedelta(days=30), expires_in=timedelta(days=60))
    return fake


def make_app(fake: FakeSemaphore) -> web.Application:
    """The fake API plus the ``/ctl/{action}`` endpoints."""

    async def ctl(request: web.Request) -> web.Response:
        action = request.match_info["action"]
        if action == "requests":  # POSTs (start / stop) received so far
            return web.json_response([[a, b, c] for a, b, c in fake.requests if a == "POST"])
        if action == "puts":  # PUTs (switch a schedule on / off) received so far
            return web.json_response([[a, b, c] for a, b, c in fake.requests if a == "PUT"])
        if action == "schedules":  # state of the schedules in the fake Semaphore
            return web.json_response([{"id": s["id"], "name": s["name"], "active": s["active"]} for s in fake.schedules.values()])
        if action == "tokens":  # the API tokens in the fake Semaphore (name, days left)
            now = datetime.now(UTC)
            return web.json_response(
                [
                    {
                        "id": token[:8],
                        "name": row["name"],
                        "days_left": None if row["expires_at"] is None else round((row["expires_at"] - now).total_seconds() / 86400, 1),
                    }
                    for token, row in fake.api_tokens.items()
                ]
            )
        if action == "token_soon":  # the own token runs out in 3 days (of 90)
            now = datetime.now(UTC)
            fake.api_tokens["good-token"].update(created=now - timedelta(days=87), expires_at=now + timedelta(days=3))
        elif action == "clear":
            fake.requests.clear()
        elif action in ("slow", "fast"):  # writing calls take 2.5 s: the card must show that it is working
            fake.write_delay = 2.5 if action == "slow" else 0.0
        elif action == "optional_token":  # make the secret survey variable optional
            for var in fake.survey_template["survey_vars"]:
                if var["name"] == "token":
                    var["required"] = False
        return web.json_response({"ok": True})

    app = fake.make_app()
    app.add_routes([web.get("/ctl/{action}", ctl)])
    return app


async def main(port: int) -> None:
    runner = web.AppRunner(make_app(build()))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"fake semaphore on http://127.0.0.1:{port}  (token: good-token)", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 13000))
