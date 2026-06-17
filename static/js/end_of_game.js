const endGameMapElement = document.getElementById('endGameMap');
const roundListElement = document.getElementById('roundList');
const janaTotalPoints = document.getElementById('janaTotalPoints');
const tobiasTotalPoints = document.getElementById('tobiasTotalPoints');

const playerStyles = {
    jana: {
        label: 'Jana',
        iconUrl: '/static/img/marker-icon-2x-blue.png',
        lineColor: '#2563eb'
    },
    tobias: {
        label: 'Tobias',
        iconUrl: '/static/img/marker-icon-2x-red.png',
        lineColor: '#dc2626'
    }
};

let endGameMap = null;
let baseMapLayer = null;
let activeLayers = [];
let isPmtilesProtocolRegistered = false;

function ensurePmtilesProtocol() {
    if (isPmtilesProtocolRegistered) return;

    const pmtilesProtocol = new pmtiles.Protocol();
    maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);
    isPmtilesProtocolRegistered = true;
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

function getResultCollection() {
    try {
        return JSON.parse(sessionStorage.getItem('resultCollection') || '{}');
    } catch (error) {
        console.error('Could not parse resultCollection:', error);
        return {};
    }
}

function getPhotoLatLng(roundResult) {
    const lat = Number(roundResult?.photo?.location?.lat);
    const lng = Number(roundResult?.photo?.location?.lng);

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return null;
    }

    return [lat, lng];
}

function getPlayerLatLng(playerResult) {
    if (!Array.isArray(playerResult?.markerLocation)) {
        return null;
    }

    const [lat, lng] = playerResult.markerLocation.map(Number);

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return null;
    }

    return [lat, lng];
}

function formatDistance(distanceMeters) {
    if (!Number.isFinite(distanceMeters)) {
        return '-';
    }

    if (distanceMeters < 1000) {
        return `${Math.round(distanceMeters)} m`;
    }

    return `${(distanceMeters / 1000).toFixed(1)} km`;
}

function formatPoints(points) {
    return `${Number(points || 0)} Punkte`;
}

async function initMap() {
    ensurePmtilesProtocol();

    endGameMap = L.map(endGameMapElement, {
        minZoom: 1,
        maxZoom: 18,
        zoomControl: true
    }).setView([49.3690, 9.5436], 5);

    baseMapLayer = await createBaseMapLayer();
    baseMapLayer.addTo(endGameMap);
}

function clearMapLayers() {
    activeLayers.forEach((layer) => layer.remove());
    activeLayers = [];
}

function addLayer(layer) {
    activeLayers.push(layer);
    return layer;
}

function bindPermanentMarkerLabel(marker, label) {
    return marker.bindTooltip(label, {
        permanent: true,
        direction: 'top',
        offset: [0, -36],
        className: 'end-marker-label'
    });
}

function createPlayerIcon(playerName) {
    const style = playerStyles[playerName] ?? playerStyles.jana;

    return L.icon({
        iconUrl: style.iconUrl,
        shadowUrl: '/static/img/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    });
}

function renderRoundMap(roundResult) {
    if (!endGameMap) return;

    clearMapLayers();

    const visiblePositions = [];
    const photoLatLng = getPhotoLatLng(roundResult);

    if (photoLatLng) {
        visiblePositions.push(photoLatLng);
        const goalMarker = addLayer(L.marker(photoLatLng, {
            icon: L.icon({
                iconUrl: '/static/img/marker-icon-2x-green.png',
                shadowUrl: '/static/img/marker-shadow.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                shadowSize: [41, 41]
            })
        }).addTo(endGameMap));

        bindPermanentMarkerLabel(goalMarker, roundResult.photo?.description || 'Ziel');
    }

    Object.entries(roundResult.players || {}).forEach(([playerName, playerResult]) => {
        const playerLatLng = getPlayerLatLng(playerResult);
        if (!playerLatLng) return;

        const style = playerStyles[playerName] ?? playerStyles.jana;
        const label = style.label;

        visiblePositions.push(playerLatLng);
        const playerMarker = addLayer(L.marker(playerLatLng, {
            icon: createPlayerIcon(playerName)
        }).addTo(endGameMap));

        bindPermanentMarkerLabel(playerMarker, `${label}: ${formatPoints(playerResult.points)}`);

        if (photoLatLng) {
            addLayer(L.polyline([playerLatLng, photoLatLng], {
                color: style.lineColor,
                weight: 3,
                opacity: 0.82,
                dashArray: '8 8'
            }).addTo(endGameMap));
        }
    });

    if (visiblePositions.length > 1) {
        endGameMap.fitBounds(L.latLngBounds(visiblePositions), {padding: [70, 70]});
    } else if (visiblePositions.length === 1) {
        endGameMap.setView(visiblePositions[0], 13);
    }
}

function getSortedResults(resultCollection) {
    return Object.entries(resultCollection)
        .sort(([firstId], [secondId]) => Number(firstId) - Number(secondId));
}

function updateTotals(resultCollection) {
    const totals = {
        jana: 0,
        tobias: 0
    };

    Object.values(resultCollection).forEach((roundResult) => {
        Object.entries(roundResult.players || {}).forEach(([playerName, playerResult]) => {
            totals[playerName] = (totals[playerName] || 0) + Number(playerResult.points || 0);
        });
    });

    janaTotalPoints.textContent = formatPoints(totals.jana);
    tobiasTotalPoints.textContent = formatPoints(totals.tobias);
}

function renderRoundList(resultCollection) {
    const sortedResults = getSortedResults(resultCollection);

    roundListElement.innerHTML = '';

    if (sortedResults.length === 0) {
        roundListElement.innerHTML = '<p class="empty-state">Noch keine Rundenergebnisse gefunden.</p>';
        return;
    }

    sortedResults.forEach(([roundId, roundResult], index) => {
        const roundButton = document.createElement('button');
        roundButton.type = 'button';
        roundButton.className = 'round-card';
        roundButton.innerHTML = `
            <div class="round-title">
                <span>Runde ${roundId}</span>
                <span>${roundResult.photo?.description || ''}</span>
            </div>
            ${renderPlayerRow('jana', roundResult.players?.jana)}
            ${renderPlayerRow('tobias', roundResult.players?.tobias)}
        `;

        roundButton.addEventListener('click', () => {
            document.querySelectorAll('.round-card').forEach((card) => {
                card.classList.remove('is-active');
            });
            roundButton.classList.add('is-active');
            renderRoundMap(roundResult);
        });

        roundListElement.appendChild(roundButton);

        if (index === 0) {
            roundButton.classList.add('is-active');
            renderRoundMap(roundResult);
        }
    });
}

function renderPlayerRow(playerName, playerResult) {
    const style = playerStyles[playerName] ?? playerStyles.jana;

    return `
        <div class="round-player">
            <span>${style.label}: ${formatDistance(Number(playerResult?.distance))}</span>
            <strong>${formatPoints(playerResult?.points)}</strong>
        </div>
    `;
}

async function initEndOfGamePage() {
    const resultCollection = getResultCollection();

    await initMap();
    updateTotals(resultCollection);
    renderRoundList(resultCollection);

    setTimeout(() => {
        endGameMap.invalidateSize(true);
    }, 100);
}

if (endGameMapElement && roundListElement) {
    initEndOfGamePage().catch((error) => {
        console.error('End of game page could not be initialized:', error);
    });
}
