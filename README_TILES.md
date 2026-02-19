# Offline Kartenkacheln herunterladen

## Methode 1: Mobile Atlas Creator (MOBAC) - Empfohlen
1. Download: https://mobac.sourceforge.io/
2. Starte MOBAC
3. Wähle die gewünschte Region aus
4. Format: "OSM Tile Storage"
5. Zoom-Level: 6-15 (je nach Detailgrad)
6. Download starten
7. Kopiere die generierten Tiles in `static/tiles/`

## Methode 2: Python Script (für kleinere Bereiche)
```python
pip install pySmartDL
```

Erstelle `download_tiles.py`:
```python
import os
import requests
from math import radians, cos, sin, asin, sqrt, pi, floor

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - sin(lat_rad) / (1.0 + cos(lat_rad)) / pi) / 2.0 * n)
    return (xtile, ytile)

def download_tiles(lat, lon, zoom_levels, radius_km=50):
    base_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    for zoom in zoom_levels:
        x, y = deg2num(lat, lon, zoom)
        tiles_to_download = 2 ** (zoom - 10) if zoom > 10 else 1

        for dx in range(-tiles_to_download, tiles_to_download + 1):
            for dy in range(-tiles_to_download, tiles_to_download + 1):
                tile_x, tile_y = x + dx, y + dy
                url = base_url.format(z=zoom, x=tile_x, y=tile_y)

                save_dir = f"static/tiles/{zoom}/{tile_x}"
                os.makedirs(save_dir, exist_ok=True)
                filepath = f"{save_dir}/{tile_y}.png"

                if not os.path.exists(filepath):
                    try:
                        r = requests.get(url, headers={'User-Agent': 'HochzeitsGeoguesser/1.0'})
                        with open(filepath, 'wb') as f:
                            f.write(r.content)
                        print(f"Downloaded: {zoom}/{tile_x}/{tile_y}")
                    except Exception as e:
                        print(f"Error: {e}")

# Beispiel: Region um Hochzeitslocation
download_tiles(51.1657, 10.4515, zoom_levels=range(6, 16))
```

## Methode 3: Offline-Karte als Bild (einfachste Lösung für Prototyp)
Verwende ein statisches Kartenbild und Leaflet mit CRS.Simple

## Wichtig:
- OSM hat Rate-Limits - verwende MOBAC für größere Downloads
- Beachte die Tile-Usage-Policy: https://operations.osmfoundation.org/policies/tiles/
- Für Hochzeit: Lade nur relevante Region herunter (spart Speicherplatz)
