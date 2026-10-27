# KPN TV voor Home Assistant

Zenders kiezen op **naam** op je KPN TV+ Box, vanuit Home Assistant.

De integratie bouwt voort op de standaardintegratie **Android TV Remote**: die regelt de verbinding met de box, deze integratie voegt daar een zenderlijst en een nette media player aan toe.

## Wat je krijgt

- **`media_player.kpn_tv`** met je zenders als bronnenlijst. Kies "RTL 4" en de box schakelt om.
- **Actie `kpn_tv.play_channel`**: zender op naam of nummer. Staat de box uit, dan zet hij hem eerst aan en wacht tot hij opgestart is.
- Volgende/vorige = zender omhoog/omlaag, volume, dempen, aan/uit, play/pauze.
- `media_player.play_media` met `media_content_type: channel` werkt ook.

Zonder extra koppeling weet de integratie niet wat er speelt: de bron is dan de zender die het laatst via Home Assistant gekozen is. Met de optionele ADB-koppeling (hieronder) weet hij het wel.

## Wat er speelt (optioneel, via ADB)

De KPN-app schrijft zender, programma, beschrijving en tijden naar het systeemlog van de box. Via de standaardintegratie **Android Debug Bridge** leest KPN TV dat uit. Je media player toont dan:

- de echte zender, ook als je met de gewone afstandsbediening zapt
- de programmatitel (`media_title`) en de zender (`media_channel`)
- de beschrijving, begin- en eindtijd (`description`, `program_start`, `program_end`)
- een voortgangsbalk bij live kijken (bij terugkijken is de positie onbekend)
- `playback_type`: `LIVE` of `SOTV` (terugkijken vanaf het begin)

Instellen:

1. Op de box: Instellingen → Apparaatvoorkeuren → Over → 7× op **Build** tikken. Daarna Ontwikkelaarsopties → **USB-foutopsporing** aan.
2. In HA: integratie **Android Debug Bridge** toevoegen met het IP-adres van de box. Op de tv de vraag "USB-foutopsporing toestaan?" bevestigen met **Altijd toestaan**.
3. KPN TV → **Configureren** → kies bij **ADB-entity** de media player van die integratie.

Goed om te weten:

- Dit is debuglogging van KPN, geen officiële functie. Na een update van de KPN-app kan het stoppen; de rest van de integratie blijft dan gewoon werken.
- De integratie leest alleen zender, titel, beschrijving en tijden. De stream-URL (met sessietoken) uit dezelfde logregel wordt al op de box weggeknipt en komt nooit in Home Assistant.
- Gelezen wordt alleen als de box aanstaat en de KPN-app op de voorgrond is, standaard elke 10 seconden.

## Installeren

1. Koppel je box eerst met **Android TV Remote** (Instellingen → Apparaten en diensten → Integratie toevoegen). Je krijgt dan een `remote.…`-entity.
2. HACS → menu rechtsboven → **Aangepaste repositories** → `https://github.com/JerryVerhoef/ha-kpn-tv`, type **Integratie**.
3. Installeer **KPN TV** en herstart Home Assistant.
4. Instellingen → Apparaten en diensten → Integratie toevoegen → **KPN TV** → kies de remote-entity van de box.

Zonder HACS: kopieer `custom_components/kpn_tv` naar `/config/custom_components/` en herstart.

## Zenderlijst

Via **Configureren** op de integratie. Eén zender per regel:

```
NPO 1 = 1
RTL 4 = 4
Discovery = 501
# regels met # worden overgeslagen
```

De meegeleverde lijst bevat alleen de hoofdzenders. Controleer de nummers met de KPN-gids, KPN wijzigt ze af en toe.

Instellingen in hetzelfde scherm:

| Optie | Standaard | Wanneer aanpassen |
|---|---|---|
| Pauze tussen cijfers | 0,3 s | Box mist cijfers → hoger |
| Wachten na aanzetten | 8 s | Eerste zender komt niet aan na aanzetten → hoger |
| Na de cijfers op OK drukken | uit | Box schakelt niet vanzelf om |

## Voorbeelden

Zender kiezen in een automatisering of script:

```yaml
action: kpn_tv.play_channel
target:
  entity_id: media_player.kpn_tv
data:
  channel: NPO 1
```

Elke ochtend om 7:30 het nieuws aan:

```yaml
triggers:
  - trigger: time
    at: "07:30:00"
actions:
  - action: kpn_tv.play_channel
    target: { entity_id: media_player.kpn_tv }
    data: { channel: NPO 1 }
```

Via de standaardactie (handig voor dashboards en spraak):

```yaml
action: media_player.select_source
target: { entity_id: media_player.kpn_tv }
data: { source: RTL 4 }
```

## Problemen

- **Na aanzetten komt de eerste zender niet aan:** verhoog "Wachten na aanzetten".
- **Verkeerde zender (cijfer gemist):** verhoog "Pauze tussen cijfers".
- **Tv gaat niet mee aan:** zet HDMI-CEC aan op de box (Apparaatvoorkeuren → Weergave en geluid → HDMI CEC) én op de tv.
- **Toetsenbord op het scherm weg** na het koppelen: dat komt door de Android TV Remote-koppeling, niet door deze integratie.
