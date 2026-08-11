import {onGamestateUpdate, updateMapPosition} from './moderator.js';
import {loadNextRound, updateView} from "./game.js";
import {getDisplayNames} from './player-names.js';

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
        await apiRequest('/gamestate', {
            method: 'PATCH',
            body: JSON.stringify({
                state: "playing",
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
