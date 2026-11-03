"""A release that exists on GitHub but not yet as a Docker image is not offered as an update."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .test_flow_and_entities import project_eid, setup

DOCKER_VERSION = "2.19.17-f8cefe6-1792391878"
NEWER = {"tag_name": "v2.19.18", "html_url": "https://example.test/r"}


async def _update(hass: HomeAssistant, fake, make_entry, **setup_state):
    server, _ = fake
    server.version = setup_state.get("version", DOCKER_VERSION)
    server.latest_release = NEWER
    server.docker_tags = setup_state.get("tags")
    server.docker_status = setup_state.get("status")
    await setup(hass, make_entry)
    return hass.states.get(project_eid(hass, "update", "update"))


async def test_no_update_while_the_docker_image_is_missing(hass, fake, make_entry) -> None:
    update = await _update(hass, fake, make_entry, tags={"2.19.17"})
    assert update.state == "off"
    assert update.attributes["latest_version"] == "2.19.17"
    assert update.attributes["release_not_yet_in_docker"] == "2.19.18"


async def test_update_when_the_docker_image_exists(hass, fake, make_entry) -> None:
    update = await _update(hass, fake, make_entry, tags={"2.19.17", "2.19.18"})
    assert update.state == "on" and update.attributes["latest_version"] == "2.19.18"
    assert "release_not_yet_in_docker" not in update.attributes


async def test_update_is_shown_when_docker_hub_cannot_be_asked(hass, fake, make_entry) -> None:
    update = await _update(hass, fake, make_entry, status=429)
    assert update.state == "on" and update.attributes["latest_version"] == "2.19.18"


async def test_other_installations_are_not_checked_against_docker(hass, fake, make_entry) -> None:
    server, _ = fake
    update = await _update(hass, fake, make_entry, version="2.19.17", tags=set())
    assert update.state == "on" and update.attributes["latest_version"] == "2.19.18"
    assert not [r for r in server.requests if r[0] == "DOCKER"]


async def test_the_semaphore_token_never_goes_to_docker_hub(hass, fake, make_entry) -> None:
    server, _ = fake
    await _update(hass, fake, make_entry, tags=set())
    assert [r for r in server.requests if r[0] == "DOCKER"]
    assert all(r[2] is None for r in server.requests if r[0] == "DOCKER")
