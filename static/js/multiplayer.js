import PocketBase from "../vendor/pocketbase/pocketbase.es.mjs";

const pb = new PocketBase('http://192.168.179.2:8090/');


let initPromise = null;

export function init_pocketbase() {
    if (initPromise) return initPromise; // prevent duplicates

    initPromise = (async () => {
        const authData = await pb.collection("users").authWithPassword(
            "nico@mail.de",
            "12345678"
        );

        console.log(pb.authStore.isValid);
        console.log(pb.authStore.token);
        console.log(pb.authStore.model);

        pb.collection('placed_points').subscribe('*', (e) => {
            console.log('Event:', e.action);
            console.log('Record:', e.record);
        });
    })();

    return initPromise;
}


export async function pushLockedLocation(latlng, roundnumber) {
    if (!pb.authStore.isValid) {
        await init_pocketbase();
    }

    let player = localStorage.getItem("playerName");
    player = player.toLowerCase();

    console.log(latlng);

    await pb.collection("placed_points").create({
        round_number: roundnumber,
        placed_by: player,
        coordinates: {
            lat: Number(latlng.lat),
            lon: Number(latlng.lng)
        }
    });
}