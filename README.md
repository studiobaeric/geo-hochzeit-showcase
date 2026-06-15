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

**macOS:**

```bash
bash tools/build_basemap.sh    # Vektor-Basemap (PMTiles, ~1.5 GB bei Zoom 10)
bash tools/fetch_fonts.sh      # Glyph-Fonts fürs Beschriften (~768 Dateien, ~13 MB)
```


**Linux:**

```bash
bash tools/build_basemap_linux.sh    # Vektor-Basemap (PMTiles, ~1.5 GB bei Zoom 10)
bash tools/fetch_fonts_linux.sh      # Glyph-Fonts fürs Beschriften (~768 Dateien, ~13 MB)
```

**Windows (PowerShell):**

```powershell
.\tools\build_basemap.ps1      # Vektor-Basemap (PMTiles, ~1.5 GB bei Zoom 10)
.\tools\fetch_fonts.ps1        # Glyph-Fonts fürs Beschriften (~768 Dateien, ~13 MB)
```

> **Hinweis (Windows):** Falls die `.ps1`-Scripts nicht starten, muss die
> PowerShell-Execution-Policy angepasst werden:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

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

| Variable        | Standard       | Bedeutung                                                      |
|-----------------|----------------|----------------------------------------------------------------|
| `MAXZOOM`       | `10`           | Höchster Detailgrad für Europa (höher = viel größer)           |
| `WORLD_MAXZOOM` | `5`            | Bis zu welchem Zoom die Weltkarte reicht (z0–n)                |
| `EUROPE_BBOX`   | `-25,32,45,72` | Region für Hoch-Zoom-Tiles `min_lon,min_lat,max_lon,max_lat`   |
| `BUILD_DATE`    | `20260608`     | Protomaps-Build-Datum (`YYYYMMDD`)                             |
| `FORCE_REBUILD` | `false`        | `true` = ignoriert Caches, lädt alles neu                      |

### Incrementales Build

Das Skript cached Zwischenergebnisse in `/tmp/basemap_{world,europe}.pmtiles`.
Beim nächsten Durchlauf werden nur fehlende Teile nachgeladen:

- **Welt** (z0–5) – einmal geladen, wird bei gleichem `WORLD_MAXZOOM`/`BUILD_DATE` wiederverwendet.
- **Europa** (z6+) – ändert sich nur `EUROPE_BBOX` (z.B. Erweiterung um Madeira),
  wird nur der neue geografische Streifen heruntergeladen und mit dem Cache gemerged.
  Gleiches gilt für eine Erhöhung von `MAXZOOM`: nur die neuen Zoom-Stufen werden
  extrahiert.
- Bei Änderung von `BUILD_DATE` oder `FORCE_REBUILD=true` wird komplett neu geladen.

> **Cache löschen:** `rm -f /tmp/basemap_{world,europe}.pmtiles /tmp/basemap_{world,europe}.meta*`

Größen des Europa-Anteils (der Weltteil ist immer nur wenige MB):

**Linux/macOS:**

```bash
MAXZOOM=10 bash tools/build_basemap.sh   # ~1.4 GB  (Standard, Stadt-Ebene)
MAXZOOM=11 bash tools/build_basemap.sh   # ~2.9 GB  (Hauptstraßennetz)
MAXZOOM=12 bash tools/build_basemap.sh   # ~6.5 GB  (die meisten Straßen)
MAXZOOM=13 bash tools/build_basemap.sh   # ~13  GB  (jede Nebenstraße)
```

**Windows (PowerShell):**

```powershell
$env:MAXZOOM=10; .\tools\build_basemap.ps1   # ~1.4 GB  (Standard, Stadt-Ebene)
$env:MAXZOOM=11; .\tools\build_basemap.ps1   # ~2.9 GB  (Hauptstraßennetz)
$env:MAXZOOM=12; .\tools\build_basemap.ps1   # ~6.5 GB  (die meisten Straßen)
$env:MAXZOOM=13; .\tools\build_basemap.ps1   # ~13  GB  (jede Nebenstraße)
```

Beispiel – nur Deutschland mit mehr Detail:

**Linux/macOS:**

```bash
EUROPE_BBOX=5.5,47,15.5,55 MAXZOOM=12 bash tools/build_basemap.sh
```

**Windows (PowerShell):**

```powershell
$env:EUROPE_BBOX="5.5,47,15.5,55"; $env:MAXZOOM=12; .\tools\build_basemap.ps1
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




### Datenbanksuperuser und Datenbankuser: 
user: nico@mail.de
PW: 12345678
