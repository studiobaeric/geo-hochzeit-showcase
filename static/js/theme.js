// Runtime-editable color theme (light/dark), set via the /config menu and
// backed by /api/theme-config so a change made on one device is broadcast to
// every other connected device immediately (via /api/events SSE) and applies
// to every page loaded afterwards - unlike localStorage alone, which would
// stay stuck to a single browser. localStorage is still used as a
// flash-free cache for the *next* load on this browser (see theme-init.js).
const CONFIG_ENDPOINT = '/api/theme-config';
const EVENTS_ENDPOINT = '/api/events';
const STORAGE_KEY = 'geohochzeit-theme-mode';

const DEFAULTS = { mode: 'dark' };

// Mirrors theme.css's --color-bg for each mode, since the mobile browser
// chrome (status bar / task switcher) reads <meta name="theme-color">
// rather than CSS custom properties.
const THEME_COLOR = { light: '#f4f5f7', dark: '#0b1120' };

let cache = { ...DEFAULTS };

function applyTheme(mode) {
    document.documentElement.setAttribute('data-theme', mode);

    const themeColorMeta = document.querySelector('meta[name="theme-color"]');
    if (themeColorMeta) {
        themeColorMeta.setAttribute('content', THEME_COLOR[mode] || THEME_COLOR.dark);
    }

    try {
        localStorage.setItem(STORAGE_KEY, mode);
    } catch (error) {
        // localStorage unavailable (private mode, etc.) - theme still works
        // for this page load, just without the flash-free cache.
    }
}

export function getThemeConfig() {
    return cache;
}

export async function loadThemeConfig() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            cache = await response.json();
        }
    } catch (error) {
        console.error('Konnte Theme-Konfiguration nicht laden, verwende Standardwerte:', error);
    }
    applyTheme(cache.mode);
    return cache;
}

export async function saveThemeConfig({ mode }) {
    const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode })
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Speichern fehlgeschlagen (${response.status})`);
    }

    cache = await response.json();
    applyTheme(cache.mode);
    return cache;
}

let eventSource = null;

// Applies theme changes made on other devices as soon as they happen, so the
// whole party stays visually in sync without anyone reloading a page.
export function subscribeThemeUpdates() {
    if (eventSource) return;

    eventSource = new EventSource(EVENTS_ENDPOINT);
    eventSource.addEventListener('theme_config', (event) => {
        cache = JSON.parse(event.data);
        applyTheme(cache.mode);
    });
    eventSource.onerror = (error) => {
        console.error('Theme-Sync-Verbindung getrennt:', error);
    };
}
