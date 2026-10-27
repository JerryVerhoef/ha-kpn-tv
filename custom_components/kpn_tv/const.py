"""Constanten voor de KPN TV-integratie."""

from __future__ import annotations

DOMAIN = "kpn_tv"

CONF_REMOTE = "remote_entity"
CONF_CHANNELS = "channels"
CONF_KEY_DELAY = "key_delay"
CONF_BOOT_DELAY = "boot_delay"
CONF_SEND_ENTER = "send_enter"
CONF_ADB_ENTITY = "adb_entity"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_NAME = "KPN TV"
DEFAULT_KEY_DELAY = 0.3
DEFAULT_BOOT_DELAY = 8
DEFAULT_SEND_ENTER = False
DEFAULT_POLL_INTERVAL = 10

# Hoe lang we maximaal wachten tot de box na het aanzetten "on" meldt.
POWER_ON_TIMEOUT = 30

SERVICE_PLAY_CHANNEL = "play_channel"
ATTR_CHANNEL = "channel"
ATTR_CHANNEL_NUMBER = "channel_number"
ATTR_CURRENT_APP = "current_app"
ATTR_DESCRIPTION = "description"
ATTR_PROGRAM_START = "program_start"
ATTR_PROGRAM_END = "program_end"
ATTR_PLAYBACK_TYPE = "playback_type"
ATTR_KPN_CHANNEL_ID = "kpn_channel_id"

MEDIA_TYPE_CHANNEL = "channel"

# Startlijst met de vaste KPN-nummers van de hoofdzenders.
# Pas aan in de opties van de integratie; één zender per regel.
DEFAULT_CHANNELS = """NPO 1 = 1
NPO 2 = 2
NPO 3 = 3
RTL 4 = 4
RTL 5 = 5
SBS6 = 6
RTL 7 = 7
Net5 = 8
RTL 8 = 10
SBS9 = 19
"""
