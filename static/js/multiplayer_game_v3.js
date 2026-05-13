/**
 * Synchronisiertes Multiplayer-Geoguesser v3
 * FIXES:
 * 1. Server speichert Tipps persistent
 * 2. Korrekte Logik bei Rundenwechsel
 * 3. Timer funktioniert zuverlässig
 * 4. Bild wird immer angezeigt
 * 5. Fehlerbehandlung auf allen Ebenen
 */

// ============== GLOBALE VARIABLEN ==============

let gameId = sessionStorage.getItem('gameId');
let playerId = sessionStorage.getItem('playerId');
let playerName = sessionStorage.getItem('playerName');
let isMultiplayer = sessionStorage.getItem('isMultiplayer') === 'true';

// Spiel-State
let map = null;
let guessMarker = null;
let currentRound = 1;
let totalRounds = 5;
let hasSubmitted = false;
let roundStatus = null;
let socket = null;
let showingResults = false;
let allPhotos = [];
let allPlayerMarkers = {};
let countdownInterval = null;
let countdownSeconds = 0;
let statusCheckInterval = null;

// ============== HAUPTINITIALISIERUNG ==============

async function initializeGame() {
    console.log('=== MULTIPLAYER GAME V3 INITIALISIERT ===');

    // Validiere Session
    if (!isMultiplayer || !gameId || !playerId) {
        console.error('❌ FEHLER: Keine gültigen Session-Daten!');
        alert('Fehler: Bitte über die Startseite ein Spiel beitreten');
        window.location.href = '/';
        return;
    }

    console.log('✅ Session-Daten validiert');
    console.log('   Game-ID:', gameId);
    console.log('   Player-ID:', playerId);
    document.getElementById('playerIdDisplay').textContent = playerId.substring(0, 8) + '...';

    // Verbinde Socket
    setupSocket();

    // Initialisiere Karte
    initializeMap();

    // Lade Spieldaten
    await loadGameData();

    console.log('✅ Spiel initialisiert, starte Status-Checks');

    // Starte regelmäßige Status-Checks
    statusCheckInterval = setInterval(checkRoundStatus, 1000);
}

// ============== SOCKET SETUP ==============

function setupSocket() {
    socket = io();

    socket.on('connect', () => {
        console.log('✅ WebSocket verbunden, trete Raum bei');
        socket.emit('join_game_room', {
            game_id: gameId,
            player_id: playerId
        });
    });

    socket.on('all_players_ready', (data) => {
        console.log('🎯 WEBSOCKET EVENT: all_players_ready', data);
        if (!showingResults) {
            console.log('   → Zeige Ergebnisse');
            showingResults = true;
            showRoundResults(data);
        }
    });

    socket.on('round_started', (data) => {
        console.log('🔄 WEBSOCKET EVENT: round_started', data);
        startNextRound(data.round_number);
    });

    socket.on('game_ended', (data) => {
        console.log('🏁 WEBSOCKET EVENT: game_ended');
        setTimeout(() => {
            sessionStorage.setItem('gameResults', JSON.stringify(data));
            window.location.href = `/results?gameId=${gameId}`;
        }, 500);
    });

    socket.on('disconnect', () => {
        console.warn('⚠️ WebSocket disconnected');
    });
}

// ============== KARTEN-INITIALISIERUNG ==============

function initializeMap() {
    map = L.map('map').setView([49.5, 9.5], 6);

    L.tileLayer('/tiles/{z}/{x}/{y}.png', {
        attribution: 'Map data &copy; OpenStreetMap contributors',
        maxZoom: 18,
        minZoom: 2
    }).addTo(map);

    // Click-Handler für Tipp-Platzierung
    map.on('click', function(e) {
        if (hasSubmitted || showingResults) {
            console.log('⚠️ Kann nicht tippen: hasSubmitted=' + hasSubmitted + ', showingResults=' + showingResults);
            return;
        }

        const { lat, lng } = e.latlng;
        console.log('📍 Marker gesetzt auf:', lat, lng);

        if (!guessMarker) {
            guessMarker = L.marker([lat, lng], {
                icon: getMarkerIcon('blue')
            }).addTo(map);
            guessMarker.bindPopup('Dein Tipp');
        } else {
            guessMarker.setLatLng([lat, lng]);
        }

        document.getElementById('submitButton').disabled = false;
    });

    console.log('✅ Karte initialisiert');
}

function getMarkerIcon(color) {
    const colors = {
        'blue': 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
        'green': 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
        'red': 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
        'orange': 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-orange.png',
        'yellow': 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-yellow.png',
        'purple': 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-purple.png',
        'pink': 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-pink.png'
    };

    return L.icon({
        iconUrl: colors[color] || colors['blue'],
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    });
}

// ============== SPIELDATEN LADEN ==============

async function loadGameData() {
    try {
        const response = await fetch(`/api/game/${gameId}/state`);
        const data = await response.json();

        if (data.success) {
            allPhotos = data.state.photos;
            totalRounds = allPhotos.length;
            console.log('✅ Fotos geladen:', totalRounds, 'Runden');

            // Lade erstes Foto
            loadPhotoForRound(currentRound);
            await loadRoundStatus();
        }
    } catch (error) {
        console.error('❌ Fehler beim Laden der Spieldaten:', error);
    }
}

function loadPhotoForRound(roundNumber) {
    if (allPhotos && allPhotos.length >= roundNumber) {
        const photo = allPhotos[roundNumber - 1];
        const photoPath = `/static/photos/${photo.filename}`;
        console.log('📷 Lade Foto für Runde', roundNumber, ':', photo.filename);

        const photoImg = document.getElementById('photoImage');
        photoImg.src = photoPath;
        photoImg.onerror = () => {
            console.error('❌ Foto konnte nicht geladen werden:', photoPath);
            photoImg.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="400" height="300"%3E%3Crect fill="%23f0f0f0" width="400" height="300"/%3E%3Ctext x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%23999" font-size="16"%3EFoto nicht gefunden%3C/text%3E%3C/svg%3E';
        };
    } else {
        console.error('❌ Foto für Runde', roundNumber, 'nicht in Array');
    }
}

// ============== RUNDEN-STATUS ==============

async function loadRoundStatus() {
    try {
        const response = await fetch(`/api/game/${gameId}/round/status`);
        const data = await response.json();

        if (data.success) {
            roundStatus = data.status;
            console.log('📊 Runden-Status geladen:', roundStatus);
            updateUI();
        }
    } catch (error) {
        console.error('❌ Fehler beim Laden des Runden-Status:', error);
    }
}

async function checkRoundStatus() {
    try {
        const response = await fetch(`/api/game/${gameId}/round/status`);
        const data = await response.json();

        if (!data.success) {
            return;
        }

        const oldStatus = roundStatus;
        roundStatus = data.status;

        // Debug: Neue Tipps eingegeben
        if (roundStatus.guesses_submitted !== oldStatus?.guesses_submitted) {
            console.log(`📊 TIPPS: ${roundStatus.guesses_submitted}/${roundStatus.total_players}`);
        }

        updateUI();

        // KRITISCH: Prüfe ob alle fertig sind
        const allReady = roundStatus.all_ready === true;
        const iSubmitted = hasSubmitted === true;
        const notShowingResults = !showingResults;

        if (allReady && iSubmitted && notShowingResults) {
            console.log('✅ TRIGGER: Alle fertig! Zeige Ergebnisse');
            showingResults = true;

            try {
                await showRoundResults(roundStatus);
            } catch (err) {
                console.error('❌ Fehler in showRoundResults():', err);
                showingResults = false;
            }
        }
    } catch (error) {
        console.error('❌ Fehler in checkRoundStatus:', error);
    }
}

// ============== UI UPDATES ==============

function updateUI() {
    if (!roundStatus) return;

    const { guesses_submitted, total_players, all_ready, players_remaining } = roundStatus;

    // Update Round-Display
    document.getElementById('roundDisplay').textContent = `Runde ${currentRound}/${totalRounds}`;
    document.getElementById('roundInfo').textContent = `${guesses_submitted}/${total_players} Spieler bereit`;

    // Update Status-Text
    let statusText = '';
    if (hasSubmitted) {
        statusText = all_ready ? '✅ ALLE TIPPS EINGEGEBEN!' : `⏳ Warten auf ${players_remaining} Spieler...`;
    } else {
        statusText = `Tippe auf die Karte (${players_remaining}/${total_players} andere spielen noch)`;
    }
    document.getElementById('statusText').textContent = statusText;

    // Update Button
    const submitBtn = document.getElementById('submitButton');
    submitBtn.disabled = !guessMarker || hasSubmitted;

    // Update Player-List
    const playerListDiv = document.getElementById('playerList');
    playerListDiv.innerHTML = `<span style="font-size: 0.85em; color: #999;">${guesses_submitted}/${total_players} bereit</span>`;
}

// ============== TIPPS ABGEBEN ==============

async function submitGuess() {
    if (!guessMarker || hasSubmitted) return;

    const latlng = guessMarker.getLatLng();
    const submitBtn = document.getElementById('submitButton');

    try {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Wird gespeichert...';

        console.log('📤 Sende Tipp für Runde', currentRound);

        const response = await fetch(`/api/game/${gameId}/guess`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                player_id: playerId,
                round_number: currentRound,
                latitude: latlng.lat,
                longitude: latlng.lng
            })
        });

        const data = await response.json();
        console.log('📡 Server Response:', data);

        if (data.success) {
            hasSubmitted = true;
            submitBtn.textContent = '✅ Tipp gespeichert';

            const statusMsg = document.getElementById('statusMessage');
            statusMsg.textContent = '⏳ Warten auf andere Spieler...';
            statusMsg.style.display = 'block';

            console.log('✅ TIPP AUF SERVER GESPEICHERT - Distanz:', data.distance_km, 'km');

            updateUI();

            // Der Tipp ist jetzt persistent auf dem Server!
        } else {
            console.error('❌ Server-Fehler:', data.error);
            alert('Fehler: ' + data.error);
            submitBtn.disabled = false;
            submitBtn.textContent = '📍 Tipp abgeben';
        }
    } catch (error) {
        console.error('❌ Fehler beim Senden des Tipps:', error);
        alert('Fehler beim Speichern des Tipps');
        submitBtn.disabled = false;
        submitBtn.textContent = '📍 Tipp abgeben';
    }
}

// ============== ERGEBNIS-ANZEIGE ==============

async function showRoundResults(status) {
    try {
        console.log('📊 LADE ERGEBNISSE FÜR RUNDE', status.round_number);

        const response = await fetch(`/api/game/${gameId}/round/${status.round_id}`);
        const data = await response.json();

        if (!data.success) {
            console.error('❌ Runden-Details nicht geladen');
            return;
        }

        const roundData = data.round_data;
        console.log('✅ Ergebnisse geladen mit', roundData.guesses.length, 'Tipps');

        // Lösche alte Marker
        clearMap();
        allPlayerMarkers = {};

        // Zeige Spieler-Tipps
        if (roundData.guesses && Array.isArray(roundData.guesses)) {
            roundData.guesses.forEach(guess => {
                const marker = L.marker([guess.latitude, guess.longitude], {
                    icon: getMarkerIcon(guess.player_color || 'blue')
                }).addTo(map);

                marker.bindPopup(`<b>${guess.player_name}</b><br/>${guess.distance_km.toFixed(2)} km`);
                allPlayerMarkers[guess.player_id] = marker;

                console.log(`   📍 ${guess.player_name}: ${guess.distance_km.toFixed(2)} km`);
            });
        }

        // Zeige korrekte Position
        if (roundData.actual_location) {
            const targetMarker = L.marker([roundData.actual_location.lat, roundData.actual_location.lng], {
                icon: getMarkerIcon('green')
            }).addTo(map);
            targetMarker.bindPopup('✅ Korrekte Position');
            console.log(`   ✅ Korrekte Position: ${roundData.actual_location.lat}, ${roundData.actual_location.lng}`);
        }

        // Zoome auf alle Marker
        const bounds = L.latLngBounds();
        Object.values(allPlayerMarkers).forEach(marker => bounds.extend(marker.getLatLng()));
        if (roundData.actual_location) {
            bounds.extend([roundData.actual_location.lat, roundData.actual_location.lng]);
        }
        if (bounds.isValid()) {
            map.fitBounds(bounds, { padding: [50, 50] });
        }

        console.log('✅ Starte Countdown (10 Sekunden)');
        startCountdown();

    } catch (error) {
        console.error('❌ Fehler in showRoundResults:', error);
        showingResults = false;
    }
}

// ============== COUNTDOWN ==============

function startCountdown() {
    console.log('⏱️ COUNTDOWN STARTET');

    countdownSeconds = 10;
    showCountdownMessage();

    if (countdownInterval) clearInterval(countdownInterval);

    countdownInterval = setInterval(() => {
        countdownSeconds--;
        showCountdownMessage();

        if (countdownSeconds <= 0) {
            clearInterval(countdownInterval);
            console.log('⏱️ COUNTDOWN BEENDET - STARTE PROGRESSION');
            progressToNextRound();
        }
    }, 1000);
}

function showCountdownMessage() {
    const statusMsg = document.getElementById('statusMessage');
    statusMsg.innerHTML = `
        <div style="font-size: 1.2em; font-weight: bold;">📊 Ergebnisse dieser Runde</div>
        <div style="font-size: 3.5em; margin: 15px 0; color: #667eea; font-weight: bold;">${countdownSeconds}</div>
        <div style="font-size: 0.95em;">Nächstes Bild in ${countdownSeconds} ${countdownSeconds === 1 ? 'Sekunde' : 'Sekunden'}...</div>
    `;
    statusMsg.style.display = 'block';
}

// ============== RUNDENWECHSEL ==============

async function progressToNextRound() {
    try {
        console.log('🔄 STARTE PROGRESSION ZUR NÄCHSTEN RUNDE');

        const response = await fetch(`/api/game/${gameId}/round/next`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        if (!response.ok) {
            console.error('❌ HTTP Error:', response.status);
            return;
        }

        const data = await response.json();
        console.log('🔄 Progression Response:', data);

        if (data.success && data.has_next) {
            console.log('✅ Nächste Runde wird gestartet (via WebSocket)');
            // WebSocket 'round_started' Event wird automatisch gesendet
        } else if (data.success && !data.has_next) {
            console.log('🏁 SPIEL BEENDET');
            sessionStorage.setItem('gameResults', JSON.stringify(data.results));
            window.location.href = `/results?gameId=${gameId}`;
        } else {
            console.error('❌ Progression fehlgeschlagen:', data);
        }
    } catch (error) {
        console.error('❌ Fehler in progressToNextRound:', error);
    }
}

function startNextRound(roundNumber) {
    console.log('🔄 STARTE NÄCHSTE RUNDE:', roundNumber);

    // Reset State
    hasSubmitted = false;
    showingResults = false;
    currentRound = roundNumber;
    countdownSeconds = 0;
    if (countdownInterval) clearInterval(countdownInterval);

    // Aufräumen
    clearMap();

    // Lade Foto
    loadPhotoForRound(currentRound);

    // Aktualisiere UI
    updateUI();

    // Lade Status
    loadRoundStatus();

    console.log('✅ Runde', currentRound, 'bereit');
}

// ============== HILFS-FUNKTIONEN ==============

function clearMap() {
    Object.values(allPlayerMarkers).forEach(marker => {
        try {
            map.removeLayer(marker);
        } catch (e) {}
    });
    allPlayerMarkers = {};

    if (guessMarker) {
        try {
            map.removeLayer(guessMarker);
        } catch (e) {}
        guessMarker = null;
    }

    const statusMsg = document.getElementById('statusMessage');
    statusMsg.style.display = 'none';
    statusMsg.innerHTML = '';
}

// ============== START ==============

window.addEventListener('load', initializeGame);

