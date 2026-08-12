// Map-data settings (region, zoom, build date) and the basemap build
// trigger, set via the /config menu and backed by /api/map/* so the
// initial "download the map" setup step (tools/build_basemap*.sh) can be
// driven from the browser instead of the terminal.
const CONFIG_ENDPOINT = '/api/map/config';
const BUILD_ENDPOINT = '/api/map/build';
const STATUS_ENDPOINT = '/api/map/build/status';

const DEFAULTS = {
    maxzoom: 13,
    world_maxzoom: 5,
    bbox: '-25,32,45,72',
    build_date: '20260608',
    photo_bbox: null,
    effective_bbox: '-25,32,45,72'
};

let cache = { ...DEFAULTS };

export function getMapConfig() {
    return cache;
}

export async function loadMapConfig() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            cache = await response.json();
        }
    } catch (error) {
        console.error('Konnte Karten-Konfiguration nicht laden, verwende Standardwerte:', error);
    }
    return cache;
}

export async function saveMapConfig({ maxzoom, world_maxzoom, bbox, build_date }) {
    const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ maxzoom, world_maxzoom, bbox, build_date })
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Speichern fehlgeschlagen (${response.status})`);
    }

    cache = await response.json();
    return cache;
}

export async function startMapBuild() {
    const response = await fetch(BUILD_ENDPOINT, { method: 'POST' });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(data.error || `Start fehlgeschlagen (${response.status})`);
    }

    return data;
}

export async function getMapBuildStatus() {
    const response = await fetch(STATUS_ENDPOINT);
    if (!response.ok) {
        throw new Error(`Status-Abfrage fehlgeschlagen (${response.status})`);
    }
    return response.json();
}
