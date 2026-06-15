// Spielzustand
import {getGamestateRecord, init_pocketbase, lockInSolution, pushLocation} from "./multiplayer.js";

let guessMarker = null;
let isLocked = false;
let currentPhoto = null;
let map = null;

// Lade Foto für Runde
export async function startNextRound(round) {
    resetMap();
    resetButtons();
    await loadPhoto(round);
    updateRoundDisplay(round);
    showView("photoView");
}

function resetMap() {
    if (guessMarker) {
        map.removeLayer(guessMarker);
        guessMarker = null;
    }
}

function resetButtons() {
    isLocked = false;
    document.getElementById('lockButton').disabled = true;
    document.getElementById('lockButton').textContent = 'Einlocken';
    document.getElementById('backToPhotoButton').style.display = 'inline-block';
}

async function loadPhoto(round) {
    console.log("Loading Photo: " + round);
    try {
        const response = await fetch('/static/data/photos.json');
        let photos = await response.json();
        currentPhoto = photos[round - 1];
        document.getElementById('photoImage').src = `/static/photos/${currentPhoto.filename}`;
    } catch (error) {
        console.error('Fehler beim Laden der Fotos:\n', error);
    }
}

function updateRoundDisplay(round) {
    document.getElementById('roundInfo').textContent = `Runde ${round}`;
}

// View-Wechsel (Photo <-> Map)
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


// document.addEventListener('DOMContentLoaded', async () => {
async function initGame() {
    if (map) return;

    const mapEl = document.getElementById('map');
    if (!mapEl) {
        console.warn('initMap: #map nicht gefunden; Abbruch');
        return;
    }

    await init_pocketbase();
    let round = (await getGamestateRecord()).round;
    console.log("Round: ", round)
    await startNextRound(round);

    map = L.map('map', {minZoom: 1, maxZoom: 18})
        .setView([49.3690, 9.5436], 6);


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
            await pushLocation({lat, lng});
        } catch (err) {
            console.error("Failed to push location:", err);
        }

        // Zeige Lock-In Button
        document.getElementById('lockButton').disabled = false;
    });

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
        lockInSolution();

        // Verstecke "Zurück zum Foto" Button
        document.getElementById('backToPhotoButton').style.display = 'none';
    });
// });
}


if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGame);
} else {
    initGame();
}
