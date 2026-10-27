"""Media player voor de KPN TV+ Box."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .channels import parse_channels, resolve_channel
from .const import (
    ATTR_CHANNEL,
    ATTR_CHANNEL_NUMBER,
    ATTR_CURRENT_APP,
    ATTR_DESCRIPTION,
    ATTR_KPN_CHANNEL_ID,
    ATTR_PLAYBACK_TYPE,
    ATTR_PROGRAM_END,
    ATTR_PROGRAM_START,
    CONF_ADB_ENTITY,
    CONF_BOOT_DELAY,
    CONF_CHANNELS,
    CONF_KEY_DELAY,
    CONF_POLL_INTERVAL,
    CONF_REMOTE,
    CONF_SEND_ENTER,
    DEFAULT_BOOT_DELAY,
    DEFAULT_CHANNELS,
    DEFAULT_KEY_DELAY,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SEND_ENTER,
    DOMAIN,
    MEDIA_TYPE_CHANNEL,
    POWER_ON_TIMEOUT,
    SERVICE_PLAY_CHANNEL,
)
from .nowplaying import KPN_APP, LOG_COMMAND, NowPlaying, NowPlayingTracker, parse_log

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
)

# Na zappen of zender kiezen even wachten tot de KPN-app gelogd heeft.
POLL_AFTER_ACTION = 3
ADB_TIMEOUT = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Maak de media player aan en registreer kpn_tv.play_channel."""
    async_add_entities([KpnTvMediaPlayer(entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PLAY_CHANNEL,
        {vol.Required(ATTR_CHANNEL): cv.string},
        "async_play_channel",
    )


def _ts(value: int | None) -> str | None:
    return dt_util.utc_from_timestamp(value).isoformat() if value else None


class KpnTvMediaPlayer(MediaPlayerEntity, RestoreEntity):
    """Een KPN TV+ Box, bediend via zijn Android TV Remote-entity.

    Optioneel leest hij via de Android Debug Bridge-integratie het log van de
    box uit om te tonen wat er speelt.
    """

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = SUPPORTED_FEATURES
    _attr_icon = "mdi:television-box"

    def __init__(self, entry: ConfigEntry) -> None:
        self._remote: str = entry.data[CONF_REMOTE]
        options = entry.options
        self._channels = parse_channels(options.get(CONF_CHANNELS, DEFAULT_CHANNELS))
        self._key_delay = float(options.get(CONF_KEY_DELAY, DEFAULT_KEY_DELAY))
        self._boot_delay = float(options.get(CONF_BOOT_DELAY, DEFAULT_BOOT_DELAY))
        self._send_enter = bool(options.get(CONF_SEND_ENTER, DEFAULT_SEND_ENTER))
        self._adb: str | None = options.get(CONF_ADB_ENTITY) or None
        self._poll_interval = float(options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))

        self._attr_name = entry.data.get(CONF_NAME, entry.title)
        self._attr_unique_id = f"{entry.entry_id}_media_player"
        self._attr_source_list = list(self._channels)
        self._channel_number: str | None = None
        self._lock = asyncio.Lock()

        self._tracker = NowPlayingTracker()
        self._now = NowPlaying()
        self._polling = False
        self._poll_errors = 0
        self._cancel_pending_poll: Any = None

    # ---- levenscyclus -------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_source = last.attributes.get("source")
            self._channel_number = last.attributes.get(ATTR_CHANNEL_NUMBER)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._remote], self._async_remote_changed
            )
        )
        if self._adb:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_poll, timedelta(seconds=self._poll_interval)
                )
            )
        self._update_from_remote()
        if self._adb:
            self._schedule_poll(1)

    @callback
    def _async_remote_changed(self, event: Event[EventStateChangedData]) -> None:
        self._update_from_remote()
        if not self._watching_kpn():
            self._clear_now_playing()
        elif self._adb:
            self._schedule_poll(POLL_AFTER_ACTION)
        self.async_write_ha_state()

    @callback
    def _update_from_remote(self) -> None:
        state = self.hass.states.get(self._remote)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._attr_available = False
            self._attr_state = None
            return
        self._attr_available = True
        if state.state != STATE_ON:
            self._attr_state = MediaPlayerState.OFF
        elif self._now.title or self._now.channel:
            self._attr_state = MediaPlayerState.PLAYING
        else:
            self._attr_state = MediaPlayerState.ON

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.hass.states.get(self._remote) if self.hass else None
        attrs: dict[str, Any] = {
            ATTR_CHANNEL_NUMBER: self._channel_number,
            ATTR_CURRENT_APP: state.attributes.get("current_activity") if state else None,
        }
        if self._adb:
            attrs.update(
                {
                    ATTR_DESCRIPTION: self._now.description,
                    ATTR_PROGRAM_START: _ts(self._now.start),
                    ATTR_PROGRAM_END: _ts(self._now.end),
                    ATTR_PLAYBACK_TYPE: self._now.playback_type,
                    ATTR_KPN_CHANNEL_ID: self._now.channel_id,
                }
            )
        return attrs

    # ---- wat speelt er (via ADB) ------------------------------------

    def _watching_kpn(self) -> bool:
        """Box aan en de KPN-app op de voorgrond (voor zover bekend)."""
        state = self.hass.states.get(self._remote)
        if state is None or state.state != STATE_ON:
            return False
        app = state.attributes.get("current_activity")
        return app in (None, KPN_APP)

    @callback
    def _schedule_poll(self, delay: float) -> None:
        if not self._adb:
            return
        if self._cancel_pending_poll:
            self._cancel_pending_poll()

        @callback
        def _fire(_now: datetime) -> None:
            self._cancel_pending_poll = None
            self.hass.async_create_task(self._async_poll())

        self._cancel_pending_poll = async_call_later(self.hass, delay, _fire)

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel_pending_poll:
            self._cancel_pending_poll()
            self._cancel_pending_poll = None

    async def _async_poll(self, _now: datetime | None = None) -> None:
        if self._polling or not self._adb:
            return
        if not self._watching_kpn():
            if self._now != NowPlaying():
                self._clear_now_playing()
                self.async_write_ha_state()
            return
        adb_state = self.hass.states.get(self._adb)
        if adb_state is None or adb_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._polling = True
        try:
            async with asyncio.timeout(ADB_TIMEOUT):
                await self.hass.services.async_call(
                    "androidtv",
                    "adb_command",
                    {ATTR_ENTITY_ID: self._adb, "command": LOG_COMMAND},
                    blocking=True,
                )
        except (TimeoutError, HomeAssistantError) as err:
            self._poll_errors += 1
            log = _LOGGER.warning if self._poll_errors == 3 else _LOGGER.debug
            log("Log van de box uitlezen via %s mislukt: %s", self._adb, err)
            return
        finally:
            self._polling = False
        self._poll_errors = 0

        state = self.hass.states.get(self._adb)
        output = state.attributes.get("adb_response") if state else None
        self._apply_now_playing(
            self._tracker.update(parse_log(output if isinstance(output, str) else None),
                                 time.time())
        )

    @callback
    def _clear_now_playing(self) -> None:
        self._tracker.reset()
        self._now = NowPlaying()
        self._attr_media_title = None
        self._attr_media_channel = None
        self._attr_media_content_type = None
        self._attr_media_duration = None
        self._attr_media_position = None
        self._attr_media_position_updated_at = None
        self._update_from_remote()

    @callback
    def _apply_now_playing(self, now: NowPlaying) -> None:
        before = (
            self._now.channel, self._now.title, self._now.start,
            self._now.description, self._now.playback_type,
        )
        after = (now.channel, now.title, now.start, now.description, now.playback_type)
        self._now = NowPlaying(**vars(now))
        if before == after:
            return

        if now.channel:
            match = next(
                ((n, num) for n, num in self._channels.items()
                 if n.casefold() == now.channel.casefold()),
                None,
            )
            if match:
                self._attr_source, self._channel_number = match
            elif now.channel != self._attr_source:
                self._attr_source = now.channel
                self._channel_number = None

        self._attr_media_title = now.title
        self._attr_media_channel = now.channel
        self._attr_media_content_type = MediaType.CHANNEL if now.channel else None
        if now.start and now.end and now.end > now.start:
            self._attr_media_duration = now.end - now.start
            if now.playback_type == "LIVE":
                # Live: de positie is "nu min begintijd"; HA loopt zelf door.
                updated = dt_util.utcnow()
                self._attr_media_position = max(
                    0, min(updated.timestamp() - now.start, now.end - now.start)
                )
                self._attr_media_position_updated_at = updated
            else:
                # Terugkijken: de echte positie is onbekend.
                self._attr_media_position = None
                self._attr_media_position_updated_at = None
        else:
            self._attr_media_duration = None
            self._attr_media_position = None
            self._attr_media_position_updated_at = None

        self._update_from_remote()
        self.async_write_ha_state()

    # ---- hulpfuncties -------------------------------------------------

    def _remote_is_on(self) -> bool:
        state = self.hass.states.get(self._remote)
        return state is not None and state.state == STATE_ON

    async def _remote_call(self, service: str, data: dict[str, Any] | None = None) -> None:
        await self.hass.services.async_call(
            "remote",
            service,
            {ATTR_ENTITY_ID: self._remote, **(data or {})},
            blocking=True,
        )

    async def _send_keys(self, keys: list[str], delay: float | None = None) -> None:
        data: dict[str, Any] = {"command": keys}
        if delay is not None and len(keys) > 1:
            data["delay_secs"] = delay
        await self._remote_call("send_command", data)

    async def _ensure_on(self) -> None:
        """Zet de box aan en wacht tot hij klaar is voor toetsen."""
        if self._remote_is_on():
            return
        await self._remote_call("turn_on")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + POWER_ON_TIMEOUT
        while not self._remote_is_on():
            if loop.time() > deadline:
                raise HomeAssistantError(
                    f"{self._remote} meldt na {POWER_ON_TIMEOUT} s nog steeds niet 'aan'"
                )
            await asyncio.sleep(0.5)
        if self._boot_delay:
            await asyncio.sleep(self._boot_delay)

    # ---- zenders ------------------------------------------------------

    async def async_play_channel(self, channel: str) -> None:
        """Kies een zender op naam (uit de zenderlijst) of op nummer."""
        try:
            name, number = resolve_channel(self._channels, channel)
        except ValueError as err:
            raise ServiceValidationError(
                f"Zender '{channel}' staat niet in de zenderlijst en is geen nummer",
                translation_domain=DOMAIN,
                translation_key="unknown_channel",
                translation_placeholders={"channel": str(channel)},
            ) from err

        async with self._lock:
            await self._ensure_on()
            keys = list(number)
            if self._send_enter:
                keys.append("ENTER")
            _LOGGER.debug("Zender %s (%s): toetsen %s", name, number, keys)
            await self._send_keys(keys, self._key_delay)

        self._attr_source = name
        self._channel_number = number
        self.async_write_ha_state()
        self._schedule_poll(POLL_AFTER_ACTION)

    async def async_select_source(self, source: str) -> None:
        await self.async_play_channel(source)

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        if media_type not in (MEDIA_TYPE_CHANNEL, "tv", "channel"):
            raise ServiceValidationError(
                f"Alleen media_content_type 'channel' wordt ondersteund, niet '{media_type}'",
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
                translation_placeholders={"media_type": str(media_type)},
            )
        await self.async_play_channel(media_id)

    async def _zap(self, key: str) -> None:
        await self._send_keys([key])
        # Zonder ADB weten we niet op welke zender de box nu uitkomt.
        if not self._adb:
            self._attr_source = None
            self._channel_number = None
            self.async_write_ha_state()
        self._schedule_poll(POLL_AFTER_ACTION)

    async def async_media_next_track(self) -> None:
        await self._zap("CHANNEL_UP")

    async def async_media_previous_track(self) -> None:
        await self._zap("CHANNEL_DOWN")

    # ---- overige bediening -------------------------------------------

    async def async_turn_on(self) -> None:
        await self._remote_call("turn_on")

    async def async_turn_off(self) -> None:
        await self._remote_call("turn_off")

    async def async_volume_up(self) -> None:
        await self._send_keys(["VOLUME_UP"])

    async def async_volume_down(self) -> None:
        await self._send_keys(["VOLUME_DOWN"])

    async def async_mute_volume(self, mute: bool) -> None:
        # De box kent alleen dempen-wisselen; de werkelijke stand is onbekend.
        await self._send_keys(["MUTE"])

    async def async_media_play(self) -> None:
        await self._send_keys(["MEDIA_PLAY"])

    async def async_media_pause(self) -> None:
        await self._send_keys(["MEDIA_PAUSE"])
