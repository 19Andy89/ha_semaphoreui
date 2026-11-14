"""Tests of the status report (pure functions)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from custom_components.semaphore_ui.api import normalize_base_url
from custom_components.semaphore_ui.report import (
    analyze_output,
    build_report,
    format_duration,
    host_lines,
)

BERLIN = ZoneInfo("Europe/Berlin")
TEMPLATE = {"id": 1, "name": "docker-system aktualisieren", "app": "ansible"}


def rows(text: str) -> list[dict]:
    return [{"id": i, "output": line} for i, line in enumerate(text.splitlines())]


FAIL_PRETTY = """\
PLAY [docker-system (Dockhand + Portainer) aktualisieren] *********************

TASK [Neue Images ziehen, Container mit neuem Image neu erstellen] *************
\x1b[0;31mfatal: [dockerhost]: FAILED! => {
    "changed": false,
    "msg": "Error when processing /home/x/docker-system: pull access denied",
    "stderr": "line one\\nfailed to pull image foo: denied"
}\x1b[0m

PLAY RECAP *********************************************************************
dockerhost                 : ok=0    changed=0    unreachable=0    failed=1    skipped=0    rescued=0    ignored=0
"""

FAIL_ONELINE = """\
TASK [Ping] ********
fatal: [dockerhost]: UNREACHABLE! => {"changed": false, "msg": "Failed to connect to the host via ssh: root@dockerhost: Permission denied (publickey,password).", "unreachable": true}
PLAY RECAP ********
dockerhost                 : ok=0    changed=0    unreachable=1    failed=0    skipped=0    rescued=0    ignored=0
"""

OK_OUT = """\
TASK [Ergebnis anzeigen] ********
ok: [dockerhost] => {"x": 1}
PLAY RECAP ********
dockerhost                 : ok=2    changed=1    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
"""


def test_failure_multiline_json_with_ansi() -> None:
    result = analyze_output(rows(FAIL_PRETTY))
    err = result["error"]
    assert err["host"] == "dockerhost"
    assert err["failed_task"].startswith("Neue Images ziehen")
    assert "pull access denied" in err["reason"]
    assert "failed to pull image foo: denied" in err["reason"]  # stderr tail
    assert "\n" not in err["reason"]
    assert result["recap"][0]["failed"] == 1
    assert result["tail"][-1].startswith("dockerhost")


def test_failure_unreachable_oneline() -> None:
    err = analyze_output(rows(FAIL_ONELINE))["error"]
    assert err["kind"] == "unreachable"
    assert "Permission denied" in err["reason"]
    assert err["failed_task"] == "Ping"


def test_error_bang_fallback_and_empty() -> None:
    out = analyze_output(rows("ERROR! the playbook: x.yml could not be found"))
    assert out["error"]["reason"] == "the playbook: x.yml could not be found"
    empty = analyze_output([])
    assert empty == {"error": None, "recap": [], "tail": [], "ha_result": None}
    assert analyze_output(None)["error"] is None


def test_report_success_de() -> None:
    task = {
        "id": 7,
        "status": "success",
        "created": "2026-10-24T12:03:00.5Z",
        "start": "2026-10-24T12:03:01.123456789Z",
        "end": "2026-10-24T12:04:13Z",
        "user_name": "Andreas",
        "params": {},
    }
    rep = build_report(
        project_id=1,
        project_name="Homelab",
        template=TEMPLATE,
        task=task,
        output=rows(OK_OUT),
        base_url="https://semaphore.example",
        lang="de",
        tz=BERLIN,
    )
    assert rep["result"] == "success" and rep["success"] is True
    assert rep["duration_seconds"] == 72 and rep["duration"] == "1 Min 12 s"
    assert rep["started_local"] == "24.10.2026 14:03:01"  # UTC+2
    assert rep["title"] == "✅ docker-system aktualisieren: erfolgreich"
    assert rep["url"] == "https://semaphore.example/project/1/templates/1?t=7"
    assert "Gestartet: 24.10.2026 14:03:01 (von Andreas)" in rep["text"]
    assert "Dauer: 1 Min 12 s" in rep["text"]
    assert "Ergebnis: erfolgreich\n• dockerhost: 1 geändert" in rep["text"]  # without HA_RESULT: the recap, no zero values
    assert "failed=0" not in rep["text"] and "ok=" not in rep["text"]
    assert rep["error"] is None
    assert rep["short"].startswith("✅ erfolgreich · 1 Min 12 s · 24.10. 14:03")
    assert len(rep["short"]) <= 255


def test_report_failure_and_dry_run_en() -> None:
    task = {
        "id": 8,
        "status": "error",
        "created": "2026-10-24T12:00:00Z",
        "start": "2026-10-24T12:00:00Z",
        "end": "2026-10-24T12:00:03Z",
        "params": {"dry_run": True},
    }
    rep = build_report(
        project_id=1,
        project_name="Homelab",
        template=TEMPLATE,
        task=task,
        output=rows(FAIL_PRETTY),
        base_url="",
        lang="en",
        tz=BERLIN,
    )
    assert rep["result"] == "failed" and rep["success"] is False
    assert rep["dry_run"] is True
    assert rep["title"] == "❌ docker-system aktualisieren (dry run): failed"
    assert rep["error"]["host"] == "dockerhost"
    assert "Error: Error when processing" in rep["text"]
    assert "Task: Neue Images ziehen" in rep["text"]
    assert rep["url"] == ""


def test_report_running_and_never_run() -> None:
    running = build_report(
        project_id=1,
        project_name="P",
        template=TEMPLATE,
        task={"id": 9, "status": "running", "created": "2026-10-24T12:00:00Z"},
        lang="de",
    )
    assert running["result"] == "running" and running["finished"] is False
    assert running["duration_seconds"] is None and running["ended"] is None
    never = build_report(project_id=1, project_name="P", template=TEMPLATE, task=None)
    assert never["status"] == "never_run" and never["result"] == "never_run"
    assert never["task_id"] is None and never["started"] is None


def test_format_duration_and_url() -> None:
    assert format_duration(5, "de") == "5 s"
    assert format_duration(120, "de") == "2 Min"
    assert format_duration(3725, "en") == "1 h 02 min"
    assert format_duration(None) is None
    assert normalize_base_url("semaphore.local:3000/") == "http://semaphore.local:3000"
    assert normalize_base_url("https://a.b/api/") == "https://a.b"
    assert normalize_base_url(" https://a.b/prefix/api ") == "https://a.b/prefix"


def _recap(host: str, *, ok: int = 1, changed: int = 0, failed: int = 0, unreachable: int = 0) -> dict:
    return {"host": host, "ok": ok, "changed": changed, "failed": failed, "unreachable": unreachable}


def test_host_lines_are_one_line_per_host_without_zero_values() -> None:
    recap = [_recap("pve", changed=4), _recap("docker", changed=1), _recap("pi", ok=3)]
    ha = {
        "needed": True,
        "updates": 29,
        "reboot_required": True,
        "hosts": {
            "pve": {"updates": 28, "installed": 0, "reboot_required": True, "needed": True},
            "docker": {"updates": 1, "reboot_required": False, "needed": True},
            "pi": {"updates": 0, "reboot_required": False, "needed": False},
        },
    }
    # dry run: "changed" is not shown, the open updates are
    assert host_lines(recap, ha, dry_run=True, lang="de") == [
        "• pve: 28 offene Updates · Neustart nötig",
        "• docker: 1 offenes Update",
        "• pi: aktuell",
    ]
    # real run: what was installed
    ha_after = {
        "hosts": {
            "pve": {"updates": 0, "installed": 28, "reboot_required": True},
            "docker": {"updates": 0, "installed": 1},
            "pi": {"updates": 0, "installed": 0},
        }
    }
    assert host_lines(recap, ha_after, dry_run=False, lang="de") == [
        "• pve: 28 installiert · Neustart nötig",
        "• docker: 1 installiert",
        "• pi: aktuell",
    ]
    assert host_lines(recap[:1], {"hosts": {"pve": {"updates": 2}}}, dry_run=True, lang="en") == [
        "• pve: 2 pending updates"
    ]


def test_host_lines_without_ha_result_use_the_recap_only() -> None:
    recap = [_recap("a", changed=3), _recap("b"), _recap("c", failed=1, unreachable=0), _recap("d", ok=0, unreachable=1)]
    assert host_lines(recap, None, dry_run=False, lang="de") == [
        "• a: 3 geändert",
        "• b: ok",
        "• c: 1 fehlgeschlagen",
        "• d: 1 nicht erreichbar",
    ]
    assert host_lines(recap[:1], None, dry_run=True, lang="de") == ["• a: 3 Änderungen offen"]


def test_host_only_known_from_ha_result_is_listed_and_action_is_named() -> None:
    ha = {"hosts": {"zeta": {"updates": 0, "needed": True}, "alpha": {"updates": 5}}}
    assert host_lines([], ha, dry_run=True, lang="de") == ["• alpha: 5 offene Updates", "• zeta: Handlungsbedarf"]
