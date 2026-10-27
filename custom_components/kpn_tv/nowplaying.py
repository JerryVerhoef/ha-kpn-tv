"""Wat er speelt, uitgelezen uit het systeemlog van de KPN TV+ Box.

De KPN-app logt bij elke zapwissel een regel met zender en programma, en
elke seconde de huidige programmatitel met start- en eindtijd. Dit is
debuglogging van KPN, geen officiële interface: een app-update kan het
uitzetten. Alles hier is daarom best effort.

Het commando draait op de box (via de Android Debug Bridge-integratie) en
stuurt alleen de relevante regels terug, zonder tijdstempels en zonder de
stream-URL (die bevat een sessietoken). Zonder tijdstempels blijft de
uitvoer gelijk zolang er niets verandert, zodat HA niet elke poll een
nieuwe toestand in de database schrijft.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

LOG_COMMAND = (
    "logcat -d -t 20000"
    " | grep -E 'setupUnicastSession: (playbackType|serviceName)|updateProgress: eventTitle'"
    " | sed -E 's/^.*(setupUnicastSession|updateProgress)/\\1/; s/ \\| uri=.*//'"
    " | uniq | tail -n 10"
)

KPN_APP = "com.kpn.tvlauncher"

_RE_SESSION = re.compile(
    r"setupUnicastSession: playbackType=(?P<type>\S+)"
    r".*?channel=Channel\{title='(?P<channel>.*?)', id='?(?P<id>\d+)"
    r"(?:.*?program=AVSProgram\{_title='(?P<program>.*?)'\})?"
)
_RE_DESCRIPTION = re.compile(
    r"setupUnicastSession: serviceName\s*=\s*\S*\s*\|\s*contentDescription\s*=\s*(?P<desc>.*)$"
)
_RE_PROGRESS = re.compile(
    r"updateProgress: eventTitle=\s*(?P<title>.*?)\s+startTime=\s*(?P<start>\d+)"
    r"\s+endTime=\s*(?P<end>\d+)"
)


@dataclass
class LogInfo:
    """Wat er uit één log-uitvoer te halen valt. None = niet gevonden."""

    channel: str | None = None
    channel_id: str | None = None
    playback_type: str | None = None
    session_program: str | None = None
    description: str | None = None
    title: str | None = None
    start: int | None = None  # epoch-seconden
    end: int | None = None


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return None if text in ("", "unknown", "null") else text


def parse_log(output: str | None) -> LogInfo:
    """Lees de uitvoer van LOG_COMMAND. De laatste regel van elk soort wint."""
    info = LogInfo()
    if not output:
        return info
    for line in output.splitlines():
        if m := _RE_SESSION.search(line):
            info.channel = _clean(m["channel"])
            info.channel_id = m["id"]
            info.playback_type = m["type"]
            info.session_program = _clean(m["program"])
            info.description = None  # hoort bij deze sessie, komt op de volgende regel
            # Voortgang van vóór deze zapwissel hoort bij de vorige zender.
            info.title = None
            info.start = info.end = None
        elif m := _RE_DESCRIPTION.search(line):
            info.description = _clean(m["desc"])
        elif m := _RE_PROGRESS.search(line):
            info.title = _clean(m["title"])
            info.start = int(m["start"]) // 1000
            info.end = int(m["end"]) // 1000
    return info


@dataclass
class NowPlaying:
    """Wat de media player toont."""

    channel: str | None = None
    channel_id: str | None = None
    playback_type: str | None = None
    title: str | None = None
    description: str | None = None
    start: int | None = None
    end: int | None = None


class NowPlayingTracker:
    """Combineert opeenvolgende polls.

    De zenderregel staat maar kort in het log; daarom onthouden we hem.
    """

    # Na het einde van een programma nog zo lang wachten op een nieuwe
    # titel voordat we aannemen dat er niets meer speelt.
    GRACE = 120

    def __init__(self) -> None:
        self.current = NowPlaying()

    def reset(self) -> None:
        self.current = NowPlaying()

    def update(self, info: LogInfo, now: float) -> NowPlaying:
        cur = self.current
        if info.channel is not None and (
            info.channel != cur.channel or info.playback_type != cur.playback_type
        ):
            # Gezapt (of live <-> terugkijken): oude programmagegevens horen
            # bij de vorige zender.
            cur = NowPlaying(
                channel=info.channel,
                channel_id=info.channel_id,
                playback_type=info.playback_type,
                title=info.session_program,
                description=info.description,
            )
        elif info.channel is not None and info.description and not cur.description:
            cur.description = info.description

        if info.title is not None:
            if info.title != cur.title:
                # Nieuw programma: beschrijving alleen houden als die erbij hoort.
                if info.title != info.session_program:
                    cur.description = None
                elif info.description:
                    cur.description = info.description
            cur.title = info.title
            cur.start = info.start
            cur.end = info.end

        # Verouderd: het programma is al een tijd voorbij en er kwam niets nieuws.
        if cur.end is not None and now > cur.end + self.GRACE:
            cur.title = cur.description = None
            cur.start = cur.end = None

        self.current = cur
        return cur
