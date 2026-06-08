import PocketBase from "../vendor/pocketbase/pocketbase.es.mjs";

const pb = new PocketBase('http://192.168.179.2:8090/');


let initPromise = null;

export function init_pocketbase() {
    if (!initPromise) {
        initPromise = (async () => {
            await pb.collection("users").authWithPassword(
                "nico@mail.de",
                "12345678"
            );
        })();
    }
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