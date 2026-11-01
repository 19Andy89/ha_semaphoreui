"""Tests of the status report (pure functions)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from custom_components.semaphore_ui.api import normalize_base_url
from custom_components.semaphore_ui.report import (
    analyze_output,
    build_report,
    format_duration,
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
    assert "dockerhost: ok=2 geändert=1 failed=0" in rep["text"]
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
