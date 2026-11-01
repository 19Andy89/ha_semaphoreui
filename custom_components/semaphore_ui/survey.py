"""Survey variables of a Semaphore template (pure functions, no Home Assistant imports).

Semaphore templates can define "survey variables" that are asked for when a task
starts. The web UI sends the values in the body of ``POST /project/{id}/tasks``:

* ``environment`` - JSON *string* with all values except secrets
* ``secret``      - JSON *string* with the values of ``secret`` variables

Types: ``""`` (string), ``text`` (multi line), ``int``, ``enum`` (one of the
listed values), ``select`` (one or more of the listed values, sent as list) and
``secret``. The server does not validate required variables or apply defaults
for API calls, so this module does both, like the web UI.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

TYPE_STRING = ""
TYPE_TEXT = "text"
TYPE_INT = "int"
TYPE_ENUM = "enum"
TYPE_SELECT = "select"
TYPE_SECRET = "secret"

INT_RE = re.compile(r"-?\d+")


class SurveyError(Exception):
    """The given values do not fit the survey of the template."""

    def __init__(
        self,
        missing: list[str],
        invalid: dict[str, str],
        unknown: list[str],
        known: list[str],
        secrets: list[str],
    ) -> None:
        self.missing = missing
        self.invalid = invalid
        self.unknown = unknown
        parts: list[str] = []
        if missing:
            shown = [f"{n} (secret: only via the action)" if n in secrets else n for n in missing]
            parts.append("missing: " + ", ".join(shown))
        if invalid:
            parts.append("invalid: " + "; ".join(f"{n} ({why})" for n, why in invalid.items()))
        if unknown:
            parts.append(
                "unknown: " + ", ".join(unknown) + f" (known: {', '.join(known) or 'none'})"
            )
        super().__init__("; ".join(parts))


@dataclass(frozen=True)
class SurveyVar:
    """One survey variable."""

    name: str
    title: str
    type: str
    required: bool
    description: str
    values: tuple[tuple[str, Any], ...]  # (label, value)
    default: tuple[str, ...]  # empty = no default

    @property
    def is_secret(self) -> bool:
        return self.type == TYPE_SECRET

    @property
    def is_multi(self) -> bool:
        return self.type == TYPE_SELECT

    @property
    def labels(self) -> list[str]:
        """Labels of the allowed values (enum/select)."""
        return [label for label, _ in self.values]

    def resolve(self, raw: Any) -> Any | None:
        """Allowed value for ``raw`` (given as value or as label), else ``None``."""
        text = str(raw)
        for _, value in self.values:
            if str(value) == text:
                return value
        for label, value in self.values:
            if label == text:
                return value
        return None

    def label_of(self, value: Any) -> str | None:
        """Label for a value."""
        for label, val in self.values:
            if str(val) == str(value):
                return label
        return None


def parse_survey_vars(template: dict[str, Any]) -> list[SurveyVar]:
    """Survey variables of a template dict from the API."""
    result: list[SurveyVar] = []
    for item in template.get("survey_vars") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        values = tuple(
            (str(v.get("name", v.get("value", ""))), v.get("value", v.get("name")))
            for v in item.get("values") or []
            if isinstance(v, dict)
        )
        default = item.get("default_value")
        if isinstance(default, (list, tuple)):
            defaults = tuple(str(d) for d in default if d not in (None, ""))
        elif default in (None, ""):
            defaults = ()
        else:
            defaults = (str(default),)
        result.append(
            SurveyVar(
                name=str(item["name"]),
                title=str(item.get("title") or item["name"]),
                type=str(item.get("type") or TYPE_STRING),
                required=bool(item.get("required")),
                description=str(item.get("description") or ""),
                values=values,
                default=defaults,
            )
        )
    return result


def _coerce(var: SurveyVar, raw: Any) -> Any:
    """Convert ``raw`` to what the web UI would send. Raises ``ValueError``."""
    if var.type == TYPE_SELECT:
        if isinstance(raw, (list, tuple)):
            items = list(raw)
        else:
            items = [s.strip() for s in str(raw).split(",") if s.strip()]
        out = []
        for item in items:
            value = var.resolve(item)
            if value is None:
                raise ValueError(f"'{item}' is not one of {var.labels}")
            out.append(value)
        return out
    if var.type == TYPE_ENUM:
        value = var.resolve(raw)
        if value is None:
            raise ValueError(f"'{raw}' is not one of {var.labels}")
        return value
    if var.type == TYPE_INT:
        if isinstance(raw, bool):
            raise ValueError("not a whole number")
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        text = str(raw).strip()
        if not INT_RE.fullmatch(text):
            raise ValueError(f"'{raw}' is not a whole number")
        return text  # the web UI sends numbers as strings, too
    return str(raw)


def build_survey_payload(
    variables: list[SurveyVar], given: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(environment, secret)`` for the task body.

    Missing values are filled from the defaults; required variables without a
    value, invalid values and unknown names raise :class:`SurveyError`.
    """
    given = dict(given or {})
    names = [v.name for v in variables]
    unknown = [name for name in given if name not in names]
    environment: dict[str, Any] = {}
    secret: dict[str, Any] = {}
    missing: list[str] = []
    invalid: dict[str, str] = {}

    for var in variables:
        raw = given.get(var.name)
        if raw is None or raw == "" or raw == []:
            if var.default:
                raw = list(var.default) if var.is_multi else var.default[0]
            else:
                if var.required:
                    missing.append(var.name)
                continue
        try:
            value = _coerce(var, raw)
        except ValueError as err:
            invalid[var.name] = str(err)
            continue
        (secret if var.is_secret else environment)[var.name] = value

    if missing or invalid or unknown:
        raise SurveyError(
            missing, invalid, unknown, names, [v.name for v in variables if v.is_secret]
        )
    return environment, secret
