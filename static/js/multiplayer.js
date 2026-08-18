import {onGamestateUpdate, updateMapPosition, onRoundConfigUpdate as onModeratorRoundConfigUpdate, onTimerUpdate as onModeratorTimerUpdate} from './moderator.js';
import {loadNextRound, updateView, onRoundConfigUpdate as onPlayerRoundConfigUpdate, onTimerUpdate as onPlayerTimerUpdate} from "./game.js";
import {getDisplayNames} from './player-names.js';
import {onThemeConfigEvent} from './theme.js';
import {onMapLabelsConfigEvent} from './map-labels-config.js';

const API_BASE = '/api';
let gamestateRecord = null;
let eventSource = null;

// Offset (seconds) to add to this browser's Date.now()-based clock to get
// the server's clock. Countdown displays are computed from a server epoch
// timestamp (timer.ends_at), so a client whose system clock is off - even
// by a couple of seconds, which is common on phones/tablets - would
// otherwise show a countdown that starts wrong and disagrees with when the
// moderator (who ends the round) sees it hit zero (#71). Updated from the
// `server_time` field the backend attaches to every timer record.
let clockOffsetSeconds = 0;

function updateClockOffset(record) {
    if (!record || typeof record.server_time !== 'number') return;
    clockOffsetSeconds = record.server_time - Date.now() / 1000;
}

// Best-effort estimate of the server's current time, in epoch seconds.
export function serverNow() {
    return Date.now() / 1000 + clockOffsetSeconds;
}

async function apiRequest(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
        headers: {'Content-Type': 'application/json'},
        ...options
    });

    if (!response.ok) {
        const error = new Error(`API request to ${path} failed with ${response.status}`);
        error.status = response.status;
        throw error;
    }

    return response.status === 204 ? null : response.json();
}

export async function initSubscriptions() {
    console.log("Initialising Subscriptions");
    try {
        await getGamestateRecord();
        initEventStream();
    } catch (e) {
        console.error(e)
    }

    console.log("Subscribed");
}

function initEventStream() {
    if (eventSource) return;

    eventSource = new EventSource(`${API_BASE}/events`);

    eventSource.addEventListener('gamestate', async (event) => {
        const record = JSON.parse(event.data);

        console.log("Received Gamestate Record:\n", record);

        const name = sessionStorage.getItem("name");
        console.log("Registered as: " + name);

        if (name === "player1" || name === "player2") {
            console.log(record.state);
            if (gamestateRecord && gamestateRecord.state === record.state && gamestateRecord.round === record.round) {
                gamestateRecord = record;
                return;
            }
            await loadNextRound(record.round);
            updateView(record.state);
        } else if (name === "Moderator") {
            await onGamestateUpdate(record);
        }
        gamestateRecord = record;
    });

    eventSource.addEventListener('placed_point', (event) => {
        const record = JSON.parse(event.data);
        console.log("Received Point Data:" + JSON.stringify(record));

        const name = sessionStorage.getItem("name");
        console.log("User is:" + name);

        if (name === "Moderator") {
            console.log("Updating Moderator Interface...")
            updateMapPosition(record);
        }
    });

    eventSource.addEventListener('round_config', (event) => {
        const record = JSON.parse(event.data);
        const name = sessionStorage.getItem("name");

        if (name === "Moderator") {
            onModeratorRoundConfigUpdate(record);
        } else if (name === "player1" || name === "player2") {
            onPlayerRoundConfigUpdate(record);
        }
    });

    eventSource.addEventListener('timer', (event) => {
        const record = JSON.parse(event.data);
        const name = sessionStorage.getItem("name");

        updateClockOffset(record);

        if (name === "Moderator") {
            onModeratorTimerUpdate(record);
        } else if (name === "player1" || name === "player2") {
            onPlayerTimerUpdate(record);
        }
    });

    // Applies to every role alike (unlike gamestate/round_config/timer
    // above), and reuses this connection rather than opening a second one -
    // see theme.js's onThemeConfigEvent for why that matters.
    eventSource.addEventListener('theme_config', (event) => {
        onThemeConfigEvent(JSON.parse(event.data));
    });

    // Also applies to every role alike - see theme_config above. Only
    // affects maps created *after* this fires (basemap.js reads the cache
    // at createBaseMapLayer() time), not one already on screen.
    eventSource.addEventListener('map_labels_config', (event) => {
        onMapLabelsConfigEvent(JSON.parse(event.data));
    });

    eventSource.onerror = (err) => {
        console.error("Subscription error: ", err);
    };
}

export async function getGamestateRecord() {
    if (gamestateRecord == null) {
        gamestateRecord = await apiRequest('/gamestate');
    }
    console.log("Gamestate:", gamestateRecord);
    return gamestateRecord;
}

export async function getPlacedPoints(roundNumber) {
    return apiRequest(`/points/${roundNumber}`);
}

export async function getRoundResults() {
    return apiRequest('/round_results');
}

export async function postRoundResult(roundNumber, players) {
    return apiRequest('/round_result', {
        method: 'POST',
        body: JSON.stringify({round_number: roundNumber, players})
    });
}

export async function pushLocation(latlng) {
    const roundnumber = gamestateRecord.round;
    const player = sessionStorage.getItem("name");
    const data = {
        round_number: roundnumber,
        placed_by: player,
        coordinates: {
            lat: Number(latlng.lat),
            lon: Number(latlng.lng)
        }
    };

    console.log(latlng);

    await apiRequest('/points', {method: 'POST', body: JSON.stringify(data)});
}

export async function unlockPlayerInput() {

    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.log("Starting next round...")

    try {
        await apiRequest('/gamestate', {method: 'PATCH', body: JSON.stringify({state: "playing"})});
    } catch (e) {
        console.error(e)
    }
}

export async function lockPlayerInput() {

    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.log("Starting next round...")

    try {
        await apiRequest('/gamestate', {method: 'PATCH', body: JSON.stringify({state: "waiting"})});
    } catch (e) {
        console.error(e)
    }
}

// Broadcasts the "finished" state so player devices (see game.js's
// updateView) navigate themselves to /results once the moderator advances
// past the last round, instead of being left on a waiting screen forever.
export async function finishGame() {
    if (sessionStorage.getItem("name") !== "Moderator") return;

    try {
        await apiRequest('/gamestate', {method: 'PATCH', body: JSON.stringify({state: "finished"})});
    } catch (e) {
        console.error(e)
    }
}

export async function startNextRound() {

    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.log("Starting next round...")

    try {
        // A new round always starts hidden ("waiting") - the moderator has
        // to explicitly reveal it (lockPlayerInputButton in manual mode, or
        // the time-control panel's Start button in countdown mode) rather
        // than it appearing the instant "Weiter" is clicked.
        await apiRequest('/gamestate', {
            method: 'PATCH',
            body: JSON.stringify({
                state: "waiting",
                round: (await getGamestateRecord()).round + 1,
                player1_locked: false,
                player2_locked: false
            })
        });
    } catch (e) {
        console.error(e)
    }
}

export async function resetGameState() {
    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.warn("MEHRZWECKEIER");

    try {
        await apiRequest('/reset', {method: 'POST'});
    } catch (e) {
        console.error(e);
    }
}

export async function lockInSolution() {
    console.log("Locking in...")
    const role = sessionStorage.getItem("name");
    if (role !== 'player1' && role !== 'player2') return;

    await apiRequest('/gamestate', {
        method: 'PATCH',
        body: JSON.stringify({[`${role}_locked`]: true})
    });
    console.log(`Pushed ${getDisplayNames()[role]} lockIn`)
}

export async function getTimerState() {
    const record = await apiRequest('/timer');
    updateClockOffset(record);
    return record;
}

export async function startTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    const record = await apiRequest('/timer/start', {method: 'POST'});
    updateClockOffset(record);
    return record;
}

export async function pauseTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    const record = await apiRequest('/timer/pause', {method: 'POST'});
    updateClockOffset(record);
    return record;
}

export async function resumeTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    const record = await apiRequest('/timer/resume', {method: 'POST'});
    updateClockOffset(record);
    return record;
}

export async function extendTimer(seconds) {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    const record = await apiRequest('/timer/extend', {method: 'POST', body: JSON.stringify({seconds})});
    updateClockOffset(record);
    return record;
}

export async function stopTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    const record = await apiRequest('/timer/stop', {method: 'POST'});
    updateClockOffset(record);
    return record;
}
