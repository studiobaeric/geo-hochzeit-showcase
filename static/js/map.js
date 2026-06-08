// Spielzustand
import {pushLocation} from "./multiplayer.js";
import {PhotoZoom} from "./photo.js";

let guessMarker = null;
let targetMarker = null;
let resultLine = null;
let isLocked = false;
let round_number = 0;
let currentPhoto = null;


// Lade Foto für Runde
async function loadPhoto(round) {
    try {
        const response = await fetch('/static/data/photos.json');
        let photos = await response.json();
        currentPhoto = photos[round];
        round_number = round;
        document.getElementById('photoImage').src = `/static/photos/${currentPhoto.filename}`;
        updateRoundDisplay();
    } catch (error) {
        console.error('Fehler beim Laden der Fotos:', error);
    }
}


// Aktualisiere Rundenanzeigefunction
function updateRoundDisplay() {
    document.getElementById('roundInfo').textContent = `Runde ${round_number}`;
}

// View-Wechsel
function showView(viewName) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(viewName).classList.add('active');

    // Zeige/verstecke photoControls basierend auf aktiver View
    const photoControls = document.getElementById('photoControls');
    if (viewName === 'photoView') {
        photoControls.style.display = 'flex';
    } else {
        photoControls.style.display = 'none';
    }

    // Karte neu rendern wenn zu mapView gewechselt wird
    if (viewName === 'mapView') {
        // Erhöhtes Timing für Android Edge Kompatibilität
        // invalidateSize muss nach DOM-Paint und nach Address-Bar-Anpassung aufgerufen werden
        setTimeout(() => {
            map.invalidateSize(true);  // true = Animate Pan/Zoom
        }, 200);
    }
}

// Setze Spielzustand für nächste Runde zurück
function resetForNextRound() {
    // Entferne Marker und Linien von der Karte
    if (guessMarker) {
        map.removeLayer(guessMarker);
        guessMarker = null;
    }
    if (targetMarker) {
        map.removeLayer(targetMarker);
        targetMarker = null;
    }
    if (resultLine) {
        map.removeLayer(resultLine);
        resultLine = null;
    }

    // Setze Spielzustand zurück
    isLocked = false;
    document.getElementById('lockButton').disabled = true;
    document.getElementById('lockButton').textContent = 'Einlocken';
    document.getElementById('result').innerHTML = '';
    document.getElementById('result').style.display = 'none';
    document.getElementById('backToPhotoButton').style.display = 'inline-block';
    document.getElementById('nextPhotoButton').style.display = 'none';
}

// Gehe zum nächsten Foto
export async function nextPhoto(round_number) {

    photoZoom.reset();
    // Leere das Foto-Element sofort, damit altes Foto nicht sichtbar ist
    document.getElementById('photoImage').src = '';
    resetForNextRound();
    await loadPhoto(round_number);
    showView('photoView');
}

function initMap() {
    if (map) return; // idempotent

    const mapEl = document.getElementById('map');
    if (!mapEl) {
        console.warn('initMap: #map nicht gefunden; Abbruch');
        return;
    }
// Initialisiere die Karte
    const map = L.map('map', {minZoom: 1, maxZoom: 18}).setView([49.3690, 9.5436], 6);


// Vektor-Basemap (MapLibre GL) aus lokaler PMTiles-Datei - komplett offline.
// PMTiles wird per HTTP-Range-Request gelesen, die Datei landet nie komplett im RAM.
    const pmtilesProtocol = new pmtiles.Protocol();
    maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);

// MapLibre v5 verlangt absolute URLs fuer sprite/glyphs/Source. Wir setzen sie
// zur Laufzeit aus location.origin zusammen, damit die App auf jedem Host/Port
// (und damit komplett offline) funktioniert, ohne hartkodierte Adresse.
    fetch('/static/data/basemap-style.json')
        .then((response) => response.json())
        .then((style) => {
            const origin = window.location.origin;
            style.sprite = origin + style.sprite;
            style.glyphs = origin + style.glyphs;
            style.sources.protomaps.url = 'pmtiles://' + origin + '/static/data/basemap.pmtiles';

            L.maplibreGL({
                style: style,
                interactive: true,
                attribution: 'Map data &copy; OpenStreetMap contributors'
            }).addTo(map);
            map.getContainer().style.pointerEvents = 'auto';
            setTimeout(() => {
                const canvas = document.querySelector('.maplibregl-canvas');
                if (canvas) {
                    canvas.style.pointerEvents = 'none';
                }
            }, 0);
        })
        .catch((error) => console.error('Fehler beim Laden der Karten-Basemap:', error));

// Click-Handler für Tipp-Platzierung
    map.on('click', async function (e) {
        if (isLocked) return; // Kein Verschieben nach Lock-In


        const {lat, lng} = e.latlng;

        // Wenn noch kein Marker gesetzt, erstelle einen
        if (!guessMarker) {
            guessMarker = L.marker([lat, lng], {
                icon: L.icon({
                    iconUrl: '/static/img/marker-icon-2x-blue.png',
                    shadowUrl: '/static/img/marker-shadow.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowSize: [41, 41]
                })
            }).addTo(map);
            guessMarker.bindPopup('Dein Tipp');
        } else {
            // Verschiebe bestehenden Marker
            guessMarker.setLatLng([lat, lng]);
        }
        try {
            await pushLocation({lat, lng}, round_number);
        } catch (err) {
            console.error("Failed to push location:", err);
        }

        // Zeige Lock-In Button
        document.getElementById('lockButton').disabled = false;
    });
}

// Map initialisieren, sobald DOM bereit ist
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMap);
} else {
    initMap();
}

// Button-Handler
document.getElementById('guessButton').addEventListener('click', function () {
    showView('mapView');
});

document.getElementById('backToPhotoButton').addEventListener('click', function () {
    if (!isLocked) {
        showView('photoView');
    }
});



// Lock-In Button Handler
document.getElementById('lockButton').addEventListener('click', function () {
    if (!guessMarker || isLocked || !currentPhoto) return;

    isLocked = true;
    this.disabled = true;
    this.textContent = 'Eingelockt!';

    // Verwende Location aus aktuellem Foto
    const actualLocation = [currentPhoto.location.lat, currentPhoto.location.lng];

    // Zeige tatsächliche Location
    targetMarker = L.marker(actualLocation, {
        icon: L.icon({
            iconUrl: '/static/img/marker-icon-2x-red.png',
            shadowUrl: '/static/img/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41]
        })
    }).addTo(map);
    targetMarker.bindPopup('<b>Tatsächliche Location</b>').openPopup();


    // Zeichne Linie zwischen Tipp und Ziel
    resultLine = L.polyline([guessMarker.getLatLng(), actualLocation], {
        color: 'red',
        weight: 3,
        opacity: 0.7,
        dashArray: '10, 10'
    }).addTo(map);


    document.getElementById('result').innerHTML = `
        <h3>Ergebnis:</h3>
        <p>Distanz: <strong>${distanceText}</strong></p>
    `;
    document.getElementById('result').style.display = 'block';

    // Verstecke "Zurück zum Foto" Button
    document.getElementById('backToPhotoButton').style.display = 'none';

    // Zeige "Nächstes Foto" Button (oder "Zum Ergebnis" wenn letzte Runde)
    if (currentPhotoIndex + 1 < photos.length) {
        document.getElementById('nextPhotoButton').textContent = 'Nächstes Foto';
        document.getElementById('nextPhotoButton').style.display = 'inline-block';
    } else {
        document.getElementById('nextPhotoButton').textContent = 'Zum Ergebnis';
        document.getElementById('nextPhotoButton').style.display = 'inline-block';
    }

    // Zoom auf beide Marker
    const bounds = L.latLngBounds([guessMarker.getLatLng(), actualLocation]);
    map.fitBounds(bounds, {padding: [50, 50]});
});

// Initialisiere Foto-Zoom
const photoZoom = new PhotoZoom('photoImage', 'photoContainer', 'resetZoomButton');