"""Schedules of Semaphore: its cron dialect and the time of the next run.

Semaphore reads cron expressions with ``robfig/cron`` (``ParseStandard``). That means:

* five fields ``minute hour day-of-month month day-of-week`` (no seconds, no year),
* ``*`` / ``?``, lists ``1,5``, ranges ``1-5``, steps ``*/15`` / ``10-50/5`` / ``5/10`` (= ``5-59/10``),
  month names ``JAN``..``DEC`` and weekday names ``SUN``..``SAT`` (Sunday is ``0``; ``7`` is invalid),
* the descriptors ``@yearly @annually @monthly @weekly @daily @midnight @hourly``,
* ``@every <duration>`` (not predictable, see :func:`next_after`),
* an optional ``TZ=Europe/Berlin`` / ``CRON_TZ=...`` prefix.

If both day-of-month and day-of-week are restricted, a day matches when **either** matches
(unless one of them starts with ``*``, then both must match) - the classic cron rule that
``robfig/cron`` follows as well. Without a ``TZ=`` prefix the schedule runs in the time zone
Semaphore is configured with (``schedule_timezone`` in ``/api/info``, default ``UTC``).

This module does not depend on Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from functools import lru_cache
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Search window for the next run (a yearly "0 0 29 2 *" needs up to 8 years).
MAX_SEARCH_DAYS = 366 * 9

SCHEDULE_TYPE_RUN_AT = "run_at"

_MONTHS = {
    name: index
    for index, name in enumerate(
        "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1
    )
}
_WEEKDAYS = {name: index for index, name in enumerate("sun mon tue wed thu fri sat".split())}
_DESCRIPTORS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ns|us|µs|ms|s|m|h)")
_DURATION_UNITS = {
    "ns": 1e-9,
    "us": 1e-6,
    "µs": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}


class CronError(ValueError):
    """The cron expression is not valid for Semaphore."""


@dataclass(frozen=True)
class CronSpec:
    """A parsed cron expression."""

    minutes: tuple[int, ...] = ()
    hours: tuple[int, ...] = ()
    days: frozenset[int] = frozenset()
    months: frozenset[int] = frozenset()
    weekdays: frozenset[int] = frozenset()
    # a day-of-month / day-of-week that begins with "*" (both must match then)
    days_any: bool = False
    weekdays_any: bool = False
    tz: tzinfo | None = None
    every: timedelta | None = None


def _number(text: str, names: dict[str, int] | None) -> int:
    """A number or (month/weekday) name."""
    lowered = text.lower()
    if names and lowered in names:
        return names[lowered]
    if text.isdigit():
        return int(text)
    raise CronError(f"Failed to parse number: {text!r}")


def _field(
    text: str, low: int, high: int, names: dict[str, int] | None = None
) -> tuple[frozenset[int], bool]:
    """Values of one field and whether it counts as "any" (starts with ``*``)."""
    if not text:
        raise CronError("Empty field")
    values: set[int] = set()
    any_value = False
    for part in text.split(","):
        if part.count("/") > 1:
            raise CronError(f"Too many slashes: {part!r}")
        range_text, _, step_text = part.partition("/")
        bounds = range_text.split("-")
        if len(bounds) > 2:
            raise CronError(f"Too many hyphens: {part!r}")
        star = False
        if bounds[0] in ("*", "?"):
            if len(bounds) != 1:
                raise CronError(f"Invalid range: {part!r}")
            start, end, star = low, high, True
        else:
            start = _number(bounds[0], names)
            end = _number(bounds[1], names) if len(bounds) == 2 else start
        step = 1
        if "/" in part:
            if not step_text.isdigit():
                raise CronError(f"Failed to parse step: {part!r}")
            step = int(step_text)
            if step == 0:
                raise CronError(f"Step of range should be a positive number: {part!r}")
            if len(bounds) == 1 and not star:
                end = high  # "5/10" means "5-max/10"
        if step > 1:
            star = False
        if start < low:
            raise CronError(f"Beginning of range ({start}) below minimum ({low}): {part!r}")
        if end > high:
            raise CronError(f"End of range ({end}) above maximum ({high}): {part!r}")
        if start > end:
            raise CronError(f"Beginning of range ({start}) beyond end of range ({end}): {part!r}")
        values.update(range(start, end + 1, step))
        any_value = any_value or star
    return frozenset(values), any_value


def _duration(text: str) -> timedelta:
    """A Go duration such as ``90s`` or ``1h30m`` (for ``@every``)."""
    rest = text.strip()
    seconds = 0.0
    position = 0
    if not rest:
        raise CronError("Empty duration")
    while position < len(rest):
        match = _DURATION_PART.match(rest, position)
        if match is None:
            raise CronError(f"Failed to parse duration: {text!r}")
        seconds += float(match[1]) * _DURATION_UNITS[match[2]]
        position = match.end()
    return timedelta(seconds=max(seconds, 1.0))


@lru_cache(maxsize=128)
def parse_cron(expression: str) -> CronSpec:
    """Parse ``expression`` the way Semaphore does (raises :class:`CronError`)."""
    spec = (expression or "").strip()
    tz: tzinfo | None = None
    if spec.startswith(("TZ=", "CRON_TZ=")):
        prefix, _, spec = spec.partition(" ")
        name = prefix.split("=", 1)[1]
        try:
            tz = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError) as err:
            raise CronError(f"Unknown time zone {name!r}") from err
        spec = spec.strip()
    if not spec:
        raise CronError("Empty spec string")
    if spec.startswith("@"):
        if spec.startswith("@every "):
            return CronSpec(every=_duration(spec[len("@every ") :]), tz=tz)
        if spec not in _DESCRIPTORS:
            raise CronError(f"Unrecognized descriptor: {spec!r}")
        spec = _DESCRIPTORS[spec]
    fields = spec.split()
    if len(fields) != 5:
        raise CronError(f"Expected exactly 5 fields, found {len(fields)}: {spec!r}")
    minutes, _ = _field(fields[0], 0, 59)
    hours, _ = _field(fields[1], 0, 23)
    days, days_any = _field(fields[2], 1, 31)
    months, _ = _field(fields[3], 1, 12, _MONTHS)
    weekdays, weekdays_any = _field(fields[4], 0, 6, _WEEKDAYS)
    return CronSpec(
        minutes=tuple(sorted(minutes)),
        hours=tuple(sorted(hours)),
        days=days,
        months=months,
        weekdays=weekdays,
        days_any=days_any,
        weekdays_any=weekdays_any,
        tz=tz,
    )


def validate_cron(expression: str) -> str | None:
    """Return the error text for an invalid expression, else ``None``."""
    try:
        parse_cron(expression)
    except CronError as err:
        return str(err)
    return None


def load_timezone(name: str | None) -> tzinfo:
    """Time zone by IANA name (``UTC`` if unknown or empty)."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return UTC


def _day_matches(spec: CronSpec, day: date) -> bool:
    if day.month not in spec.months:
        return False
    in_month = day.day in spec.days
    in_week = ((day.weekday() + 1) % 7) in spec.weekdays  # Python: Monday = 0, cron: Sunday = 0
    if spec.days_any or spec.weekdays_any:
        return in_month and in_week
    return in_month or in_week


def next_after(
    spec: CronSpec, after: datetime, default_tz: tzinfo = UTC
) -> datetime | None:
    """The first run strictly after ``after`` (UTC), ``None`` if there is none.

    ``@every`` gives ``None``: Semaphore starts that timer when it (re)loads the schedules, so
    the next run cannot be derived from the expression.
    """
    if spec.every is not None:
        return None
    tz = spec.tz or default_tz
    local = after.astimezone(tz)
    first_day = local.date()
    for offset in range(MAX_SEARCH_DAYS):
        day = first_day + timedelta(days=offset)
        if not _day_matches(spec, day):
            continue
        for hour in spec.hours:
            for minute in spec.minutes:
                candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
                if candidate > after:
                    return candidate.astimezone(UTC)
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def next_run_of(
    schedule: dict[str, Any], now: datetime, default_tz: tzinfo = UTC
) -> datetime | None:
    """Next run of a schedule as Semaphore's API returns it (``None`` if off or not predictable)."""
    if not schedule.get("active"):
        return None
    if schedule.get("type") == SCHEDULE_TYPE_RUN_AT:
        run_at = _parse_time(schedule.get("run_at"))
        return run_at if run_at is not None and run_at > now else None
    try:
        spec = parse_cron(schedule.get("cron_format") or "")
    except CronError:
        return None
    return next_after(spec, now, default_tz)
