"""Repairs: problems the user has to fix show up under Settings -> Repairs.

* ``token_rejected`` - Semaphore answers 401: reported at once, fixable in the dialog
  (enter a new token, see ``repairs.py``).
* ``unreachable`` - Semaphore does not answer (or answers with an error) for
  ``REPAIR_AFTER`` seconds without a break.
* ``project_missing`` - the project is gone or this token may not see it (HTTP 403/404),
  for ``REPAIR_AFTER`` seconds without a break.

A successful poll removes all of them again. The start of a series of failures is kept
in ``hass.data`` (not in the coordinator): while Home Assistant retries the setup, a
new coordinator is created every time and would never reach the limit otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PROJECT_NAME,
    DOMAIN,
    ISSUE_KINDS,
    ISSUE_PROJECT,
    ISSUE_TOKEN,
    ISSUE_UNREACHABLE,
    REPAIR_AFTER,
)

_KEY = f"{DOMAIN}_problems"


@dataclass
class _Series:
    """The current series of failed polls of one entry."""

    kind: str
    since: datetime
    shown_detail: str | None = None


def issue_id(kind: str, entry_id: str) -> str:
    """Id of the issue of one entry (one entry = one project)."""
    return f"{kind}_{entry_id}"


def _series(hass: HomeAssistant) -> dict[str, _Series]:
    return hass.data.setdefault(_KEY, {})


def _create(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: str,
    *,
    fixable: bool,
    severity: ir.IssueSeverity,
    **placeholders: str,
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(kind, entry.entry_id),
        is_fixable=fixable,
        is_persistent=False,
        severity=severity,
        translation_key=kind,
        translation_placeholders={
            "project": entry.data.get(CONF_PROJECT_NAME, ""),
            "url": entry.data.get(CONF_URL, ""),
            **placeholders,
        },
        data={"entry_id": entry.entry_id},
    )


def report_token_rejected(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The token was rejected: reported at once (the server is reachable)."""
    _series(hass).pop(entry.entry_id, None)
    for kind in (ISSUE_UNREACHABLE, ISSUE_PROJECT):
        ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry.entry_id))
    _create(
        hass, entry, ISSUE_TOKEN, fixable=True, severity=ir.IssueSeverity.ERROR
    )


def report_failure(
    hass: HomeAssistant, entry: ConfigEntry, kind: str, detail: str
) -> None:
    """A poll failed (``kind``: unreachable or project_missing).

    Nothing is reported before the failures have lasted ``REPAIR_AFTER`` seconds;
    one hiccup or a restart of Semaphore is not a repair.
    """
    series = _series(hass)
    now = dt_util.utcnow()
    current = series.get(entry.entry_id)
    if current is None or current.kind != kind:
        if current is not None:  # the other kind of problem is outdated now
            ir.async_delete_issue(hass, DOMAIN, issue_id(current.kind, entry.entry_id))
        current = series[entry.entry_id] = _Series(kind, now)
    if (now - current.since).total_seconds() < REPAIR_AFTER:
        return
    if current.shown_detail == detail:
        return
    current.shown_detail = detail
    local = dt_util.as_local(current.since)
    _create(
        hass,
        entry,
        kind,
        fixable=False,
        severity=(
            ir.IssueSeverity.WARNING if kind == ISSUE_UNREACHABLE else ir.IssueSeverity.ERROR
        ),
        detail=detail,
        since=local.strftime("%d.%m. %H:%M"),
    )


def report_ok(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A poll worked: the problems are gone."""
    _series(hass).pop(entry.entry_id, None)
    for kind in ISSUE_KINDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry.entry_id))


def clear(hass: HomeAssistant, entry_id: str) -> None:
    """The entry was removed: remove its issues too."""
    _series(hass).pop(entry_id, None)
    for kind in ISSUE_KINDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry_id))
