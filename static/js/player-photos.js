// Runtime-editable player profile photos (set via the /config menu), backed
// by /api/player-config so an upload made on one device is visible to every
// other device that (re)loads a page afterwards - unlike a local file,
// which would stay stuck to a single browser.
// static/config/players.js's PHOTO_1/PHOTO_2 remain the fallback used
// before the config API has ever been reached, or while no custom photo
// has been uploaded yet for a role.
//
// `player1`/`player2` are downscaled/recompressed copies - fine for the
// small badges shown on players' own (tablet) screens. `player1_hq`/
// `player2_hq` are the untouched originals, used only by the moderator's
// screen (projected via beamer, so it needs full quality); they fall back
// to the same downscaled copy for photos uploaded before this field existed.
import { PHOTO_1, PHOTO_2 } from '../config/players.js';

const CONFIG_ENDPOINT = '/api/player-config';

let cache = { player1: PHOTO_1, player2: PHOTO_2, player1_hq: PHOTO_1, player2_hq: PHOTO_2 };

function toCache(data) {
    const player1 = data.player1_photo || PHOTO_1;
    const player2 = data.player2_photo || PHOTO_2;
    return {
        player1,
        player2,
        player1_hq: data.player1_photo_hq || player1,
        player2_hq: data.player2_photo_hq || player2
    };
}

export function getPhotoFilenames() {
    return cache;
}

export async function loadPhotoFilenames() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            cache = toCache(await response.json());
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

    cache = toCache(data);
    return cache;
}
