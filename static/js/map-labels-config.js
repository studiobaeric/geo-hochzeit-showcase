// Runtime-editable "map without city names" option (#38), set via the
// /config menu and backed by /api/map-labels-config so a change made on one
// device is broadcast to every other connected device immediately (via
// /api/events SSE) - mirrors theme.js's approach. basemap.js reads
// getMapLabelsConfig() when building the map style, toggling the
// visibility of the already-downloaded basemap's place-label layers; no
// new map data is fetched for this.
const CONFIG_ENDPOINT = '/api/map-labels-config';
const EVENTS_ENDPOINT = '/api/events';

const DEFAULTS = { hide_city_labels: false };

let cache = { ...DEFAULTS };

export function getMapLabelsConfig() {
    return cache;
}

export async function loadMapLabelsConfig() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            cache = await response.json();
        }
    } catch (error) {
        console.error('Konnte Karten-Beschriftungs-Konfiguration nicht laden, verwende Standardwerte:', error);
    }
    return cache;
}

export async function saveMapLabelsConfig({ hide_city_labels }) {
    const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hide_city_labels })
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Speichern fehlgeschlagen (${response.status})`);
    }

    cache = await response.json();
    return cache;
}

// Applies a map_labels_config record received from *any* /api/events
// stream - this page's own (see subscribeMapLabelsUpdates) or, on pages
// that already keep one open via multiplayer.js's initSubscriptions, that
// shared connection - see theme.js's onThemeConfigEvent for why reusing it
// matters. Only updates the cache basemap.js reads on its next
// createBaseMapLayer() call; it does not re-style a map already on screen.
export function onMapLabelsConfigEvent(record) {
    cache = record;
}

let eventSource = null;

// Only used on pages that don't already keep an /api/events connection
// open via multiplayer.js (start/config/end_of_game/results) - game.html
// and moderator.html instead route map_labels_config through that shared
// connection.
export function subscribeMapLabelsUpdates() {
    if (eventSource) return;

    eventSource = new EventSource(EVENTS_ENDPOINT);
    eventSource.addEventListener('map_labels_config', (event) => {
        onMapLabelsConfigEvent(JSON.parse(event.data));
    });
    eventSource.onerror = (error) => {
        console.error('Karten-Beschriftungs-Sync-Verbindung getrennt:', error);
    };
}
