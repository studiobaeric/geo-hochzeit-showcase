import PocketBase from "../vendor/pocketbase/pocketbase.es.mjs";
import {updateMapPosition} from './moderator.js';

const pb = new PocketBase('http://localhost:8090/');
const gamestate_id = "000000000000000";
let initPromise = null;
let gamestateRecord = null;


export async function init_pocketbase() {
    if (initPromise) return initPromise; // prevent duplicates
    console.log("Initialising Pocketbase connection...");

    initPromise = (async () => {
        await pb.collection("users").authWithPassword(
            "nico@mail.de",
            "12345678"
        );
        console.log("Authenticated: " + pb.authStore.isValid);
    })();

    await (initPromise);

    console.log("Authorization finished. Subscribing...")

    await initGamestateSubscription();
    await initPlacedPointsSubscription()
    await getGamestateRecord();

    console.log("Initialization finished");

    return pb;
}

async function initGamestateSubscription() {
    await pb.collection('gamestate').subscribe('*', (e) => {

        const record = e.record
        gamestateRecord = record;
        console.log("Received Gamestate Record:\n" + e.record);

        if (e.action === "create" || e.action === "update") {
            const name = sessionStorage.getItem("name");
            console.log("Registered as: " + name);

            if (name === "Jana" || name === "Tobias") {
                console.log(record.state);

                if (record.state === "playing") {
                    window.location.href = "/game";
                } else if (record.state === "waiting") {
                    window.location.href = "/wait_screen";
                }
            }
        }
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
    if (!pb.authStore.isValid) {
        await init_pocketbase();
    }
    if (gamestateRecord == null) {
        gamestateRecord = await pb.collection('gamestate').getFirstListItem('');
    }
    console.log("Received Gamestate:", gamestateRecord);
    return gamestateRecord;
}

export async function pushLocation(latlng) {
    if (!pb.authStore.isValid) {
        await init_pocketbase();
    }

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

export async function startNextRound() {
    console.log(sessionStorage.getItem("name"));
    if (sessionStorage.getItem("name") !== "Moderator") return;

    if (!pb.authStore.isValid) {
        await init_pocketbase();
    }

    console.log("Starting next round...")

    try {
        pb.collection('gamestate').update(gamestate_id, {state: "playing"});
    } catch (e) {
        console.error(e)
    }
}

export async function resetGameState() {
    if (sessionStorage.getItem("name") !== "Moderator") return;

    if (!pb.authStore.isValid) {
        await init_pocketbase();
    }

    console.warn("MEHRZWECKEIER");

    try {
        await pb.collection('gamestate').update(gamestate_id, {
            state: "waiting",
            round: 1
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
