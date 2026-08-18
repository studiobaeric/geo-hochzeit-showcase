import { getDisplayNames, loadDisplayNames } from './player-names.js';
import { ensurePmtilesProtocol, createBaseMapLayer, createMarkerIcon, formatDistance } from './basemap.js';
import { resetGameState } from './multiplayer.js';
import { loadResultCollection, getSortedResults } from './round-results.js';
import { loadThemeConfig, subscribeThemeUpdates } from './theme.js';

loadThemeConfig();
subscribeThemeUpdates();

const endGameMapElement = document.getElementById('endGameMap');
const roundListElement = document.getElementById('roundList');
const player1TotalPoints = document.getElementById('player1TotalPoints');
const player2TotalPoints = document.getElementById('player2TotalPoints');
const player1PlayerName = document.getElementById('player1PlayerName');
const player2PlayerName = document.getElementById('player2PlayerName');
const resetGameButton = document.getElementById('resetGameButton');

// Populated by applyDisplayNames() once loadDisplayNames() has resolved -
// every function below is only ever called after that has happened.
let playerStyles = null;

function applyDisplayNames() {
    const names = getDisplayNames();

    if (player1PlayerName) player1PlayerName.textContent = names.player1;
    if (player2PlayerName) player2PlayerName.textContent = names.player2;

    playerStyles = {
        player1: {
            label: names.player1,
            iconUrl: '/static/img/marker-icon-2x-blue.png',
            lineColor: '#2563eb'
        },
        player2: {
            label: names.player2,
            iconUrl: '/static/img/marker-icon-2x-red.png',
            lineColor: '#dc2626'
        }
    };
}

let endGameMap = null;
let baseMapLayer = null;
let activeLayers = [];

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
    const style = playerStyles[playerName] ?? playerStyles.player1;

    return createMarkerIcon(style.iconUrl);
}

function renderRoundMap(roundResult) {
    if (!endGameMap) return;

    clearMapLayers();

    const visiblePositions = [];
    const photoLatLng = getPhotoLatLng(roundResult);

    if (photoLatLng) {
        visiblePositions.push(photoLatLng);
        const goalMarker = addLayer(L.marker(photoLatLng, {
            icon: createMarkerIcon('/static/img/marker-icon-2x-green.png')
        }).addTo(endGameMap));

        bindPermanentMarkerLabel(goalMarker, roundResult.photo?.description || 'Ziel');
    }

    Object.entries(roundResult.players || {}).forEach(([playerName, playerResult]) => {
        const playerLatLng = getPlayerLatLng(playerResult);
        if (!playerLatLng) return;

        const style = playerStyles[playerName] ?? playerStyles.player1;
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

function updateTotals(resultCollection) {
    const totals = {
        player1: 0,
        player2: 0
    };

    Object.values(resultCollection).forEach((roundResult) => {
        Object.entries(roundResult.players || {}).forEach(([playerName, playerResult]) => {
            totals[playerName] = (totals[playerName] || 0) + Number(playerResult.points || 0);
        });
    });

    player1TotalPoints.textContent = formatPoints(totals.player1);
    player2TotalPoints.textContent = formatPoints(totals.player2);
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
                <span>Runde ${roundResult.position}</span>
                <span>${roundResult.photo?.description || ''}</span>
            </div>
            ${renderPlayerRow('player1', roundResult.players?.player1)}
            ${renderPlayerRow('player2', roundResult.players?.player2)}
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
    const style = playerStyles[playerName] ?? playerStyles.player1;

    return `
        <div class="round-player">
            <span>${style.label}: ${formatDistance(Number(playerResult?.distance))}</span>
            <strong>${formatPoints(playerResult?.points)}</strong>
        </div>
    `;
}

async function initEndOfGamePage() {
    await loadDisplayNames();
    applyDisplayNames();

    const resultCollection = await loadResultCollection();

    await initMap();
    updateTotals(resultCollection);
    renderRoundList(resultCollection);

    setTimeout(() => {
        endGameMap.invalidateSize(true);
    }, 100);
}

resetGameButton?.addEventListener('click', async () => {
    if (resetGameButton.disabled) return;
    resetGameButton.disabled = true;
    try {
        await resetGameState();
        window.location.href = '/';
    } finally {
        resetGameButton.disabled = false;
    }
});

if (endGameMapElement && roundListElement) {
    initEndOfGamePage().catch((error) => {
        console.error('End of game page could not be initialized:', error);
    });
}
