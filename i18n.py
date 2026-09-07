"""UI string translations, keyed by dotted lookup paths (e.g.
"config.player.section_title") shared between server-rendered Jinja
templates and client-side JS.

Strings live in static/i18n/<locale>.json as nested objects mirroring the
key path (so "config.player.section_title" is
translations["config"]["player"]["section_title"]). "de" is the reference
locale that every key is first authored in - see the i18n foundation
section of #98 - and every other locale is a key-for-key translation of
it. A key missing from a non-German locale (e.g. a newer string not yet
translated) falls back to the German value instead of breaking the page;
a key missing everywhere falls back to the key itself, so a typo'd lookup
is visibly obvious rather than raising.

Templates use the `t()` Jinja global (see app.py's context processor) for
strings baked into the server-rendered HTML. Inline/module scripts within
those same templates can use `{{ t('key') }}` too, since Jinja renders the
whole file - including <script> blocks - as one text template. Only
strings actually assembled at runtime in JS (loops, dynamic values) go
through static/js/i18n.js's t(), which reads window.I18N - the same
locale's dict (pre-merged with the German fallback) embedded once per page
load via the `i18n_json` context variable, so the client never needs a
separate fetch or its own fallback logic.
"""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "de"
SUPPORTED_LOCALES = ("de", "en", "es", "fr", "it", "pt")

# Shown as option labels in the start page's language menu - each language
# names itself, so no translation is needed.
LOCALE_NAMES = {
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
    "pt": "Português",
}

# Flag icon (static/img/flags/<file>) shown next to each language's name in
# the same menu. Not Unicode flag emoji: those render as plain two-letter
# country-code text rather than a flag on several platforms (Windows shows
# the code by design; various Linux fonts lack flag glyphs entirely), which
# defeats the point of a flag icon - an actual SVG renders identically
# everywhere.
LOCALE_FLAGS = {
    "de": "de.svg",
    "en": "gb.svg",
    "es": "es.svg",
    "fr": "fr.svg",
    "it": "it.svg",
    "pt": "pt.svg",
}

# Released binaries (see tools/build_release.py) ship this module frozen
# into the executable, so __file__ resolves inside PyInstaller's onefile
# temp extraction dir rather than next to the actual executable - mirrors
# app.py's frozen-path handling (see there for details).
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_I18N_DIR = os.path.join(_PROJECT_ROOT, "static", "i18n")


def _load_locale_file(locale):
    path = os.path.join(_I18N_DIR, f"{locale}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read translation file %s: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}


# Loaded once at import time - these are static files shipped with the
# app, not runtime-editable state, so there's nothing to reload.
_TRANSLATIONS = {locale: _load_locale_file(locale) for locale in SUPPORTED_LOCALES}


def _lookup(translations, dotted_key):
    node = translations
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def translate(locale, dotted_key):
    """Look up `dotted_key` in `locale`'s strings, falling back to
    DEFAULT_LOCALE and then to the key itself so a missing translation
    never breaks the page."""
    value = _lookup(_TRANSLATIONS.get(locale, {}), dotted_key)
    if value is not None:
        return value

    value = _lookup(_TRANSLATIONS.get(DEFAULT_LOCALE, {}), dotted_key)
    if value is not None:
        return value

    logger.warning("Missing translation key %r for locale %r (and fallback %r)", dotted_key, locale, DEFAULT_LOCALE)
    return dotted_key


def _deep_merge(base, overrides):
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def translations_for(locale):
    """Full string tree for `locale`, with any key missing from it filled
    in from DEFAULT_LOCALE - what static/js/i18n.js's t() reads via
    window.I18N, so client-side lookups need no fallback logic of their
    own."""
    base = _TRANSLATIONS.get(DEFAULT_LOCALE, {})
    if locale == DEFAULT_LOCALE:
        return base
    return _deep_merge(base, _TRANSLATIONS.get(locale, {}))
