// Runtime-editable display names (set via the /config menu), backed by
// /api/player-config so a change made on one device is visible to every
// other device that (re)loads a page afterwards - unlike localStorage,
// which would stay stuck to a single browser.
// static/config/players.js's NAME_1/NAME_2 remain the fallback used before
// the config API has ever been reached (e.g. offline / first paint).
import { NAME_1, NAME_2 } from '../config/players.js';
import { tf } from './i18n.js';

const CONFIG_ENDPOINT = '/api/player-config';

let cache = { player1: NAME_1, player2: NAME_2 };

export function getDisplayNames() {
    return cache;
}

export async function loadDisplayNames() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            const data = await response.json();
            cache = {
                player1: data.player1_name || NAME_1,
                player2: data.player2_name || NAME_2
            };
        }
    } catch (error) {
        console.error('Konnte Spielernamen nicht laden, verwende Standardwerte:', error);
    }
    return cache;
}

export async function saveDisplayNames({ player1, player2 }) {
    const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player1_name: player1, player2_name: player2 })
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || tf('api.save_failed', { status: response.status }));
    }

    const data = await response.json();
    cache = {
        player1: data.player1_name || NAME_1,
        player2: data.player2_name || NAME_2
    };
    return cache;
}
