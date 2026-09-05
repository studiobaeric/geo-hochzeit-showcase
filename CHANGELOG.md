# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and version numbers follow [Semantic Versioning](https://semver.org/) once
the first tagged release exists. See [RELEASING.md](RELEASING.md) for how
entries here turn into a tagged release with downloadable binaries.

## [Unreleased]

### Added
- Config menu (`/config`) now has a "Gefahrenzone" section at the very
  bottom with a "Spiel komplett zurücksetzen" button, running the same
  factory reset as `tools/reset_state.py` (via `POST /api/reset-to-defaults`)
  directly from the browser. A confirmation dialog requires typing
  "Where2Win" exactly before the reset button is even clickable, so it
  can't be triggered by an accidental click (#137).
- `tools/reset_state.py` CLI to reset the system to its default state:
  restores player names/round settings to their defaults, deletes all
  uploaded profile/round photos and the current game progress, and
  restores the shipped default round photos (rather than leaving none),
  so the app is ready to be configured again from scratch for a new
  event (#72). The default round *and* player profile photos' files are
  never deleted from disk (even if removed/replaced from `/config`), so
  they stay recoverable; and, like uploaded round photos, the default
  round photos now ship both a downscaled copy and a full-resolution one
  for the moderator's beamer view (#86). Works against a running server
  too: if one answers at `RESET_SERVER_URL` (defaulting to
  `http://127.0.0.1:8080`), the reset happens through its own new
  `POST /api/reset-to-defaults` so the change is live immediately,
  instead of only writing to disk and needing a restart to take effect.
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

### Fixed

- Countdown timer (`/api/timer`) now sends the server's clock reading with
  every update, and the moderator's and players' browsers use it to correct
  for their own clock drift instead of trusting their own `Date.now()`
  outright. Previously a device whose system clock was off by even a couple
  of seconds would show the round countdown starting already wrong and
  disagreeing with when the moderator's browser actually ends the round
  (#71).

### Changed

- Countdown mode no longer jumps straight to the solution view when the
  timer runs out or once both players have locked in their guess - it now
  just stops the timer and locks player input, the same as it already did
  when the moderator pressed the resolve button manually. Revealing the
  solution still requires the moderator to click "Runde auflösen" (renamed
  from "Auflösung"), so they can moderate/discuss the round first. The
  countdown's "Start" button is also now disabled instead of clickable
  again once it's been used for a round, preventing an accidental restart
  from re-opening player input mid-round. The moderator's countdown display
  now reads 0:00 (instead of jumping back up to the full round duration)
  once the round has stopped this way, until the next round starts (#101).
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
