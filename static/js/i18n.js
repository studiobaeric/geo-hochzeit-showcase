// Client-side lookups for UI strings that are only assembled at runtime in
// JS (loops, values interpolated into a label) - server-rendered markup is
// already translated by Jinja's `t()` global before it reaches the browser
// (see i18n.py / app.py's inject_i18n), so most strings never go through
// here at all.
//
// window.I18N is set once per page load by a small inline script each
// template embeds right after <body> (see templates/*.html) - the current
// locale's full string tree, already merged with the German fallback
// server-side (see i18n.translations_for), so lookups here need no
// fallback logic of their own.
const EVENTS_ENDPOINT = '/api/events';

export function t(key) {
    let node = window.I18N;
    for (const part of key.split('.')) {
        if (node && typeof node === 'object' && Object.prototype.hasOwnProperty.call(node, part)) {
            node = node[part];
        } else {
            return key;
        }
    }
    return typeof node === 'string' ? node : key;
}

// Like t(), but substitutes `{name}`-style placeholders in the looked-up
// string with `vars.name` - for the handful of strings whose word order
// can't be reproduced by just concatenating translated fragments (e.g. a
// possessive like "{name}'s guess").
export function tf(key, vars) {
    let result = t(key);
    for (const [name, value] of Object.entries(vars)) {
        result = result.replaceAll(`{${name}}`, value);
    }
    return result;
}

let eventSource = null;

// A locale change re-renders every server-side string on the next load, so
// unlike theme_config (applied live via CSS custom properties) the
// simplest correct response to a change made on another device is a full
// reload rather than trying to re-translate the DOM in place.
export function onLocaleConfigEvent(record) {
    if (record.locale && record.locale !== window.I18N_LOCALE) {
        window.location.reload();
    }
}

// Used on pages that don't already keep an /api/events connection open via
// multiplayer.js (start/config/end_of_game/results) - see theme.js's
// subscribeThemeUpdates for why game.html/moderator.html instead route
// locale_config through that shared connection.
export function subscribeLocaleUpdates() {
    if (eventSource) return;

    eventSource = new EventSource(EVENTS_ENDPOINT);
    eventSource.addEventListener('locale_config', (event) => {
        onLocaleConfigEvent(JSON.parse(event.data));
    });
    eventSource.onerror = (error) => {
        console.error('Sprach-Sync-Verbindung getrennt:', error);
    };
}
