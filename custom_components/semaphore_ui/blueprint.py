"""Keep the notification blueprint up to date.

Home Assistant never installs blueprints on its own and HACS has no blueprint category. So the
integration downloads ``semaphore_task_result.yaml`` from the GitHub release on request (update
entity + button of the project device) and puts it where the import dialog would put it
(``/config/blueprints/automation/19Andy89/``); automations that use it keep working.

* The file is written exactly as it is in the release (byte for byte), so that tools which compare
  it with the ``source_url`` (Spook's blueprint updates, Home Assistant's own check) see no difference.
  Which release was installed is remembered separately (``.storage``), together with a hash of the file.
  A file counts as the latest version whenever its content equals the one in the latest release
  (e.g. between two dev builds that did not touch the blueprint). A file that is neither the latest
  nor the one we installed counts as "unknown".
* An existing different file is saved as ``<name>.yaml.bak`` first.
* Stable version installed: only the latest stable release counts. Dev pre-release installed
  (``x.y.z-dev.N``): the newest release including pre-releases counts, so its blueprint is offered too.
* Only fixed GitHub URLs are used; the Semaphore token is never sent there.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
import os
from pathlib import Path
import hashlib
import re

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.loader import async_get_integration

from .api import REQUEST_TIMEOUT
from .const import (
    BLUEPRINT_FILE,
    BLUEPRINT_RAW_URL,
    BLUEPRINT_RELEASE_URL,
    BLUEPRINT_RELEASES_URL,
    BLUEPRINT_SCAN_INTERVAL,
    BLUEPRINT_SOURCE,
    BLUEPRINT_SUBDIR,
    CONF_CHECK_UPDATES,
    DOMAIN,
)
from .coordinator import SemaphoreConfigEntry

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_blueprint"
# Versions 0.22.0-dev.1 to dev.7 wrote this line at the top of the file; it is removed on the next install
STAMP_RE = re.compile(r"\A# ha_semaphoreui blueprint (?P<tag>v?[0-9A-Za-z.\-+]+)\r?\n")
MAX_BYTES = 200_000
NOT_INSTALLED = "not installed"
UNKNOWN = "unknown (own or older file)"


class BlueprintError(HomeAssistantError):
    """The blueprint could not be downloaded or written."""


@dataclass(frozen=True)
class BlueprintData:
    """What is known about the blueprint right now."""

    installed: str  # version, NOT_INSTALLED or UNKNOWN
    latest: str | None  # release tag, ``None`` if unknown (check off / GitHub not reachable)
    release_url: str | None
    path: str


def blueprint_path(hass: HomeAssistant) -> Path:
    """Where the blueprint lives in the configuration directory."""
    return Path(hass.config.path("blueprints", "automation", BLUEPRINT_SUBDIR, BLUEPRINT_FILE))


def unstamp(text: str) -> str:
    """The text without the stamp line that early dev versions of this integration added."""
    return STAMP_RE.sub("", text, count=1)


def sha256(text: str) -> str:
    """Hash of a file's text (what we remember about the file we wrote)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def looks_like_the_blueprint(text: str) -> bool:
    """Cheap safety check before a file is written (a real YAML parse happens in Home Assistant)."""
    return (
        0 < len(text) <= MAX_BYTES
        and re.search(r"^blueprint:\s*$", text, re.M) is not None
        and re.search(r"^\s+domain:\s*automation\s*$", text, re.M) is not None
    )


def installed_version(
    path: Path,
    latest_text: str | None,
    latest_tag: str | None,
    remembered: dict[str, str] | None = None,
) -> str:
    """Version of the installed file (blocking: reads the file)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return NOT_INSTALLED
    except (OSError, UnicodeDecodeError):
        return UNKNOWN
    if latest_text is not None and latest_tag and unstamp(text) == unstamp(latest_text):
        return latest_tag  # same content as the latest release: nothing to update
    if remembered and remembered.get("sha256") == sha256(text) and remembered.get("tag"):
        return remembered["tag"]  # the file we wrote, untouched
    if match := STAMP_RE.match(text):
        return match["tag"]  # written by an early dev version
    return UNKNOWN


def write_blueprint(path: Path, content: str) -> bool:
    """Write the file (blocking). A different old file is kept as ``.bak``. ``True``: backup made."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = False
    if path.exists():
        try:
            if unstamp(path.read_text(encoding="utf-8")) != content:
                backup = True
                path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
        except OSError as err:
            raise BlueprintError(f"Backup of {path.name} failed: {err}") from err
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as err:
        raise BlueprintError(f"Could not write {path}: {err}") from err
    finally:
        tmp.unlink(missing_ok=True)
    return backup


async def async_is_dev_version(hass: HomeAssistant) -> bool:
    """``True`` if a dev pre-release of the integration (``x.y.z-dev.N``) is installed."""
    integration = await async_get_integration(hass, DOMAIN)
    return "-dev" in str(integration.version)


async def async_fetch_latest(
    session: aiohttp.ClientSession, *, with_text: bool, include_dev: bool = False
) -> tuple[str, str | None, str | None] | None:
    """``(tag, release_url, text)`` of the latest release (``None``: not reachable / nothing found).

    ``include_dev``: the newest release counts even if it is a pre-release (for people on a dev version).
    """
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT * 2):
            async with session.get(
                BLUEPRINT_RELEASES_URL if include_dev else BLUEPRINT_RELEASE_URL,
                headers={"Accept": "application/vnd.github+json"},
            ) as resp:
                if resp.status != 200:
                    return None
                release = await resp.json(content_type=None)
            if include_dev:  # the list: newest first
                release = release[0] if isinstance(release, list) and release else None
            tag = str(release.get("tag_name") or "") if isinstance(release, dict) else ""
            if not re.fullmatch(r"v?[0-9A-Za-z.\-+]+", tag):
                return None
            text: str | None = None
            if with_text:
                async with session.get(
                    BLUEPRINT_RAW_URL.format(tag=tag, path=BLUEPRINT_SOURCE)
                ) as resp:
                    if resp.status != 200:
                        return None
                    raw = await resp.read()
                if len(raw) > MAX_BYTES:
                    return None
                text = raw.decode("utf-8")
    except (TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug("Could not look up the blueprint release: %s", err)
        return None
    return tag, release.get("html_url"), text


class SemaphoreBlueprintCoordinator(DataUpdateCoordinator[BlueprintData]):
    """Compares the installed blueprint with the latest release (rarely, one request pair)."""

    config_entry: SemaphoreConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SemaphoreConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} blueprint {entry.title}",
            update_interval=timedelta(seconds=BLUEPRINT_SCAN_INTERVAL),
        )
        self.check_updates: bool = entry.options.get(CONF_CHECK_UPDATES, True)
        self._store: Store[dict[str, str]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def _async_update_data(self) -> BlueprintData:
        latest = None
        if self.check_updates:
            latest = await async_fetch_latest(
                async_get_clientsession(self.hass),
                with_text=True,
                include_dev=await async_is_dev_version(self.hass),
            )
        path = blueprint_path(self.hass)
        tag, url, text = latest if latest else (None, None, None)
        remembered = await self._store.async_load()
        installed = await self.hass.async_add_executor_job(installed_version, path, text, tag, remembered)
        return BlueprintData(installed, tag, url, str(path))

    async def async_install(self) -> str:
        """Download the latest release and write it. Returns the version. Raises :class:`BlueprintError`."""
        fetched = await async_fetch_latest(
            async_get_clientsession(self.hass),
            with_text=True,
            include_dev=await async_is_dev_version(self.hass),
        )
        if fetched is None or fetched[2] is None:
            raise BlueprintError("The blueprint could not be downloaded from GitHub")
        tag, _url, text = fetched
        if not looks_like_the_blueprint(text):
            raise BlueprintError("The downloaded file is not the expected blueprint; nothing was written")
        path = blueprint_path(self.hass)
        content = unstamp(text)
        backup = await self.hass.async_add_executor_job(write_blueprint, path, content)
        await self._store.async_save({"tag": tag, "sha256": sha256(content)})
        _LOGGER.info(
            "Blueprint %s %s written to %s%s",
            BLUEPRINT_FILE,
            tag,
            path,
            " (old file kept as .bak)" if backup else "",
        )
        # automations that use the blueprint read the new file
        if self.hass.services.has_service("automation", "reload"):
            await self.hass.services.async_call("automation", "reload", blocking=False)
        await self.async_refresh()
        return tag
