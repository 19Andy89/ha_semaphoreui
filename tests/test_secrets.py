"""Token and stored login are not kept as plain text in the config entry."""

from __future__ import annotations

from custom_components.semaphore_ui.const import CONF_API_TOKEN, CONF_RENEW_PASSWORD, CONF_RENEW_USER
from custom_components.semaphore_ui.secrets_store import PREFIX, seal, unseal
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .fake_semaphore import TOKEN
from .test_flow_and_entities import setup


async def test_a_plain_text_entry_is_encrypted_at_start(hass: HomeAssistant, fake, make_entry) -> None:
    entry = make_entry({CONF_RENEW_USER: "andy", CONF_RENEW_PASSWORD: "geheim"})
    entry.add_to_hass(hass)
    assert entry.data[CONF_API_TOKEN] == TOKEN  # as an older version stored it
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_API_TOKEN].startswith(PREFIX) and TOKEN not in entry.data[CONF_API_TOKEN]
    assert entry.options[CONF_RENEW_PASSWORD].startswith(PREFIX)
    assert "geheim" not in entry.options[CONF_RENEW_PASSWORD]
    assert entry.options[CONF_RENEW_USER] == "andy"
    assert unseal(hass, entry.data[CONF_API_TOKEN]) == TOKEN
    assert unseal(hass, entry.options[CONF_RENEW_PASSWORD]) == "geheim"


async def test_sealing_is_idempotent_and_reads_plain_text(hass: HomeAssistant, fake, make_entry) -> None:
    await setup(hass, make_entry)  # loads the key
    sealed = seal(hass, "abc")
    assert sealed.startswith(PREFIX) and seal(hass, sealed) == sealed
    assert unseal(hass, sealed) == "abc"
    assert unseal(hass, "klartext") == "klartext"  # entry from before the encryption
    assert unseal(hass, None) is None and unseal(hass, "") == ""
    assert seal(hass, "abc") != sealed  # fresh nonce every time


async def test_a_token_that_cannot_be_decrypted_asks_for_a_new_one(
    hass: HomeAssistant, fake, make_entry
) -> None:
    entry = await setup(hass, make_entry)
    assert entry.data[CONF_API_TOKEN].startswith(PREFIX)
    # the key file got lost: another key now
    from cryptography.fernet import Fernet

    hass.data["semaphore_ui_cipher"] = Fernet(Fernet.generate_key())
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler("semaphore_ui")
    assert any(flow["context"]["source"] == "reauth" for flow in flows)
