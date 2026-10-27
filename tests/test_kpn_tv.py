"""Tests voor KPN TV."""

from __future__ import annotations

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kpn_tv.channels import (
    ChannelListError,
    parse_channels,
    resolve_channel,
)
from custom_components.kpn_tv.const import (
    CONF_BOOT_DELAY,
    CONF_CHANNELS,
    CONF_KEY_DELAY,
    CONF_REMOTE,
    CONF_SEND_ENTER,
    DOMAIN,
)

REMOTE = "remote.kpn_tv_box"
PLAYER = "media_player.kpn_tv"


# ---- zenderlijst ------------------------------------------------------


def test_parse_channels() -> None:
    text = "NPO 1 = 1\n\n# commentaar\nRTL 4=4\nDiscovery = 0501\n"
    assert parse_channels(text) == {"NPO 1": "1", "RTL 4": "4", "Discovery": "501"}


@pytest.mark.parametrize("bad", ["NPO 1", "= 1", "NPO = een", "A = 1\na = 2"])
def test_parse_channels_errors(bad: str) -> None:
    with pytest.raises(ChannelListError):
        parse_channels(bad)


def test_resolve_channel() -> None:
    ch = {"NPO 1": "1", "RTL 4": "4"}
    assert resolve_channel(ch, "rtl 4") == ("RTL 4", "4")
    assert resolve_channel(ch, "4") == ("RTL 4", "4")
    assert resolve_channel(ch, "501") == (None, "501")
    with pytest.raises(ValueError):
        resolve_channel(ch, "Netflix")


# ---- opzet ------------------------------------------------------------


def _register_remote(hass: HomeAssistant, state: str = "on") -> list[ServiceCall]:
    """Nep-remote: houdt aanroepen bij en gaat aan bij turn_on."""
    hass.states.async_set(REMOTE, state, {"current_activity": "com.kpn.tvlauncher"})
    calls: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(call)
        if call.service == "turn_on":
            hass.states.async_set(REMOTE, "on")
        elif call.service == "turn_off":
            hass.states.async_set(REMOTE, "off")

    for service in ("send_command", "turn_on", "turn_off"):
        hass.services.async_register("remote", service, handler)
    return calls


async def _setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="KPN TV",
        unique_id=REMOTE,
        data={"name": "KPN TV", CONF_REMOTE: REMOTE},
        options={
            CONF_CHANNELS: "NPO 1 = 1\nRTL 4 = 4\nDiscovery = 501\n",
            CONF_KEY_DELAY: 0.3,
            CONF_BOOT_DELAY: 0,
            CONF_SEND_ENTER: False,
            **options,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _keys(calls: list[ServiceCall]) -> list[list[str]]:
    return [c.data["command"] for c in calls if c.service == "send_command"]


# ---- config flow ------------------------------------------------------


async def test_config_flow(hass: HomeAssistant) -> None:
    _register_remote(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "KPN TV", CONF_REMOTE: REMOTE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_REMOTE] == REMOTE
    assert "NPO 1 = 1" in result["options"][CONF_CHANNELS]
    await hass.async_block_till_done()

    # Tweede keer dezelfde box: afgebroken.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "KPN TV", CONF_REMOTE: REMOTE}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_options_flow_validates(hass: HomeAssistant) -> None:
    _register_remote(hass)
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    base = {CONF_KEY_DELAY: 0.3, CONF_BOOT_DELAY: 8, CONF_SEND_ENTER: False}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CHANNELS: "NPO 1 zonder nummer", **base}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CHANNELS: "invalid_channels"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CHANNELS: "Veronica = 8", **base}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # Na herladen staat de nieuwe lijst in de bronnen.
    assert hass.states.get(PLAYER).attributes["source_list"] == ["Veronica"]


# ---- media player -----------------------------------------------------


async def test_state_follows_remote(hass: HomeAssistant) -> None:
    _register_remote(hass, "off")
    await _setup(hass)
    assert hass.states.get(PLAYER).state == "off"
    hass.states.async_set(REMOTE, "on")
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "on"
    hass.states.async_set(REMOTE, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "unavailable"


async def test_play_channel_by_name(hass: HomeAssistant) -> None:
    calls = _register_remote(hass)
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "play_channel", {"entity_id": PLAYER, "channel": "discovery"},
        blocking=True,
    )
    send = [c for c in calls if c.service == "send_command"][0]
    assert send.data["command"] == ["5", "0", "1"]
    assert send.data["delay_secs"] == 0.3
    state = hass.states.get(PLAYER)
    assert state.attributes["source"] == "Discovery"
    assert state.attributes["channel_number"] == "501"
    # Box stond al aan: geen turn_on.
    assert not [c for c in calls if c.service == "turn_on"]


async def test_select_source_and_play_media(hass: HomeAssistant) -> None:
    calls = _register_remote(hass)
    await _setup(hass, **{CONF_SEND_ENTER: True})
    await hass.services.async_call(
        "media_player", "select_source", {"entity_id": PLAYER, "source": "RTL 4"},
        blocking=True,
    )
    await hass.services.async_call(
        "media_player", "play_media",
        {"entity_id": PLAYER, "media_content_type": "channel", "media_content_id": "12"},
        blocking=True,
    )
    assert _keys(calls) == [["4", "ENTER"], ["1", "2", "ENTER"]]
    assert hass.states.get(PLAYER).attributes.get("source") is None
    assert hass.states.get(PLAYER).attributes["channel_number"] == "12"


async def test_play_channel_turns_box_on(hass: HomeAssistant) -> None:
    calls = _register_remote(hass, "off")
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "play_channel", {"entity_id": PLAYER, "channel": "NPO 1"},
        blocking=True,
    )
    assert [c.service for c in calls] == ["turn_on", "send_command"]
    # Eén cijfer: geen delay_secs nodig.
    assert calls[1].data["command"] == ["1"]
    assert "delay_secs" not in calls[1].data


async def test_unknown_channel(hass: HomeAssistant) -> None:
    calls = _register_remote(hass)
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "play_channel", {"entity_id": PLAYER, "channel": "Netflix"},
            blocking=True,
        )
    assert not calls


async def test_zapping_and_keys(hass: HomeAssistant) -> None:
    calls = _register_remote(hass)
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "play_channel", {"entity_id": PLAYER, "channel": "NPO 1"}, blocking=True
    )
    for service in ("media_next_track", "volume_up", "media_pause"):
        await hass.services.async_call(
            "media_player", service, {"entity_id": PLAYER}, blocking=True
        )
    assert _keys(calls) == [["1"], ["CHANNEL_UP"], ["VOLUME_UP"], ["MEDIA_PAUSE"]]
    # Na zappen is de zender onbekend.
    assert hass.states.get(PLAYER).attributes.get("source") is None

    await hass.services.async_call(
        "media_player", "turn_off", {"entity_id": PLAYER}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "off"
