import {
    unlockPlayerInput, startNextRound, lockPlayerInput, resetGameState, getGamestateRecord,
    initSubscriptions, getPlacedPoints, getRoundResults, postRoundResult,
    getTimerState, startTimer, pauseTimer, resumeTimer, extendTimer, stopTimer, serverNow, finishGame
} from './multiplayer.js';
import { getPhotoFilenames, loadPhotoFilenames } from './player-photos.js';
import { getDisplayNames, loadDisplayNames } from './player-names.js';
import { ensurePmtilesProtocol, createBaseMapLayer, createMarkerIcon, formatDistance } from './basemap.js';
import { loadRoundConfig } from './round-config.js';
import { loadThemeConfig } from './theme.js';
import { loadMapLabelsConfig } from './map-labels-config.js';
import { loadScoringConfig, getScoringConfig, calculateRoundPoints } from './scoring-config.js';
import { confirmDialog } from './confirm-dialog.js';
import { t, tf } from './i18n.js';

// Live updates arrive over multiplayer.js's shared /api/events connection
// (see its 'theme_config'/'map_labels_config' listeners) rather than a
// second one here - see theme.js's onThemeConfigEvent for why that matters.
loadThemeConfig();
loadMapLabelsConfig();

const currentPhotoImage = document.getElementById('currentPhotoImage');
const currentPhotoFallback = document.getElementById('currentPhotoFallback');
const moderatorApp = document.getElementById('moderatorApp');
const resolutionView = document.getElementById('resolutionView');
const resolutionMapElement = document.getElementById('resolutionMap');
const mainControlButton = document.getElementById('mainControlButton');

const roundIndicator = document.getElementById("currentRound");

const lockPlayerInputButton = document.getElementById('lockPlayerInputButton');
const continueButton = document.getElementById('continueButton');
const resetGameButton = document.getElementById('resetGameButton');
const resultContinueButton = document.getElementById('resultContinueButton');

const timeControlPanel = document.getElementById('timeControlPanel');
const countdownControls = document.getElementById('countdownControls');
const countdownDisplay = document.getElementById('countdownDisplay');
const timerStartButton = document.getElementById('timerStartButton');
const timerPauseButton = document.getElementById('timerPauseButton');
const timerExtendButton = document.getElementById('timerExtendButton');

const roundResultView = document.getElementById('roundResultView');
const playerPointElements = {
    player1: document.getElementById('player1CurrentPoints'),
    player2: document.getElementById('player2CurrentPoints')
};
const resolutionDistanceElements = {
    player1: document.getElementById('player1ResolutionDistance'),
    player2: document.getElementById('player2ResolutionDistance')
};
const playerMapElements = {
    player1: document.getElementById('leftPlayerMap'),
    player2: document.getElementById('rightPlayerMap')
};

let currentPhoto = null;
let resolutionMap = null;
let locationMarker = null;
let baseMapLayer = null;
let resolutionPlayerMarkers = {};
let latestPlayerRecords = {};

let leftPlayerMap = null;
let rightPlayerMap = null;
let leftPlayerMarker = null;
let rightPlayerMarker = null;

let round = 0;
let playerInputLocked = false;
let photos = {};
let currentGameState = 'waiting';

let roundConfig = { mode: 'manual', duration_seconds: 60, extend_seconds: 30 };
let timerState = { running: false, paused: false, ends_at: null, remaining_seconds: null };
let autoStoppedForRound = false;
// Whether the countdown has already been started once for the current round -
// keeps Start disabled (rather than clickable again) after it stops, so the
// moderator can't accidentally re-open player input for a round already in
// progress (#101).
let timerStartedForRound = false;
let playerLockedIn = { player1: false, player2: false };

// latestPlayerRecords/resolutionPlayerMarkers are plain objects, not Maps -
// they must be reassigned/removed explicitly, a bare `.clear` call is a
// silent no-op and leaves stale guesses from the previous round/game around.
function clearRoundRecords() {
    latestPlayerRecords = {};
    Object.values(resolutionPlayerMarkers).forEach((marker) => {
        marker.line?.remove();
        marker.remove();
    });
    resolutionPlayerMarkers = {};
}

// The server-persisted round results are the source of truth for the score
// (see game_state.py's `/api/round_result`), so a moderator page refresh -
// or the whole process restarting - can rebuild pointByName from there
// instead of relying on this browser's sessionStorage.
async function restoreScoreState() {
    resultCollection = {};
    pointByName = {player1: 0, player2: 0};

    try {
        const roundResults = await getRoundResults();
        roundResults.forEach((roundResult) => {
            resultCollection[roundResult.round_number] = roundResult;
            Object.entries(roundResult.players || {}).forEach(([playerName, playerResult]) => {
                pointByName[playerName] = (pointByName[playerName] || 0) + Number(playerResult.points || 0);
            });
        });
    } catch (error) {
        console.error('Could not restore round results from server:', error);
    }
}

async function hydratePlacedPoints() {
    try {
        const records = await getPlacedPoints(round);
        for (const record of records) {
            await updateMapPosition(record);
        }
    } catch (error) {
        console.error('Could not restore placed points for current round:', error);
    }
}

function applyDisplayNames() {
    const names = getDisplayNames();
    const photoFilenames = getPhotoFilenames();

    const player1ScoreName = document.getElementById('player1ScoreName');
    if (player1ScoreName) player1ScoreName.textContent = names.player1;

    const player2ScoreName = document.getElementById('player2ScoreName');
    if (player2ScoreName) player2ScoreName.textContent = names.player2;

    // Full resolution here too - this is the moderator's beamer-projected
    // screen, not a player's tablet, so the downscaled copy would look soft.
    const player1Photo = document.getElementById('player1Photo');
    if (player1Photo) {
        player1Photo.alt = `${t('moderator.player_photo_alt_prefix')}${names.player1}`;
        player1Photo.src = `/static/photos/${photoFilenames.player1_hq}`;
    }

    const player2Photo = document.getElementById('player2Photo');
    if (player2Photo) {
        player2Photo.alt = `${t('moderator.player_photo_alt_prefix')}${names.player2}`;
        player2Photo.src = `/static/photos/${photoFilenames.player2_hq}`;
    }

    if (resolutionDistanceElements.player1) resolutionDistanceElements.player1.textContent = `${names.player1}: -`;
    if (resolutionDistanceElements.player2) resolutionDistanceElements.player2.textContent = `${names.player2}: -`;

    const resultRowNamePlayer1 = document.getElementById('resultRowNamePlayer1');
    if (resultRowNamePlayer1) resultRowNamePlayer1.textContent = names.player1;

    const resultRowNamePlayer2 = document.getElementById('resultRowNamePlayer2');
    if (resultRowNamePlayer2) resultRowNamePlayer2.textContent = names.player2;
}

await loadDisplayNames();
await loadPhotoFilenames();
applyDisplayNames();

let pointByName = {
    player1: 0,
    player2: 0
};

let resultCollection = {};

const playerStyles = {
        player1: {
            iconUrl: '/static/img/marker-icon-2x-blue.png',
            lineColor: '#2563eb'
        },
        player2: {
            iconUrl: '/static/img/marker-icon-2x-red.png',
            lineColor: '#dc2626'
        }
};

function getPlayerStyles(){
    return playerStyles;
}

function getEndScore(){
    return pointByName;
}

// aufrufen mit neuer nummer für neues photo
async function loadCurrentPhoto(photo=round) {
    if (!currentPhotoImage || !currentPhotoFallback) return;

    try {
        currentPhoto = photos[photo-1];

        if (!currentPhoto) return;

        // Prefer the untouched full-resolution copy for the beamer-projected
        // display - the default `filename` is downscaled for players/tablets
        // and would look soft blown up on a projector. Older photos.json
        // entries (from before filename_hq existed) fall back to it.
        currentPhotoImage.src = `/static/photos/${currentPhoto.filename_hq || currentPhoto.filename}`;
    } catch (error) {
        console.error('Moderator photo could not be loaded:', error);
    } finally {
        updatePhotoVisibility();
    }
}

// Mirrors the player view: the round's photo only appears on the moderator
// page once the round is actually running (state "playing"), not the
// instant it's loaded/preloaded - matches #16's "image is shown only after
// the start" requirement.
function updatePhotoVisibility() {
    if (!currentPhotoImage || !currentPhotoFallback) return;

    const shouldShow = currentGameState === 'playing' && Boolean(currentPhoto);
    currentPhotoImage.classList.toggle('is-loaded', shouldShow);
    currentPhotoFallback.classList.toggle('is-hidden', shouldShow);

    if (!shouldShow) {
        currentPhotoFallback.textContent = currentGameState === 'waiting'
            ? t('moderator.waiting_for_start')
            : t('moderator.current_photo_fallback');
    }
}

function formatSeconds(totalSeconds) {
    const clamped = Math.max(0, Math.round(totalSeconds || 0));
    const minutes = Math.floor(clamped / 60);
    const seconds = clamped % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function computeRemainingSeconds() {
    if (timerState.paused) return timerState.remaining_seconds ?? 0;
    if (timerState.running) return Math.max(0, (timerState.ends_at ?? 0) - serverNow());
    // Not running and not paused is ambiguous by itself - it's both the
    // "before Start" state (should preview the full round duration) and the
    // "round is over" state after a timeout/both-locked-in/manual resolve
    // stopped the timer (should read 0, not jump back up to the full
    // duration, until the next round resets timerStartedForRound) (#101).
    if (timerStartedForRound) return 0;
    return roundConfig.duration_seconds;
}

function renderTimeControlPanel() {
    if (!timeControlPanel) return;

    const isCountdownMode = roundConfig.mode === 'countdown';
    lockPlayerInputButton?.classList.toggle('is-hidden', isCountdownMode);
    countdownControls?.classList.toggle('is-hidden', !isCountdownMode);

    if (!isCountdownMode) return;

    const remaining = computeRemainingSeconds();
    if (countdownDisplay) countdownDisplay.textContent = formatSeconds(remaining);
    countdownControls.classList.toggle('is-urgent', timerState.running && !timerState.paused && remaining <= 10);

    timerStartButton?.classList.toggle('is-hidden', timerState.running);
    if (timerStartButton) timerStartButton.disabled = timerStartedForRound;
    timerPauseButton?.classList.toggle('is-hidden', !timerState.running);
    timerExtendButton?.classList.toggle('is-hidden', !timerState.running);
    if (timerPauseButton) timerPauseButton.textContent = timerState.paused ? t('moderator.resume_button') : t('moderator.pause_button');
    if (timerExtendButton) timerExtendButton.textContent = `+${roundConfig.extend_seconds}s`;
}

// Ends the round: locks player input so guesses stop, and (in countdown
// mode) stops the timer. Triggered either by the countdown reaching 0, both
// players locking in, or the moderator's manual "Runde auflösen" click.
async function lockRoundInput() {
    // Always lock, never toggle - if the moderator had already locked player
    // input manually before pressing "Runde auflösen", toggling would flip it
    // back to unlocked and let players guess again on the round being
    // resolved (#66).
    await lockPlayerInput();

    if (roundConfig.mode === 'countdown') {
        try {
            await stopTimer();
        } catch (error) {
            console.error('Could not stop timer:', error);
        }
    }
}

// Only the moderator's manual "Runde auflösen" click reveals the solution
// view - the countdown reaching 0 (or both players locking in early, see
// maybeAutoStopTimer) stops the timer and locks input, but leaves showing
// the solution up to the moderator, who may want to moderate/discuss the
// round first (#101).
async function triggerResolution() {
    showResolutionView();
    await lockRoundInput();
}

// Guarded by autoStoppedForRound so a slow network response or a couple of
// overlapping ticks can't fire it twice for the same round. Stops the timer
// early once both players have locked in their guess, since there's nothing
// left to count down for (#101).
async function maybeAutoStopTimer() {
    if (roundConfig.mode !== 'countdown') return;
    if (!timerState.running || timerState.paused) return;
    if (autoStoppedForRound) return;
    if (currentGameState !== 'playing') return;

    const timeIsUp = computeRemainingSeconds() <= 0;
    const bothPlayersLockedIn = playerLockedIn.player1 && playerLockedIn.player2;
    if (!timeIsUp && !bothPlayersLockedIn) return;

    autoStoppedForRound = true;
    await lockRoundInput();
}

export function onRoundConfigUpdate(record) {
    roundConfig = record;
    renderTimeControlPanel();
}

export function onTimerUpdate(record) {
    timerState = record;
    renderTimeControlPanel();
    maybeAutoStopTimer();
}

function getRecordLatLng(record) {
    const lat = Number(record?.coordinates?.lat);
    const lng = Number(record?.coordinates?.lon ?? record?.coordinates?.lng);

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return null;
    }

    return [lat, lng];
}

function getPlayerTarget(record) {
    const role = getPlayerRole(record);

    if (role === 'player1') {
        return {
            map: leftPlayerMap,
            marker: leftPlayerMarker,
            setMarker: (marker) => {
                leftPlayerMarker = marker;
            },
            label: getDisplayNames().player1
        };
    }

    if (role === 'player2') {
        return {
            map: rightPlayerMap,
            marker: rightPlayerMarker,
            setMarker: (marker) => {
                rightPlayerMarker = marker;
            },
            label: getDisplayNames().player2
        };
    }

    return null;
}

function getPlayerRole(record) {
    const role = String(record?.placed_by || '').trim();
    return role === 'player1' || role === 'player2' ? role : undefined;
}

// Guesses (placed_points) are keyed by round_number = the 1-based position
// in photos.json (see multiplayer.js's pushLocation, which sends
// gamestateRecord.round). That is NOT the same number space as
// currentPhoto.id: ids are assigned once and never reused/renumbered (see
// photo_config.py), so they drift out of sync with position as soon as a
// photo is deleted or the round order is changed (/config's up/down
// sorting, #51) - comparing against currentPhoto.id here would silently
// discard every guess for a round with reordered/renumbered photos.
function isCurrentPhotoRecord(record) {
    if (!round) return true;

    return Number(record?.round_number) === Number(round);
}

function updateResolutionDistanceDisplay(role, distanceMeters) {
    const distanceElement = resolutionDistanceElements[role];
    if (!distanceElement) return;

    const displayName = getDisplayNames()[role] ?? role;
    distanceElement.textContent = `${displayName}: ${formatDistance(distanceMeters)}`;
}

function syncResolutionPlayerMarkers() {
    if (!resolutionMap) return;

    const photoLatLng = currentPhoto?.location
        ? [currentPhoto.location.lat, currentPhoto.location.lng]
        : null;
    const visiblePositions = photoLatLng ? [photoLatLng] : [];


    Object.entries(latestPlayerRecords).forEach(([role, record]) => {
        const latLng = getRecordLatLng(record);
        if (!latLng || !role) return;

        const playerStyle = playerStyles[role] ?? playerStyles.player1;
        visiblePositions.push(latLng);

        if (resolutionPlayerMarkers[role]) {
            resolutionPlayerMarkers[role].setLatLng(latLng);
            if (photoLatLng) {
                const distanceMeters = L.latLng(latLng).distanceTo(L.latLng(photoLatLng));

                resolutionPlayerMarkers[role].line?.setLatLngs([latLng, photoLatLng]);
                updateResolutionDistanceDisplay(role, distanceMeters);
            }
            return;
        }

        const marker = L.marker(latLng, {
            icon: createMarkerIcon(playerStyle.iconUrl)
        }).addTo(resolutionMap);

        const displayName = getDisplayNames()[role] ?? role;
        marker.bindPopup(displayName);
        marker.bindTooltip(displayName, {
            permanent: true,
            direction: 'top',
            offset: [0, -35],
            className: 'player-name-tooltip'
        });

        if (photoLatLng) {
            const distanceMeters = L.latLng(latLng).distanceTo(L.latLng(photoLatLng));

            marker.line = L.polyline([latLng, photoLatLng], {
                color: playerStyle.lineColor,
                weight: 3,
                opacity: 0.8,
                dashArray: '8 8'
            }).addTo(resolutionMap);

            updateResolutionDistanceDisplay(role, distanceMeters);
        }

        resolutionPlayerMarkers[role] = marker;
    });

    if (visiblePositions.length > 1) {
        resolutionMap.fitBounds(L.latLngBounds(visiblePositions), {padding: [50, 50]});
    }
}

export async function updateMapPosition(record) {
    const role = getPlayerRole(record);

    // Ignore guesses that belong to a round we've already moved past (e.g. a
    // late-arriving event, or leftover data from before a game reset) - they
    // must never silently count towards the current round's score.
    if (!role || !isCurrentPhotoRecord(record)) return;

    latestPlayerRecords[role] = record;


    if (!leftPlayerMap || !rightPlayerMap) {
        await initModeratorMaps();
    }

    const latLng = getRecordLatLng(record);
    const target = getPlayerTarget(record);

    if (!latLng || !target?.map) return;

    if (target.marker) {
        target.marker.setLatLng(latLng);
    } else {
        const marker = L.marker(latLng, {
            icon: createMarkerIcon(playerStyles[role].iconUrl)
        }).addTo(target.map);

        marker.bindPopup(tf('moderator.player_guess_label', { name: target.label }));
        target.setMarker(marker);
    }

    target.map.setView(latLng, Math.max(target.map.getZoom(), 8));
}

// Germany overview - what each player map starts at, and what it should
// return to once a round's guess marker is cleared (see
// showModPageNextRound()), rather than staying zoomed in on the last guess.
const INITIAL_PLAYER_MAP_CENTER = [49.3690, 9.5436];
const INITIAL_PLAYER_MAP_ZOOM = 5;

function createPlayerMap(elementId) {
    return L.map(elementId, {
        minZoom: 1,
        maxZoom: 18,
        zoomControl: true
    }).setView(INITIAL_PLAYER_MAP_CENTER, INITIAL_PLAYER_MAP_ZOOM);
}

async function initModeratorMaps() {
    if (leftPlayerMap && rightPlayerMap) return;
    if (!document.getElementById('leftPlayerMap') || !document.getElementById('rightPlayerMap')) return;

    ensurePmtilesProtocol();

    leftPlayerMap = createPlayerMap('leftPlayerMap');
    rightPlayerMap = createPlayerMap('rightPlayerMap');

    const leftBaseMapLayer = await createBaseMapLayer();
    const rightBaseMapLayer = await createBaseMapLayer();

    leftBaseMapLayer.addTo(leftPlayerMap);
    rightBaseMapLayer.addTo(rightPlayerMap);

    setTimeout(() => {
        leftPlayerMap.invalidateSize(true);
        rightPlayerMap.invalidateSize(true);
    }, 200);
}

async function initResolutionMap() {
    if (resolutionMap || !currentPhoto?.location) return;

    const {lat, lng} = currentPhoto.location;
    ensurePmtilesProtocol();

    resolutionMap = L.map(resolutionMapElement, {
        minZoom: 1,
        maxZoom: 18,
        zoomControl: false
    }).setView([lat, lng], 13);

    L.control.zoom({position: 'topright'}).addTo(resolutionMap);
    // City names always shown here regardless of the "map without city
    // names" setting (#38/#95) - the small player-guess maps stay
    // unlabeled while guessing is in progress, but once a round is
    // resolved (this "Auflösung" map) the moderator wants labels back to
    // make sense of the result.
    baseMapLayer = await createBaseMapLayer({ hideCityLabels: false });
    baseMapLayer.addTo(resolutionMap);

    locationMarker = L.marker([lat, lng], {
        icon: createMarkerIcon('/static/img/marker-icon-2x-green.png')
    }).addTo(resolutionMap);
    // autoPan disabled: showResolutionView() already setView()s the map
    // exactly onto this marker before opening its popup every round, so
    // the popup's own default auto-pan (which only nudges the view just
    // far enough for the popup to fit, not re-center it - see #113) would
    // otherwise undo that centering instead of leaving it alone.
    locationMarker.bindPopup(currentPhoto.description || t('moderator.default_photo_position'), {autoPan: false}).openPopup();
}

async function showResolutionView() {

    if (!currentPhoto?.location) return;

    moderatorApp.classList.add('is-hidden');
    resolutionView.classList.add('is-active');
    continueButton.classList.add('is-active');

    try {
        await initResolutionMap();
        const {lat, lng} = currentPhoto.location;
        // animate:false forces an exact re-center (Leaflet's default animated
        // panBy() is offset/pixel-based and only approximates the target
        // when it's close to the map's previous center - see #113).
        resolutionMap.setView([lat, lng], 13, {animate: false});
        locationMarker.setLatLng([lat, lng]);
        locationMarker.setPopupContent(currentPhoto.description || t('moderator.default_photo_position'));
        locationMarker.openPopup();
        syncResolutionPlayerMarkers();

        setTimeout(() => {
            resolutionMap.invalidateSize(true);
        }, 100);
    } catch (error) {
        console.error('Moderator map could not be loaded:', error);
    }
}

async function showModPageNextRound() {

    await loadCurrentPhoto(round);

    await startNextRound();

    // The round we just advanced to always starts hidden/"waiting" (see
    // startNextRound()) - set this synchronously rather than waiting on the
    // gamestate SSE round-trip, so the previous round's photo can't flash
    // on screen for that brief window.
    currentGameState = 'waiting';
    updatePhotoVisibility();

    moderatorApp.classList.remove('is-hidden');
    resolutionView.classList.remove('is-active');

    clearRoundRecords();

    leftPlayerMarker?.remove();
    rightPlayerMarker?.remove();

    leftPlayerMarker = null;
    rightPlayerMarker = null;

    // Otherwise each map stays zoomed in on wherever the last round's guess
    // landed instead of showing the overview the next round should start from.
    leftPlayerMap?.setView(INITIAL_PLAYER_MAP_CENTER, INITIAL_PLAYER_MAP_ZOOM);
    rightPlayerMap?.setView(INITIAL_PLAYER_MAP_CENTER, INITIAL_PLAYER_MAP_ZOOM);
}

function distanceCalculator(playerLatLng, targetLatLng){
    return L.latLng(playerLatLng).distanceTo(L.latLng(targetLatLng));
}


/***
 * pointByName
 */
async function calculatePoints() {
    if (!currentPhoto?.location) {
        return [];
    }

    const targetLatLng = [
        currentPhoto.location.lat,
        currentPhoto.location.lng
    ];

    const scoringConfig = getScoringConfig();
    let roundPoints = {};

    ["player1", "player2"].forEach((role) => {
        const playerLatLng = getRecordLatLng(latestPlayerRecords[role]);
        let distanceMeters = null;

        if (playerLatLng) {
            distanceMeters = distanceCalculator(
                playerLatLng,
                targetLatLng
            );
        }

        const points = calculateRoundPoints(distanceMeters, scoringConfig);

        roundPoints[role] = {
            points: points,
            distance: distanceMeters
        }

        pointByName[role] += points;
    });

    const players = {
        player1: {
            markerLocation: getRecordLatLng(latestPlayerRecords.player1),
            points: roundPoints.player1.points,
            distance: roundPoints.player1.distance
        },
        player2: {
            markerLocation: getRecordLatLng(latestPlayerRecords.player2),
            points: roundPoints.player2.points,
            distance: roundPoints.player2.distance
        }
    };

    resultCollection[currentPhoto.id] = {
        photo: currentPhoto,
        players
    };

    // Persist to the server so the round result survives a restart and is
    // available to the end-of-game screen even after a page reload.
    try {
        await postRoundResult(currentPhoto.id, players);
    } catch (error) {
        console.error('Could not persist round result to server:', error);
    }

    return players;
}

function updateCurrentPointDisplay() {
    Object.entries(pointByName).forEach(([name, points]) => {
        const pointElement = playerPointElements[name];
        if (!pointElement) return;

        pointElement.textContent = `${points} ${t('common.points_suffix')}`;
    });
}

function showRoundResult(roundPlayers) {
    const sortedResults = Object.entries(roundPlayers ?? {})
        .map(([role, result]) => ({
            name: getDisplayNames()[role] ?? role,
            points: result.points
        }))
        .sort((a, b) => b.points - a.points);

    const resultRows = document.querySelectorAll('.result-row');

    sortedResults.forEach((result, index) => {
        const row = resultRows[index];
        if (!row) return;

        row.querySelector('.result-player-name').textContent = result.name;
        row.querySelector('.result-player-points').textContent = `${result.points} ${t('common.points_suffix')}`;
    });

    roundResultView.classList.add('is-active');
}

export async function onGamestateUpdate(record) {
    console.log("Moderator updating with Gamestate: ", record)

    const previousRound = round;

    playerInputLocked = (record.state === "waiting");
    currentGameState = record.state;
    console.log("round running: " + playerInputLocked);
    round = record.round;
    console.log("Round: ", round)
    roundIndicator.textContent = round;

    if (round !== previousRound) {
        autoStoppedForRound = false;
        timerStartedForRound = false;
    }

    ['player1', 'player2'].forEach((role) => {
        const lockedIn = Boolean(record[`${role}_locked`]);
        playerLockedIn[role] = lockedIn;
        playerMapElements[role]?.classList.toggle('is-locked-in', lockedIn);
        playerMapElements[role]?.classList.toggle('is-input-disabled', playerInputLocked);
        // Read by moderator.css's ::after { content: attr(...) } stamp.
        playerMapElements[role]?.setAttribute('data-locked-in-label', t('moderator.locked_in_stamp'));
    });
    maybeAutoStopTimer();

    if (!playerInputLocked) {
        lockPlayerInputButton.textContent = t('moderator.deny_input_button');
        lockPlayerInputButton.style.backgroundColor = "red";
        lockPlayerInputButton.style.color = "white";
    } else {
        lockPlayerInputButton.textContent = t('moderator.allow_input_button');
        lockPlayerInputButton.style.backgroundColor = "green";
        lockPlayerInputButton.style.color = "white";
    }

    await loadCurrentPhoto();
    renderTimeControlPanel();
}

async function toggleLockPlayerScreen(){

    if (playerInputLocked) {
            await unlockPlayerInput();
        } else {
            await lockPlayerInput();
    }
};

function initEventListeners() {
    lockPlayerInputButton?.addEventListener('click', async () => {
        await toggleLockPlayerScreen();
    });

    continueButton?.addEventListener('click', async () => {
        // Guard against a double-click firing this twice - calculatePoints()
        // adds to pointByName, so a repeat call would double-count the round.
        if (continueButton.disabled) return;
        continueButton.disabled = true;
        try {
            await lockPlayerInput();
            const roundPlayers = await calculatePoints();
            showRoundResult(roundPlayers);
            continueButton.classList.remove('is-active');
        } finally {
            continueButton.disabled = false;
        }
    });


    resetGameButton?.addEventListener('click', async () => {
        const confirmed = await confirmDialog(
            t('moderator.reset_confirm_text'),
            { confirmLabel: t('moderator.reset_confirm_label') }
        );
        if (!confirmed) return;

        await resetGameState();
        clearRoundRecords();

        pointByName = {
            player1: 0,
            player2: 0
        };
        resultCollection = {};
        autoStoppedForRound = false;
        timerStartedForRound = false;
        playerLockedIn = { player1: false, player2: false };

        updateCurrentPointDisplay()

    });

    timerStartButton?.addEventListener('click', async () => {
        if (timerStartButton.disabled) return;
        timerStartButton.disabled = true;
        try {
            // Unlocking input reveals the photo (state -> "playing"); the
            // countdown then starts from the same click, matching #16's
            // "moderator starts the timer by clicking start".
            await unlockPlayerInput();
            await startTimer();
            // Keep Start disabled even after the timer stops (naturally, both
            // players locking in, or a manual "Runde auflösen") - restarting
            // it would re-open player input for a round already in progress
            // (#101). renderTimeControlPanel() keeps re-applying this every
            // tick, so it survives the countdown's own is-hidden toggling.
            timerStartedForRound = true;
        } catch (error) {
            timerStartButton.disabled = false;
            console.error('Could not start timer:', error);
        }
    });

    timerPauseButton?.addEventListener('click', async () => {
        if (timerPauseButton.disabled) return;
        timerPauseButton.disabled = true;
        try {
            if (timerState.paused) {
                await resumeTimer();
            } else {
                await pauseTimer();
            }
        } finally {
            timerPauseButton.disabled = false;
        }
    });

    timerExtendButton?.addEventListener('click', async () => {
        try {
            await extendTimer(roundConfig.extend_seconds);
        } catch (error) {
            console.error('Could not extend timer:', error);
        }
    });

    resultContinueButton?.addEventListener('click', async () => {
        // Guard against a double-click firing this twice - it would advance
        // the round (or jump to end_of_game) more than once.
        if (resultContinueButton.disabled) return;
        resultContinueButton.disabled = true;
        try {
            roundResultView.classList.remove('is-active');
            updateCurrentPointDisplay();

            const currentRound = (await getGamestateRecord()).round;

            if (currentRound >= photos.length) {
                // Broadcasts "finished" so player devices navigate to their
                // own /results screen (see game.js's updateView) before this
                // browser leaves for the moderator's own /end_of_game view.
                await finishGame();
                window.location.href = "/end_of_game";
            } else {
                await showModPageNextRound();
            }
        } finally {
            resultContinueButton.disabled = false;
        }
    });

    window.addEventListener('resize', () => {
        leftPlayerMap?.invalidateSize(true);
        rightPlayerMap?.invalidateSize(true);
    });
}

if (moderatorApp) {

    const response = await fetch('/static/config/photos.json');
    if (!response.ok) {
        console.error(`Failed to load photos.json: ${response.status}`);
        photos = [];
    } else {
        photos = await response.json();
    }

    if (sessionStorage.getItem("name") === null) {
        sessionStorage.setItem("name", "Moderator");
    }

    // Restore points/round history from the server so a moderator page
    // refresh (or a restart of the server process) doesn't wipe the
    // scoreboard back to 0.
    await restoreScoreState();

    roundConfig = await loadRoundConfig();
    await loadScoringConfig();
    try {
        timerState = await getTimerState();
    } catch (error) {
        console.error('Could not load timer state:', error);
    }

    await initSubscriptions();

    await onGamestateUpdate(await getGamestateRecord());

    // Recover markers/points for guesses already placed in the current round
    // (e.g. the moderator reloaded the page after players had already guessed).
    await hydratePlacedPoints();

    updateCurrentPointDisplay();

    initEventListeners();

    await loadCurrentPhoto();

    renderTimeControlPanel();
    setInterval(() => {
        renderTimeControlPanel();
        maybeAutoStopTimer();
    }, 250);

    mainControlButton?.addEventListener('click', async () => {
        await triggerResolution();
    });

    initModeratorMaps().catch((error) => {
        console.error('Moderator maps could not be loaded:', error);
    });
}
