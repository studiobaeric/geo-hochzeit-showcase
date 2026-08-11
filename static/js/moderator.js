import {
    unlockPlayerInput, startNextRound, lockPlayerInput, resetGameState, getGamestateRecord,
    initSubscriptions, getPlacedPoints, getRoundResults, postRoundResult
} from './multiplayer.js';
import { displayNames, photoFilenames } from '../config/players.js';
import { ensurePmtilesProtocol, createBaseMapLayer, createMarkerIcon, formatDistance } from './basemap.js';


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
    const player1ScoreName = document.getElementById('player1ScoreName');
    if (player1ScoreName) player1ScoreName.textContent = displayNames.player1;

    const player2ScoreName = document.getElementById('player2ScoreName');
    if (player2ScoreName) player2ScoreName.textContent = displayNames.player2;

    const player1Photo = document.getElementById('player1Photo');
    if (player1Photo) {
        player1Photo.alt = `Bild_${displayNames.player1}`;
        player1Photo.src = `/static/photos/${photoFilenames.player1}`;
    }

    const player2Photo = document.getElementById('player2Photo');
    if (player2Photo) {
        player2Photo.alt = `Bild_${displayNames.player2}`;
        player2Photo.src = `/static/photos/${photoFilenames.player2}`;
    }

    if (resolutionDistanceElements.player1) resolutionDistanceElements.player1.textContent = `${displayNames.player1}: -`;
    if (resolutionDistanceElements.player2) resolutionDistanceElements.player2.textContent = `${displayNames.player2}: -`;

    const resultRowNamePlayer1 = document.getElementById('resultRowNamePlayer1');
    if (resultRowNamePlayer1) resultRowNamePlayer1.textContent = displayNames.player1;

    const resultRowNamePlayer2 = document.getElementById('resultRowNamePlayer2');
    if (resultRowNamePlayer2) resultRowNamePlayer2.textContent = displayNames.player2;
}

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

        currentPhotoImage.src = `/static/photos/${currentPhoto.filename}`;
        currentPhotoImage.classList.add('is-loaded');
        currentPhotoFallback.classList.add('is-hidden');
    } catch (error) {
        console.error('Moderator photo could not be loaded:', error);
    }
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
            label: displayNames.player1
        };
    }

    if (role === 'player2') {
        return {
            map: rightPlayerMap,
            marker: rightPlayerMarker,
            setMarker: (marker) => {
                rightPlayerMarker = marker;
            },
            label: displayNames.player2
        };
    }

    return null;
}

function getPlayerRole(record) {
    const role = String(record?.placed_by || '').trim();
    return role === 'player1' || role === 'player2' ? role : undefined;
}

function isCurrentPhotoRecord(record) {
    if (!currentPhoto?.id) return true;

    return Number(record?.round_number) === Number(currentPhoto.id);
}

function updateResolutionDistanceDisplay(role, distanceMeters) {
    const distanceElement = resolutionDistanceElements[role];
    if (!distanceElement) return;

    const displayName = displayNames[role] ?? role;
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

        const displayName = displayNames[role] ?? role;
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

        marker.bindPopup(`${target.label}s Tipp`);
        target.setMarker(marker);
    }

    target.map.setView(latLng, Math.max(target.map.getZoom(), 8));
}

function createPlayerMap(elementId) {
    return L.map(elementId, {
        minZoom: 1,
        maxZoom: 18,
        zoomControl: true
    }).setView([49.3690, 9.5436], 5);
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
    baseMapLayer = await createBaseMapLayer();
    baseMapLayer.addTo(resolutionMap);

    locationMarker = L.marker([lat, lng], {
        icon: createMarkerIcon('/static/img/marker-icon-2x-green.png')
    }).addTo(resolutionMap);
    locationMarker.bindPopup(currentPhoto.description || 'Bildposition').openPopup();
}

async function showResolutionView() {

    if (!currentPhoto?.location) return;

    moderatorApp.classList.add('is-hidden');
    resolutionView.classList.add('is-active');
    continueButton.classList.add('is-active');

    try {
        await initResolutionMap();
        const {lat, lng} = currentPhoto.location;
        resolutionMap.setView([lat, lng], 13);
        locationMarker.setLatLng([lat, lng]);
        locationMarker.setPopupContent(currentPhoto.description || 'Bildposition');
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

    moderatorApp.classList.remove('is-hidden');
    resolutionView.classList.remove('is-active');

    clearRoundRecords();

    leftPlayerMarker?.remove();
    rightPlayerMarker?.remove();

    leftPlayerMarker = null;
    rightPlayerMarker = null;

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

    const maxPoints = 1000;
    const minPoints = 100;

    const perfectRadiusMeters = 500; // bis hier volle Punkte
    const distanceScaleMeters = 100000;
    let roundPoints = {};


    ["player1", "player2"].forEach((role) => {
        const playerLatLng = getRecordLatLng(latestPlayerRecords[role]);
        let points = 0;
        let distanceMeters = null;

        if (playerLatLng) {
            distanceMeters = distanceCalculator(
                playerLatLng,
                targetLatLng
            );

            if (distanceMeters <= perfectRadiusMeters) {
                points = maxPoints;
            } else {
                const effectiveDistance =
                    distanceMeters - perfectRadiusMeters;

                points = Math.round(
                    minPoints +
                    (maxPoints - minPoints) *
                    Math.exp(
                        -effectiveDistance / distanceScaleMeters
                    )
                );

                // niemals unter minPoints
                points = Math.max(minPoints, points);
                points = Math.min(maxPoints, points);

            }
        }

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
}

function updateCurrentPointDisplay() {
    Object.entries(pointByName).forEach(([name, points]) => {
        const pointElement = playerPointElements[name];
        if (!pointElement) return;

        pointElement.textContent = `${points} Punkte`;
    });
}

function showRoundResult() {
    const sortedResults = Object.entries(pointByName)
        .map(([role, points]) => ({
            name: displayNames[role] ?? role,
            points
        }))
        .sort((a, b) => b.points - a.points);

    const resultRows = document.querySelectorAll('.result-row');

    sortedResults.forEach((result, index) => {
        const row = resultRows[index];
        if (!row) return;

        row.querySelector('.result-player-name').textContent = result.name;
        row.querySelector('.result-player-points').textContent = `${result.points} Punkte`;
    });

    roundResultView.classList.add('is-active');
}

export async function onGamestateUpdate(record) {
    console.log("Moderator updating with Gamestate: ", record)

    playerInputLocked = (record.state === "waiting");
    console.log("round running: " + playerInputLocked);
    round = record.round;
    console.log("Round: ", round)
    roundIndicator.textContent = round;

    ['player1', 'player2'].forEach((role) => {
        playerMapElements[role]?.classList.toggle('is-locked-in', Boolean(record[`${role}_locked`]));
    });

    if (!playerInputLocked) {
        lockPlayerInputButton.textContent = "Input Verbieten";
        lockPlayerInputButton.style.backgroundColor = "red";
        lockPlayerInputButton.style.color = "white";
    } else {
        lockPlayerInputButton.textContent = "Input Erlauben";
        lockPlayerInputButton.style.backgroundColor = "green";
        lockPlayerInputButton.style.color = "white";
    }

    await loadCurrentPhoto();
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
            await calculatePoints();
            showRoundResult();
            continueButton.classList.remove('is-active');
        } finally {
            continueButton.disabled = false;
        }
    });


    resetGameButton?.addEventListener('click', async () => {
        await resetGameState();
        clearRoundRecords();

        pointByName = {
            player1: 0,
            player2: 0
        };
        resultCollection = {};

        updateCurrentPointDisplay()

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

            if (currentRound >= photos.length)
                window.location.href = "/end_of_game";
            else
                await showModPageNextRound();
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

    await initSubscriptions();

    await onGamestateUpdate(await getGamestateRecord());

    // Recover markers/points for guesses already placed in the current round
    // (e.g. the moderator reloaded the page after players had already guessed).
    await hydratePlacedPoints();

    updateCurrentPointDisplay();

    initEventListeners();

    await loadCurrentPhoto();

    mainControlButton?.addEventListener('click', async () => {
        showResolutionView();
        await toggleLockPlayerScreen();
    });

    initModeratorMaps().catch((error) => {
        console.error('Moderator maps could not be loaded:', error);
    });
}
