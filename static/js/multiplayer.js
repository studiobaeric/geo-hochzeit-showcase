import {onGamestateUpdate, updateMapPosition, onRoundConfigUpdate as onModeratorRoundConfigUpdate, onTimerUpdate as onModeratorTimerUpdate} from './moderator.js';
import {loadNextRound, updateView, onRoundConfigUpdate as onPlayerRoundConfigUpdate, onTimerUpdate as onPlayerTimerUpdate} from "./game.js";
import {getDisplayNames} from './player-names.js';
import {onThemeConfigEvent} from './theme.js';

const API_BASE = '/api';
let gamestateRecord = null;
let eventSource = null;

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
    return apiRequest('/timer');
}

export async function startTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    return apiRequest('/timer/start', {method: 'POST'});
}

export async function pauseTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    return apiRequest('/timer/pause', {method: 'POST'});
}

export async function resumeTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    return apiRequest('/timer/resume', {method: 'POST'});
}

export async function extendTimer(seconds) {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    return apiRequest('/timer/extend', {method: 'POST', body: JSON.stringify({seconds})});
}

export async function stopTimer() {
    if (sessionStorage.getItem("name") !== "Moderator") return;
    return apiRequest('/timer/stop', {method: 'POST'});
}
