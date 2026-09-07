"""Every locale must translate every key that "de" (the reference locale,
see i18n.py's module docstring) defines - a key missing from one locale
silently falls back to German instead of failing loudly, so this is easy
to miss when adding a new string or a new locale."""

import i18n


def _dotted_keys(tree, prefix=""):
    keys = set()
    for key, value in tree.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            keys |= _dotted_keys(value, f"{dotted}.")
        else:
            keys.add(dotted)
    return keys


def test_every_locale_has_all_reference_keys():
    reference_keys = _dotted_keys(i18n._TRANSLATIONS[i18n.DEFAULT_LOCALE])
    assert reference_keys, "reference locale should not be empty"

    for locale in i18n.SUPPORTED_LOCALES:
        if locale == i18n.DEFAULT_LOCALE:
            continue
        locale_keys = _dotted_keys(i18n._TRANSLATIONS[locale])
        missing = reference_keys - locale_keys
        assert not missing, f"locale {locale!r} is missing translations for: {sorted(missing)}"
