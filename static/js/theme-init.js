// Applies the last-known theme (light/dark) synchronously, before the page
// paints and before the (deferred, module-loaded) theme.js has a chance to
// fetch anything from the server. Without this, every page load would flash
// the default theme for a moment before switching to the configured one.
// Deliberately a plain classic script (no type="module", no defer) so the
// browser runs it immediately and blocks rendering until it's done - must be
// the first thing in <head>, before any stylesheet.
(function () {
    try {
        var cached = localStorage.getItem('geohochzeit-theme-mode');
        if (cached === 'light' || cached === 'dark') {
            document.documentElement.setAttribute('data-theme', cached);
        }
    } catch (error) {
        // localStorage unavailable (private mode, etc.) - theme.js will
        // still apply the server-side setting once it loads.
    }
})();
