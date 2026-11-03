"""Fixtures for the Semaphore UI tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.semaphore_ui import coordinator
from custom_components.semaphore_ui.const import (
    CONF_API_TOKEN,
    CONF_PROJECT_ID,
    CONF_PROJECT_NAME,
    DOMAIN,
)
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL

from .fake_semaphore import TOKEN, FakeSemaphore


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
