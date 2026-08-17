# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and version numbers follow [Semantic Versioning](https://semver.org/) once
the first tagged release exists. See [RELEASING.md](RELEASING.md) for how
entries here turn into a tagged release with downloadable binaries.

## [Unreleased]

### Added
- Config menu (`/config`) now has a "Verlängerung pro Klick (Sekunden)" field
  for countdown mode, so the amount of time the moderator's timer "+Xs"
  button adds per click is editable instead of a fixed 30 seconds (#42).
- Config menu (`/config`) can now upload player profile photos and manage
  round photos (add/edit/delete, unlimited count) directly in the browser,
  instead of hand-editing `static/config/players.js` / `photos.json`.
  Uploading a round photo auto-fills its position from the photo's GPS
  EXIF metadata when present, still editable afterwards. All photos are
  shown blurred behind a click-to-reveal spoiler to avoid accidentally
  exposing round locations on a shared screen.

### Changed

- Renamed the project to "Kartenquiz" (previously "Hochzeits-Geoguesser"),
  updating page titles, the README, and release artifact/binary names.
- CI workflows now use `actions/checkout@v7`, `actions/setup-python@v7`,
  `actions/upload-artifact@v7`, `actions/download-artifact@v8`, and
  `softprops/action-gh-release@v3`, all of which run on Node.js 24 instead
  of the deprecated Node.js 20.
- The `pytest` CI job now also tests Python 3.13, plus a "latest" entry
  pinned to `setup-python`'s bare `"3"` version spec, which always resolves
  to the newest available stable CPython 3.x release - so each new Python
  version starts getting tested automatically, without a workflow edit,
  the day it's released. A failure on that entry is a normal, visible,
  blocking CI failure like any other version. The end-to-end smoke test
  job now runs on that same rolling latest version too, instead of a
  fixed `3.12`.
