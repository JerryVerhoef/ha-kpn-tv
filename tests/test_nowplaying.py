"""Tests voor 'wat speelt er', met echte uitvoer van een KPN TV+ Box."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from homeassistant.util import dt as dt_util

from custom_components.kpn_tv.const import (
    CONF_ADB_ENTITY,
    CONF_BOOT_DELAY,
    CONF_CHANNELS,
    CONF_KEY_DELAY,
    CONF_POLL_INTERVAL,
    CONF_REMOTE,
    CONF_SEND_ENTER,
    DOMAIN,
)
from custom_components.kpn_tv.nowplaying import (
    LOG_COMMAND,
    NowPlayingTracker,
    parse_log,
)

# Echte uitvoer van LOG_COMMAND op een KPN TV+ Box.
REAL_OUTPUT = """setupUnicastSession: playbackType=LIVE | channel=Channel{title='NPO 1', id='18} | program=null | vod=null | recording=null
setupUnicastSession: serviceName  = LIVE | contentDescription = unknown
setupUnicastSession: playbackType=LIVE | channel=Channel{title='NPO 2', id='19} | program=AVSProgram{_title='Podium Klassiek special: Tania Kross'} | vod=null | recording=null
setupUnicastSession: serviceName  = LIVE | contentDescription =
updateProgress: eventTitle= Podium Klassiek special: Tania Kross startTime= 1793129100000 endTime= 1793131800000
setupUnicastSession: playbackType=SOTV | channel=Channel{title='NPO 2', id='19} | program=AVSProgram{_title='Podium Klassiek special: Tania Kross'} | vod=null | recording=null
setupUnicastSession: serviceName  = SOTV | contentDescription = Een muzikaal feest met en voor Tania Kross.
updateProgress: eventTitle= Podium Klassiek special: Tania Kross startTime= 1793129100000 endTime= 1793131800000"""

START, END = 1793129100, 1793131800
DURING = START + 600

REMOTE = "remote.kpn"
ADB = "media_player.android_tv_kpn"
PLAYER = "media_player.kpn_tv"


# ---- parser -----------------------------------------------------------


def test_command_strips_url() -> None:
    assert "uri=" in LOG_COMMAND  # wordt er op de box af geknipt
    assert "logcat -d -t" in LOG_COMMAND


def test_parse_real_output() -> None:
    info = parse_log(REAL_OUTPUT)
    assert info.channel == "NPO 2"
    assert info.channel_id == "19"
    assert info.playback_type == "SOTV"
    assert info.session_program == "Podium Klassiek special: Tania Kross"
    assert info.description == "Een muzikaal feest met en voor Tania Kross."
    assert info.title == "Podium Klassiek special: Tania Kross"
    assert (info.start, info.end) == (START, END)


def test_parse_empty_and_unknown() -> None:
    assert parse_log(None).channel is None
    assert parse_log("").title is None
    info = parse_log(REAL_OUTPUT.split("\n", 2)[0] + "\n" + REAL_OUTPUT.split("\n")[1])
    assert info.channel == "NPO 1"
    assert info.session_program is None
    assert info.description is None  # "unknown"


def test_progress_before_zap_is_ignored() -> None:
    out = (
        "updateProgress: eventTitle= Oud programma startTime= 1000000 endTime= 2000000\n"
        "setupUnicastSession: playbackType=LIVE | channel=Channel{title='RTL 4', id='5} "
        "| program=AVSProgram{_title='Nieuws'} | vod=null | recording=null"
    )
    info = parse_log(out)
    assert info.channel == "RTL 4"
    assert info.title is None


# ---- tracker ----------------------------------------------------------


def test_tracker_keeps_channel_after_it_leaves_the_log() -> None:
    t = NowPlayingTracker()
    t.update(parse_log(REAL_OUTPUT), DURING)
    # Later: alleen nog voortgangsregels in het log.
    np = t.update(parse_log(REAL_OUTPUT.splitlines()[-1]), DURING + 60)
    assert np.channel == "NPO 2"
    assert np.title == "Podium Klassiek special: Tania Kross"
    assert np.description == "Een muzikaal feest met en voor Tania Kross."


def test_tracker_new_programme_drops_description() -> None:
    t = NowPlayingTracker()
    t.update(parse_log(REAL_OUTPUT), DURING)
    np = t.update(
        parse_log(f"updateProgress: eventTitle= Journaal startTime= {END}000 endTime= {END + 900}000"),
        END + 10,
    )
    assert np.channel == "NPO 2"
    assert np.title == "Journaal"
    assert np.description is None


def test_tracker_zap_resets() -> None:
    t = NowPlayingTracker()
    t.update(parse_log(REAL_OUTPUT), DURING)
    np = t.update(
        parse_log(
            REAL_OUTPUT + "\nsetupUnicastSession: playbackType=LIVE | channel=Channel{title='RTL 4', id='5} "
            "| program=AVSProgram{_title='Nieuws'} | vod=null | recording=null"
        ),
        DURING + 5,
    )
    assert (np.channel, np.title, np.description, np.start) == ("RTL 4", "Nieuws", None, None)


def test_tracker_stale_after_end() -> None:
    t = NowPlayingTracker()
    t.update(parse_log(REAL_OUTPUT), DURING)
    np = t.update(parse_log(""), END + NowPlayingTracker.GRACE + 1)
    assert np.title is None
    assert np.channel == "NPO 2"


# ---- integratie in HA -------------------------------------------------


async def _setup(hass: HomeAssistant, output: dict) -> list[ServiceCall]:
    hass.states.async_set(REMOTE, "on", {"current_activity": "com.kpn.tvlauncher"})
    hass.states.async_set(ADB, "playing", {"adb_response": None})
    calls: list[ServiceCall] = []

    async def remote(call: ServiceCall) -> None:
        calls.append(call)

    async def adb(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set(ADB, "playing", {"adb_response": output["text"]})

    for s in ("send_command", "turn_on", "turn_off"):
        hass.services.async_register("remote", s, remote)
    hass.services.async_register("androidtv", "adb_command", adb)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="KPN TV",
        unique_id=REMOTE,
        data={"name": "KPN TV", CONF_REMOTE: REMOTE},
        options={
            CONF_CHANNELS: "NPO 1 = 1\nNPO 2 = 2\n",
            CONF_KEY_DELAY: 0.3,
            CONF_BOOT_DELAY: 0,
            CONF_SEND_ENTER: False,
            CONF_ADB_ENTITY: ADB,
            CONF_POLL_INTERVAL: 10,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return calls


async def _tick(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + dt_util.dt.timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_media_player_shows_now_playing(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(dt_util.utc_from_timestamp(DURING))
    output = {"text": REAL_OUTPUT}
    calls = await _setup(hass, output)
    await _tick(hass, 2)

    adb_calls = [c for c in calls if c.domain == "androidtv"]
    assert adb_calls and adb_calls[0].data["command"] == LOG_COMMAND

    state = hass.states.get(PLAYER)
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Podium Klassiek special: Tania Kross"
    assert state.attributes["media_channel"] == "NPO 2"
    assert state.attributes["source"] == "NPO 2"
    assert state.attributes["channel_number"] == "2"
    assert state.attributes["description"] == "Een muzikaal feest met en voor Tania Kross."
    assert state.attributes["media_duration"] == END - START
    assert state.attributes["playback_type"] == "SOTV"
    # Terugkijken: positie onbekend.
    assert "media_position" not in state.attributes


async def test_live_position_and_app_switch(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(dt_util.utc_from_timestamp(DURING))
    live = "\n".join(REAL_OUTPUT.splitlines()[:5])  # tot en met de LIVE-voortgang
    output = {"text": live}
    await _setup(hass, output)
    await _tick(hass, 2)
    state = hass.states.get(PLAYER)
    assert state.attributes["playback_type"] == "LIVE"
    assert state.attributes["media_position"] == DURING - START

    # Naar Netflix: niets meer tonen.
    hass.states.async_set(REMOTE, "on", {"current_activity": "com.netflix.ninja"})
    await hass.async_block_till_done()
    state = hass.states.get(PLAYER)
    assert state.state == "on"
    assert "media_title" not in state.attributes

    # Box uit: geen ADB-aanroepen meer.
    hass.states.async_set(REMOTE, "off")
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "off"


async def test_no_polling_when_off(hass: HomeAssistant) -> None:
    calls = await _setup(hass, {"text": REAL_OUTPUT})
    hass.states.async_set(REMOTE, "off")
    await hass.async_block_till_done()
    before = len([c for c in calls if c.domain == "androidtv"])
    await _tick(hass, 30)
    assert len([c for c in calls if c.domain == "androidtv"]) == before
