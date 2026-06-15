import {unlockPlayerInput, startNextRound, lockPlayerInput, resetGameState, init_pocketbase, getGamestateRecord} from './multiplayer.js';


const currentPhotoImage = document.getElementById('currentPhotoImage');
const currentPhotoFallback = document.getElementById('currentPhotoFallback');
const moderatorApp = document.getElementById('moderatorApp');
const resolutionView = document.getElementById('resolutionView');
const resolutionMapElement = document.getElementById('resolutionMap');
const mainControlButton = document.getElementById('mainControlButton');

const lockPlayerInputButton = document.getElementById('lockPlayerInputButton');
const continueButton = document.getElementById('continueButton');
const resetGameButton = document.getElementById('resetGameButton');
const resultContinueButton = document.getElementById('resultContinueButton');

const roundResultView = document.getElementById('roundResultView');

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
let isPmtilesProtocolRegistered = false;

let round = 0
let playerInputLocked = false;

function ensurePmtilesProtocol() {
    if (isPmtilesProtocolRegistered) return;

    const pmtilesProtocol = new pmtiles.Protocol();
    maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);
    isPmtilesProtocolRegistered = true;
}

// aufrufen mit neuer nummer für neues photo
async function loadCurrentPhoto(photo = round) {
    if (!currentPhotoImage || !currentPhotoFallback) return;

    try {
        const response = await fetch('/static/data/photos.json');
        const photos = await response.json();
        currentPhoto = photos[photo];

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
    const playerName = String(record?.placed_by || '').trim().toLowerCase();

    if (playerName === 'jana') {
        return {
            map: leftPlayerMap,
            marker: leftPlayerMarker,
            setMarker: (marker) => {
                leftPlayerMarker = marker;
            },
            label: 'Jana'
        };
    }

    if (playerName === 'tobias') {
        return {
            map: rightPlayerMap,
            marker: rightPlayerMarker,
            setMarker: (marker) => {
                rightPlayerMarker = marker;
            },
            label: 'Tobias'
        };
    }

    return null;
}

function getPlayerName(record) {
    return String(record?.placed_by || '').trim().toLowerCase();
}

function isCurrentPhotoRecord(record) {
    if (!currentPhoto?.id) return true;

    return Number(record?.round_number) === Number(currentPhoto.id);
}

function syncResolutionPlayerMarkers() {
    if (!resolutionMap) return;

    const visiblePositions = currentPhoto?.location
        ? [[currentPhoto.location.lat, currentPhoto.location.lng]]
        : [];

    Object.values(latestPlayerRecords).forEach((record) => {
        if (!isCurrentPhotoRecord(record)) return;

        const latLng = getRecordLatLng(record);
        const playerName = getPlayerName(record);

        if (!latLng || !playerName) return;
        visiblePositions.push(latLng);

        if (resolutionPlayerMarkers[playerName]) {
            resolutionPlayerMarkers[playerName].setLatLng(latLng);
            return;
        }

        const marker = L.marker(latLng, {
            icon: L.icon({
                iconUrl: '/static/img/marker-icon-2x-blue.png',
                shadowUrl: '/static/img/marker-shadow.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                shadowSize: [41, 41]
            })
        }).addTo(resolutionMap);

        marker.bindPopup(`${playerName.charAt(0).toUpperCase() + playerName.slice(1)}s Tipp`);
        resolutionPlayerMarkers[playerName] = marker;
    });

    if (visiblePositions.length > 1) {
        resolutionMap.fitBounds(L.latLngBounds(visiblePositions), {padding: [50, 50]});
    }
}

export async function updateMapPosition(record) {
    const playerName = getPlayerName(record);
    latestPlayerRecords[playerName] = record;
    syncResolutionPlayerMarkers();

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
            icon: L.icon({
                iconUrl: '/static/img/marker-icon-2x-blue.png',
                shadowUrl: '/static/img/marker-shadow.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                shadowSize: [41, 41]
            })
        }).addTo(target.map);

        marker.bindPopup(`${target.label}s Tipp`);
        target.setMarker(marker);
    }

    target.map.setView(latLng, Math.max(target.map.getZoom(), 8));
    syncResolutionPlayerMarkers();
}


async function createBaseMapLayer() {
    const response = await fetch('/static/data/basemap-style.json');
    const style = await response.json();
    const origin = window.location.origin;

    style.sprite = origin + style.sprite;
    style.glyphs = origin + style.glyphs;
    style.sources.protomaps.url = `pmtiles://${origin}/static/data/basemap.pmtiles`;

    return L.maplibreGL({
        style,
        attribution: 'Map data &copy; OpenStreetMap contributors'
    });
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
        icon: L.icon({
            iconUrl: '/static/img/marker-icon-2x-red.png',
            shadowUrl: '/static/img/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41]
        })
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


}

function showRoundResult(results) {
    const sortedResults = [...results].sort((a, b) => b.points - a.points);
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

    if (!playerInputLocked) {
        lockPlayerInputButton.textContent = "Input Verbieten";
        lockPlayerInputButton.style.backgroundColor = "red";
        lockPlayerInputButton.style.color = "white";
    } else {
        lockPlayerInputButton.textContent = "Input Erlauben";
        lockPlayerInputButton.style.backgroundColor = "green";
        lockPlayerInputButton.style.color = "white";
    }

    await loadCurrentPhoto()
}

function initEventListeners() {
    lockPlayerInputButton?.addEventListener('click', async () => {
        if (playerInputLocked) {
            await unlockPlayerInput();
        } else {
            await lockPlayerInput();
        }
    });

    continueButton?.addEventListener('click', () => {
        showRoundResult([
            {name: 'Jana', points: 850},
            {name: 'Tobias', points: 620}
        ]);
        continueButton.classList.remove('is-active');
    });


    resetGameButton?.addEventListener('click', async () => {
        await resetGameState();
        latestPlayerRecords.clear;
    });

    resultContinueButton?.addEventListener('click', async () => {
        roundResultView.classList.remove('is-active');
        await showModPageNextRound();
    });

    window.addEventListener('resize', () => {
        leftPlayerMap?.invalidateSize(true);
        rightPlayerMap?.invalidateSize(true);
    });
}

if (moderatorApp) {

    await init_pocketbase();

    await onGamestateUpdate(await getGamestateRecord());

    mainControlButton?.addEventListener('click', showResolutionView);

    initEventListeners();

    await loadCurrentPhoto();

    initModeratorMaps().catch((error) => {
        console.error('Moderator maps could not be loaded:', error);
    });
}
