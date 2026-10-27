"""Zenderlijst: tekst inlezen en zenders opzoeken."""

from __future__ import annotations


class ChannelListError(ValueError):
    """Fout in de zenderlijst, met het regelnummer erbij."""

    def __init__(self, line_no: int, line: str) -> None:
        super().__init__(f"Regel {line_no}: '{line}'")
        self.line_no = line_no
        self.line = line


def parse_channels(text: str) -> dict[str, str]:
    """Lees 'Naam = nummer' per regel in.

    Lege regels en regels die met # beginnen worden overgeslagen.
    Geeft een dict naam -> nummer (als tekst), in de volgorde van de lijst.
    """
    channels: dict[str, str] = {}
    seen: set[str] = set()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, number = line.rpartition("=")
        name, number = name.strip(), number.strip()
        if not sep or not name or not number.isdigit():
            raise ChannelListError(line_no, line)
        key = name.casefold()
        if key in seen:
            raise ChannelListError(line_no, line)
        seen.add(key)
        channels[name] = str(int(number))
    return channels


def resolve_channel(channels: dict[str, str], channel: str) -> tuple[str | None, str]:
    """Zoek een zender op naam (hoofdletterongevoelig) of nummer.

    Geeft (naam of None, nummer). Gooit ValueError als het niet lukt.
    """
    wanted = str(channel).strip()
    for name, number in channels.items():
        if name.casefold() == wanted.casefold():
            return name, number
    if wanted.isdigit():
        number = str(int(wanted))
        name = next((n for n, num in channels.items() if num == number), None)
        return name, number
    raise ValueError(wanted)
