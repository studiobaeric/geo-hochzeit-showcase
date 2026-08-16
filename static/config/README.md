# Spiel-Konfiguration

Alles, was pro Hochzeit angepasst werden muss, liegt gesammelt hier:

- **`players.js`** – Fallback-Namen der beiden Spieler (`NAME_1`/`NAME_2`)
  und Fallback-Dateinamen ihrer Profilfotos (`PHOTO_1`/`PHOTO_2`), genutzt
  bevor je etwas über das Konfigurationsmenü geändert wurde.
- **`photos.json`** – die Runden-Fotos: pro Runde ein Bild, die dazugehörige
  Koordinate (`location.lat`/`location.lng`) und eine Beschreibung.

Beide Dateien lassen sich von Hand bearbeiten, müssen es aber nicht mehr:
im Konfigurationsmenü (`/config`) lassen sich Spielernamen, Spielerfotos
und beliebig viele Rundenfotos (inkl. Position und Beschreibung) direkt im
Browser hochladen/bearbeiten/löschen - siehe game_state.py's
`/api/player-config`(`/photo/<role>`) und photo_config.py's
`/api/round-photos`. Ein hochgeladenes Rundenfoto übernimmt automatisch die
GPS-Position aus seinen EXIF-Metadaten, falls vorhanden.

Die eigentlichen Bilddateien (Profilfotos wie Rundenfotos) gehören nach
[`static/photos/`](../photos/README.md) - dorthin speichert auch das
Konfigurationsmenü hochgeladene Fotos automatisch.
