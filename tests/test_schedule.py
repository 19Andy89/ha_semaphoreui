"""Cron the way Semaphore reads it (robfig/cron ParseStandard) and the time of the next run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.semaphore_ui.schedule import (
    CronError,
    load_timezone,
    next_after,
    next_run_of,
    parse_cron,
    validate_cron,
)

BERLIN = ZoneInfo("Europe/Berlin")
# Thursday evening
NOW = datetime(2026, 10, 29, 22, 10, tzinfo=UTC)


def at(text: str, tz=UTC) -> datetime:
    """``2026-10-30 02:00`` in the given zone, as UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=tz).astimezone(UTC)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0 2 * * *", at("2026-10-30 02:00")),
        # the typo that really happened: every minute between 02:00 and 02:59
        ("* 2 * * *", at("2026-10-30 02:00")),
        ("*/15 * * * *", at("2026-10-29 22:15")),
        ("5 * * * *", at("2026-10-29 23:05")),
        ("10-50/20 * * * *", at("2026-10-29 22:30")),
        ("5/20 * * * *", at("2026-10-29 22:25")),  # "5/20" = "5-59/20"
        ("0 6 * * MON-FRI", at("2026-10-30 06:00")),
        ("0 6 * * 1,3", at("2026-11-02 06:00")),
        ("0 6 * jan,nov *", at("2026-11-01 06:00")),
        ("30 3 1,15 * *", at("2026-11-01 03:30")),
        ("0 0 29 2 *", at("2028-02-29 00:00")),
        ("@hourly", at("2026-10-29 23:00")),
        ("@daily", at("2026-10-30 00:00")),
        ("@midnight", at("2026-10-30 00:00")),
        ("@weekly", at("2026-11-01 00:00")),  # Sunday
        ("@monthly", at("2026-11-01 00:00")),
        ("@yearly", at("2027-01-01 00:00")),
        ("  0   2  *  *  *  ", at("2026-10-30 02:00")),
        ("0 2 ? * *", at("2026-10-30 02:00")),
    ],
)
def test_next_run_in_utc(expression: str, expected: datetime) -> None:
    assert next_after(parse_cron(expression), NOW) == expected


def test_the_next_run_is_always_after_now() -> None:
    """At 02:00:00 exactly the run of 02:00 is "now", the next one is the day after."""
    spec = parse_cron("0 2 * * *")
    assert next_after(spec, at("2026-10-30 02:00")) == at("2026-10-31 02:00")
    assert next_after(spec, at("2026-10-30 01:59") + timedelta(seconds=59)) == at("2026-10-30 02:00")


def test_day_of_month_or_day_of_week_when_both_are_restricted() -> None:
    """Classic cron: "the 1st OR a Monday" - but "*/2" in one field does not make it an OR."""
    both = parse_cron("0 0 1 * 1")
    assert next_after(both, at("2026-10-29 12:00")) == at("2026-11-01 00:00")  # the 1st (a Sunday)
    assert next_after(both, at("2026-11-01 12:00")) == at("2026-11-02 00:00")  # then Monday
    # a "*" in one of the fields: both fields have to match ("every day" AND Monday = Mondays)
    star = parse_cron("0 0 * * 1")
    assert next_after(star, at("2026-10-29 12:00")) == at("2026-11-02 00:00")
    stepped = parse_cron("0 0 */2 * 1")  # step > 1: not "any" -> OR rule
    assert next_after(stepped, at("2026-10-29 12:00")) == at("2026-10-31 00:00")  # odd day 31


def test_time_zone_of_semaphore_and_of_the_expression() -> None:
    spec = parse_cron("0 2 * * *")
    # after the clocks went back (Oct 25) Berlin is UTC+1, in summer UTC+2
    assert next_after(spec, NOW, BERLIN) == at("2026-10-30 02:00", BERLIN) == at("2026-10-30 01:00")
    assert next_after(spec, at("2026-07-01 12:00"), BERLIN) == at("2026-07-02 02:00", BERLIN) == at("2026-07-02 00:00")
    # "TZ=" in the expression wins over the zone of the server
    prefixed = parse_cron("TZ=Europe/Berlin 0 2 * * *")
    assert next_after(prefixed, NOW, UTC) == at("2026-10-30 01:00")
    assert next_after(parse_cron("CRON_TZ=America/New_York 0 2 * * *"), NOW, BERLIN) == at("2026-10-30 02:00", ZoneInfo("America/New_York"))


def test_a_time_that_does_not_exist_runs_at_the_shifted_time() -> None:
    """02:30 is skipped when the clocks go forward (2026-03-29 in Berlin)."""
    spec = parse_cron("30 2 * * *")
    result = next_after(spec, at("2026-03-28 12:00", BERLIN), BERLIN)
    assert result == at("2026-03-29 01:30")  # = 03:30 CEST, the same instant Go computes


def test_every_cannot_be_predicted() -> None:
    spec = parse_cron("@every 1h30m")
    assert spec.every == timedelta(hours=1, minutes=30)
    assert next_after(spec, NOW) is None
    assert parse_cron("@every 90s").every == timedelta(seconds=90)


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "0 24 * * *",
        "0 0 0 * *",
        "0 0 32 * *",
        "0 0 * 13 *",
        "0 0 * * 7",  # Sunday is 0 only
        "*/0 * * * *",
        "5-1 * * * *",
        "a b c d e",
        "@sometimes",
        "@every soon",
        "TZ=Nowhere/Land 0 2 * * *",
        "1-2-3 * * * *",
        "1/2/3 * * * *",
        "*-5 * * * *",
    ],
)
def test_invalid_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(CronError):
        parse_cron(expression)
    assert validate_cron(expression)


def test_valid_expression_has_no_error() -> None:
    assert validate_cron("0 2 * * *") is None
    assert validate_cron("TZ=Europe/Berlin @daily") is None


def test_next_run_of_a_schedule_from_the_api() -> None:
    cron = {"active": True, "type": "", "cron_format": "0 2 * * *"}
    assert next_run_of(cron, NOW) == at("2026-10-30 02:00")
    assert next_run_of({**cron, "active": False}, NOW) is None
    assert next_run_of({**cron, "cron_format": "* 2 *"}, NOW) is None  # invalid: no crash
    assert next_run_of({**cron, "cron_format": "@every 5m"}, NOW) is None
    assert next_run_of({**cron, "type": None}, NOW) == at("2026-10-30 02:00")

    once = {"active": True, "type": "run_at", "run_at": "2026-11-05T08:30:00Z", "cron_format": ""}
    assert next_run_of(once, NOW) == at("2026-11-05 08:30")
    assert next_run_of({**once, "run_at": "2026-10-01T08:30:00Z"}, NOW) is None  # in the past
    assert next_run_of({**once, "run_at": None}, NOW) is None
    assert next_run_of({**once, "run_at": "tomorrow"}, NOW) is None
    assert next_run_of({**once, "run_at": "2026-11-05T09:30:00+01:00"}, NOW) == at("2026-11-05 08:30")


def test_time_zone_names() -> None:
    assert load_timezone("Europe/Berlin") == BERLIN
    assert load_timezone(None) == UTC
    assert load_timezone("") == UTC
    assert load_timezone("Nowhere/Land") == UTC
