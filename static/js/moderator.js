import {init_pocketbase, startNextRound} from './multiplayer.js';

const currentPhotoImage = document.getElementById('currentPhotoImage');
const currentPhotoFallback = document.getElementById('currentPhotoFallback');
const moderatorApp = document.getElementById('moderatorApp');
const resolutionView = document.getElementById('resolutionView');
const resolutionMapElement = document.getElementById('resolutionMap');
const mainControlButton = document.getElementById('mainControlButton');

const startButton = document.getElementById('startButton');

let currentPhoto = null;
let resolutionMap = null;
let locationMarker = null;
let baseMapLayer = null;

let leftPlayerMap = null;
let rightPlayerMap = null;
let leftPlayerMarker = null;
let rightPlayerMarker = null;
let isPmtilesProtocolRegistered = false;

function ensurePmtilesProtocol() {
    if (isPmtilesProtocolRegistered) return;

    const pmtilesProtocol = new pmtiles.Protocol();
    maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);
    isPmtilesProtocolRegistered = true;
}

// aufrufen mit neuer nummer für neues photo
async function loadCurrentPhoto(photo=0) {
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

export async function updateMapPosition(record) {
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

    try {
        await initResolutionMap();
        const {lat, lng} = currentPhoto.location;
        resolutionMap.setView([lat, lng], 13);
        locationMarker.setLatLng([lat, lng]);
        locationMarker.setPopupContent(currentPhoto.description || 'Bildposition');
        locationMarker.openPopup();

        setTimeout(() => {
            resolutionMap.invalidateSize(true);
        }, 100);
    } catch (error) {
        console.error('Moderator map could not be loaded:', error);
    }
}

if (moderatorApp) {
    mainControlButton?.addEventListener('click', showResolutionView);
    startButton?.addEventListener('click', () => {
        console.log("Clicked Start button")
        startNextRound;

        startButton.textContent = "Gestartet ...";
        startButton.disabled = true;
        } );

    loadCurrentPhoto();

    init_pocketbase().catch((error) => {
        console.error('Moderator multiplayer could not be initialized:', error);
    });
    initModeratorMaps().catch((error) => {
        console.error('Moderator maps could not be loaded:', error);
    });

    window.addEventListener('resize', () => {
        leftPlayerMap?.invalidateSize(true);
        rightPlayerMap?.invalidateSize(true);
    });
}
