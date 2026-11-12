"""0.22.0: download the notification blueprint (update entity + button of the project device)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.update import SERVICE_INSTALL
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.semaphore_ui import blueprint
from custom_components.semaphore_ui.const import CONF_CHECK_UPDATES, DOMAIN

from .fake_semaphore import FakeSemaphore

TARGET = Path("blueprints/automation/19Andy89/semaphore_task_result.yaml")


async def start(hass: HomeAssistant, tmp_path: Path, make_entry, options: dict[str, Any] | None = None):
    hass.config.config_dir = str(tmp_path)  # never write into the shared test configuration
    entry = make_entry(options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity(hass: HomeAssistant, platform: str, entry, suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")
    assert entity_id, (platform, suffix)
    return entity_id


def github_requests(server: FakeSemaphore) -> list[tuple[str, str, str | None]]:
    return [r for r in server.requests if r[0] == "BLUEPRINT"]


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_stamp_roundtrip() -> None:
    text = "blueprint:\n  domain: automation\n"
    stamped = blueprint.stamp("v1.2.3", text)
    assert stamped.startswith("# ha_semaphoreui blueprint v1.2.3\n")
    assert blueprint.unstamp(stamped) == text
    assert blueprint.stamp("v2.0.0", stamped) == blueprint.stamp("v2.0.0", text)  # no double stamp


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("blueprint:\n  name: x\n  domain: automation\n", True),
        ("blueprint:\n  domain: script\n", False),
        ("<html>404</html>", False),
        ("", False),
        ("blueprint:\n  domain: automation\n" + "#" * 300_000, False),
    ],
)
def test_only_the_blueprint_is_accepted(text: str, ok: bool) -> None:
    assert blueprint.looks_like_the_blueprint(text) is ok


# --------------------------------------------------------------------------- #
# entities
# --------------------------------------------------------------------------- #
async def test_not_installed_shows_an_update(hass: HomeAssistant, fake, make_entry, tmp_path: Path) -> None:
    server, _ = fake
    entry = await start(hass, tmp_path, make_entry)
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "not installed"
    assert state.attributes["latest_version"] == "v9.0.0"
    assert state.attributes["release_url"] == "https://example.test/ha_release"
    assert not (tmp_path / TARGET).exists()  # nothing is written on its own
    assert all(auth is None for _k, _p, auth in github_requests(server))  # the Semaphore token never goes to GitHub


async def test_the_button_downloads_the_blueprint(hass: HomeAssistant, fake, make_entry, tmp_path: Path) -> None:
    server, _ = fake
    entry = await start(hass, tmp_path, make_entry)
    await hass.services.async_call(
        "button", SERVICE_PRESS, {ATTR_ENTITY_ID: entity(hass, "button", entry, "blueprint_download")}, blocking=True
    )
    await hass.async_block_till_done()
    written = (tmp_path / TARGET).read_text(encoding="utf-8")
    assert written.startswith("# ha_semaphoreui blueprint v9.0.0\n")
    assert blueprint.unstamp(written) == server.blueprint_text
    assert not (tmp_path / (str(TARGET) + ".bak")).exists()  # nothing to back up
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_OFF and state.attributes["installed_version"] == "v9.0.0"


async def test_an_old_different_file_is_kept_as_bak(hass: HomeAssistant, fake, make_entry, tmp_path: Path) -> None:
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    target.write_text("blueprint:\n  name: my own version\n  domain: automation\n", encoding="utf-8")
    entry = await start(hass, tmp_path, make_entry)
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_ON and state.attributes["installed_version"] == blueprint.UNKNOWN
    await hass.services.async_call(
        "update", SERVICE_INSTALL, {ATTR_ENTITY_ID: entity(hass, "update", entry, "blueprint_update")}, blocking=True
    )
    assert target.read_text(encoding="utf-8").startswith("# ha_semaphoreui blueprint v9.0.0\n")
    assert "my own version" in Path(str(target) + ".bak").read_text(encoding="utf-8")


async def test_a_file_imported_by_hand_with_the_same_content_is_current(
    hass: HomeAssistant, fake, make_entry, tmp_path: Path
) -> None:
    server, _ = fake
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    target.write_text(server.blueprint_text, encoding="utf-8")
    entry = await start(hass, tmp_path, make_entry)
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_OFF and state.attributes["installed_version"] == "v9.0.0"


async def test_a_new_release_shows_an_update(hass: HomeAssistant, fake, make_entry, tmp_path: Path) -> None:
    server, _ = fake
    entry = await start(hass, tmp_path, make_entry)
    button = entity(hass, "button", entry, "blueprint_download")
    await hass.services.async_call("button", SERVICE_PRESS, {ATTR_ENTITY_ID: button}, blocking=True)
    server.blueprint_release = {"tag_name": "v9.1.0", "html_url": "https://example.test/ha_release2"}
    await entry.runtime_data.blueprint_coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_ON
    assert (state.attributes["installed_version"], state.attributes["latest_version"]) == ("v9.0.0", "v9.1.0")


async def test_github_not_reachable_writes_nothing(hass: HomeAssistant, fake, make_entry, tmp_path: Path) -> None:
    server, _ = fake
    server.blueprint_release = None
    entry = await start(hass, tmp_path, make_entry)
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_OFF  # unknown latest version: no update is claimed
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", SERVICE_PRESS, {ATTR_ENTITY_ID: entity(hass, "button", entry, "blueprint_download")}, blocking=True
        )
    assert not (tmp_path / TARGET).exists()


async def test_a_wrong_download_is_refused(hass: HomeAssistant, fake, make_entry, tmp_path: Path) -> None:
    server, _ = fake
    server.blueprint_text = "<html>not the blueprint</html>"
    entry = await start(hass, tmp_path, make_entry)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", SERVICE_PRESS, {ATTR_ENTITY_ID: entity(hass, "button", entry, "blueprint_download")}, blocking=True
        )
    assert not (tmp_path / TARGET).exists()


async def test_with_the_check_off_nothing_is_requested_until_the_button(
    hass: HomeAssistant, fake, make_entry, tmp_path: Path
) -> None:
    server, _ = fake
    entry = await start(hass, tmp_path, make_entry, {CONF_CHECK_UPDATES: False})
    assert github_requests(server) == []
    await hass.services.async_call(
        "button", SERVICE_PRESS, {ATTR_ENTITY_ID: entity(hass, "button", entry, "blueprint_download")}, blocking=True
    )
    assert (tmp_path / TARGET).exists()


async def test_a_stable_version_ignores_dev_blueprints(hass: HomeAssistant, fake, make_entry, tmp_path: Path) -> None:
    server, _ = fake
    entry = await start(hass, tmp_path, make_entry)  # the installed test version is a stable one
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.attributes["latest_version"] == "v9.0.0"
    assert not any(path == "/bp/releases" for _k, path, _a in github_requests(server))


async def test_a_dev_version_also_offers_the_dev_blueprint(
    hass: HomeAssistant, fake, make_entry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, _ = fake

    async def dev(_hass: HomeAssistant) -> bool:
        return True

    monkeypatch.setattr(blueprint, "async_is_dev_version", dev)
    entry = await start(hass, tmp_path, make_entry)
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_ON and state.attributes["latest_version"] == "v9.1.0-dev.3"
    assert state.attributes["release_url"] == "https://example.test/ha_dev_release"
    await hass.services.async_call(
        "button", SERVICE_PRESS, {ATTR_ENTITY_ID: entity(hass, "button", entry, "blueprint_download")}, blocking=True
    )
    assert (tmp_path / TARGET).read_text(encoding="utf-8").startswith("# ha_semaphoreui blueprint v9.1.0-dev.3\n")
    state = hass.states.get(entity(hass, "update", entry, "blueprint_update"))
    assert state.state == STATE_OFF and state.attributes["installed_version"] == "v9.1.0-dev.3"


async def test_the_dev_check_recognises_dev_versions(hass: HomeAssistant) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    for version, expected in (("0.22.0-dev.2", True), ("0.22.0", False)):
        with patch.object(blueprint, "async_get_integration", AsyncMock(return_value=SimpleNamespace(version=version))):
            assert await blueprint.async_is_dev_version(hass) is expected
