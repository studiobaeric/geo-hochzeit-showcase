// Small always-available "level 0" overview map for /config's Kartendaten
// section (issue #108): shows every configured Kartenausschnitt as a
// rectangle, colour-coded by its zoom cap (degree of detail), and tells
// apart what's actually been downloaded (the last successful build) from
// what's merely configured/pending.
//
// Unlike the real offline basemap (static/data/basemap.pmtiles - fetched on
// demand, can be gigabytes), this needs no map-tile data of its own beyond
// static/data/world-land-110m.geojson: a ~85KB, 110m-resolution (i.e. very
// vague) land-outline simplification of Natural Earth's public-domain
// ne_110m_land dataset, small enough to ship with the app/binary itself
// rather than being downloaded on demand, so the map is available
// immediately and works fully offline before any real download - and
// before the user has even opened the picker once.

const WORLD_BOUNDS = [[-85, -180], [85, 180]];
const WORLD_LAND_URL = '/static/data/world-land-110m.geojson';
const OCEAN_FILL = '#dce7f0';
const LAND_FILL = '#c9d9c3';
const LAND_BORDER = '#a9bfa1';
const GRATICULE_COLOR = '#9fb4c4';
const LON_LINES = [-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150];
const LAT_LINES = [-60, -30, 0, 30, 60];

// Fetched (and parsed) once and reused by every map overview instance on
// the page, the same way basemap.js caches basemap-style.json.
let worldLandPromise = null;

function fetchWorldLand() {
    if (!worldLandPromise) {
        worldLandPromise = fetch(WORLD_LAND_URL).then((response) => response.json());
    }
    return worldLandPromise;
}

// Piecewise colour ramp from "very coarse" to "maximum detail" - shared by
// the map rectangles and the legend so both always agree.
const ZOOM_COLOR_STOPS = [
    { zoom: 0, color: [254, 243, 199] },  // pale amber
    { zoom: 5, color: [251, 191, 36] },   // amber
    { zoom: 8, color: [249, 115, 22] },   // orange
    { zoom: 11, color: [220, 38, 38] },   // red
    { zoom: 14, color: [127, 29, 29] }    // dark red
];

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function rgbToCss([r, g, b]) {
    return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

export function colorForZoom(zoom) {
    const z = Math.max(ZOOM_COLOR_STOPS[0].zoom, Math.min(ZOOM_COLOR_STOPS[ZOOM_COLOR_STOPS.length - 1].zoom, zoom));
    for (let i = 0; i < ZOOM_COLOR_STOPS.length - 1; i++) {
        const from = ZOOM_COLOR_STOPS[i];
        const to = ZOOM_COLOR_STOPS[i + 1];
        if (z >= from.zoom && z <= to.zoom) {
            const t = to.zoom === from.zoom ? 0 : (z - from.zoom) / (to.zoom - from.zoom);
            return rgbToCss(from.color.map((v, idx) => lerp(v, to.color[idx], t)));
        }
    }
    return rgbToCss(ZOOM_COLOR_STOPS[ZOOM_COLOR_STOPS.length - 1].color);
}

function boundsFromBbox(bbox) {
    if (!bbox) return null;
    const parts = String(bbox).split(',').map((part) => parseFloat(part.trim()));
    if (parts.length !== 4 || parts.some((part) => Number.isNaN(part))) return null;
    const [minLon, minLat, maxLon, maxLat] = parts;
    return [[minLat, minLon], [maxLat, maxLon]];
}

function drawGraticule(map, pane) {
    const graticule = L.layerGroup();
    LON_LINES.forEach((lon) => {
        L.polyline([[-85, lon], [85, lon]], { color: GRATICULE_COLOR, weight: 1, interactive: false, pane }).addTo(graticule);
    });
    LAT_LINES.forEach((lat) => {
        L.polyline([[lat, -180], [lat, 180]], { color: GRATICULE_COLOR, weight: 1, interactive: false, pane }).addTo(graticule);
    });
    graticule.addTo(map);
}

function renderLegend(legendEl) {
    if (!legendEl) return;
    legendEl.innerHTML = '';

    const scale = document.createElement('div');
    scale.className = 'overview-map-legend-scale';
    const bar = document.createElement('div');
    bar.className = 'overview-map-legend-bar';
    bar.style.background = `linear-gradient(90deg, ${ZOOM_COLOR_STOPS.map(
        (stop) => `${rgbToCss(stop.color)} ${(stop.zoom / 14) * 100}%`
    ).join(', ')})`;
    scale.appendChild(bar);

    const labels = document.createElement('div');
    labels.className = 'overview-map-legend-labels';
    const first = document.createElement('span');
    first.textContent = 'grob (Zoom 0)';
    const last = document.createElement('span');
    last.textContent = 'sehr detailliert (Zoom 14)';
    labels.appendChild(first);
    labels.appendChild(last);
    scale.appendChild(labels);
    legendEl.appendChild(scale);

    const states = document.createElement('div');
    states.className = 'overview-map-legend-states';
    states.innerHTML =
        '<span class="overview-map-legend-state"><span class="overview-map-legend-swatch is-downloaded"></span>heruntergeladen</span>' +
        '<span class="overview-map-legend-state"><span class="overview-map-legend-swatch is-planned"></span>geplant, noch nicht heruntergeladen</span>';
    legendEl.appendChild(states);
}

/**
 * Creates the overview map inside `mapEl` (and, if given, its legend inside
 * `legendEl`). Returns `{ render, invalidateSize }` - call `render({
 * regions, downloaded })` whenever the configured or downloaded regions
 * change, with the same `{ name, bbox, maxzoom }` shape used elsewhere in
 * this page (an `effective_bbox`, if present, is preferred over `bbox`).
 */
export function createMapOverview(mapEl, legendEl) {
    const map = L.map(mapEl, {
        center: [20, 10],
        zoom: 1,
        minZoom: 1,
        maxZoom: 6,
        maxBounds: WORLD_BOUNDS,
        maxBoundsViscosity: 1.0,
        attributionControl: false,
        zoomSnap: 0.5
    });

    // Ocean, land and graticule all sit in a dedicated pane below Leaflet's
    // default overlayPane (used by regionLayer below), so the land outline
    // - fetched asynchronously and potentially added after the region
    // rectangles already are - can never end up drawn on top of them.
    map.createPane('mapOverviewBackground');
    map.getPane('mapOverviewBackground').style.zIndex = 350;
    const backgroundPane = 'mapOverviewBackground';

    L.rectangle(WORLD_BOUNDS, {
        color: 'transparent', weight: 0, fillColor: OCEAN_FILL, fillOpacity: 1, interactive: false, pane: backgroundPane
    }).addTo(map);
    fetchWorldLand().then((geojson) => {
        L.geoJSON(geojson, {
            pane: backgroundPane,
            style: { color: LAND_BORDER, weight: 1, fillColor: LAND_FILL, fillOpacity: 1, interactive: false }
        }).addTo(map);
    }).catch(() => {
        // No land outline, no problem - the graticule plus region
        // rectangles are still fully usable on their own.
    });
    drawGraticule(map, backgroundPane);
    map.fitBounds(WORLD_BOUNDS);

    const regionLayer = L.layerGroup().addTo(map);
    renderLegend(legendEl);

    function render({ regions = [], downloaded = [] } = {}) {
        regionLayer.clearLayers();
        const byZoomAsc = (a, b) => a.maxzoom - b.maxzoom;
        const regionKey = (r) => `${r.name}|${r.bbox}|${r.maxzoom}`;
        const downloadedKeys = new Set(downloaded.map(regionKey));

        // Downloaded regions first (solid fill), least to most detailed so
        // a nested detailed region visually sits "inside" the coarser one.
        [...downloaded].sort(byZoomAsc).forEach((region) => {
            const bounds = boundsFromBbox(region.effective_bbox || region.bbox);
            if (!bounds) return;
            const color = colorForZoom(region.maxzoom);
            L.rectangle(bounds, { color, weight: 1, fillColor: color, fillOpacity: 0.55, interactive: false })
                .bindTooltip(`${region.name} – heruntergeladen bis Zoom ${region.maxzoom}`, { sticky: true })
                .addTo(regionLayer);
        });

        // Then configured regions that don't already match a downloaded one
        // exactly - dashed outline plus a faint fill, so "still to
        // download" reads as visually distinct from "already there" even
        // for a world-spanning region, whose border would otherwise sit
        // right on the map's own edge and be invisible.
        [...regions].sort(byZoomAsc).forEach((region) => {
            if (downloadedKeys.has(regionKey(region))) return;
            const bounds = boundsFromBbox(region.effective_bbox || region.bbox);
            if (!bounds) return;
            const color = colorForZoom(region.maxzoom);
            L.rectangle(bounds, { color, weight: 2, dashArray: '6 5', fillColor: color, fillOpacity: 0.15, interactive: false })
                .bindTooltip(`${region.name} – geplant bis Zoom ${region.maxzoom} (noch nicht heruntergeladen)`, { sticky: true })
                .addTo(regionLayer);
        });
    }

    setTimeout(() => map.invalidateSize(), 50);
    return { render, invalidateSize: () => map.invalidateSize() };
}
