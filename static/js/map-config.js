// Map-data settings (regions with their own bbox/zoom, build date) and the
// basemap build trigger, set via the /config menu and backed by
// /api/map/* so the initial "download the map" setup step
// (tools/build_basemap*) can be driven from the browser instead of the
// terminal.
const CONFIG_ENDPOINT = '/api/map/config';
const BUILD_ENDPOINT = '/api/map/build';
const STATUS_ENDPOINT = '/api/map/build/status';

const DEFAULTS = {
    regions: [
        { name: 'Welt', bbox: '-180,-90,180,90', maxzoom: 5, effective_bbox: '-180,-90,180,90' },
        { name: 'Europa', bbox: '-25,32,45,72', maxzoom: 13, effective_bbox: '-25,32,45,72' }
    ],
    // '' = resolved to the newest available Protomaps build at build time,
    // mirroring DEFAULT_MAP_CONFIG in map_build.py - never hardcode a fixed
    // date here again, Protomaps' ~5-day retention window will 404 it.
    build_date: '',
    photo_bbox: null
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

export async function saveMapConfig({ regions, build_date }) {
    const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ regions, build_date })
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
