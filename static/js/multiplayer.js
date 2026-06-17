import PocketBase from "../vendor/pocketbase/pocketbase.es.mjs";
import {onGamestateUpdate, updateMapPosition} from './moderator.js';
import {ClientResponseError} from "../vendor/pocketbase/pocketbase.es.mjs";
import {showView} from "./map.js";

//192.168.179.2
const pb = new PocketBase('http://localhost:8090/');
const gamestate_id = "000000000000000";
let gamestateRecord = null;

export default pb;

export async function initSubscriptions() {
    console.log("Initialising Subscriptions");
    try {
        await initGamestateSubscription();
        await initPlacedPointsSubscription()
        await getGamestateRecord();
    } catch (e) {
        console.error(e)
    }

    console.log("Subscribed");
}

async function initGamestateSubscription() {
    await pb.collection('gamestate').subscribe('*', (e) => {

        const record = e.record;
        console.log("Received Gamestate Record:\n", e.record);

        if (e.action === "create" || e.action === "update") {
            const name = sessionStorage.getItem("name");
            console.log("Registered as: " + name);

            if (name === "Jana" || name === "Tobias") {
                console.log(record.state);
                if (gamestateRecord.state === record.state && gamestateRecord.round === record.round) {
                    gamestateRecord = e.record;
                    return;
                }
                startNextRound();
            }
            if (name === "Moderator") {
                onGamestateUpdate(record);
            }
        }
        gamestateRecord = e.record;
    }, (err) => {
        console.error("Subscription error: ", err);
    });
}

async function initPlacedPointsSubscription() {
    await pb.collection('placed_points').subscribe('*', (e) => {
        console.log("Received Point Data:" + e.record);

        const record = e.record;

        if (e.action === "create" || e.action === "update") {
            const name = sessionStorage.getItem("name");
            console.log("User is:" + name);

            if (name === "Moderator") {
                console.log("Updating Moderator Interface...")
                updateMapPosition(record);
            }
        }
    }, (err) => {
        console.error("Subscription error:  ", err);
    });
}

export async function getGamestateRecord() {
    try {
        if (gamestateRecord == null) {
            gamestateRecord = await pb.collection('gamestate').getFirstListItem('');
        }
        console.log("Gamestate:", gamestateRecord);
        return gamestateRecord;
    } catch (e) {
        if (e instanceof ClientResponseError) {
            gamestateRecord = await pb.collection("gamestate").create({
                id: gamestate_id,
                state: "waiting",
            });
        }
    }
}

export async function pushLocation(latlng) {
    const roundnumber = gamestateRecord.round;
    const player = sessionStorage.getItem("name").toLowerCase();
    const data = {
        round_number: roundnumber,
        placed_by: player,
        coordinates: {
            lat: Number(latlng.lat),
            lon: Number(latlng.lng)
        }
    };

    console.log(latlng);

    try {
        // Try to find an existing record for this round and player
        const existingRecord = await pb.collection("placed_points").getFirstListItem(
            `round_number = ${roundnumber} && placed_by = "${player}"`
        );
        // If found, update it
        await pb.collection("placed_points").update(existingRecord.id, data);
        console.log("Updated existing record");
    } catch (err) {
        // If not found (404), create a new record
        if (err.status === 404) {
            await pb.collection("placed_points").create(data);
            console.log("Created new record");
        } else {
            throw err; // Re-throw other errors
        }
    }
}

export async function unlockPlayerInput() {

    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.log("Starting next round...")

    try {
        pb.collection('gamestate').update(gamestate_id, {state: "playing"});
    } catch (e) {
        console.error(e)
    }
}

export async function lockPlayerInput() {

    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.log("Starting next round...")

    try {
        pb.collection('gamestate').update(gamestate_id, {state: "waiting"});
    } catch (e) {
        console.error(e)
    }
}

export async function startNextRound() {

    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.log("Starting next round...")

    try {
        pb.collection('gamestate').update(gamestate_id, {
            state: "playing",
            round: (await getGamestateRecord()).round + 1,
            jana_locked: false,
            tobias_locked: false
        });
    } catch (e) {
        console.error(e)
    }
}

export async function resetGameState() {
    if (sessionStorage.getItem("name") !== "Moderator") return;

    console.warn("MEHRZWECKEIER");

    try {
        await pb.collection('gamestate').update(gamestate_id, {
            state: "waiting",
            round: 1,
            jana_locked: false,
            tobias_locked: false
        });

        const records = await pb.collection('placed_points').getFullList();

        console.log(records);

        for (const record of records) {
            console.log(record);
            await pb.collection('placed_points').delete(record.id);
        }

    } catch (e) {
        console.error(e);
    }
}

export async function lockInSolution() {
    console.log("Locking in...")
    if (sessionStorage.getItem("name") === "Jana") {
        pb.collection("gamestate").update(gamestate_id, {
            jana_locked: true
        });
        console.log("Pushed Jana lockIn")

    } else if (sessionStorage.getItem("name") === "Tobias") {
        pb.collection("gamestate").update(gamestate_id, {
            tobias_locked: true
        });
        console.log("Pushed Tobias lockIn")
    }
}