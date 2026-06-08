# Hochzeits-Geoguesser

Errate die Orte von Hochzeitsfotos auf einer Karte. Die Karte ist eine
**komplett offline** gerenderte OpenStreetMap-Vektorkarte (MapLibre GL +
PMTiles) – im Spielbetrieb wird **kein** Internet benötigt.

## Setup nach dem Klonen

**1. Python-Umgebung & Abhängigkeiten** (nur Flask):

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Karten-Assets** – zwei davon sind zu groß bzw. zu zahlreich für Git und
werden einmalig lokal erzeugt:

```bash
bash tools/build_basemap.sh    # Vektor-Basemap (PMTiles, ~1.5 GB bei Zoom 10)
bash tools/fetch_fonts.sh      # Glyph-Fonts fürs Beschriften (~768 Dateien, ~13 MB)
```

Alles andere (Leaflet, MapLibre, PMTiles-Lib, Sprite, Style, Marker-Icons)
liegt bereits eingecheckt in `static/`.

## App starten

```bash
source .venv/bin/activate        # falls noch nicht aktiv
python app.py                    # http://localhost:8080
```

## Offline-Karte (PMTiles) bauen

Die Kartendaten (`static/data/basemap.pmtiles`) sind zu groß für Git und
werden **nicht** eingecheckt. Das Skript baut die Karte in zwei Schritten und
merged das Ergebnis:

1. **Weltweit z0–5** – winzige Übersichts-Tiles (wenige MB), damit man beim
   weit Herauszoomen immer die ganze Erde sieht.
2. **Europa z6–10** – detaillierte Tiles für den europäischen Spielbereich
   (~1.4 GB).

```bash
bash tools/build_basemap.sh
```

Das Skript lädt bei Bedarf automatisch die `pmtiles`-CLI herunter und schreibt
`static/data/basemap.pmtiles`.

### Zoom-Stufe / Region konfigurieren

| Variable        | Standard       | Bedeutung                                                      |
|-----------------|----------------|----------------------------------------------------------------|
| `MAXZOOM`       | `10`           | Höchster Detailgrad für Europa (höher = viel größer)           |
| `WORLD_MAXZOOM` | `5`            | Bis zu welchem Zoom die Weltkarte reicht (z0–n)                |
| `EUROPE_BBOX`   | `-25,34,45,72` | Region für Hoch-Zoom-Tiles `min_lon,min_lat,max_lon,max_lat`   |
| `BUILD_DATE`    | `20260608`     | Protomaps-Build-Datum (`YYYYMMDD`)                             |

Größen des Europa-Anteils (der Weltteil ist immer nur wenige MB):

```bash
MAXZOOM=10 bash tools/build_basemap.sh   # ~1.4 GB  (Standard, Stadt-Ebene)
MAXZOOM=11 bash tools/build_basemap.sh   # ~2.9 GB  (Hauptstraßennetz)
MAXZOOM=12 bash tools/build_basemap.sh   # ~6.5 GB  (die meisten Straßen)
MAXZOOM=13 bash tools/build_basemap.sh   # ~13  GB  (jede Nebenstraße)
```

Beispiel – nur Deutschland mit mehr Detail:

```bash
EUROPE_BBOX=5.5,47,15.5,55 MAXZOOM=12 bash tools/build_basemap.sh
```

> **Hinweis:** Protomaps hält die täglichen Planet-Builds nur ~5 Tage vor.
> Falls der Download 404 liefert, ein aktuelles Datum von
> <https://build.protomaps.com> als `BUILD_DATE` setzen.

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
