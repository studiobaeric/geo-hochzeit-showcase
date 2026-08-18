// Map-based position picker used by /config wherever a lat/lng or a
// download-region bbox would otherwise have to be typed in by hand (see
// issue #30). This is the *only* place those values can be set - the
// config page itself only ever shows a read-only display of the current
// value. Manual numeric entry is still possible, but only via the fields
// inside this picker's own modal.
//
// Two modes share one modal + Leaflet map instance:
//
//  - pickPoint(): for round-photo positions. Prefers the same offline
//    PMTiles basemap the game itself uses ("original experience"), falling
//    back to an online OSM layer when no map has been downloaded yet.
//  - pickBBox(): for a download region's bounding box. Always uses the
//    online OSM layer, since the whole point is choosing what to download
//    before any offline map exists.
//
// Both resolve a Promise with the picked value, or null if the user
// cancelled - callers don't need to know anything about Leaflet.
import { ensurePmtilesProtocol, createBaseMapLayer, createMarkerIcon } from './basemap.js';

const ACCENT_COLOR = '#4f46e5';
const DEFAULT_CENTER = [49.3690, 9.5436];
const DEFAULT_ZOOM = 6;
const DEFAULT_BBOX_BOUNDS = [[32, -25], [72, 45]]; // roughly Europe

const OSM_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>-Mitwirkende';

let dom = null;
let map = null;
let pointMarker = null;
let swHandle = null;
let neHandle = null;
let rectangle = null;
let resolveFn = null;

function fmt(n) {
    return Number(n).toFixed(6);
}

function clampLat(lat) {
    return Math.max(-90, Math.min(90, lat));
}

function clampLon(lon) {
    return Math.max(-180, Math.min(180, lon));
}

function parseBBox(bbox) {
    if (!bbox) return null;
    const parts = String(bbox).split(',').map((part) => parseFloat(part.trim()));
    if (parts.length !== 4 || parts.some((part) => Number.isNaN(part))) return null;
    const [minLon, minLat, maxLon, maxLat] = parts;
    return { minLon, minLat, maxLon, maxLat };
}

function buildDom() {
    if (dom) return dom;

    const overlay = document.createElement('div');
    overlay.className = 'position-picker-overlay';
    overlay.innerHTML = `
        <div class="position-picker-dialog" role="dialog" aria-modal="true">
            <div class="position-picker-header">
                <h3 class="position-picker-title"></h3>
                <button type="button" class="position-picker-close" aria-label="Schließen">&times;</button>
            </div>
            <p class="position-picker-hint"></p>
            <p class="position-picker-notice" hidden></p>
            <div class="position-picker-map"></div>
            <div class="position-picker-manual-point field-row" hidden>
                <div class="field">
                    <label>Breitengrad (lat)</label>
                    <input type="number" step="any" min="-90" max="90" class="position-picker-manual-lat">
                </div>
                <div class="field">
                    <label>Längengrad (lng)</label>
                    <input type="number" step="any" min="-180" max="180" class="position-picker-manual-lng">
                </div>
            </div>
            <div class="position-picker-manual-bbox" hidden>
                <div class="position-picker-manual-bbox-grid">
                    <div class="field">
                        <label>Min. Längengrad (min_lon)</label>
                        <input type="number" step="any" min="-180" max="180" class="position-picker-manual-minlon">
                    </div>
                    <div class="field">
                        <label>Min. Breitengrad (min_lat)</label>
                        <input type="number" step="any" min="-90" max="90" class="position-picker-manual-minlat">
                    </div>
                    <div class="field">
                        <label>Max. Längengrad (max_lon)</label>
                        <input type="number" step="any" min="-180" max="180" class="position-picker-manual-maxlon">
                    </div>
                    <div class="field">
                        <label>Max. Breitengrad (max_lat)</label>
                        <input type="number" step="any" min="-90" max="90" class="position-picker-manual-maxlat">
                    </div>
                </div>
                <button type="button" class="map-pick-button position-picker-use-view">📐 Aktuellen Kartenausschnitt übernehmen</button>
            </div>
            <div class="position-picker-actions">
                <button type="button" class="config-button back position-picker-cancel">Abbrechen</button>
                <button type="button" class="config-button save position-picker-confirm" disabled>✓ Übernehmen</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    dom = {
        overlay,
        title: overlay.querySelector('.position-picker-title'),
        hint: overlay.querySelector('.position-picker-hint'),
        notice: overlay.querySelector('.position-picker-notice'),
        mapEl: overlay.querySelector('.position-picker-map'),
        manualPointWrap: overlay.querySelector('.position-picker-manual-point'),
        manualLat: overlay.querySelector('.position-picker-manual-lat'),
        manualLng: overlay.querySelector('.position-picker-manual-lng'),
        manualBboxWrap: overlay.querySelector('.position-picker-manual-bbox'),
        manualMinLon: overlay.querySelector('.position-picker-manual-minlon'),
        manualMinLat: overlay.querySelector('.position-picker-manual-minlat'),
        manualMaxLon: overlay.querySelector('.position-picker-manual-maxlon'),
        manualMaxLat: overlay.querySelector('.position-picker-manual-maxlat'),
        useViewButton: overlay.querySelector('.position-picker-use-view'),
        closeButton: overlay.querySelector('.position-picker-close'),
        cancelButton: overlay.querySelector('.position-picker-cancel'),
        confirmButton: overlay.querySelector('.position-picker-confirm')
    };

    dom.closeButton.addEventListener('click', () => finish(null));
    dom.cancelButton.addEventListener('click', () => finish(null));
    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) finish(null);
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && overlay.classList.contains('is-active')) finish(null);
    });

    return dom;
}

function teardownMap() {
    if (map) {
        map.remove();
        map = null;
    }
    pointMarker = null;
    swHandle = null;
    neHandle = null;
    rectangle = null;
}

function finish(result) {
    if (!resolveFn) return;
    const resolve = resolveFn;
    resolveFn = null;
    teardownMap();
    dom.overlay.classList.remove('is-active');
    resolve(result);
}

async function hasOfflineMap() {
    try {
        const response = await fetch('/static/data/basemap.pmtiles', { method: 'HEAD' });
        return response.ok;
    } catch (error) {
        return false;
    }
}

async function attachOfflineLayer(targetMap, mapEl) {
    ensurePmtilesProtocol();
    // City names always shown here regardless of the game's "map without
    // city names" setting (#38) - this is the moderator placing a round
    // photo's position, not a player guessing one.
    const layer = await createBaseMapLayer({ interactive: true, hideCityLabels: false });
    layer.addTo(targetMap);
    // Same quirk workaround as game.js: the MapLibre canvas otherwise
    // swallows clicks/drags meant for Leaflet's own marker layer.
    targetMap.getContainer().style.pointerEvents = 'auto';
    setTimeout(() => {
        const canvas = mapEl.querySelector('.maplibregl-canvas');
        if (canvas) canvas.style.pointerEvents = 'none';
    }, 0);
}

function attachOnlineLayer(targetMap) {
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: OSM_ATTRIBUTION
    }).addTo(targetMap);
}

function handleIcon() {
    return L.divIcon({
        className: 'position-picker-handle',
        iconSize: [18, 18],
        iconAnchor: [9, 9]
    });
}

/**
 * Opens the picker to choose a single lat/lng, e.g. for a round photo's
 * location. Resolves { lat, lng } or null if cancelled.
 */
export function pickPoint({ lat, lng, title } = {}) {
    const d = buildDom();
    const hasInitial = Number.isFinite(lat) && Number.isFinite(lng);

    d.title.textContent = title ? `Position wählen – ${title}` : 'Position auf der Karte wählen';
    d.hint.textContent = 'Karte antippen, die Markierung ziehen oder die Koordinaten unten eintragen.';
    d.manualPointWrap.hidden = false;
    d.manualBboxWrap.hidden = true;
    d.notice.hidden = true;
    d.confirmButton.disabled = !hasInitial;
    d.manualLat.value = hasInitial ? fmt(lat) : '';
    d.manualLng.value = hasInitial ? fmt(lng) : '';

    return new Promise((resolve) => {
        resolveFn = resolve;
        d.overlay.classList.add('is-active');

        let current = hasInitial ? { lat, lng } : null;
        d.confirmButton.onclick = () => finish(current ? { lat: current.lat, lng: current.lng } : null);

        map = L.map(d.mapEl, { minZoom: 1, maxZoom: 18 });
        map.setView(current ? [current.lat, current.lng] : DEFAULT_CENTER, current ? 15 : DEFAULT_ZOOM);

        function place(latlng, { syncInputs = true } = {}) {
            current = { lat: latlng.lat, lng: latlng.lng };
            if (!pointMarker) {
                pointMarker = L.marker(latlng, {
                    icon: createMarkerIcon('/static/img/marker-icon-2x-blue.png'),
                    draggable: true
                }).addTo(map);
                pointMarker.on('drag', (event) => place(event.target.getLatLng()));
            } else {
                pointMarker.setLatLng(latlng);
            }
            if (syncInputs) {
                d.manualLat.value = fmt(current.lat);
                d.manualLng.value = fmt(current.lng);
            }
            d.confirmButton.disabled = false;
        }

        if (current) place(L.latLng(current.lat, current.lng));
        map.on('click', (event) => place(event.latlng));

        function applyManualInputs() {
            const manualLat = parseFloat(d.manualLat.value);
            const manualLng = parseFloat(d.manualLng.value);
            if (!Number.isFinite(manualLat) || !Number.isFinite(manualLng)) return;
            const latlng = L.latLng(clampLat(manualLat), clampLon(manualLng));
            place(latlng, { syncInputs: false });
            map.panTo(latlng);
        }
        d.manualLat.oninput = applyManualInputs;
        d.manualLng.oninput = applyManualInputs;

        hasOfflineMap().then((offlineAvailable) => {
            if (offlineAvailable) {
                attachOfflineLayer(map, d.mapEl);
            } else {
                attachOnlineLayer(map);
                d.notice.hidden = false;
                d.notice.textContent =
                    'ℹ️ Die Offline-Karte wurde noch nicht heruntergeladen – Online-Karte wird angezeigt.';
            }
        });

        setTimeout(() => map.invalidateSize(), 50);
    });
}

/**
 * Opens the picker to choose a download-region bbox. Resolves
 * { bbox: "min_lon,min_lat,max_lon,max_lat" } or null if cancelled.
 */
export function pickBBox({ bbox, title } = {}) {
    const d = buildDom();
    const parsed = parseBBox(bbox);

    d.title.textContent = title ? `Kartenausschnitt wählen – ${title}` : 'Kartenausschnitt wählen';
    d.hint.textContent =
        'Eckpunkte ziehen, die Karte verschieben/zoomen und übernehmen, oder den Kartenausschnitt ' +
        'unten eintragen.';
    d.manualPointWrap.hidden = true;
    d.manualBboxWrap.hidden = false;
    d.notice.hidden = true;
    d.confirmButton.disabled = false;
    d.manualMinLon.value = parsed ? fmt(parsed.minLon) : '';
    d.manualMinLat.value = parsed ? fmt(parsed.minLat) : '';
    d.manualMaxLon.value = parsed ? fmt(parsed.maxLon) : '';
    d.manualMaxLat.value = parsed ? fmt(parsed.maxLat) : '';

    return new Promise((resolve) => {
        resolveFn = resolve;
        d.overlay.classList.add('is-active');

        let bounds = parsed
            ? L.latLngBounds([parsed.minLat, parsed.minLon], [parsed.maxLat, parsed.maxLon])
            : L.latLngBounds(...DEFAULT_BBOX_BOUNDS);

        function bboxString(b) {
            return [
                fmt(clampLon(b.getWest())),
                fmt(clampLat(b.getSouth())),
                fmt(clampLon(b.getEast())),
                fmt(clampLat(b.getNorth()))
            ].join(',');
        }

        function syncManualInputs() {
            d.manualMinLon.value = fmt(clampLon(bounds.getWest()));
            d.manualMinLat.value = fmt(clampLat(bounds.getSouth()));
            d.manualMaxLon.value = fmt(clampLon(bounds.getEast()));
            d.manualMaxLat.value = fmt(clampLat(bounds.getNorth()));
        }

        function syncFromHandles() {
            bounds = L.latLngBounds(swHandle.getLatLng(), neHandle.getLatLng());
            rectangle.setBounds(bounds);
            syncManualInputs();
        }

        function renderHandles({ refit = false, syncInputs = true } = {}) {
            const sw = bounds.getSouthWest();
            const ne = bounds.getNorthEast();

            if (!rectangle) {
                rectangle = L.rectangle(bounds, { color: ACCENT_COLOR, weight: 2, fillOpacity: 0.12 }).addTo(map);
            } else {
                rectangle.setBounds(bounds);
            }

            if (!swHandle) {
                swHandle = L.marker(sw, { icon: handleIcon(), draggable: true }).addTo(map);
                swHandle.on('drag', syncFromHandles);
            } else {
                swHandle.setLatLng(sw);
            }

            if (!neHandle) {
                neHandle = L.marker(ne, { icon: handleIcon(), draggable: true }).addTo(map);
                neHandle.on('drag', syncFromHandles);
            } else {
                neHandle.setLatLng(ne);
            }

            if (syncInputs) syncManualInputs();
            if (refit) map.fitBounds(bounds, { padding: [20, 20] });
        }

        function applyManualBbox() {
            const minLon = parseFloat(d.manualMinLon.value);
            const minLat = parseFloat(d.manualMinLat.value);
            const maxLon = parseFloat(d.manualMaxLon.value);
            const maxLat = parseFloat(d.manualMaxLat.value);
            if (![minLon, minLat, maxLon, maxLat].every(Number.isFinite)) return;
            bounds = L.latLngBounds(
                [clampLat(minLat), clampLon(minLon)],
                [clampLat(maxLat), clampLon(maxLon)]
            );
            renderHandles({ syncInputs: false });
        }
        [d.manualMinLon, d.manualMinLat, d.manualMaxLon, d.manualMaxLat].forEach((input) => {
            input.oninput = applyManualBbox;
        });

        d.useViewButton.onclick = () => {
            bounds = map.getBounds();
            renderHandles();
        };
        d.confirmButton.onclick = () => finish({ bbox: bboxString(bounds) });

        map = L.map(d.mapEl, { minZoom: 1, maxZoom: 18 });
        attachOnlineLayer(map);
        map.fitBounds(bounds, { padding: [20, 20] });
        renderHandles();

        setTimeout(() => map.invalidateSize(), 50);
    });
}
