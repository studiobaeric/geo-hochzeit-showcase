# Hochzeitsfotos

Lege hier deine Hochzeitsfotos ab, die im Spiel verwendet werden sollen -
oder lade sie im Konfigurationsmenü (`/config`) direkt im Browser hoch,
dann landen sie automatisch hier. Die restliche Spiel-Konfiguration
(Spielernamen, Profilfotos, Rundenfotos mit Orten) liegt gesammelt in
[`static/config/`](../config/).

## Format
- Unterstützte Formate: JPG, PNG, GIF, WebP
- Maximale Dateigröße pro Upload: 20 MB
- Von Hand abgelegte Dateinamen müssen mit den Einträgen in
  `static/config/photos.json` übereinstimmen (über das Konfigurationsmenü
  hochgeladene Fotos bekommen automatisch einen eindeutigen Dateinamen und
  werden automatisch eingetragen).

## Beispiel
Wenn in `photos.json` ein Foto mit `"filename": "brautpaar.jpg"` definiert ist, muss hier eine Datei `brautpaar.jpg` existieren.
