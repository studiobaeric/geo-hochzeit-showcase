import { getDisplayNames, loadDisplayNames } from './player-names.js';
import { ensurePmtilesProtocol, createBaseMapLayer, createMarkerIcon, formatDistance } from './basemap.js';
import { resetGameState } from './multiplayer.js';
import { loadResultCollection, getSortedResults } from './round-results.js';
import { loadThemeConfig, subscribeThemeUpdates } from './theme.js';
import { loadMapLabelsConfig, subscribeMapLabelsUpdates } from './map-labels-config.js';
import { loadScoringConfig, getScoringConfig, getRadiusBands } from './scoring-config.js';
import { t, subscribeLocaleUpdates } from './i18n.js';

loadThemeConfig();
subscribeThemeUpdates();
loadMapLabelsConfig();
subscribeMapLabelsUpdates();
subscribeLocaleUpdates();

// No live subscription for this one, unlike theme/map-labels (cosmetic
// chrome for a screen that sits on display between games) - the scoring
// config only needs to be correct for the round data this page renders
// once, right after the game ends. A 3rd persistent /api/events connection
// here (on top of theme's and map-labels' own) risks the connection-
// scarcity issue theme.js's subscribeThemeUpdates warns about: with
// player1/player2 already holding their own connections open via
// multiplayer.js, browsers cap concurrent HTTP/1.1 connections per origin
// at 6, and this page alone would already account for 3 of them. Awaited
// (unlike loadThemeConfig()/loadMapLabelsConfig() above) inside
// initEndOfGamePage() itself - see there for why.

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
    return `${Number(points || 0)} ${t('common.points_suffix')}`;
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

        bindPermanentMarkerLabel(goalMarker, roundResult.photo?.description || t('end_of_game.default_target_label'));

        // Concentric orange-to-blue rings visualizing how the exponential/
        // linear algorithms' points decay beyond the full-points radius
        // (#144 follow-up) - see scoring-config.js's getRadiusBands() for
        // the falloff math/coloring. Added before the full-points circle
        // below so that circle renders on top of them.
        getRadiusBands(getScoringConfig()).forEach((band) => {
            addLayer(L.circle(photoLatLng, {
                radius: band.radius,
                color: band.color,
                weight: 0,
                fillColor: band.color,
                fillOpacity: 0.12,
                interactive: false
            }).addTo(endGameMap));
        });

        // Full-points radius from the scoring config (#144) - same
        // orange/transparent treatment as moderator.js's resolution map, so
        // the two round-result views read consistently.
        addLayer(L.circle(photoLatLng, {
            radius: getScoringConfig().perfect_radius_meters,
            color: '#f97316',
            weight: 2,
            fillColor: '#f97316',
            fillOpacity: 0.15,
            interactive: false
        }).addTo(endGameMap));
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
        roundListElement.innerHTML = `<p class="empty-state">${t('end_of_game.no_round_results')}</p>`;
        return;
    }

    sortedResults.forEach(([roundId, roundResult], index) => {
        const roundButton = document.createElement('button');
        roundButton.type = 'button';
        roundButton.className = 'round-card';
        roundButton.innerHTML = `
            <div class="round-title">
                <span>${t('common.round_label')} ${roundResult.position}</span>
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

    // Awaited (unlike loadResultCollection() right after it) so
    // renderRoundMap()'s first call - from renderRoundList() below - always
    // reads the real perfect_radius_meters, not scoring-config.js's 500m
    // default from a fetch that hadn't resolved yet.
    await loadScoringConfig();
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
