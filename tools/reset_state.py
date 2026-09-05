#!/usr/bin/env python3
"""Reset Kartenquiz/Where2Win to its default out-of-the-box state.

Wipes everything that gets customized for one event - player names/photos
(game_state.py's player_config), round-timing settings (round_config), the
list of round photos with their guess locations (photo_config.py's
static/config/photos.json, restored to the shipped defaults rather than
emptied - see photo_config._DEFAULT_ROUND_PHOTOS) and any in-progress game
(round/score/timer) - so the app is ready to be configured again from
scratch for a new event.

Works whether the server is running or not:
  - If a server answers at SERVER_URL (env var RESET_SERVER_URL, defaulting
    to http://127.0.0.1:<app.PORT>), the reset happens through its own
    POST /api/reset-to-defaults - the exact same reset functions below,
    just called inside that already-running process. Its in-memory state,
    the files it persists to, and every connected client (via the
    player_config/round_config/gamestate SSE broadcasts those functions
    already send) all pick up the change immediately - no restart needed.
  - Otherwise (no server running, e.g. before it's ever been started),
    this falls back to writing straight to the files
    game_state.py/photo_config.py persist to (GAME_STATE_FILE /
    ROUND_PHOTOS_FILE, defaulting to data/game_state.json and
    static/config/photos.json next to this script's project root) - the
    same way those modules load them back on the next `python app.py`
    startup. A server started *after* this runs picks the new state up
    normally, same as any other out-of-band edit to those files.

Usage:
    python tools/reset_state.py          # asks for confirmation first
    python tools/reset_state.py --yes    # reset without asking
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import game_state  # noqa: E402
import photo_config  # noqa: E402
from app import PORT  # noqa: E402

SERVER_URL = os.environ.get("RESET_SERVER_URL", f"http://127.0.0.1:{PORT}")


def _reset_via_running_server():
    """POST to a currently running server's own /api/reset-to-defaults.

    Returns the parsed JSON response on success, or None if no server
    answers at SERVER_URL - connection refused, timed out, or an error
    response - in which case the caller falls back to resetting the files
    directly.
    """
    req = urllib.request.Request(f"{SERVER_URL}/api/reset-to-defaults", method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def reset(*, confirm) -> None:
    if confirm and not _confirm():
        print("Aborted - nothing was changed.")
        return

    result = _reset_via_running_server()
    if result is not None:
        previous_player_config = result["previous_player_config"]
        photos_removed = result["round_photos_removed"]
        print(f"Reset to default state (via the running server at {SERVER_URL}):")
    else:
        previous_player_config = game_state.reset_to_defaults()
        photos_removed = photo_config.clear_round_photos()
        print("Reset to default state (no running server found - reset the files directly):")

    print(
        f"  - players: {previous_player_config['player1_name']!r}/"
        f"{previous_player_config['player2_name']!r} -> "
        f"{game_state._DEFAULT_PLAYER_CONFIG['player1_name']!r}/"
        f"{game_state._DEFAULT_PLAYER_CONFIG['player2_name']!r}, "
        "custom profile photos cleared"
    )
    print(f"  - round photos: restored to defaults, {photos_removed} self-uploaded photo(s) removed")
    print("  - game progress and round-timing settings: reset to defaults")

    if result is None:
        print(
            f"\nNo server answered at {SERVER_URL}. If one is actually running "
            "(a different host/port, e.g. behind RESET_SERVER_URL), it will keep "
            "serving the old state - including now-deleted photo filenames - until "
            "it's restarted."
        )


def _confirm() -> bool:
    answer = input(
        "This deletes all uploaded player and round photos, restores the "
        "default round photos, and resets player names, round settings and "
        "game progress to their defaults. Continue? [y/N] "
    )
    return answer.strip().lower() in ("y", "yes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "-y", "--yes", action="store_true", help="reset without asking for confirmation"
    )
    args = parser.parse_args()

    reset(confirm=not args.yes)


if __name__ == "__main__":
    main()
