// Shared MapLibre/PMTiles basemap bootstrap used by game.js, moderator.js
// and end_of_game.js. Keeping this in one place avoids the three call
// sites drifting out of sync with each other.

let isPmtilesProtocolRegistered = false;

export function ensurePmtilesProtocol() {
    if (isPmtilesProtocolRegistered) return;

    const pmtilesProtocol = new pmtiles.Protocol();
    maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);
    isPmtilesProtocolRegistered = true;
}

// basemap-style.json is ~260KB. moderator.js alone creates three maps
// (left/right player + resolution) from it, so without caching the raw
// fetch+parse happened three times over on the moderator's device. Fetched
// (and parsed) once per page load and reused from then on.
let stylePromise = null;

function fetchBaseStyle() {
    if (!stylePromise) {
        stylePromise = fetch('/static/data/basemap-style.json').then((response) => response.json());
    }
    return stylePromise;
}

export async function createBaseMapLayer(extraOptions = {}) {
    const cachedStyle = await fetchBaseStyle();
    // Each caller rewrites sprite/glyphs/source URLs (and MapLibre mutates
    // the object further once it's handed off), so every map needs its own
    // copy rather than sharing the cached one.
    const style = JSON.parse(JSON.stringify(cachedStyle));
    const origin = window.location.origin;

    style.sprite = origin + style.sprite;
    style.glyphs = origin + style.glyphs;
    style.sources.protomaps.url = `pmtiles://${origin}/static/data/basemap.pmtiles`;

    return L.maplibreGL({
        style,
        attribution: 'Map data &copy; OpenStreetMap contributors',
        ...extraOptions
    });
}

// Standard Leaflet marker icon (blue/red/green pins) - same size/anchor
// across the app, only the iconUrl differs per player/target.
export function createMarkerIcon(iconUrl) {
    return L.icon({
        iconUrl,
        shadowUrl: '/static/img/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    });
}

export function formatDistance(distanceMeters) {
    if (!Number.isFinite(distanceMeters)) {
        return '-';
    }

    if (distanceMeters < 1000) {
        return `${Math.round(distanceMeters)} m`;
    }

    return `${(distanceMeters / 1000).toFixed(1)} km`;
}
