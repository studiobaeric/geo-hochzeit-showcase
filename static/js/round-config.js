// Runtime-editable round timing settings (set via the /config menu), backed
// by /api/round-config so a change made on one device is visible to every
// other device that (re)loads a page afterwards.
const CONFIG_ENDPOINT = '/api/round-config';

const DEFAULTS = { mode: 'manual', duration_seconds: 60 };

let cache = { ...DEFAULTS };

export function getRoundConfig() {
    return cache;
}

export async function loadRoundConfig() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            cache = await response.json();
        }
    } catch (error) {
        console.error('Konnte Rundenzeit-Konfiguration nicht laden, verwende Standardwerte:', error);
    }
    return cache;
}

export async function saveRoundConfig({ mode, duration_seconds }) {
    const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, duration_seconds })
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Speichern fehlgeschlagen (${response.status})`);
    }

    cache = await response.json();
    return cache;
}
