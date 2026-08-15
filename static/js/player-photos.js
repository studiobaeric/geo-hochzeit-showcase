// Runtime-editable player profile photos (set via the /config menu), backed
// by /api/player-config so an upload made on one device is visible to every
// other device that (re)loads a page afterwards - unlike a local file,
// which would stay stuck to a single browser.
// static/config/players.js's PHOTO_1/PHOTO_2 remain the fallback used
// before the config API has ever been reached, or while no custom photo
// has been uploaded yet for a role.
import { PHOTO_1, PHOTO_2 } from '../config/players.js';

const CONFIG_ENDPOINT = '/api/player-config';

let cache = { player1: PHOTO_1, player2: PHOTO_2 };

export function getPhotoFilenames() {
    return cache;
}

export async function loadPhotoFilenames() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            const data = await response.json();
            cache = {
                player1: data.player1_photo || PHOTO_1,
                player2: data.player2_photo || PHOTO_2
            };
        }
    } catch (error) {
        console.error('Konnte Spielerfotos nicht laden, verwende Standardwerte:', error);
    }
    return cache;
}

export async function uploadPlayerPhoto(role, file) {
    const formData = new FormData();
    formData.append('photo', file);

    const response = await fetch(`${CONFIG_ENDPOINT}/photo/${role}`, { method: 'POST', body: formData });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || `Hochladen fehlgeschlagen (${response.status})`);
    }

    cache = {
        player1: data.player1_photo || PHOTO_1,
        player2: data.player2_photo || PHOTO_2
    };
    return cache;
}
