// Per-player "game over" screen, shown on player1's/player2's own device
// once the moderator advances past the last round (see game.js's
// updateView reacting to the "finished" gamestate broadcast). Distinct from
// /end_of_game, which is the moderator's shared/beamer screen.
import { getDisplayNames, loadDisplayNames } from './player-names.js';
import { formatDistance } from './basemap.js';
import { loadResultCollection, getSortedResults } from './round-results.js';
import { loadThemeConfig, subscribeThemeUpdates } from './theme.js';
import { t, subscribeLocaleUpdates } from './i18n.js';

loadThemeConfig();
subscribeThemeUpdates();
subscribeLocaleUpdates();

const ROLE = sessionStorage.getItem('name');
const OPPONENT_ROLE = { player1: 'player2', player2: 'player1' }[ROLE];
const PLAYER_ROLES = ['player1', 'player2'];

// Cards stay in a fixed player1 (left) / player2 (right) order rather than
// self/opponent, so a card doesn't jump sides depending on who's looking -
// whichever one belongs to the viewer is highlighted instead (see
// renderTotals).
const cardEls = {
    player1: {
        card: document.getElementById('player1Card'),
        name: document.getElementById('player1Name'),
        total: document.getElementById('player1Total'),
        badge: document.getElementById('player1Badge')
    },
    player2: {
        card: document.getElementById('player2Card'),
        name: document.getElementById('player2Name'),
        total: document.getElementById('player2Total'),
        badge: document.getElementById('player2Badge')
    }
};
const avgDistanceEl = document.getElementById('avgDistance');
const closestGuessEl = document.getElementById('closestGuess');
const closestGuessCaptionEl = document.getElementById('closestGuessCaption');
const furthestGuessEl = document.getElementById('furthestGuess');
const furthestGuessCaptionEl = document.getElementById('furthestGuessCaption');
const roundListEl = document.getElementById('roundList');
const goHomeButton = document.getElementById('goHomeButton');

function formatPoints(points) {
    return `${Number(points || 0)} ${t('common.points_suffix')}`;
}

// distance is null when the player never placed a guess that round - show
// that as "-" rather than as formatDistance(Number(null)), which would
// read as a suspiciously perfect 0 m guess (see computeOwnStats).
function formatPlayerDistance(distance) {
    return distance === null || distance === undefined ? '–' : formatDistance(Number(distance));
}

function computeOwnStats(sortedResults) {
    const distances = [];

    sortedResults.forEach(([, roundResult]) => {
        // distance is null when the player never placed a guess that round
        // (see game_state.py's _validate_round_result) - Number(null) is 0,
        // not NaN, so that has to be excluded before the isFinite check or
        // a skipped round would look like a perfect 0m guess.
        const rawDistance = roundResult.players?.[ROLE]?.distance;
        if (rawDistance === null || rawDistance === undefined) return;

        const distanceMeters = Number(rawDistance);
        if (!Number.isFinite(distanceMeters)) return;

        distances.push({
            distanceMeters,
            description: roundResult.photo?.description || `${t('common.round_label')} ${roundResult.position}`
        });
    });

    if (distances.length === 0) {
        return { average: null, closest: null, furthest: null };
    }

    const average = distances.reduce((sum, d) => sum + d.distanceMeters, 0) / distances.length;
    const closest = distances.reduce((best, d) => (d.distanceMeters < best.distanceMeters ? d : best));
    const furthest = distances.reduce((worst, d) => (d.distanceMeters > worst.distanceMeters ? d : worst));

    return { average, closest, furthest };
}

function renderStats(sortedResults) {
    const { average, closest, furthest } = computeOwnStats(sortedResults);

    avgDistanceEl.textContent = average !== null ? formatDistance(average) : '–';
    closestGuessEl.textContent = closest ? formatDistance(closest.distanceMeters) : '–';
    closestGuessCaptionEl.textContent = closest ? closest.description : '';
    furthestGuessEl.textContent = furthest ? formatDistance(furthest.distanceMeters) : '–';
    furthestGuessCaptionEl.textContent = furthest ? furthest.description : '';
}

function renderTotals(sortedResults) {
    const names = getDisplayNames();
    const totals = { player1: 0, player2: 0 };

    sortedResults.forEach(([, roundResult]) => {
        PLAYER_ROLES.forEach((role) => {
            totals[role] += Number(roundResult.players?.[role]?.points || 0);
        });
    });

    PLAYER_ROLES.forEach((role) => {
        const els = cardEls[role];
        els.name.textContent = names[role];
        els.total.textContent = formatPoints(totals[role]);
        els.card.classList.toggle('score-card--self', role === ROLE);
    });

    cardEls.player1.badge.classList.toggle('is-visible', totals.player1 > totals.player2);
    cardEls.player2.badge.classList.toggle('is-visible', totals.player2 > totals.player1);
}

function renderRoundList(sortedResults) {
    const names = getDisplayNames();
    roundListEl.innerHTML = '';

    if (sortedResults.length === 0) {
        roundListEl.innerHTML = `<p class="empty-state">${t('results.no_results')}</p>`;
        return;
    }

    sortedResults.forEach(([, roundResult]) => {
        const selfResult = roundResult.players?.[ROLE];
        const opponentResult = roundResult.players?.[OPPONENT_ROLE];

        const row = document.createElement('div');
        row.className = 'round-row';
        row.innerHTML = `
            <div class="round-row-title">
                <span>${t('common.round_label')} ${roundResult.position}</span>
                <span>${roundResult.photo?.description || ''}</span>
            </div>
            <div class="round-row-player round-row-player-self">
                <span>${names[ROLE]}: ${formatPlayerDistance(selfResult?.distance)}</span>
                <strong>${formatPoints(selfResult?.points)}</strong>
            </div>
            <div class="round-row-player">
                <span>${names[OPPONENT_ROLE]}: ${formatPlayerDistance(opponentResult?.distance)}</span>
                <strong>${formatPoints(opponentResult?.points)}</strong>
            </div>
        `;
        roundListEl.appendChild(row);
    });
}

async function initResultsPage() {
    await loadDisplayNames();

    const resultCollection = await loadResultCollection();
    const sortedResults = getSortedResults(resultCollection);

    renderTotals(sortedResults);
    renderStats(sortedResults);
    renderRoundList(sortedResults);
}

goHomeButton?.addEventListener('click', () => {
    window.location.href = '/';
});

if (ROLE === 'player1' || ROLE === 'player2') {
    initResultsPage().catch((error) => {
        console.error('Results page could not be initialized:', error);
    });
} else {
    // Only players (not the moderator, who gets /end_of_game) land here -
    // send anything else back to the start screen, same guard as game.js's
    // initGame for a missing/invalid role.
    window.location.href = '/';
}
