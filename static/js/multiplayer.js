import PocketBase from "../vendor/pocketbase/pocketbase.es.mjs";
import {updateMapPosition} from './moderator.js';

const pb = new PocketBase('http://192.168.179.2:8090/');

const gamestate_id = "000000000000000";


let initPromise = null;

export async function init_pocketbase() {
    if (initPromise) return initPromise; // prevent duplicates
    console.log("Initialising Pocketbase connection...")

    initPromise = (async () => {
        const authData = await pb.collection("users").authWithPassword(
            "nico@mail.de",
            "12345678"
        );

        console.log(pb.authStore.isValid);
        console.log(pb.authStore.token);
        console.log(pb.authStore.model);
    })();

    await initPromise;

    console.log("Authorized. Subscribing...")
    console.log("Connected", pb.realtime.isConnected)

    pb.collection('gamestate').subscribe('*', (e) => {
        const record = e.record
        console.log("record:" + e.record);
        console.log(record.state)

        if (e.action === "create" || e.action === "update") {
            const name = localStorage.getItem("name");
            console.log(name)
            if (name === "Jana" || name === "Tobias") {
                console.log("name")
                if (record.state === "none_finished") {
                    console.log("state")
                    window.location.href = "game.html";
                }
            }
        }
    });

    pb.collection('placed_points').subscribe('*', (e) => {

        console.log("Received Point Data:" + e.record);

        const record = e.record;

        if (e.action === "create" || e.action === "update") {
            const name = localStorage.getItem("name");
            console.log("User is:" + name);
            if (name === "Moderator") {
                console.log("Updating Moderator Interface...")

                //Moderator Interface Change
                updateMapPosition(record);

            }
        }
    });

    console.log("Initialization finished");

    return initPromise;
}


export async function pushLocation(latlng, roundnumber) {
    if (!pb.authStore.isValid) {
        await init_pocketbase();
    }

    const player = localStorage.getItem("playerName").toLowerCase();
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

export function startNextRound() {
    if (localStorage.getItem("name") !== "Moderator") return;

    console.log("Starting next round...")

    pb.collection('gamestate').update(gamestate_id, {state: "none_finished"});
}

