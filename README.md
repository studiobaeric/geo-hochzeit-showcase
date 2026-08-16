# Hochzeits-Geoguesser

[![Tests](https://github.com/n1c01/Geo_Hochzeit/actions/workflows/tests.yml/badge.svg)](https://github.com/n1c01/Geo_Hochzeit/actions/workflows/tests.yml)
[![Release](https://github.com/n1c01/Geo_Hochzeit/actions/workflows/release.yml/badge.svg)](https://github.com/n1c01/Geo_Hochzeit/actions/workflows/release.yml)

Errate die Orte von Hochzeitsfotos auf einer Karte. Die Karte ist eine
**komplett offline** gerenderte OpenStreetMap-Vektorkarte (MapLibre GL +
PMTiles) – im Spielbetrieb wird **kein** Internet benötigt.

## Download (ohne Python-Setup)

Für Windows, macOS und Linux gibt es auf der
[Releases-Seite](https://github.com/n1c01/Geo_Hochzeit/releases) fertige,
startklare Binaries – kein Python nötig. Entpacken, ausführbare Datei
starten, Browser öffnet sich automatisch auf `http://localhost:8080`.
Details zu Inhalt und Grenzen dieser Builds (z.B. Offline-Karte fehlt und
muss wie unten beschrieben ergänzt werden) stehen im mitgelieferten
`README.txt` und in [RELEASING.md](RELEASING.md). Wer stattdessen aus dem
Quellcode entwickeln oder selbst bauen möchte, macht mit den Schritten
unten weiter.

## Setup nach dem Klonen

**1. Python-Umgebung & Abhängigkeiten** (nur Flask):

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Karten-Assets** – zwei davon sind zu groß bzw. zu zahlreich für Git und
werden einmalig lokal erzeugt:

`tools/build_basemap.py` is plain Python and works the same on every OS -
only the font-fetching script differs per platform:

**macOS:**

```bash
python3 tools/build_basemap.py   # Vektor-Basemap (PMTiles, ~1.5 GB bei Zoom 10)
bash tools/fetch_fonts.sh        # Glyph-Fonts fürs Beschriften (~768 Dateien, ~13 MB)
```


**Linux:**

```bash
python3 tools/build_basemap.py   # Vektor-Basemap (PMTiles, ~1.5 GB bei Zoom 10)
bash tools/fetch_fonts_linux.sh  # Glyph-Fonts fürs Beschriften (~768 Dateien, ~13 MB)
```

**Windows (PowerShell):**

```powershell
python tools/build_basemap.py  # Vektor-Basemap (PMTiles, ~1.5 GB bei Zoom 10)
.\tools\fetch_fonts.ps1        # Glyph-Fonts fürs Beschriften (~768 Dateien, ~13 MB)
```

> **Hinweis (Windows):** Falls `fetch_fonts.ps1` nicht startet, muss die
> PowerShell-Execution-Policy angepasst werden:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

Alles andere (Leaflet, MapLibre, PMTiles-Lib, Sprite, Style, Marker-Icons)
liegt bereits eingecheckt in `static/`.

## Spiel konfigurieren (Namen & Fotos)

Für eine neue Hochzeit anpassen:

- **Spielernamen & Profilfotos:** [`static/config/players.js`](static/config/players.js)
  (Fallback-Werte) - lassen sich zur Laufzeit im Konfigurationsmenü ändern,
  siehe unten.
- **Rundenfotos & Orte:** [`static/config/photos.json`](static/config/photos.json)
  (Fallback-Datei) - lassen sich zur Laufzeit im Konfigurationsmenü
  hinzufügen/bearbeiten/löschen, siehe unten.
- **Bilddateien ablegen:** [`static/photos/`](static/photos/README.md)

Details siehe [`static/config/README.md`](static/config/README.md).

### Nutzernamen, Fotos & Rundenfotos zur Laufzeit ändern

Auf der Startseite führt der ⚙️-Button oben rechts zum Konfigurationsmenü
(`/config`). Dort lassen sich direkt im Browser ändern, ohne die
Konfigurationsdateien von Hand zu bearbeiten oder den Server neu zu
starten - praktisch, wenn kurzfristig noch jemand anderes mitspielt oder
neue Rundenfotos dazukommen:

- die Nutzernamen der beiden Spieler
  (`GET`/`PATCH /api/player-config`),
- die Profilfotos der beiden Spieler
  (`POST /api/player-config/photo/<player1|player2>`),
- die Rundenfotos inklusive Beschreibung und Position - beliebig viele,
  keine Obergrenze
  (`GET`/`POST /api/round-photos`, `PATCH`/`DELETE /api/round-photos/<id>`).
  Beim Hochladen eines Rundenfotos wird, falls vorhanden, die
  GPS-Position aus den Bilddaten (EXIF) automatisch ins Positionsfeld
  übernommen (`POST /api/round-photos/exif-location`); sie lässt sich
  danach weiterhin frei ändern. Alle Fotos werden im Konfigurationsmenü
  zunächst unscharf/verborgen dargestellt und erst nach einem Klick
  angezeigt, damit auf einem geteilten Bildschirm nichts versehentlich
  verraten wird.

Alle Änderungen werden serverseitig gespeichert und gelten dadurch sofort
für alle Geräte, die die Seite (neu) laden.

## App starten

Spielstand und Live-Sync laufen direkt in Flask (siehe `game_state.py`) -
kein separater Datenbankprozess mehr nötig. Der Spielstand wird bei jeder
Änderung zusätzlich nach `data/game_state.json` gespiegelt und beim Start
wieder eingelesen, damit ein Neustart oder Absturz des Server-Prozesses den
laufenden Spielstand nicht verliert. Über die Umgebungsvariable
`GAME_STATE_FILE` lässt sich ein anderer Pfad wählen; ein leerer Wert
schaltet die Persistenz ganz ab.

```bash
source .venv/bin/activate        # falls noch nicht aktiv
python app.py                    # http://localhost:8080
```

## Tests

Backend-Tests (Flask-Routen + `/api/*`) mit pytest:

```bash
pip install -r requirements-dev.txt
pytest
```

## Offline-Karte (PMTiles) bauen

Die Kartendaten (`static/data/basemap.pmtiles`) sind zu groß für Git und
werden **nicht** eingecheckt.

### Über das Webinterface (empfohlen für's initiale Einrichten)

Im Konfigurationsmenü (`/config`) gibt es den Abschnitt **„Kartendaten“**:
dort lassen sich beliebig viele **Kartenausschnitte** anlegen, jeder mit
eigenem Namen, Bounding Box und Detailgrad (Zoom, als beschriftetes
Dropdown statt Zahlenfeld) – z.B. ein weltweiter Ausschnitt mit wenig Detail
für die Übersicht, dazu ein oder mehrere einzelne Orte in hohem Detail.
Das Protomaps-Build-Datum kann leer bleiben - dann wird beim Herunterladen
automatisch der neueste tatsächlich verfügbare Stand ermittelt (Protomaps
hält tägliche Builds nur ca. 5 Tage vor, ein fest eingetragenes Datum würde
irgendwann ungültig werden). Nur für einen gezielt fixierten Stand lässt
sich optional ein Datum eintragen; ein Link zur
[Build-Übersicht](https://build.protomaps.com) zeigt, welche Daten dort
gerade verfügbar sind. Der Download-Button startet `tools/build_basemap.py`
direkt auf dem Server (`POST /api/map/build`) - das Skript ist reines
Python und läuft identisch auf Linux, macOS und Windows. Während des
Downloads zeigt die Seite Fortschritt und Log live an (per Polling von
`GET /api/map/build/status`): welcher Kartenausschnitt gerade geladen wird,
inklusive Fortschrittsbalken.

Die Ausschnitte werden von grob nach fein sortiert und so gemerged, dass
jeder nur die Zoomstufen oberhalb des vorherigen Ausschnitts beisteuert,
begrenzt auf seine eigene Bounding Box. Der **detailreichste** Ausschnitt
wird dabei **automatisch erweitert**, falls nötig, damit er immer alle
Fotostandorte aus [`static/config/photos.json`](static/config/photos.json)
mit Rand umschließt – so ist für jede Runde garantiert Kartendaten in hohem
Detail vorhanden, unabhängig davon, welchen Ausschnitt man konfiguriert hat.
Die gespeicherten (eigenen) Ausschnitte bleiben dabei unverändert; nur der
Build selbst nutzt bei Bedarf den erweiterten Bereich (`effective_bbox` je
Ausschnitt, sichtbar über `GET /api/map/config`).

### Über die Kommandozeile

Ohne Web-UI lässt sich das Skript weiterhin direkt aufrufen - ein einziges
`tools/build_basemap.py`, identisch auf Linux/macOS/Windows (frühere
Versionen hatten separate `build_basemap_linux.sh`/`.sh`/`.ps1`-Scripts).
Ohne weitere Angaben baut es die Karte in zwei Schritten (Legacy-Modus) und
merged das Ergebnis:

1. **Weltweit z0–5** – winzige Übersichts-Tiles (wenige MB), damit man beim
   weit Herauszoomen immer die ganze Erde sieht.
2. **Europa z6–13** – detaillierte Tiles für den europäischen Spielbereich.

```bash
python3 tools/build_basemap.py   # Linux/macOS
```

```powershell
python tools/build_basemap.py    # Windows
```

Das Skript lädt bei Bedarf automatisch die `pmtiles`-CLI herunter (reines
Python, ohne curl/unzip/tar) und schreibt `static/data/basemap.pmtiles`.

Für mehr als zwei Ausschnitte (wie im Webinterface) lässt sich `REGIONS_FILE`
auf eine eigene TSV-Datei zeigen (`Name<TAB>Bounding-Box<TAB>Zoom`, eine
Zeile pro Ausschnitt, aufsteigend nach Zoom sortiert):

```bash
printf 'Welt\t-180,-90,180,90\t5\nEuropa\t-25,32,45,72\t11\nMadeira\t-17.5,32.5,-16.5,33\t14\n' > /tmp/regions.tsv
REGIONS_FILE=/tmp/regions.tsv python3 tools/build_basemap.py
```

### pmtiles installieren

Das Build-Skript versucht automatisch, die `pmtiles`-CLI zu finden (via PATH oder
`tools/bin/`) und lädt sie falls nötig herunter. Falls der automatische Download
fehlschlägt oder nicht funktioniert, gibt es alternative Installationsmethoden:

#### macOS

**Option 1: Homebrew (empfohlen):**

```bash
brew install pmtiles
```

**Option 2: Manuelle Installation:**

```bash
# Release herunterladen und entpacken (passende Architektur wählen)
unzip go-pmtiles-*.zip
sudo mv pmtiles /usr/local/bin/
chmod +x /usr/local/bin/pmtiles
pmtiles --version
```

#### Linux

**Option 1: apt (Debian/Ubuntu):**

```bash
sudo apt update
sudo apt install pmtiles
pmtiles --version
```

**Option 2: Manuelle Installation:**

```bash
# Release von https://github.com/protomaps/go-pmtiles/releases herunterladen
# (x86_64 oder aarch64 je nach CPU)
unzip go-pmtiles-*.zip
sudo mv pmtiles /usr/local/bin/
chmod +x /usr/local/bin/pmtiles
pmtiles --version
```

#### Windows

**Option 1: Scoop (empfohlen):**

```powershell
scoop install pmtiles
```

**Option 2: Chocolatey:**

```powershell
choco install pmtiles
```

**Option 3: Manuelle Installation:**

1. Release von [go-pmtiles](https://github.com/protomaps/go-pmtiles/releases) herunterladen
   (Windows_x86_64.zip)
2. ZIP-Datei entpacken
3. `pmtiles.exe` zu einer dieser Optionen hinzufügen:
   - In einen Ordner im PATH (z.B. `C:\Program Files\pmtiles\`) und zu PATH hinzufügen
   - Oder direkt in `tools\bin\` des Projekts kopieren

   ```powershell
   Copy-Item pmtiles.exe .\tools\bin\
   ```

4. Überprüfen:

   ```powershell
   pmtiles --version
   ```

#### Fallback: Lokale Installation

Falls die globale Installation nicht funktioniert, können Sie pmtiles lokal im
Projektverzeichnis installieren (alle Betriebssysteme):

```bash
# macOS/Linux
mkdir -p tools/bin
unzip go-pmtiles-*.zip -d tools/bin/
chmod +x tools/bin/pmtiles

# Windows (PowerShell)
mkdir -p tools\bin
Expand-Archive -Path go-pmtiles-*.zip -DestinationPath tools\bin
```

Das Build-Skript sucht automatisch dort nach pmtiles.

### Zoom-Stufe / Region konfigurieren

| Variable        | Standard       | Bedeutung                                                        |
|-----------------|----------------|-------------------------------------------------------------------|
| `REGIONS_FILE`  | –              | TSV-Datei `Name<TAB>bbox<TAB>maxzoom`, ein Ausschnitt pro Zeile, aufsteigend nach Zoom |
| `MAXZOOM`       | `13`           | Legacy-Modus (kein `REGIONS_FILE`): Detailgrad des Europa-Ausschnitts |
| `WORLD_MAXZOOM` | `5`            | Legacy-Modus: bis zu welchem Zoom die Weltübersicht reicht (z0–n) |
| `EUROPE_BBOX`   | `-25,32,45,72` | Legacy-Modus: Bounding Box `min_lon,min_lat,max_lon,max_lat` für den Detail-Ausschnitt |
| `BUILD_DATE`    | *(leer)*       | Protomaps-Build-Datum (`YYYYMMDD`). Leer = automatisch der neueste tatsächlich verfügbare Stand (siehe `resolve_latest_build_date` in `tools/build_basemap.py`); manuell nur nötig, um einen bestimmten Stand zu fixieren – aktuelle Werte auf <https://build.protomaps.com> |
| `FORCE_REBUILD` | `false`        | `true` = ignoriert Caches, lädt alles neu                        |
| `CACHE_DIR`     | `/tmp`         | Wo die Zwischenergebnisse je Ausschnitt liegen                   |
| `DRY_RUN`       | `false`        | `true` = zeigt nur den Bauplan (keine Downloads, keine Schreibzugriffe) – für Tests |

Ohne `REGIONS_FILE` synthetisiert das Skript intern zwei Ausschnitte
("Welt" und "Europa") aus den Legacy-Variablen, genau wie zuvor.

### Caching

Jeder Ausschnitt wird einzeln unter `CACHE_DIR` zwischengespeichert
(`basemap_region_<n>.pmtiles` + `.meta`), passend zu seiner Bounding
Box/Zoomspanne/`BUILD_DATE`. Ändert sich ein Ausschnitt nicht, wird er beim
nächsten Lauf übersprungen; ändert er sich (Bbox, Zoom oder `BUILD_DATE`),
wird nur dieser eine Ausschnitt neu heruntergeladen. `FORCE_REBUILD=true`
verwirft alle Caches.

> **Cache löschen:** `rm -f /tmp/basemap_region_*.pmtiles /tmp/basemap_region_*.meta*`

Größengefühl für einen einzelnen Ausschnitt über ganz Europa (grob, hängt
stark vom Ausschnitt ab):

```
Zoom 10  ~1.4 GB  (Standard, Stadt-Ebene)
Zoom 11  ~2.9 GB  (Hauptstraßennetz)
Zoom 12  ~6.5 GB  (die meisten Straßen)
Zoom 13  ~13  GB  (jede Nebenstraße)
```

Beispiel – nur Deutschland mit mehr Detail (Legacy-Modus):

**Linux/macOS:**

```bash
EUROPE_BBOX=5.5,47,15.5,55 MAXZOOM=12 python3 tools/build_basemap.py
```

**Windows (PowerShell):**

```powershell
$env:EUROPE_BBOX="5.5,47,15.5,55"; $env:MAXZOOM=12; python tools/build_basemap.py
```

> **Hinweis:** Protomaps hält die täglichen Planet-Builds nur ~5 Tage vor.
> `BUILD_DATE` leer lassen (Standard) löst das automatisch auf; nur falls
> hier bewusst ein festes Datum gesetzt wurde und der Download mit einem
> 404 fehlschlägt, ein aktuelles Datum von <https://build.protomaps.com>
> eintragen.

Die PMTiles-Datei muss **nicht** komplett in den RAM passen: der Browser liest
sie per Range-Request, der Flask-Static-Handler liefert nur die angeforderten
Byte-Bereiche von der Platte.

## Karten-Style neu erzeugen (optional)

Style und Sprite sind bereits in `static/` eingecheckt; das ist nur nötig,
wenn das Theme geändert werden soll. Erzeugt `static/data/basemap-style.json`
aus dem `light`-Theme von
[`@protomaps/basemaps`](https://github.com/protomaps/basemaps):

```bash
cd tools && npm install && node build_style.mjs
```

Die Glyph-Fonts (`static/fonts/`, via `tools/fetch_fonts.sh`) und das Sprite
(`static/sprites/`) stammen aus
[`protomaps/basemaps-assets`](https://github.com/protomaps/basemaps-assets).
