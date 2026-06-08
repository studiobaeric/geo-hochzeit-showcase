// Spielzustand
import {init_pocketbase, pushLockedLocation} from "./multiplayer.js";
import {PhotoZoom} from "./photo.js";

let guessMarker = null;
let targetMarker = null;
let resultLine = null;
let isLocked = false;
let photos = [];
let currentPhotoIndex = 0;
let currentPhoto = null;
let totalRounds = 0;
const gameRole = sessionStorage.getItem('gameRole') || localStorage.getItem('playerName') || 'Jana';
const isModerator = gameRole === 'moderator';

// Score-Tracking
let gameResults = {
    rounds: [],
    totalDistance: 0
};

/*
window.addEventListener("load", function () {
    if (!sessionStorage.getItem("geladen")) {
        init_pocketbase();
        sessionStorage.setItem("geladen", "true");
    }
});

 */

// Lade Foto-Daten
async function loadPhotos() {
    try {
        const response = await fetch('/static/data/photos.json');
        photos = await response.json();
        totalRounds = photos.length;
        if (photos.length > 0) {
            loadPhoto(0);
        }
    } catch (error) {
        console.error('Fehler beim Laden der Fotos:', error);
    }
}

// Lade ein spezifisches Foto
export function loadPhoto(index) {
    if (index >= 0 && index < photos.length) {
        currentPhotoIndex = index;
        currentPhoto = photos[index];
        document.getElementById('photoImage').src = `/static/photos/${currentPhoto.filename}`;
        updateRoundDisplay();
    }
}

// Aktualisiere Rundenanzeigefunction 
function updateRoundDisplay() {
    const roundInfo = `Runde ${currentPhotoIndex + 1} / ${totalRounds}`;
    document.getElementById('roundInfo').textContent = roundInfo;
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
function nextPhoto() {
    if (currentPhotoIndex + 1 < photos.length) {
        photoZoom.reset();
        // Leere das Foto-Element sofort, damit altes Foto nicht sichtbar ist
        document.getElementById('photoImage').src = '';
        resetForNextRound();
        loadPhoto(currentPhotoIndex + 1);
        showView('photoView');
    } else {
        // Spiel beendet - speichere Ergebnisse und navigiere zur Ergebnisseite
        sessionStorage.setItem('gameResults', JSON.stringify(gameResults));
        window.location.href = '/results';
    }
}

function showModeratorPhoto(index) {
    if (index < 0 || index >= photos.length) return;

    photoZoom.reset();
    document.getElementById('photoImage').src = '';
    loadPhoto(index);
    updateModeratorControls();
}

function updateModeratorControls() {
    const prevButton = document.getElementById('moderatorPrevButton');
    const nextButton = document.getElementById('moderatorNextButton');

    prevButton.disabled = currentPhotoIndex === 0;
    nextButton.disabled = currentPhotoIndex + 1 >= photos.length;
}

function initModeratorMode() {
    document.body.classList.add('moderator-mode');
    document.getElementById('photoView').classList.add('active');
    document.getElementById('mapView').classList.add('active');
    document.getElementById('moderatorControls').style.display = 'flex';
    updateModeratorControls();

    setTimeout(() => {
        map.invalidateSize(true);
    }, 250);
}

// Zeige Spiel-Ende Bildschirm
function showGameOver() {
    document.getElementById('result').innerHTML = `
        <h2>Spiel beendet!</h2>
        <p>Du hast alle ${totalRounds} Runden gespielt.</p>
        <button id="restartButton" class="btn-primary">Neu starten</button>
    `;
    document.getElementById('result').style.display = 'block';
    document.getElementById('backToPhotoButton').style.display = 'none';
    document.getElementById('nextPhotoButton').style.display = 'none';
    document.getElementById('lockButton').style.display = 'none';

    document.getElementById('restartButton').addEventListener('click', function () {
        // Leere das Foto-Element sofort
        document.getElementById('photoImage').src = '';
        resetForNextRound();
        loadPhoto(0);
        showView('photoView');
        document.getElementById('lockButton').style.display = 'inline-block';
    });
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
            attribution: 'Map data &copy; OpenStreetMap contributors'
        }).addTo(map);
    })
    .catch((error) => console.error('Fehler beim Laden der Karten-Basemap:', error));

// Click-Handler für Tipp-Platzierung
map.on('click', function(e) {
    if (isModerator) return;
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

document.getElementById('nextPhotoButton').addEventListener('click', function () {
    nextPhoto();
});

document.getElementById('moderatorPrevButton').addEventListener('click', function() {
    showModeratorPhoto(currentPhotoIndex - 1);
});

document.getElementById('moderatorNextButton').addEventListener('click', function() {
    showModeratorPhoto(currentPhotoIndex + 1);
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

    // Berechne Distanz (Haversine-Formel)
    const distance = calculateDistance(
        guessMarker.getLatLng().lat,
        guessMarker.getLatLng().lng,
        actualLocation[0],
        actualLocation[1]
    );

    // Speichere Runden-Ergebnis
    const distanceText = distance < 1
        ? `${Math.round(distance * 1000)} Meter`
        : `${distance.toFixed(2)} km`;

    gameResults.rounds.push({
        roundNumber: currentPhotoIndex + 1,
        description: currentPhoto.description,
        distance: distanceText,
        distanceKm: distance,
        filename: currentPhoto.filename
    });
    gameResults.totalDistance += distance;

    pushLockedLocation(guessMarker.getLatLng(), currentPhotoIndex +1)

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

// Haversine-Formel für Distanzberechnung
function calculateDistance(lat1, lon1, lat2, lon2) {
    const R = 6371; // Erdradius in km
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);

    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
        Math.sin(dLon / 2) * Math.sin(dLon / 2);

    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

function toRad(degrees) {
    return degrees * (Math.PI / 180);
}

// App initialisieren
function resetGame() {
    // Setze alle Werte zurück
    gameResults = {
        rounds: [],
        totalDistance: 0
    };
    guessMarker = null;
    targetMarker = null;
    resultLine = null;
    isLocked = false;
    currentPhotoIndex = 0;
    loadPhoto(0);
    resetForNextRound();
    showView('photoView');
    document.getElementById('lockButton').style.display = 'inline-block';
}

// Initialisiere Foto-Zoom
const photoZoom = new PhotoZoom('photoImage', 'photoContainer', 'resetZoomButton');

loadPhotos().then(() => {
    if (isModerator) {
        initModeratorMode();
    }
});
