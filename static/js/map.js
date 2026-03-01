// Spielzustand
let guessMarker = null;
let targetMarker = null;
let resultLine = null;
let isLocked = false;
let photos = [];
let currentPhotoIndex = 0;
let currentPhoto = null;
let totalRounds = 0;

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
function loadPhoto(index) {
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
        // Leere das Foto-Element sofort, damit altes Foto nicht sichtbar ist
        document.getElementById('photoImage').src = '';
        resetForNextRound();
        loadPhoto(currentPhotoIndex + 1);
        showView('photoView');
    } else {
        // Spiel beendet
        showGameOver();
    }
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

    document.getElementById('restartButton').addEventListener('click', function() {
        // Leere das Foto-Element sofort
        document.getElementById('photoImage').src = '';
        resetForNextRound();
        loadPhoto(0);
        showView('photoView');
        document.getElementById('lockButton').style.display = 'inline-block';
    });
}

// Initialisiere die Karte
const map = L.map('map').setView([49.3690, 9.5436], 6);

// Verwende lokale Tiles
L.tileLayer('/tiles/{z}/{x}/{y}.png', {
    attribution: 'Map data &copy; OpenStreetMap contributors',
    maxZoom: 18,
    minZoom: 3
}).addTo(map);

// Click-Handler für Tipp-Platzierung
map.on('click', function(e) {
    if (isLocked) return; // Kein Verschieben nach Lock-In

    const { lat, lng } = e.latlng;

    // Wenn noch kein Marker gesetzt, erstelle einen
    if (!guessMarker) {
        guessMarker = L.marker([lat, lng], {
            icon: L.icon({
                iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
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
document.getElementById('guessButton').addEventListener('click', function() {
    showView('mapView');
});

document.getElementById('backToPhotoButton').addEventListener('click', function() {
    if (!isLocked) {
        showView('photoView');
    }
});

document.getElementById('nextPhotoButton').addEventListener('click', function() {
    nextPhoto();
});

// Lock-In Button Handler
document.getElementById('lockButton').addEventListener('click', function() {
    if (!guessMarker || isLocked || !currentPhoto) return;

    isLocked = true;
    this.disabled = true;
    this.textContent = 'Eingelockt!';

    // Verwende Location aus aktuellem Foto
    const actualLocation = [currentPhoto.location.lat, currentPhoto.location.lng];

    // Zeige tatsächliche Location
    targetMarker = L.marker(actualLocation, {
        icon: L.icon({
            iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
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

    // Zeichne Linie zwischen Tipp und Ziel
    resultLine = L.polyline([guessMarker.getLatLng(), actualLocation], {
        color: 'red',
        weight: 3,
        opacity: 0.7,
        dashArray: '10, 10'
    }).addTo(map);

    // Zeige Distanz
    const distanceText = distance < 1
        ? `${Math.round(distance * 1000)} Meter`
        : `${distance.toFixed(2)} km`;

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
    map.fitBounds(bounds, { padding: [50, 50] });
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
loadPhotos();

// Initialisiere Foto-Zoom
const photoZoom = new PhotoZoom('photoImage', 'photoContainer', 'resetZoomButton');
