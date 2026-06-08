import PocketBase from "pocketbase";

const pb = new PocketBase('http://192.168.172.2');


function init() {
    pb.collection('placed_points').subscribe('*', function (e) {
        console.log('Event:', e.action);
        console.log('Record:', e.record);
    });
}


export async function pushLockedLocation(location) {
    print("Sending Data...")
    try {
        await pb.collection('placed_points').send({
            round_number: 1,
            by_player: localStorage.getItem('playerName'),
            coordinates: {"lon": location.longitude, "lat": location.latitude}
        });

        console.log('Placed point gespeichert');
    } catch (error) {
        console.error('Fehler beim Speichern:', error);
    }
}

