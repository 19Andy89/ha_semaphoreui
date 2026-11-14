"""Build a ready-to-use status report ("what ran when, how long, result, why").

Pure functions without Home Assistant imports, so they are easy to test.

The report is a flat, JSON serialisable dict. It is used as

* payload of the events ``semaphore_ui_task_started`` / ``semaphore_ui_task_finished``,
* response of the action ``semaphore_ui.run_template``,
* attributes of the ``Summary`` sensor of each template.

``title`` and ``text`` can be passed straight to a notification.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
import json
import math
import re
from typing import Any

from .const import STATUS_ACTIVE, STATUS_FINISHED, STATUS_NEVER_RUN

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TASK_RE = re.compile(r"^(?:TASK|PLAY|RUNNING HANDLER)\s*\[(?P<name>.*?)\]")
FATAL_RE = re.compile(
    r"^fatal: \[(?P<host>[^\]]+?)(?: -> [^\]]+)?\]: "
    r"(?P<kind>FAILED|UNREACHABLE)! =>\s*(?P<rest>.*)$"
)
ITEM_FAILED_RE = re.compile(
    r"^failed: \[(?P<host>[^\]]+?)(?: -> [^\]]+)?\](?: \(item=.*?\))? =>\s*(?P<rest>.*)$"
)
RECAP_RE = re.compile(
    r"^(?P<host>\S+)\s*:\s*ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)\s+"
    r"unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)"
)
MSG_RE = re.compile(r'"msg":\s*"((?:[^"\\]|\\.)*)"')
# "ok: [host] =>", "changed: [host]", "fatal: [host -> other]: ..."
HOST_HEADER_RE = re.compile(
    r"^(?:ok|changed|failed|fatal|skipping|ignoring):\s*\[(?P<host>[^\]]+?)(?: -> [^\]]+)?\]"
)
# the object sits inside a JSON string (result_format=json) or a YAML "..." string: {\"a\": 1}
ESCAPED_JSON_RE = re.compile(r'^\{(?:\s|\\[nrt])*\\"')
STRING_BODY_RE = re.compile(r'(?:[^"\\]|\\.)*')

# Marker a playbook prints to tell Home Assistant whether there is something to do:
#   HA_RESULT {"updates": 3, "reboot_required": false}
HA_MARKER = "HA_RESULT"
MAX_MARKER_LINES = 300
MAX_PACKAGES = 200  # package names kept per host (the number of updates is always the full count)
MAX_PACKAGE_NAME = 80
# optional disk figures a host may report in HA_RESULT (key -> highest accepted value)
DISK_KEYS: dict[str, float | None] = {
    "disk_free_mib": None,
    "disk_required_mib": None,
    "disk_used_percent": 100.0,
}
MAX_NOTES = 10  # notes of all hosts together
MAX_NOTE_LEN = 200

TAIL_LINES = 8
MAX_REASON = 300
MAX_LINE = 200
MAX_SHORT = 255

TEXTS: dict[str, dict[str, str]] = {
    "de": {
        "success": "erfolgreich",
        "failed": "fehlgeschlagen",
        "stopped": "abgebrochen",
        "running": "läuft",
        "queued": "wartet",
        "never_run": "noch nie ausgeführt",
        "dry_run": "Testlauf",
        "started": "Gestartet",
        "duration": "Dauer",
        "result": "Ergebnis",
        "error": "Fehler",
        "task": "Task",
        "host": "Host",
        "note": "Notiz",
        "parameters": "Parameter",
        "by": "von",
        "schedule": "Zeitplan",
        "integration": "Integration",
        "h": "Std",
        "min": "Min",
        "s": "s",
        "dt_long": "%d.%m.%Y %H:%M:%S",
        "dt_short": "%d.%m. %H:%M",
        "changed": "geändert",
        "host_pending": "{n} offene Updates",
        "host_pending_1": "1 offenes Update",
        "host_changes_open": "{n} Änderungen offen",
        "host_changed": "{n} geändert",
        "host_failed": "{n} fehlgeschlagen",
        "host_unreachable": "{n} nicht erreichbar",
        "host_current": "aktuell",
        "host_ok": "ok",
        "host_action": "Handlungsbedarf",
        "pending_updates": "Offene Updates",
        "installed_n": "{n} installiert",
        "reboot_required": "Neustart nötig",
        "nothing_to_do": "Nichts zu tun",
        "hint": "Hinweis",
        "reason_unknown": "Ursache nicht erkennbar (Task-Log in Semaphore öffnen)",
    },
    "en": {
        "success": "successful",
        "failed": "failed",
        "stopped": "stopped",
        "running": "running",
        "queued": "queued",
        "never_run": "never run",
        "dry_run": "dry run",
        "started": "Started",
        "duration": "Duration",
        "result": "Result",
        "error": "Error",
        "task": "Task",
        "host": "Host",
        "note": "Note",
        "parameters": "Parameters",
        "by": "by",
        "schedule": "schedule",
        "integration": "integration",
        "h": "h",
        "min": "min",
        "s": "s",
        "dt_long": "%Y-%m-%d %H:%M:%S",
        "dt_short": "%m-%d %H:%M",
        "changed": "changed",
        "host_pending": "{n} pending updates",
        "host_pending_1": "1 pending update",
        "host_changes_open": "{n} changes pending",
        "host_changed": "{n} changed",
        "host_failed": "{n} failed",
        "host_unreachable": "{n} unreachable",
        "host_current": "up to date",
        "host_ok": "ok",
        "host_action": "Action needed",
        "pending_updates": "Pending updates",
        "installed_n": "{n} installed",
        "reboot_required": "Reboot required",
        "nothing_to_do": "Nothing to do",
        "hint": "Hint",
        "reason_unknown": "reason unknown (open the task log in Semaphore)",
    },
}

ICONS = {
    "success": "✅",
    "failed": "❌",
    "stopped": "⏹️",
    "running": "▶️",
    "queued": "⏳",
    "never_run": "➖",
}

# Keys of the report dict (used to exclude them from the recorder).
REPORT_KEYS = (
    "project",
    "project_id",
    "template",
    "template_id",
    "task_id",
    "status",
    "result",
    "success",
    "finished",
    "dry_run",
    "started_by",
    "note",
    "parameters",
    "created",
    "started",
    "ended",
    "started_local",
    "ended_local",
    "duration_seconds",
    "duration",
    "error",
    "recap",
    "output_tail",
    "ha_result",
    "url",
    "title",
    "text",
    "short",
)


def _texts(lang: str | None) -> dict[str, str]:
    return TEXTS["de" if (lang or "").lower().startswith("de") else "en"]


def truncate(text: str, limit: int) -> str:
    """Shorten ``text`` to ``limit`` characters."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_time(value: Any) -> datetime | None:
    """Parse a timestamp of the API into an aware datetime."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.year < 2000:  # Go zero time "0001-01-01T00:00:00Z"
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def task_status(task: dict[str, Any] | None) -> str:
    """Raw status of a task (``never_run`` if there is no task)."""
    return (task or {}).get("status") or STATUS_NEVER_RUN


def task_started(task: dict[str, Any] | None) -> datetime | None:
    """Start of the task (falls back to the creation time)."""
    if not task:
        return None
    return parse_time(task.get("start")) or parse_time(task.get("created"))


def task_ended(task: dict[str, Any] | None) -> datetime | None:
    """End of a finished task."""
    if not task or task_status(task) not in STATUS_FINISHED:
        return None
    return parse_time(task.get("end"))


def task_duration(task: dict[str, Any] | None) -> int | None:
    """Duration of a finished task in seconds."""
    start, end = task_started(task), task_ended(task)
    if start is None or end is None:
        return None
    return max(0, round((end - start).total_seconds()))


def _parameters(task: dict[str, Any] | None) -> dict[str, Any]:
    """Survey values the task was started with (secrets are never stored)."""
    raw = (task or {}).get("environment")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def is_dry_run(task: dict[str, Any] | None) -> bool:
    """Was the task a dry run?"""
    if not task:
        return False
    params = task.get("params")
    if isinstance(params, dict) and params.get("dry_run"):
        return True
    return bool(task.get("dry_run"))


def result_of(status: str) -> str:
    """Normalised result: success, failed, stopped, running, queued, never_run."""
    if status == "success":
        return "success"
    if status == "error":
        return "failed"
    if status in ("stopped", "rejected"):
        return "stopped"
    if status in ("starting", "running", "stopping"):
        return "running"
    if status in STATUS_ACTIVE:
        return "queued"
    return "never_run"


def format_duration(seconds: int | None, lang: str | None = "de") -> str | None:
    """``72`` -> ``1 Min 12 s``."""
    if seconds is None:
        return None
    t = _texts(lang)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} {t['h']} {minutes:02d} {t['min']}"
    if minutes:
        return f"{minutes} {t['min']} {secs:02d} {t['s']}" if secs else f"{minutes} {t['min']}"
    return f"{secs} {t['s']}"


# --------------------------------------------------------------------------- #
# Log analysis
# --------------------------------------------------------------------------- #
def _rows_to_lines(rows: list[dict[str, Any]] | None) -> list[str]:
    lines: list[str] = []
    for row in rows or []:
        for line in str(row.get("output", "")).splitlines():
            lines.append(ANSI_RE.sub("", line).rstrip())
    return lines


BLOCK_INDICATORS = frozenset({"|", "|-", "|+", ">", ">-", ">+"})
YAML_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):(?:\s+(?P<value>.*))?$")


def _yaml_scalar(parts: list[str]) -> str:
    """Text of a (possibly folded or quoted) YAML scalar given as its lines."""
    head = parts[0].strip() if parts else ""
    if head in BLOCK_INDICATORS:
        return " ".join(part.strip() for part in parts[1:]).strip()
    text = " ".join(part.strip() for part in parts).strip()
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) >= 2 and text[0] == text[-1] == '"':
        try:
            return str(json.loads(text))
        except ValueError:
            return text[1:-1]
    return text


def _yaml_result_block(lines: list[str], idx: int) -> dict[str, str] | None:
    """Top level ``key: value`` pairs of the indented block after ``FAILED! =>``.

    Ansible's ``yaml`` result format prints the result as YAML below the header
    line instead of JSON on the same line.
    """
    base: int | None = None
    pairs: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines[idx + 1 : idx + 400]:
        if not line.strip() or not line[0].isspace():
            break
        indent = len(line) - len(line.lstrip())
        if base is None:
            base = indent
        if indent < base:
            break
        key = YAML_KEY_RE.match(line.strip()) if indent == base else None
        if key and not line.strip().startswith("- "):
            current = pairs.setdefault(key["key"], [])
            current.append(key["value"] or "")
        elif current is not None:
            current.append(line.strip())
    if not pairs:
        return None
    return {key: _yaml_scalar(parts) for key, parts in pairs.items()}


def _collect_payload(lines: list[str], idx: int, rest: str) -> Any:
    """Return the payload that follows ``=>`` (JSON on one or several lines, or a YAML block)."""
    buf = rest.strip()
    if not buf:
        return _yaml_result_block(lines, idx) or buf
    if not buf.startswith("{"):
        return buf
    try:
        return json.loads(buf)
    except ValueError:
        pass
    for line in lines[idx + 1 : idx + 400]:
        if TASK_RE.match(line) or line.startswith("PLAY RECAP"):
            break
        buf += "\n" + line
        if line.lstrip().startswith("}"):
            try:
                return json.loads(buf)
            except ValueError:
                continue
    return buf


def _reason_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        msg = payload.get("msg") or payload.get("message") or payload.get("reason")
        if msg is not None and not isinstance(msg, str):
            msg = json.dumps(msg, ensure_ascii=False)
        msg = (msg or "").strip()
        stderr = payload.get("stderr")
        if isinstance(stderr, str) and stderr.strip() and stderr.strip() not in msg:
            tail = [ln.strip() for ln in stderr.strip().splitlines() if ln.strip()][-2:]
            msg = f"{msg}: {' | '.join(tail)}" if msg else " | ".join(tail)
        return msg
    if isinstance(payload, str):
        match = MSG_RE.search(payload)
        if match:
            try:
                return json.loads(f'"{match.group(1)}"')
            except ValueError:
                return match.group(1)
        return payload
    return ""


# --------------------------------------------------------------------------- #
# HA_RESULT marker ("is there something to do?")
# --------------------------------------------------------------------------- #
def _as_count(value: Any) -> int | None:
    """Non-negative integer (``3``, ``3.0`` or ``"3"``), otherwise ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _as_number(value: Any, *, maximum: float | None = None) -> float | None:
    """Non-negative number with one decimal (``4.2``, ``"4.2"``), otherwise ``None`` (also above ``maximum``)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    if maximum is not None and value > maximum:
        return None
    return round(float(value), 1)


def _as_flag(value: Any) -> bool | None:
    """Boolean (also ``0/1`` and ``"true"/"no"``), otherwise ``None``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "on", "1"):
            return True
        if text in ("false", "no", "off", "0"):
            return False
    return None


def _as_notes(value: Any) -> list[str]:
    """Short hints of one host (``"text"`` or ``["text", ...]``), trimmed and without duplicates."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    notes: list[str] = []
    for item in items:
        if isinstance(item, (dict, list)):
            continue
        text = truncate(" ".join(str(item).split()), MAX_NOTE_LEN)
        if text and text not in notes:
            notes.append(text)
    return notes


def _decode_marker(lines: list[str], idx: int, rest: str, single_quoted: bool) -> dict | None:
    """Decode the JSON object after the marker (it may continue on the next lines).

    Ansible folds long values in the ``yaml`` result format (continuation lines are
    indented) and escapes quotes and line breaks in the ``json`` format. Both are handled.
    """
    text = rest
    for extra in range(MAX_MARKER_LINES + 1):
        candidate = text.strip()
        if single_quoted:
            candidate = candidate.replace("''", "'")  # YAML '...' escapes ' as ''
        data = None
        try:
            if ESCAPED_JSON_RE.match(candidate):
                # cut the string literal at its closing quote and unescape it
                candidate = json.loads(f'"{STRING_BODY_RE.match(candidate).group(0)}"')
            data, _end = json.JSONDecoder().raw_decode(candidate)
        except ValueError:
            pass  # not complete yet (folded over more lines) or no JSON
        if isinstance(data, dict):
            return data
        position = idx + 1 + extra
        if position >= len(lines):
            return None
        line = lines[position]
        if not line.strip() or not line[0].isspace():
            return None  # the folded value ends at the first unindented/empty line
        text += " " + line.strip()
    return None


def _marker_payloads(lines: list[str]) -> list[tuple[str, dict]]:
    """All ``HA_RESULT {...}`` objects of the log as ``(host, payload)``."""
    found: list[tuple[str, dict]] = []
    host: str | None = None
    for idx, line in enumerate(lines):
        header = HOST_HEADER_RE.match(line)
        if header:
            host = header["host"].strip()
        elif TASK_RE.match(line):
            host = None
        pos = line.find(HA_MARKER)
        if pos < 0:
            continue
        before = line[pos - 1] if pos else ""
        if before and (before.isalnum() or before == "_"):
            continue  # part of another word
        rest = line[pos + len(HA_MARKER) :].lstrip(": \t")
        if not rest.startswith("{"):
            continue  # e.g. the name of a task that mentions the marker
        payload = _decode_marker(lines, idx, rest, single_quoted=before == "'")
        if payload is None:
            continue
        name = payload.get("host")
        found.append(
            (str(name).strip() if isinstance(name, str) and name.strip() else (host or "unknown"), payload)
        )
    return found


def parse_ha_result(lines: list[str]) -> dict[str, Any] | None:
    """Evaluate the ``HA_RESULT {...}`` lines a playbook printed (``None`` if there are none).

    Keys of the JSON object (all optional): ``updates`` (number of pending updates),
    ``installed`` (number of updates this run installed; leave it out in a dry run), ``reboot_required`` (bool), ``needed`` (bool, overrides the rule below),
    ``packages`` (list of names), ``disk_free_mib`` / ``disk_required_mib`` (MiB free / needed
    by the updates) and ``disk_used_percent`` (0-100) of the host (shown only), ``notes`` (a hint or a list of hints, e.g. "Debian 13
    available"; shown only, they do not count as action), ``host`` (otherwise the host
    of the Ansible output).
    Without ``needed``, action is needed if ``updates > 0`` or ``reboot_required``.
    The last line per host wins.
    """
    hosts: dict[str, dict[str, Any]] = {}
    packages: list[str] = []
    for host, payload in _marker_payloads(lines):
        updates = _as_count(payload.get("updates"))
        installed = _as_count(payload.get("installed"))
        reboot = _as_flag(payload.get("reboot_required"))
        explicit = _as_flag(payload.get("needed")) if "needed" in payload else None
        hosts[host] = {
            "needed": explicit
            if explicit is not None
            else bool((updates or 0) > 0 or reboot),
            "updates": updates,
            "reboot_required": reboot,
        }
        if installed is not None:
            hosts[host]["installed"] = installed
        # optional disk figures of the host (root file system): free, needed by the updates, used in percent
        for key, maximum in DISK_KEYS.items():
            number = _as_number(payload.get(key), maximum=maximum)
            if number is not None:
                hosts[host][key] = number
        notes = _as_notes(payload.get("notes", payload.get("note")))
        if notes:
            hosts[host]["notes"] = notes
        names = payload.get("packages")
        if isinstance(names, list):
            own: list[str] = []
            for name in names:
                text = truncate(str(name), MAX_PACKAGE_NAME)
                if text and text not in own:
                    own.append(text)
                if text and text not in packages:
                    packages.append(text)
            if own:
                hosts[host]["packages"] = own[:MAX_PACKAGES]  # the card shows them per host
                if len(own) > MAX_PACKAGES:
                    hosts[host]["packages_omitted"] = len(own) - MAX_PACKAGES
    if not hosts:
        return None
    counts = [h["updates"] for h in hosts.values() if h["updates"] is not None]
    installed_counts = [h["installed"] for h in hosts.values() if "installed" in h]
    flags = [h["reboot_required"] for h in hosts.values() if h["reboot_required"] is not None]
    return {
        "needed": any(h["needed"] for h in hosts.values()),
        "updates": sum(counts) if counts else None,
        "installed": sum(installed_counts) if installed_counts else None,
        "reboot_required": any(flags) if flags else None,
        "hosts": hosts,
        "packages": packages[:MAX_PACKAGES],
        "notes": [
            {"host": host, "text": text} for host, info in hosts.items() for text in info.get("notes", [])
        ][:MAX_NOTES],
    }


def analyze_output(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Extract failure reason, play recap, ``HA_RESULT`` and the last lines of a task log."""
    lines = _rows_to_lines(rows)
    result: dict[str, Any] = {"error": None, "recap": [], "tail": [], "ha_result": None}
    if not lines:
        return result

    non_empty = [ln for ln in lines if ln.strip()]
    result["tail"] = [truncate(ln, MAX_LINE) for ln in non_empty[-TAIL_LINES:]]

    current_task: str | None = None
    failure: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    in_recap = False

    for idx, line in enumerate(lines):
        if line.startswith("PLAY RECAP"):
            in_recap = True
            continue
        if in_recap:
            match = RECAP_RE.match(line.strip())
            if match:
                result["recap"].append(
                    {
                        "host": match["host"],
                        "ok": int(match["ok"]),
                        "changed": int(match["changed"]),
                        "unreachable": int(match["unreachable"]),
                        "failed": int(match["failed"]),
                    }
                )
            continue

        task_match = TASK_RE.match(line)
        if task_match:
            current_task = task_match["name"].strip()
            continue

        if failure is None:
            fatal = FATAL_RE.match(line) or ITEM_FAILED_RE.match(line)
            if fatal:
                payload = _collect_payload(lines, idx, fatal["rest"])
                kind = fatal.groupdict().get("kind") or "FAILED"
                reason = " ".join(_reason_from_payload(payload).split()) or kind.lower()
                failure = {
                    "reason": truncate(reason, MAX_REASON),
                    "failed_task": current_task,
                    "host": fatal["host"],
                    "kind": kind.lower(),
                }
                continue

        if fallback is None:
            text = None
            if line.startswith("ERROR!"):
                text = line[len("ERROR!") :]
            elif line.startswith("[ERROR]:"):
                text = line[len("[ERROR]:") :]
            if text and text.strip():
                fallback = {
                    "reason": truncate(" ".join(text.split()), MAX_REASON),
                    "failed_task": current_task,
                    "host": None,
                    "kind": "error",
                }

    result["error"] = failure or fallback
    result["ha_result"] = parse_ha_result(lines)
    return result


# --------------------------------------------------------------------------- #
# Failures (attributes of the problem sensors)
# --------------------------------------------------------------------------- #
def failure_info(report: dict[str, Any]) -> dict[str, Any] | None:
    """Compact description of a failed run (``None`` if the run did not fail).

    Answers "which template (where), why (reason) and at which step/host (what)".
    """
    if report.get("result") != "failed":
        return None
    error = report.get("error") or {}
    tail = report.get("output_tail") or []
    return {
        "template": report["template"],
        "template_id": report["template_id"],
        "task_id": report["task_id"],
        "reason": error.get("reason") or (tail[-1] if tail else None),
        "failed_task": error.get("failed_task"),
        "host": error.get("host"),
        "kind": error.get("kind"),
        "dry_run": report["dry_run"],
        "started_local": report["started_local"],
        "ended_local": report["ended_local"],
        "ended": report["ended"],
        "url": report["url"],
    }


def failure_text(info: dict[str, Any], lang: str | None = "de") -> str:
    """One line: ``Template (#12, 26.10.2026 04:12:00): reason · Task: step · Host: pi``."""
    t = _texts(lang)
    head = f"{info['template']} (#{info['task_id']}"
    when = info.get("ended_local") or info.get("started_local")
    if when:
        head += f", {when}"
    head += ")"
    parts = [info.get("reason") or t["reason_unknown"]]
    if info.get("failed_task"):
        parts.append(f"{t['task']}: {info['failed_task']}")
    if info.get("host"):
        parts.append(f"{t['host']}: {info['host']}")
    return f"{head}: " + " · ".join(parts)


def ha_result_text(ha_result: dict[str, Any], lang: str | None = "de") -> str:
    """``Offene Updates: 3 · Neustart nötig`` / ``Nichts zu tun``."""
    t = _texts(lang)
    parts: list[str] = []
    # "Offene Updates: 0" next to "Neustart nötig" says nothing: only name updates that are open
    if isinstance(ha_result.get("updates"), (int, float)) and ha_result["updates"] > 0:
        parts.append(f"{t['pending_updates']}: {ha_result['updates']}")
    installed = ha_result.get("installed")
    if isinstance(installed, (int, float)) and not isinstance(installed, bool) and installed > 0:
        parts.append(t["installed_n"].format(n=int(installed)))  # what this run installed
    if ha_result.get("reboot_required"):
        parts.append(t["reboot_required"])
    if not parts:
        parts.append(t["pending_updates"] if ha_result.get("needed") else t["nothing_to_do"])
    return " · ".join(parts)


def host_lines(
    recap: list[dict[str, Any]],
    ha_result: dict[str, Any] | None,
    *,
    dry_run: bool,
    lang: str | None = "de",
) -> list[str]:
    """One line per host, without zero values: ``• pve: 28 offene Updates · Neustart nötig``.

    With ``HA_RESULT`` the numbers are exact (open / installed updates, reboot). Without it only the
    Ansible recap is known: ``changed`` of a dry run is what would change, of a real run what changed.
    """
    t = _texts(lang)
    reported = (ha_result or {}).get("hosts") or {}
    names = [r["host"] for r in recap]
    names += sorted(h for h in reported if h not in names)
    by_recap = {r["host"]: r for r in recap}
    lines: list[str] = []
    for name in names:
        rec = by_recap.get(name)
        info = reported.get(name)
        bits: list[str] = []
        if info:
            updates = info.get("updates")
            if isinstance(updates, (int, float)) and not isinstance(updates, bool) and updates > 0:
                bits.append(t["host_pending_1"] if updates == 1 else t["host_pending"].format(n=int(updates)))
            installed = info.get("installed")
            if isinstance(installed, (int, float)) and not isinstance(installed, bool) and installed > 0:
                bits.append(t["installed_n"].format(n=int(installed)))
            if info.get("reboot_required"):
                bits.append(t["reboot_required"])
        elif rec and rec["changed"] > 0:
            bits.append(t["host_changes_open" if dry_run else "host_changed"].format(n=rec["changed"]))
        if rec and rec["failed"] > 0:
            bits.append(t["host_failed"].format(n=rec["failed"]))
        if rec and rec["unreachable"] > 0:
            bits.append(t["host_unreachable"].format(n=rec["unreachable"]))
        if not bits:
            bits.append(t["host_action"] if info and info.get("needed") else t["host_current" if info else "host_ok"])
        lines.append(f"• {name}: {' · '.join(bits)}")
    return lines


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def build_report(
    *,
    project_id: int,
    project_name: str,
    template: dict[str, Any],
    task: dict[str, Any] | None,
    output: list[dict[str, Any]] | None = None,
    base_url: str = "",
    lang: str | None = "de",
    tz: tzinfo | None = None,
) -> dict[str, Any]:
    """Return the report of ``task`` (``None`` = template was never run)."""
    t = _texts(lang)
    status = task_status(task)
    result = result_of(status)
    finished = status in STATUS_FINISHED
    dry_run = is_dry_run(task)
    template_name = template.get("name") or f"#{template.get('id')}"

    started = task_started(task)
    ended = task_ended(task)
    created = parse_time((task or {}).get("created"))
    duration_s = task_duration(task)
    duration_text = format_duration(duration_s, lang)

    def local(value: datetime | None, key: str) -> str | None:
        if value is None:
            return None
        return (value.astimezone(tz) if tz else value).strftime(t[key])

    started_by = None
    if task:
        if task.get("user_name"):
            started_by = task["user_name"]
        elif task.get("schedule_id"):
            started_by = t["schedule"]
        elif task.get("integration_id"):
            started_by = t["integration"]

    analysis = analyze_output(output) if (output is not None and finished) else None
    error = None
    if result == "failed":
        error = (analysis or {}).get("error") or None

    task_id = (task or {}).get("id")
    url = ""
    if base_url and task_id is not None:
        url = (
            f"{base_url}/project/{project_id}/templates/{template.get('id')}"
            f"?t={task_id}"
        )

    note = ((task or {}).get("message") or "").strip() or None
    parameters = _parameters(task)
    icon = ICONS[result]
    title = f"{icon} {template_name}"
    if dry_run:
        title += f" ({t['dry_run']})"
    title += f": {t[result]}"

    recap = (analysis or {}).get("recap", [])
    ha_result = (analysis or {}).get("ha_result")

    # --- multi line text for push messages ---
    lines: list[str] = []
    if started:
        line = f"{t['started']}: {local(started, 'dt_long')}"
        if started_by:
            line += f" ({t['by']} {started_by})"
        lines.append(line)
    if duration_text:
        lines.append(f"{t['duration']}: {duration_text}")
    if finished:
        lines.append(f"{t['result']}: {t[result]}")
        lines.extend(host_lines(recap, ha_result, dry_run=dry_run, lang=lang))
    if ha_result:
        # one host: its line already says it all; several hosts (or none named): add the total
        if len((ha_result.get("hosts") or {})) != 1:
            lines.append(ha_result_text(ha_result, lang))
        for item in (ha_result.get("notes") or [])[:3]:
            lines.append(f"{t['hint']} ({item['host']}): {item['text']}")
    if error:
        lines.append(f"{t['error']}: {error['reason']}")
        if error.get("failed_task"):
            lines.append(f"{t['task']}: {error['failed_task']}")
        if error.get("host"):
            lines.append(f"{t['host']}: {error['host']}")
    elif result == "failed" and analysis and analysis["tail"]:
        lines.append(f"{t['error']}: {analysis['tail'][-1]}")
    if parameters:
        shown = ", ".join(f"{k}={v}" for k, v in parameters.items())
        lines.append(f"{t['parameters']}: {truncate(shown, MAX_LINE)}")
    if note:
        lines.append(f"{t['note']}: {note}")

    # --- one line summary (state of the summary sensor) ---
    short_parts = [icon, t[result]]
    if dry_run:
        short_parts.append(f"({t['dry_run']})")
    if duration_text:
        short_parts.append(f"· {duration_text}")
    if started:
        short_parts.append(f"· {local(started, 'dt_short')}")
    if error:
        short_parts.append(f"· {error['reason']}")
    short = truncate(" ".join(short_parts), MAX_SHORT)

    return {
        "project": project_name,
        "project_id": project_id,
        "template": template_name,
        "template_id": template.get("id"),
        "task_id": task_id,
        "status": status,
        "result": result,
        "success": True if result == "success" else (False if result == "failed" else None),
        "finished": finished,
        "dry_run": dry_run,
        "started_by": started_by,
        "note": note,
        "parameters": parameters,
        "created": created.isoformat() if created else None,
        "started": started.isoformat() if started else None,
        "ended": ended.isoformat() if ended else None,
        "started_local": local(started, "dt_long"),
        "ended_local": local(ended, "dt_long"),
        "duration_seconds": duration_s,
        "duration": duration_text,
        "error": error,
        "recap": recap,
        "output_tail": (analysis or {}).get("tail", []),
        "ha_result": ha_result,
        "url": url,
        "title": title,
        "text": "\n".join(lines),
        "short": short,
    }
