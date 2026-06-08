import PocketBase from "../vendor/pocketbase/pocketbase.es.mjs";

const pb = new PocketBase('http://192.168.172.2');


function init() {
    pb.collection('placed_points').subscribe('*', function (e) {
        console.log('Event:', e.action);
        console.log('Record:', e.record);
    });
}


export async function pushLockedLocation(location) {
    try {
        await pb.collection('placed_points').create({
            round_number: 1,
            by_player: localStorage.getItem('playerName'),
            coordinates: {"lon": location.longitude, "lat": location.latitude}
        });

        console.log('Placed point gespeichert');
    } catch (error) {
        console.error('Fehler beim Speichern:', error);
    }
}

