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


export async function pushLockedLocation(location) {
    if (!pb.authStore.isValid) {
        console.log("User is NOT authenticated. Authenticating...");
        await init_pocketbase();
    }

    console.log("Uploading Pinned location...");

    try {
        await pb.collection("placed_points").create({
            round_number: 1,
            by_player: localStorage.getItem("playerName"),
            coordinates: {
                lon: location.longitude,
                lat: location.latitude
            }
        });

        console.log("Placed point gespeichert");
    } catch (error) {
        console.error(error);
    }
}