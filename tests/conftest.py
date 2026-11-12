"""Fixtures for the Semaphore UI tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.semaphore_ui import blueprint, coordinator
from custom_components.semaphore_ui.const import (
    CONF_API_TOKEN,
    CONF_PROJECT_ID,
    CONF_PROJECT_NAME,
    DOMAIN,
)
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL

from .fake_semaphore import TOKEN, FakeSemaphore


def _require_supported_home_assistant() -> None:
    """Stop with a clear message if the installed Home Assistant is older than hacs.json demands.

    Otherwise a too old test environment shows up as dozens of confusing failures.
    """
    import json
    from pathlib import Path

    from homeassistant.const import __version__ as installed

    wanted = json.loads((Path(__file__).parents[1] / "hacs.json").read_text())["homeassistant"]

    def parts(version: str) -> tuple[int, ...]:
        return tuple(int(p) for p in version.split("b")[0].split(".")[:3] if p.isdigit())

    if parts(installed) < parts(wanted):
        pytest.exit(
            f"Home Assistant {installed} is installed, but this integration needs {wanted} or newer "
            "(hacs.json). Install the current test requirements: pip install -r requirements_test.txt",
            returncode=4,
        )


_require_supported_home_assistant()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load custom_components/semaphore_ui in every test."""


@pytest.fixture
async def fake(socket_enabled, monkeypatch) -> AsyncGenerator[tuple[FakeSemaphore, str]]:
    """A running fake Semaphore server: (state, base_url)."""
    server = FakeSemaphore()
    url = await server.start_server()
    monkeypatch.setattr(coordinator, "GITHUB_LATEST_URL", f"{url}/github/latest")
    monkeypatch.setattr(coordinator, "DOCKER_TAG_URL", f"{url}/docker/tags/{{tag}}")
    monkeypatch.setattr(blueprint, "BLUEPRINT_RELEASE_URL", f"{url}/bp/release")
    # independent of the manifest version (the dev workflow stamps "-dev.N" into it before the tests run)
    async def _stable(_hass: Any) -> bool:
        return False

    monkeypatch.setattr(blueprint, "async_is_dev_version", _stable)
    monkeypatch.setattr(blueprint, "BLUEPRINT_RELEASES_URL", f"{url}/bp/releases")
    monkeypatch.setattr(blueprint, "BLUEPRINT_RAW_URL", f"{url}/bp/raw/{{tag}}/{{path}}")
    yield server, url
    await server.close()


@pytest.fixture
def entry_data() -> dict[str, Any]:
    """Config entry data factory input."""
    return {
        CONF_API_TOKEN: TOKEN,
        CONF_PROJECT_ID: 1,
        CONF_PROJECT_NAME: "Homelab",
        CONF_VERIFY_SSL: True,
    }


@pytest.fixture
def make_entry(fake, entry_data):
    """Return a MockConfigEntry that points to the fake server."""
    _, url = fake

    def _make(options: dict[str, Any] | None = None) -> MockConfigEntry:
        return MockConfigEntry(
            domain=DOMAIN,
            title="Semaphore – Homelab",
            unique_id=f"{url}#1",
            data={**entry_data, CONF_URL: url},
            options=options or {},
        )

    return _make
