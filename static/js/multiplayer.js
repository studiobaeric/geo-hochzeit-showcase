import PocketBase from "../vendor/pocketbase/pocketbase.es.mjs";

const pb = new PocketBase('http://192.168.179.2:8090/');

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

    console.log();

    pb.collection('gamestate').subscribe('*', (e) => {
        const record = e.record

        console.log("record:" + e.record);
        console.log(record.state)

        if (e.action === "update") {
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

        if (e.action === "update") {
            const name = localStorage.getItem("name");
            console.log("User is:" + name);
            if (name === "Moderator") {
                console.log("Updating Moderator Interface...")

                //Moderator Interface Change

            }
        }
    });

    console.log("Initialization finished");

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