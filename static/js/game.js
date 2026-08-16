// Spielzustand
import {getGamestateRecord, initSubscriptions, lockInSolution, pushLocation} from "./multiplayer.js";
import {ensurePmtilesProtocol, createBaseMapLayer, createMarkerIcon} from "./basemap.js";
import {PhotoZoom} from "./photo.js";
import {loadDisplayNames} from "./player-names.js";
import {loadRoundConfig} from "./round-config.js";
import {loadThemeConfig} from "./theme.js";

// Live updates arrive over multiplayer.js's shared /api/events connection
// (see its 'theme_config' listener) rather than a second one here - see
// theme.js's onThemeConfigEvent for why that matters.
loadThemeConfig();

let guessMarker = null;
let isLocked = false;
let currentPhoto = null;
let map = null;
let allPhotos = null;

let roundConfig = { mode: 'manual', duration_seconds: 60 };
let timerState = { running: false, paused: false, ends_at: null, remaining_seconds: null };
const roundTimerElement = document.getElementById('roundTimer');
// game.js is imported (for loadNextRound/updateView) from every role's page via
// multiplayer.js, but #photoContainer only exists on the player's photo view -
// guard the PhotoZoom setup so it's a no-op on the moderator page.
const photoZoom = document.getElementById('photoContainer')
    ? new PhotoZoom('photoImage', 'photoContainer', 'resetZoomButton')
    : null;

// Lade Foto für Runde
export async function loadNextRound(round) {
    resetMap();
    resetButtons();
    await loadPhoto(round);
    updateRoundDisplay(round);
}

export function updateView(state) {
    console.log("Synchronizing current View to Gamestate...")
    if (state === "playing") {
        showView('photoView');
    } else if (state === "waiting") {
        showView('waitView')
    }
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
    document.getElementById('lockButton').textContent = 'Einloggen';
    document.getElementById('backToPhotoButton').style.display = 'inline-block';
    photoZoom?.reset();
}

async function loadPhoto(round) {
    console.log("Loading Photo: " + round);
    try {
        if (!allPhotos) {
            const response = await fetch('/static/config/photos.json');
            if (!response.ok) {
                throw new Error(`Failed to load photos.json: ${response.status}`);
            }
            allPhotos = await response.json();
        }

        currentPhoto = allPhotos[round - 1];
        if (!currentPhoto) {
            throw new Error(`No photo configured for round ${round}`);
        }
        document.getElementById('photoImage').src = `/static/photos/${currentPhoto.filename}`;
    } catch (error) {
        console.error('Fehler beim Laden der Fotos:\n', error);
    }
}

function updateRoundDisplay(round) {
    const totalRounds = allPhotos?.length;
    document.getElementById('roundInfo').textContent = totalRounds
        ? `Runde ${round} / ${totalRounds}`
        : `Runde ${round}`;
}

function formatSeconds(totalSeconds) {
    const clamped = Math.max(0, Math.round(totalSeconds || 0));
    const minutes = Math.floor(clamped / 60);
    const seconds = clamped % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function computeRemainingSeconds() {
    if (timerState.paused) return timerState.remaining_seconds ?? 0;
    if (timerState.running) return Math.max(0, (timerState.ends_at ?? 0) - (Date.now() / 1000));
    return roundConfig.duration_seconds;
}

// Renders the moderator-synced countdown (see game_state.py's /api/timer)
// next to the round indicator. Hidden entirely in manual mode, or before
// the moderator has pressed Start for the current round.
function renderRoundTimer() {
    if (!roundTimerElement) return;

    const shouldShow = roundConfig.mode === 'countdown' && timerState.running;
    roundTimerElement.classList.toggle('is-hidden', !shouldShow);
    if (!shouldShow) return;

    const remaining = computeRemainingSeconds();
    roundTimerElement.textContent = formatSeconds(remaining);
    roundTimerElement.classList.toggle('is-urgent', !timerState.paused && remaining <= 10);
}

export function onRoundConfigUpdate(record) {
    roundConfig = record;
    renderRoundTimer();
}

export function onTimerUpdate(record) {
    timerState = record;
    renderRoundTimer();
}

// View-Wechsel (Wait <-> Photo <-> Map)
function showView(viewName) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    console.log("Showing View: ", document.getElementById(viewName))
    document.getElementById(viewName).classList.add('active');

    // Zeige/verstecke photoControls basierend auf aktiver View
    const photoControls = document.getElementById('photoControls');
    photoControls.classList.remove('active');

    console.log("Showing View: ", viewName)

    if (viewName == 'photoView') {
        photoControls.classList.add('active');
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


async function initGame() {
    if (sessionStorage.getItem("name") === null) {
        window.location.href = "/";
        return;
    }

    if (map) return;

    const mapEl = document.getElementById('map');
    if (!mapEl) {
        console.warn('initGame: #game nicht gefunden; Abbruch');
        return;
    }

    await loadDisplayNames();

    roundConfig = await loadRoundConfig();
    renderRoundTimer();
    setInterval(renderRoundTimer, 250);

    await initSubscriptions();

    let gamestateRecord = await getGamestateRecord();
    console.log("Gamestate: ", gamestateRecord);
    await loadNextRound(gamestateRecord.round);
    updateView(gamestateRecord.state)

    map = L.map('map', {minZoom: 1, maxZoom: 18})
        .setView([49.3690, 9.5436], 6);


    // Vektor-Basemap (MapLibre GL) aus lokaler PMTiles-Datei - komplett offline.
    // PMTiles wird per HTTP-Range-Request gelesen, die Datei landet nie komplett im RAM.
    ensurePmtilesProtocol();

    // MapLibre v5 verlangt absolute URLs fuer sprite/glyphs/Source; createBaseMapLayer()
    // setzt sie zur Laufzeit aus location.origin zusammen, damit die App auf jedem
    // Host/Port (und damit komplett offline) funktioniert, ohne hartkodierte Adresse.
    createBaseMapLayer({interactive: true})
        .then((baseMapLayer) => {
            baseMapLayer.addTo(map);
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
                icon: createMarkerIcon('/static/img/marker-icon-2x-blue.png')
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
        this.textContent = 'Eingeloggt!';
        lockInSolution();

        // Verstecke "Zurück zum Foto" Button
        document.getElementById('backToPhotoButton').style.display = 'none';
    });
}

if (!(sessionStorage.getItem("name") === "Moderator")) {

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initGame);
    } else {
        initGame();
    }
}
