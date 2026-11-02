"""The ``HA_RESULT {...}`` marker a playbook prints: parsing real Ansible output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.semaphore_ui.report import (
    analyze_output,
    build_report,
    ha_result_text,
    parse_ha_result,
)

FIXTURES = Path(__file__).parent / "fixtures"


def lines_of(name: str) -> list[str]:
    """Log lines of a recorded real ``ansible-playbook`` run."""
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def rows_of(text: str) -> list[dict]:
    """The log the way the Semaphore API returns it (one row per line)."""
    return [{"output": line, "time": "2026-10-28T03:00:00Z"} for line in text.splitlines()]


@pytest.mark.parametrize("name", ["check_yaml.log", "check_json.log"])
def test_two_hosts_are_summed_up(name: str) -> None:
    result = parse_ha_result(lines_of(name))
    assert result is not None
    assert result["needed"] is True
    assert result["updates"] == 4
    assert result["reboot_required"] is False
    assert result["hosts"] == {
        "adguard": {"needed": True, "updates": 2, "reboot_required": False, "packages": ["libssl3", "openssl"]},
        "dockerhost": {"needed": True, "updates": 2, "reboot_required": False, "packages": ["libssl3", "openssl"]},
    }
    assert result["packages"] == ["libssl3", "openssl"]  # no duplicates across hosts, each host keeps its own list


@pytest.mark.parametrize("name", ["long_yaml.log", "long_json.log"])
def test_long_value_folded_over_many_lines(name: str) -> None:
    """The yaml result format folds long values, the json format keeps one line."""
    result = parse_ha_result(lines_of(name))
    assert result is not None
    assert result["updates"] == 30
    assert result["reboot_required"] is True
    assert len(result["packages"]) == 30
    assert result["packages"][0].startswith("Inst package-with-a-long-name-1 [1.0-1]")
    assert result["packages"][-1].startswith("Inst package-with-a-long-name-30 ")


@pytest.mark.parametrize("name", ["nice_yaml.log", "nice_json.log"])
def test_pretty_printed_json(name: str) -> None:
    """``to_nice_json``: block scalar (yaml) / ``\\n`` escapes (json)."""
    result = parse_ha_result(lines_of(name))
    assert result is not None
    assert result["updates"] == 2
    assert result["packages"] == ["it's-a-pkg", "libssl3"]


@pytest.mark.parametrize("name", ["apos_yaml.log", "apos_json.log"])
def test_apostrophe_and_unicode_escapes(name: str) -> None:
    """YAML writes ``it's`` as ``it''s`` inside '...'; ``to_json`` escapes umlauts."""
    result = parse_ha_result(lines_of(name))
    assert result is not None
    assert result["packages"] == ["it's-a-pkg", "libssl3", "umläut-ü"]


def test_marker_before_a_failure_still_counts() -> None:
    """A run that fails later keeps what it reported before."""
    lines = lines_of("failing_yaml.log")
    result = parse_ha_result(lines)
    assert result is not None
    assert result["needed"] is True
    assert result["updates"] == 4
    assert result["reboot_required"] is True
    analysis = analyze_output(rows_of("\n".join(lines)))
    assert analysis["ha_result"] == result
    assert analysis["error"]["host"] == "adguard"  # the failure analysis still works


def test_no_marker_means_no_result() -> None:
    assert parse_ha_result([]) is None
    assert parse_ha_result(["PLAY [x] ***", "ok: [h]", "PLAY RECAP ***"]) is None


def test_ignores_the_marker_in_names_and_other_words() -> None:
    lines = [
        "TASK [Ergebnis HA_RESULT {melden}] *****",
        "ok: [h] => ",
        "    msg: 'MY_HA_RESULT {\"updates\": 9}'",
        "    msg: 'HA_RESULT {kaputt'",
        "    msg: 'HA_RESULT nur text'",
    ]
    assert parse_ha_result(lines) is None


def test_explicit_needed_overrides_the_rule() -> None:
    lines = [
        "ok: [a] => ",
        "    msg: 'HA_RESULT {\"updates\": 5, \"needed\": false}'",
        "ok: [b] => ",
        "    msg: 'HA_RESULT {\"updates\": 0, \"needed\": true}'",
    ]
    result = parse_ha_result(lines)
    assert result is not None
    assert result["hosts"]["a"]["needed"] is False
    assert result["hosts"]["b"]["needed"] is True
    assert result["needed"] is True
    assert result["updates"] == 5


def test_rules_without_explicit_needed() -> None:
    def parse(payload: str) -> dict:
        result = parse_ha_result(["ok: [h] => ", f"    msg: 'HA_RESULT {payload}'"])
        assert result is not None
        return result

    assert parse('{"updates": 0, "reboot_required": false}')["needed"] is False
    assert parse('{"updates": 1}')["needed"] is True
    assert parse('{"reboot_required": true}')["needed"] is True
    empty = parse("{}")
    assert empty["needed"] is False and empty["updates"] is None
    assert empty["reboot_required"] is None


def test_values_are_coerced_defensively() -> None:
    result = parse_ha_result(
        [
            "ok: [h] => ",
            '    msg: \'HA_RESULT {"updates": "7", "reboot_required": "yes", "packages": [1, null]}\'',
        ]
    )
    assert result is not None
    assert result["updates"] == 7
    assert result["reboot_required"] is True
    bad = parse_ha_result(
        ["ok: [h] => ", '    msg: \'HA_RESULT {"updates": -3, "reboot_required": "vielleicht"}\'']
    )
    assert bad is not None
    assert bad["updates"] is None and bad["reboot_required"] is None
    assert bad["needed"] is False


def test_last_line_per_host_wins_and_host_key_is_used() -> None:
    lines = [
        "TASK [a] ***",
        "ok: [h1] => ",
        "    msg: 'HA_RESULT {\"updates\": 5}'",
        "TASK [b] ***",
        "ok: [h1] => ",
        "    msg: 'HA_RESULT {\"updates\": 0}'",
        "ok: [localhost] => ",
        "    msg: 'HA_RESULT {\"host\": \"pve\", \"updates\": 2}'",
    ]
    result = parse_ha_result(lines)
    assert result is not None
    assert result["hosts"]["h1"]["updates"] == 0
    assert result["hosts"]["pve"]["updates"] == 2
    assert "localhost" not in result["hosts"]
    assert result["updates"] == 2


def test_host_name_of_delegated_and_looped_tasks() -> None:
    lines = [
        "changed: [dockerhost -> localhost] => (item=x) => {\"a\": 1}",
        "    msg: 'HA_RESULT {\"updates\": 1}'",
    ]
    result = parse_ha_result(lines)
    assert result is not None
    assert list(result["hosts"]) == ["dockerhost"]


def test_package_list_is_limited() -> None:
    names = ", ".join(f'"pkg-{i}"' for i in range(300))
    result = parse_ha_result(["ok: [h] => ", f"    msg: 'HA_RESULT {{\"packages\": [{names}]}}'"])
    assert result is not None
    assert len(result["packages"]) == 200
    assert result["hosts"]["h"]["packages_omitted"] == 100  # the card says how many are not listed


def test_two_hundred_packages_all_arrive() -> None:
    """199 updates (a real run) are listed completely - the list was cut at 50 before."""
    names = ", ".join(f'"lib-{i}"' for i in range(199))
    result = parse_ha_result(["ok: [h] => ", f"    msg: 'HA_RESULT {{\"updates\": 199, \"packages\": [{names}]}}'"])
    assert result["updates"] == 199
    assert len(result["hosts"]["h"]["packages"]) == 199
    assert "packages_omitted" not in result["hosts"]["h"]


def test_marker_in_stdout_of_a_shell_task() -> None:
    """``ansible.builtin.shell: echo HA_RESULT ...`` shown with ``-v``."""
    lines = [
        "changed: [h] => {",
        '    "stdout": "HA_RESULT {\\"updates\\": 3, \\"reboot_required\\": false}",',
        '    "stdout_lines": [',
        '        "HA_RESULT {\\"updates\\": 3, \\"reboot_required\\": false}"',
        "    ]",
        "}",
    ]
    result = parse_ha_result(lines)
    assert result is not None
    assert result["updates"] == 3


def test_ansi_colours_and_semaphore_rows_are_handled() -> None:
    log = "\n".join(
        [
            "\x1b[0;32mok: [adguard] => \x1b[0m",
            "\x1b[0;32m    msg: 'HA_RESULT {\"updates\": 1, \"reboot_required\": true}'\x1b[0m",
        ]
    )
    analysis = analyze_output(rows_of(log))
    assert analysis["ha_result"]["updates"] == 1
    assert analysis["ha_result"]["reboot_required"] is True


def test_report_contains_the_result_and_a_text_line() -> None:
    template = {"id": 7, "name": "Updates"}
    task = {
        "id": 70,
        "status": "success",
        "start": "2026-10-28T03:00:00Z",
        "end": "2026-10-28T03:01:00Z",
        "params": {"dry_run": True},
    }
    report = build_report(
        project_id=1,
        project_name="Homelab",
        template=template,
        task=task,
        output=rows_of("\n".join(lines_of("check_yaml.log"))),
        lang="de",
    )
    assert report["ha_result"]["needed"] is True
    assert report["ha_result"]["updates"] == 4
    assert "Offene Updates: 4" in report["text"]
    # without log (running, never run, log not readable) there is no result
    for output, status in ((None, "success"), (rows_of("x"), "running")):
        other = build_report(
            project_id=1,
            project_name="Homelab",
            template=template,
            task={**task, "status": status},
            output=output,
        )
        assert other["ha_result"] is None
    never = build_report(project_id=1, project_name="Homelab", template=template, task=None)
    assert never["ha_result"] is None


def test_result_text() -> None:
    assert (
        ha_result_text({"needed": True, "updates": 3, "reboot_required": True}, "de")
        == "Offene Updates: 3 · Neustart nötig"
    )
    assert ha_result_text({"needed": False, "updates": None, "reboot_required": None}, "de") == (
        "Nichts zu tun"
    )
    assert ha_result_text({"needed": True, "updates": 1, "reboot_required": False}, "en") == (
        "Pending updates: 1"
    )


@pytest.mark.parametrize(
    ("name", "reason", "task", "host"),
    [
        (
            "unreachable_yaml.log",
            "Task failed: Unable to execute ssh command line on a controller: "
            "[Errno 2] No such file or directory: b'ssh'",
            "Erreichbarkeit",
            "weg",
        ),
        (
            "unreachable_json.log",
            "Task failed: Unable to execute ssh command line on a controller: "
            "[Errno 2] No such file or directory: b'ssh'",
            "Erreichbarkeit",
            "weg",
        ),
        (
            "failing_yaml.log",
            "The command exited with a non-zero return code.",
            "Danach geht etwas schief",
            "adguard",
        ),
        (
            "failing_json.log",
            "The command exited with a non-zero return code.",
            "Danach geht etwas schief",
            "adguard",
        ),
    ],
)
def test_failure_reason_in_yaml_and_json_result_format(
    name: str, reason: str, task: str, host: str
) -> None:
    """The reason is found in both result formats of ansible-core (yaml: block below ``=>``)."""
    error = analyze_output(rows_of("\n".join(lines_of(name))))["error"]
    assert error is not None
    assert error["reason"] == reason
    assert error["failed_task"] == task
    assert error["host"] == host


@pytest.mark.parametrize("name", ["debian_hint_yaml.log", "debian_hint_json.log"])
def test_debian_hint_of_the_example_playbook(name: str) -> None:
    """Output of ``playbooks/update-linux.yml``: the Debian check runs before ``HA_RESULT``.

    adguard is "Debian 12" (stable is 13 -> hint), dockerhost is "Debian 13" (no hint); both have updates.
    """
    result = parse_ha_result(lines_of(name))
    assert result is not None
    assert result["needed"] is True
    assert result["updates"] == 4
    assert result["hosts"]["adguard"]["notes"] == ["Debian 12 (bookworm) installiert, aktuell stabil ist Debian 13 (trixie)"]
    assert "notes" not in result["hosts"]["dockerhost"]
    assert [n["host"] for n in result["notes"]] == ["adguard"]


@pytest.mark.parametrize("name", ["notes_yaml.log", "notes_json.log"])
def test_notes_are_read_in_both_result_formats(name: str) -> None:
    """``notes`` (list or single text) per host; Umlauts and an apostrophe survive."""
    result = parse_ha_result(lines_of(name))
    assert result is not None
    assert result["needed"] is False  # a hint alone is no action
    assert result["updates"] == 0
    assert result["hosts"]["adguard"]["notes"] == [
        "Installiert: Debian 12 (bookworm). Aktuell stabil: Debian 13 (trixie). "
        "HINWEIS: Distributionsupgrade prüfen!"
    ]
    assert result["hosts"]["dockerhost"]["notes"] == ["it's old: Kernel > 2 Jahre"]
    assert [(n["host"], n["text"][:12]) for n in result["notes"]] == [
        ("adguard", "Installiert:"),
        ("dockerhost", "it's old: Ke"),
    ]


def test_notes_are_cleaned_and_limited() -> None:
    long_text = "x" * 500
    lines = [
        "TASK [melden] ****",
        "ok: [h1] => {",
        '    "msg": "HA_RESULT '
        + '{\\"updates\\": 1, \\"notes\\": [\\"  a   b  \\", \\"a b\\", \\"\\", 5, ' 
        + f'\\"{long_text}\\"]}}"',
        "}",
    ]
    result = parse_ha_result(lines)
    assert result is not None
    notes = result["hosts"]["h1"]["notes"]
    assert notes[0] == "a b"  # trimmed, duplicates and empty texts dropped
    assert notes[1] == "5"
    assert len(notes[2]) <= 200 and notes[2].startswith("xxx")


def test_hosts_without_notes_keep_the_old_shape() -> None:
    result = parse_ha_result(lines_of("check_yaml.log"))
    assert result is not None
    assert result["notes"] == []
    assert all("notes" not in info for info in result["hosts"].values())


def test_notes_show_up_in_the_push_text() -> None:
    report = build_report(
        project_id=1,
        project_name="Homelab",
        template={"id": 2, "name": "linux lxc aktualisieren"},
        task={"id": 9, "status": "success", "start": "2026-10-29T04:00:01Z", "end": "2026-10-29T04:00:40Z"},
        output=rows_of("\n".join(lines_of("notes_yaml.log"))),
        lang="de",
    )
    assert "Hinweis (adguard): Installiert: Debian 12" in report["text"]
    assert report["ha_result"]["notes"][0]["host"] == "adguard"


# --------------------------------------------------------------------------- #
# 0.4.0: disk figures of the hosts
# --------------------------------------------------------------------------- #
def _marker(payload: dict, host: str = "dockerhost") -> list[str]:
    return [f"ok: [{host}] =>", f"    msg: 'HA_RESULT {json.dumps(payload)}'"]


def test_disk_figures_are_taken_per_host() -> None:
    lines = _marker({"updates": 2, "disk_free_mib": 4300.55, "disk_required_mib": "310,2", "disk_used_percent": 62.4}) + _marker(
        {"updates": 0}, "adguard"
    )
    result = parse_ha_result(lines)
    assert result["hosts"]["dockerhost"]["disk_free_mib"] == 4300.6  # one decimal
    assert result["hosts"]["dockerhost"]["disk_required_mib"] == 310.2  # text with a decimal comma
    assert result["hosts"]["dockerhost"]["disk_used_percent"] == 62.4
    assert not [k for k in result["hosts"]["adguard"] if k.startswith("disk_")]  # a host without figures has none


@pytest.mark.parametrize("bad", [-1, True, "viel", None, float("inf"), [1], {"a": 1}])
def test_nonsense_disk_figures_are_ignored(bad) -> None:
    result = parse_ha_result(_marker({"updates": 1, "disk_free_mib": bad, "disk_required_mib": bad, "disk_used_percent": bad}))
    assert result["hosts"]["dockerhost"]["updates"] == 1
    assert not [k for k in result["hosts"]["dockerhost"] if k.startswith("disk_")]


def test_a_percentage_above_100_is_ignored() -> None:
    result = parse_ha_result(_marker({"updates": 1, "disk_used_percent": 140, "disk_free_mib": 10}))
    assert "disk_used_percent" not in result["hosts"]["dockerhost"]
    assert result["hosts"]["dockerhost"]["disk_free_mib"] == 10


def test_disk_figures_do_not_change_whether_action_is_needed() -> None:
    result = parse_ha_result(_marker({"updates": 0, "disk_free_mib": 5, "disk_used_percent": 99}))
    assert result["needed"] is False
