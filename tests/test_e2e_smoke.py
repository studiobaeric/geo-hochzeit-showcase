"""Browser-driven smoke test for the full game/reset flow.

The rest of the suite tests game_state.py's HTTP contract directly (via
Flask's test client) and never loads a page in a real browser, so it can't
catch frontend/backend integration bugs - e.g. a round's points not
actually reaching the server, or the moderator/endscreen scoreboard not
being rebuildable from the persisted JSON after a reload (see #14).

This test runs the real app as a subprocess and drives it with Playwright,
covering exactly that path: start -> moderator + two players -> a round is
played and scored -> a moderator page reload reconstructs the scoreboard
from the server (not sessionStorage) -> the end-of-game screen renders the
same data -> resetting from there clears the persisted game state.

Skipped (not failed) when Playwright/its browser isn't installed, since
it's only pulled in via requirements-e2e.txt and installed in its own CI
job - the regular test job intentionally doesn't have it.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync_api.sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path):
    """Run the real Flask app (not the test client) as a subprocess.

    A subprocess - rather than an in-process thread - is used so the app's
    module-level state (game_state's in-memory dicts, loaded once at
    import time from GAME_STATE_FILE) starts completely fresh and isolated
    from every other test in this suite.
    """
    port = _free_port()
    state_file = tmp_path / "game_state.json"
    env = {**os.environ, "GAME_STATE_FILE": str(state_file)}

    proc = subprocess.Popen(
        [sys.executable, "-c", f"import app; app.app.run(host='127.0.0.1', port={port}, threaded=True)"],
        cwd=REPO_ROOT,
        env=env,
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            probe = browser.new_context().new_page()
            for _ in range(50):
                try:
                    if probe.request.get(base_url).ok:
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            else:
                pytest.fail("Server did not start in time")
            browser.close()

        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_full_round_reload_and_reset_flow(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")

        # Unlock round 1 and have both players place a guess.
        moderator_page.click("#lockPlayerInputButton")
        context.request.post(
            f"{live_server}/api/points",
            data={"round_number": 1, "placed_by": "player1", "coordinates": {"lat": 49.37, "lng": 9.54}},
        )
        context.request.post(
            f"{live_server}/api/points",
            data={"round_number": 1, "placed_by": "player2", "coordinates": {"lat": 50.0, "lng": 10.0}},
        )
        # The moderator page picks up both guesses asynchronously over SSE
        # (see multiplayer.js's `placed_point` listener) - give that a beat
        # to land before resolving the round, or calculatePoints() runs
        # against an empty latestPlayerRecords.
        moderator_page.wait_for_timeout(500)

        # Resolve the round - this is what should persist the round result
        # to the server (game_state.py's /api/round_result). The click
        # itself only dispatches the DOM event; it doesn't wait for the
        # async calculatePoints()/postRoundResult() chain it triggers, so
        # wait for that chain's visible side effect (the round-result view)
        # before asserting on what it persisted.
        moderator_page.click("#mainControlButton")
        moderator_page.wait_for_selector("#continueButton.is-active")
        moderator_page.click("#continueButton")
        moderator_page.wait_for_selector("#roundResultView.is-active")

        round_results = context.request.get(f"{live_server}/api/round_results").json()
        assert len(round_results) == 1
        assert round_results[0]["round_number"] == 1
        player1_points = round_results[0]["players"]["player1"]["points"]
        assert player1_points > 0

        moderator_page.click("#resultContinueButton")

        # A moderator page reload mid-game must rebuild the scoreboard from
        # the server's round results, not reset it to 0 (#14). The element
        # exists in the static HTML immediately (as "0 Punkte"), so waiting
        # for it to merely appear would race restoreScoreState()'s async
        # fetch - wait for the text itself to update instead.
        moderator_page.reload()
        moderator_page.wait_for_function(
            f"document.querySelector('#player1CurrentPoints')?.textContent.includes('{player1_points}')"
        )

        # The end-of-game screen must show the same, server-sourced totals.
        moderator_page.goto(f"{live_server}/end_of_game")
        moderator_page.wait_for_function(
            f"document.querySelector('#player1TotalPoints')?.textContent.includes('{player1_points}')"
        )

        # Resetting from the end screen must clear the persisted game state
        # and send the moderator back to the start page (#14).
        moderator_page.click("#resetGameButton")
        moderator_page.wait_for_url(f"{live_server}/")

        gamestate = context.request.get(f"{live_server}/api/gamestate").json()
        assert gamestate == {
            "state": "waiting",
            "round": 1,
            "player1_locked": False,
            "player2_locked": False,
        }
        assert context.request.get(f"{live_server}/api/round_results").json() == []

        browser.close()


def test_locked_in_guess_survives_reload(live_server):
    """Regression test for #85: a player who locked in a guess and then
    reloaded the page lost the lock (game.js's `isLocked` is a plain module
    variable, so it always started false again), letting them place a new
    guess even though the moderator screen still showed them as locked in.
    Reloading must restore the lock from the server's gamestate record
    instead.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")
        # Wait for the player's own SSE subscription to be live before the
        # moderator broadcasts the unlock, or the broadcast can race ahead
        # of EventSource's connection and never reach this page.
        player1.wait_for_selector("#waitView.active")

        # Unlock round 1 so the player sees the photo, then walk them
        # through the real guess -> lock-in flow (not the API directly),
        # so this exercises the same click handlers a real player hits.
        moderator_page.click("#lockPlayerInputButton")
        player1.wait_for_selector("#photoView.active")
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")
        player1.wait_for_timeout(600)  # let Leaflet finish invalidateSize()

        player1.click("#map")
        player1.wait_for_selector("#lockButton:not(:disabled)")
        player1.click("#lockButton")
        player1.wait_for_selector("#lockButton:disabled")
        player1.wait_for_function(
            "document.querySelector('#lockButton')?.textContent === 'Tipp abgegeben!'"
        )

        gamestate = context.request.get(f"{live_server}/api/gamestate").json()
        assert gamestate["player1_locked"] is True

        player1.reload()
        player1.wait_for_selector("#photoView.active")
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")

        # The lock must already be restored, without the player doing
        # anything - and there must be exactly the one restored marker, not
        # a fresh empty map waiting for a new guess.
        player1.wait_for_selector("#lockButton:disabled")
        player1.wait_for_function(
            "document.querySelector('#lockButton')?.textContent === 'Tipp abgegeben!'"
        )
        player1.wait_for_function("document.querySelectorAll('.leaflet-marker-icon').length === 1")

        # Let the map's own invalidateSize()-triggered re-centering settle
        # before taking a "before" snapshot, or its animation - not the
        # click below - would explain a changed marker position.
        player1.wait_for_timeout(600)
        marker_position_before = player1.eval_on_selector(
            ".leaflet-marker-icon", "el => el.style.transform"
        )

        # Clicking the map must be a no-op post-lock: no second marker, no
        # move of the existing one. (300, 300) - not a corner - so this
        # actually hits the map surface rather than Leaflet's own top-left
        # zoom control, which isn't gated by isLocked and would zoom the
        # view regardless, invalidating this assertion.
        player1.click("#map", position={"x": 300, "y": 300})
        player1.wait_for_timeout(300)
        assert player1.query_selector_all(".leaflet-marker-icon").__len__() == 1
        assert (
            player1.eval_on_selector(".leaflet-marker-icon", "el => el.style.transform")
            == marker_position_before
        )

        browser.close()


def test_unlocked_guess_survives_reload(live_server):
    """Follow-up to #85: a placed-but-not-locked-in guess used to vanish on
    reload (guessMarker is a plain module variable, reset fresh on load),
    even though the point was already persisted server-side via /api/points.
    Reloading must restore the marker, and the guess must still be movable
    and lockable afterwards since it was never locked in.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")
        player1.wait_for_selector("#waitView.active")

        moderator_page.click("#lockPlayerInputButton")
        player1.wait_for_selector("#photoView.active")
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")
        player1.wait_for_timeout(600)  # let Leaflet finish invalidateSize()

        # Place a guess but do NOT lock it in.
        player1.click("#map")
        player1.wait_for_selector("#lockButton:not(:disabled)")

        gamestate = context.request.get(f"{live_server}/api/gamestate").json()
        assert gamestate["player1_locked"] is False

        player1.reload()
        player1.wait_for_selector("#photoView.active")
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")

        # The unlocked guess must reappear on its own, and the lock button
        # must reflect "a guess exists, not yet locked in" - enabled, not
        # showing the locked-in label.
        player1.wait_for_function("document.querySelectorAll('.leaflet-marker-icon').length === 1")
        assert not player1.is_disabled("#lockButton")
        assert player1.text_content("#lockButton") == 'Tipp abgeben'

        # It must still be possible to move the restored guess and lock it
        # in afterwards - restoring the marker must not accidentally lock
        # it. (300, 300) - not a corner - so this actually hits the map
        # surface rather than Leaflet's own top-left zoom control.
        player1.wait_for_timeout(600)
        position_before_move = player1.eval_on_selector(
            ".leaflet-marker-icon", "el => el.style.transform"
        )
        player1.click("#map", position={"x": 300, "y": 300})
        player1.wait_for_timeout(300)
        assert player1.query_selector_all(".leaflet-marker-icon").__len__() == 1
        assert (
            player1.eval_on_selector(".leaflet-marker-icon", "el => el.style.transform")
            != position_before_move
        )

        player1.click("#lockButton")
        player1.wait_for_selector("#lockButton:disabled")
        gamestate = context.request.get(f"{live_server}/api/gamestate").json()
        assert gamestate["player1_locked"] is True

        browser.close()


def test_locking_in_one_player_does_not_lock_the_other(live_server):
    """Player isolation regression test requested on #85's PR: the fix
    reads/writes gamestate's `${role}_locked` keyed by the reloading page's
    own sessionStorage role, so player1 locking in a guess must not lock -
    or otherwise disable - player2's own map/lock button, on the server or
    after either player reloads.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")
        player1.wait_for_selector("#waitView.active")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")
        player2.wait_for_selector("#waitView.active")

        moderator_page.click("#lockPlayerInputButton")
        player1.wait_for_selector("#photoView.active")
        player2.wait_for_selector("#photoView.active")

        # Player1 places a guess and locks it in. Player2 never touches
        # their own map.
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")
        player1.wait_for_timeout(600)
        player1.click("#map")
        player1.wait_for_selector("#lockButton:not(:disabled)")
        player1.click("#lockButton")
        player1.wait_for_selector("#lockButton:disabled")

        gamestate = context.request.get(f"{live_server}/api/gamestate").json()
        assert gamestate["player1_locked"] is True
        assert gamestate["player2_locked"] is False

        # Player2's own map must be entirely unaffected: no guess, lock
        # button in its default "nothing placed yet" state (disabled, but
        # for the opposite reason - no marker, not a lock).
        player2.click("#guessButton")
        player2.wait_for_selector("#mapView.active")
        player2.wait_for_timeout(600)
        assert player2.query_selector_all(".leaflet-marker-icon").__len__() == 0
        assert player2.is_disabled("#lockButton")
        assert player2.text_content("#lockButton") == 'Tipp abgeben'

        # Player2 must still be able to place and lock in their own guess
        # independently.
        player2.click("#map")
        player2.wait_for_selector("#lockButton:not(:disabled)")
        player2.click("#lockButton")
        player2.wait_for_selector("#lockButton:disabled")

        gamestate = context.request.get(f"{live_server}/api/gamestate").json()
        assert gamestate["player1_locked"] is True
        assert gamestate["player2_locked"] is True

        # And a reload of either player must restore only that player's own
        # lock state, not bleed the other's in.
        player1.reload()
        player1.wait_for_selector("#photoView.active")
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")
        player1.wait_for_function(
            "document.querySelector('#lockButton')?.textContent === 'Tipp abgegeben!'"
        )

        player2.reload()
        player2.wait_for_selector("#photoView.active")
        player2.click("#guessButton")
        player2.wait_for_selector("#mapView.active")
        player2.wait_for_function(
            "document.querySelector('#lockButton')?.textContent === 'Tipp abgegeben!'"
        )

        browser.close()


def test_placed_guess_is_not_visible_to_other_player(live_server):
    """Player isolation regression test requested on #85's PR: restoring a
    guess on reload (see restoreGuessState in game.js) fetches every point
    placed for the round via GET /api/points/<round> and must filter down
    to this page's own role - not render whichever player's marker happens
    to come back first, or player2 would see player1's guess (and vice
    versa) instead of their own.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")
        player1.wait_for_selector("#waitView.active")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")
        player2.wait_for_selector("#waitView.active")

        moderator_page.click("#lockPlayerInputButton")
        player1.wait_for_selector("#photoView.active")
        player2.wait_for_selector("#photoView.active")

        # Only player1 places a guess (deliberately at a distinct spot from
        # anything player2 will place below, and away from Leaflet's own
        # top-left zoom control so this actually reaches the map), and
        # does not lock it in.
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")
        player1.wait_for_timeout(600)
        player1.click("#map", position={"x": 300, "y": 300})
        player1.wait_for_selector("#lockButton:not(:disabled)")

        # Player2 opening the map for the first time must see nothing -
        # player1's point, fetched via the same /api/points/<round> call,
        # must not leak onto player2's page.
        player2.click("#guessButton")
        player2.wait_for_selector("#mapView.active")
        player2.wait_for_timeout(600)
        assert player2.query_selector_all(".leaflet-marker-icon").__len__() == 0

        # Player2 places their own guess elsewhere.
        player2.click("#map", position={"x": 200, "y": 150})
        player2.wait_for_selector("#lockButton:not(:disabled)")

        # A reload of each page must restore exactly one marker - that
        # page's own guess, not the other player's.
        player1.reload()
        player1.wait_for_selector("#photoView.active")
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")
        player1.wait_for_function("document.querySelectorAll('.leaflet-marker-icon').length === 1")

        player2.reload()
        player2.wait_for_selector("#photoView.active")
        player2.click("#guessButton")
        player2.wait_for_selector("#mapView.active")
        player2.wait_for_function("document.querySelectorAll('.leaflet-marker-icon').length === 1")

        points = context.request.get(f"{live_server}/api/points/1").json()
        assert len(points) == 2
        placed_by = {record["placed_by"] for record in points}
        assert placed_by == {"player1", "player2"}

        browser.close()


def test_finishing_the_last_round_sends_players_to_their_own_results_screen(live_server):
    """Regression test for #80: nothing in the app used to navigate to
    /results, so it was dead code. Playing through every configured round
    must now broadcast the "finished" gamestate (see moderator.js's
    resultContinueButton handler / multiplayer.js's finishGame()), which
    sends each player's own device to /results - distinct from the
    moderator's shared /end_of_game screen - showing their own totals.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        photos = context.request.get(f"{live_server}/api/round-photos").json()
        num_rounds = len(photos)
        assert num_rounds > 0

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")

        for round_number in range(1, num_rounds + 1):
            moderator_page.click("#lockPlayerInputButton")
            context.request.post(
                f"{live_server}/api/points",
                data={
                    "round_number": round_number,
                    "placed_by": "player1",
                    "coordinates": {"lat": 49.37, "lng": 9.54},
                },
            )
            context.request.post(
                f"{live_server}/api/points",
                data={
                    "round_number": round_number,
                    "placed_by": "player2",
                    "coordinates": {"lat": 50.0, "lng": 10.0},
                },
            )
            moderator_page.wait_for_timeout(500)

            moderator_page.click("#mainControlButton")
            moderator_page.wait_for_selector("#continueButton.is-active")
            moderator_page.click("#continueButton")
            moderator_page.wait_for_selector("#roundResultView.is-active")
            moderator_page.click("#resultContinueButton")

        # The moderator lands on their own shared screen...
        moderator_page.wait_for_url(f"{live_server}/end_of_game")

        # ...while both players are sent to their own per-player screen.
        player1.wait_for_url(f"{live_server}/results")
        player2.wait_for_url(f"{live_server}/results")

        round_results = context.request.get(f"{live_server}/api/round_results").json()
        assert len(round_results) == num_rounds
        player1_total = sum(r["players"]["player1"]["points"] for r in round_results)

        player1.wait_for_function(
            f"document.querySelector('#player1Total')?.textContent.includes('{player1_total}')"
        )
        # Every round played must show up in the per-round breakdown.
        player1.wait_for_function(
            f"document.querySelectorAll('#roundList .round-row').length === {num_rounds}"
        )

        browser.close()


def test_moderator_still_records_guesses_after_a_photo_id_position_drift(live_server):
    """Regression test: players' guesses were silently dropped from the
    moderator's view (and the round scored 0 for everyone) as soon as a
    round's photo id stopped matching its 1-based position in
    photos.json - which happens as soon as /config's round reordering
    (#51) is used (or an earlier photo is deleted).

    Guesses (placed_points) are keyed by round_number = position (see
    multiplayer.js's pushLocation), but moderator.js's isCurrentPhotoRecord
    used to compare that against currentPhoto.id instead - a different
    number space that drifts from position the moment photo ids stop
    matching their array index. Reordering round 1 and round 2 here
    reproduces exactly that drift: round 1 now shows the photo whose id
    is 2, not 1.

    This mutates the real static/config/photos.json via the same
    /api/round-photos/reorder endpoint /config uses (the same file
    game.js/moderator.js fetch directly, so a redirected ROUND_PHOTOS_FILE
    wouldn't be visible to the browser) - the original order is restored
    in `finally` regardless of outcome.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context()

            original_photos = context.request.get(f"{live_server}/api/round-photos").json()
            original_order = [photo["id"] for photo in original_photos]
            swapped_order = [original_order[1], original_order[0], *original_order[2:]]

            reorder_response = context.request.post(
                f"{live_server}/api/round-photos/reorder", data={"order": swapped_order}
            )
            assert reorder_response.ok

            try:
                moderator_page = context.new_page()
                moderator_page.goto(live_server)
                moderator_page.click("button[data-name='Moderator']")
                moderator_page.wait_for_selector("#lockPlayerInputButton")

                player1 = context.new_page()
                player1.goto(live_server)
                player1.click("#player1Button")

                player2 = context.new_page()
                player2.goto(live_server)
                player2.click("#player2Button")

                # Unlock round 1 (now showing the photo that used to be round
                # 2, whose id is 2, not 1) and have both players place a
                # guess, exactly like test_full_round_reload_and_reset_flow.
                moderator_page.click("#lockPlayerInputButton")
                context.request.post(
                    f"{live_server}/api/points",
                    data={"round_number": 1, "placed_by": "player1", "coordinates": {"lat": 49.37, "lng": 9.54}},
                )
                context.request.post(
                    f"{live_server}/api/points",
                    data={"round_number": 1, "placed_by": "player2", "coordinates": {"lat": 50.0, "lng": 10.0}},
                )
                moderator_page.wait_for_timeout(500)

                moderator_page.click("#mainControlButton")
                moderator_page.wait_for_selector("#continueButton.is-active")
                moderator_page.click("#continueButton")
                moderator_page.wait_for_selector("#roundResultView.is-active")

                round_results = context.request.get(f"{live_server}/api/round_results").json()
                assert len(round_results) == 1
                players = round_results[0]["players"]

                # Before the fix both guesses were rejected by
                # isCurrentPhotoRecord (round_number 1 != currentPhoto.id
                # 2), so latestPlayerRecords stayed empty and both players
                # scored 0 despite having placed a guess.
                assert players["player1"]["points"] > 0
                assert players["player2"]["points"] > 0
                assert players["player1"]["markerLocation"] is not None
                assert players["player2"]["markerLocation"] is not None
            finally:
                context.request.post(
                    f"{live_server}/api/round-photos/reorder", data={"order": original_order}
                )
        finally:
            browser.close()


def test_auflosung_keeps_player_input_locked_even_if_already_locked(live_server):
    """Regression test for #66: pressing "Auflösung" toggled the lock state
    instead of unconditionally locking it. If the moderator had already
    locked player input manually (clicking "Spieler Input Erlauben"/
    "Verbieten" a second time) before pressing "Auflösung", the toggle
    flipped the state back to "playing" - re-enabling the players to guess
    on the round that was supposed to be finished.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")
        player1.wait_for_selector("#waitView.active")

        # Unlock round 1 via the UI, then lock it again manually before
        # resolving - this is the sequence that used to make "Auflösung"
        # re-unlock input. The second lock is done via the same API call the
        # button itself makes (rather than a second click on
        # #lockPlayerInputButton) so moderator_page's own gamestate SSE
        # subscription - the thing that actually drives triggerResolution()'s
        # playerInputLocked - is what's being exercised here, not Chromium's
        # click-actionability timing for two clicks on one element.
        moderator_page.click("#lockPlayerInputButton")
        player1.wait_for_selector("#photoView.active")
        moderator_page.wait_for_selector("#lockPlayerInputButton:has-text('Input Verbieten')")

        context.request.patch(f"{live_server}/api/gamestate", data={"state": "waiting"})
        player1.wait_for_selector("#waitView.active")
        moderator_page.wait_for_selector("#lockPlayerInputButton:has-text('Input Erlauben')")

        moderator_page.click("#mainControlButton")
        moderator_page.wait_for_selector("#continueButton.is-active")

        gamestate = context.request.get(f"{live_server}/api/gamestate").json()
        assert gamestate["state"] == "waiting"
        player1.wait_for_selector("#waitView.active")

        browser.close()


def test_basemap_style_is_fetched_once_across_all_moderator_maps(live_server):
    """Regression test for optimization #1 from #79: moderator.js creates
    three MapLibre maps from the same ~260KB static/data/basemap-style.json
    - the left player map and right player map as soon as the moderator
    view loads, then a third (resolutionMap) the first time a round is
    resolved. Before basemap.js cached the parsed style (see its
    fetchBaseStyle()), every one of those calls did its own fetch +
    JSON.parse of that file, so this single page load network-fetched the
    same 260KB three times.

    This drives the moderator through exactly that sequence - page load,
    then Auflösung - and asserts the moderator's page only ever issues ONE
    network request for basemap-style.json, no matter how many maps get
    created. Request *count* is used rather than wall-clock timing, since
    page-load timing is too noisy/flaky to assert on reliably in CI - the
    number of times the same resource is fetched is the direct,
    deterministic signature of the fix.

    The listener is attached to moderator_page specifically, not the
    browser context: each page/tab is its own JS module realm with its own
    independent copy of basemap.js's cache, so player1/player2 (opened
    below, and each loading their own single map via game.js) legitimately
    add one fetch apiece in their own tab - that's expected and unrelated
    to what's being tested here, which is fetch reuse *within* one page.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        style_requests = []

        moderator_page = context.new_page()
        moderator_page.on(
            "request",
            lambda request: style_requests.append(request.url)
            if request.url.endswith("/static/data/basemap-style.json")
            else None,
        )
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")
        # initModeratorMaps() (left + right player maps) runs fire-and-forget
        # right after the moderator view loads - wait for both to actually
        # render before moving on, so their fetches have already happened.
        moderator_page.wait_for_function(
            "document.querySelectorAll('#leftPlayerMap .maplibregl-canvas, "
            "#rightPlayerMap .maplibregl-canvas').length === 2"
        )

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")

        moderator_page.click("#lockPlayerInputButton")
        context.request.post(
            f"{live_server}/api/points",
            data={"round_number": 1, "placed_by": "player1", "coordinates": {"lat": 49.37, "lng": 9.54}},
        )
        context.request.post(
            f"{live_server}/api/points",
            data={"round_number": 1, "placed_by": "player2", "coordinates": {"lat": 50.0, "lng": 10.0}},
        )
        moderator_page.wait_for_timeout(500)

        # Auflösung creates the third map (resolutionMap) - previously a
        # third, separate fetch of the same style JSON.
        moderator_page.click("#mainControlButton")
        moderator_page.wait_for_selector("#continueButton.is-active")
        moderator_page.wait_for_selector("#resolutionMap .maplibregl-canvas")

        assert len(style_requests) == 1, (
            f"expected exactly 1 request for basemap-style.json across the moderator's "
            f"3 maps, got {len(style_requests)}: {style_requests}"
        )

        browser.close()


def test_player_maps_reset_view_for_the_next_round(live_server):
    """Regression test reported against PR #83's review: placing a guess
    zooms that player's map in on the guessed location (updateMapPosition()
    setView-ing to at least zoom 8), but advancing past a round's Auflösung
    used to only clear the guess marker (showModPageNextRound()) - the map
    itself stayed zoomed in on the previous round's guess instead of
    returning to the initial Germany overview the next round should start
    from.

    moderator.js doesn't expose the maps' center/zoom to the page for
    assertions, so this instead patches L.Map.prototype.setView (via an
    init script, before any page script runs) to record every call made on
    the left player map, then checks the *last* recorded zoom once round 2
    starts: it must be back to the initial zoom (5), not left at the
    zoomed-in level a guess sets (>= 8). This needs no production code
    changes - it only observes calls the app already makes.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.add_init_script(
            """
            window.__leftMapSetViewCalls = [];
            let _L;
            Object.defineProperty(window, 'L', {
                configurable: true,
                get() { return _L; },
                set(value) {
                    _L = value;
                    if (value?.Map?.prototype && !value.Map.prototype.__setViewPatched) {
                        const original = value.Map.prototype.setView;
                        value.Map.prototype.setView = function (center, zoom, options) {
                            if (this._container?.id === 'leftPlayerMap') {
                                window.__leftMapSetViewCalls.push(zoom);
                            }
                            return original.call(this, center, zoom, options);
                        };
                        value.Map.prototype.__setViewPatched = true;
                    }
                },
            });
            """
        )
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")
        moderator_page.wait_for_selector("#leftPlayerMap .maplibregl-canvas")

        # createPlayerMap()'s own setView (zoom 5) must have already been
        # recorded by now.
        initial_calls = moderator_page.evaluate("window.__leftMapSetViewCalls")
        assert initial_calls == [5], f"expected only the initial zoom-5 setView, got {initial_calls}"

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")

        moderator_page.click("#lockPlayerInputButton")
        context.request.post(
            f"{live_server}/api/points",
            data={"round_number": 1, "placed_by": "player1", "coordinates": {"lat": 49.37, "lng": 9.54}},
        )
        context.request.post(
            f"{live_server}/api/points",
            data={"round_number": 1, "placed_by": "player2", "coordinates": {"lat": 50.0, "lng": 10.0}},
        )
        moderator_page.wait_for_timeout(500)

        zoomed_calls = moderator_page.evaluate("window.__leftMapSetViewCalls")
        assert zoomed_calls[-1] >= 8, f"expected the guess to zoom in to >= 8, got {zoomed_calls}"

        moderator_page.click("#mainControlButton")
        moderator_page.wait_for_selector("#continueButton.is-active")
        moderator_page.click("#continueButton")
        moderator_page.wait_for_selector("#roundResultView.is-active")
        moderator_page.click("#resultContinueButton")
        moderator_page.wait_for_selector("#moderatorApp:not(.is-hidden)")

        final_calls = moderator_page.evaluate("window.__leftMapSetViewCalls")
        assert final_calls[-1] == 5, (
            f"left player map should have reset to the initial zoom (5) for round 2, "
            f"got setView call history {final_calls}"
        )

        browser.close()


def test_auflosung_map_recenters_exactly_without_animation(live_server):
    """Regression test for #113/#118: Auflösung's resolutionMap.setView()
    used to rely on Leaflet's default animated pan, which only
    approximates the target when it's close to the map's previous center,
    so the map didn't always end up exactly centered on the round's photo
    location. The fix (moderator.js's showResolutionView) passes
    {animate: false} to setView() - forcing an exact, synchronous
    re-center - and {autoPan: false} to the location marker's popup, so
    the popup's own auto-pan (which nudges the view just far enough for
    the popup to fit) can't undo that centering.

    This patches L.Map.prototype.setView and L.Marker.prototype.bindPopup
    (before any page script runs) to record every call made against the
    resolutionMap container / its location marker, then asserts every
    recorded setView call used {animate: false} and targeted exactly the
    resolved round's photo location, and that the location marker's popup
    was bound with {autoPan: false}.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.add_init_script(
            """
            window.__resolutionSetViewCalls = [];
            window.__resolutionPopupOptions = [];
            let _L;
            Object.defineProperty(window, 'L', {
                configurable: true,
                get() { return _L; },
                set(value) {
                    _L = value;
                    if (value?.Map?.prototype && !value.Map.prototype.__setViewPatched) {
                        const originalSetView = value.Map.prototype.setView;
                        value.Map.prototype.setView = function (center, zoom, options) {
                            if (this._container?.id === 'resolutionMap') {
                                window.__resolutionSetViewCalls.push({ center, zoom, options });
                            }
                            return originalSetView.call(this, center, zoom, options);
                        };
                        value.Map.prototype.__setViewPatched = true;
                    }
                    if (value?.Marker?.prototype && !value.Marker.prototype.__bindPopupPatched) {
                        const originalBindPopup = value.Marker.prototype.bindPopup;
                        value.Marker.prototype.bindPopup = function (content, options) {
                            if (options && 'autoPan' in options) {
                                window.__resolutionPopupOptions.push(options);
                            }
                            return originalBindPopup.call(this, content, options);
                        };
                        value.Marker.prototype.__bindPopupPatched = true;
                    }
                },
            });
            """
        )
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        photos = context.request.get(f"{live_server}/api/round-photos").json()
        num_rounds = min(2, len(photos))
        assert num_rounds >= 1

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")

        for round_number in range(1, num_rounds + 1):
            moderator_page.click("#lockPlayerInputButton")
            context.request.post(
                f"{live_server}/api/points",
                data={"round_number": round_number, "placed_by": "player1", "coordinates": {"lat": 49.37, "lng": 9.54}},
            )
            context.request.post(
                f"{live_server}/api/points",
                data={"round_number": round_number, "placed_by": "player2", "coordinates": {"lat": 50.0, "lng": 10.0}},
            )
            moderator_page.wait_for_timeout(500)

            moderator_page.click("#mainControlButton")
            # resolutionMap.setView() gets called from more than just the one
            # line under test here: initResolutionMap() does its own
            # L.map(...).setView(...) the first time it creates the map (no
            # `options` argument, only on round 1), and
            # syncResolutionPlayerMarkers()'s resolutionMap.fitBounds(...)
            # internally calls setView() too (with a `{padding: [...]}`
            # options object, once per round both players have a marker).
            # The recentering call under test - showResolutionView()'s
            # resolutionMap.setView([lat, lng], 13, {animate: false}) - is
            # the only one of the three that ever passes an `animate` key,
            # so filter on that specifically rather than "any options".
            moderator_page.wait_for_function(
                f"window.__resolutionSetViewCalls.filter(c => c.options && 'animate' in c.options)"
                f".length === {round_number}"
            )

            if round_number < num_rounds:
                moderator_page.click("#continueButton")
                moderator_page.wait_for_selector("#roundResultView.is-active")
                moderator_page.click("#resultContinueButton")

        setview_calls = [
            call
            for call in moderator_page.evaluate("window.__resolutionSetViewCalls")
            if call["options"] and "animate" in call["options"]
        ]
        assert len(setview_calls) == num_rounds, (
            f"expected one recentering setView call on the resolution map per "
            f"round resolved (excluding initResolutionMap()'s one-time "
            f"map-creation setView and fitBounds()'s own internal setView, "
            f"neither of which passes an `animate` option), got {setview_calls}"
        )
        for round_number, call in enumerate(setview_calls, start=1):
            expected = photos[round_number - 1]["location"]
            assert call["options"]["animate"] is False, (
                f"round {round_number}'s Auflösung setView must use animate: false "
                f"so the map re-centers exactly instead of approximating via an "
                f"animated pan, got {call}"
            )
            assert call["center"][0] == pytest.approx(expected["lat"], abs=1e-6)
            assert call["center"][1] == pytest.approx(expected["lng"], abs=1e-6)

        popup_options = moderator_page.evaluate("window.__resolutionPopupOptions")
        assert any(options.get("autoPan") is False for options in popup_options), (
            "the resolution map's location-marker popup must be bound with "
            "autoPan: false, or its own auto-pan can undo the map's exact "
            "re-centering onto the photo location"
        )

        browser.close()


def test_guess_map_canvas_is_resized_once_visible(live_server):
    """Regression test for #90/#93: the player's guess map is created (as
    part of initGame()) while #mapView can still be display:none - e.g.
    before the player has clicked "Tipp abgeben" - so MapLibre GL sizes
    its WebGL canvas from a 0x0 container, leaving the map blank once the
    view becomes visible (reported on Android tablets, though the
    underlying "canvas created while hidden" issue isn't browser-specific).
    The fix explicitly calls the underlying maplibregl.Map's resize(),
    both when #mapView becomes visible (showView()'s setTimeout) and, if
    the view was already visible by then, once the basemap layer finishes
    loading (initGame()'s createBaseMapLayer().then(...)) - covering both
    possible orderings of "view becomes visible" vs. "basemap finishes
    loading".

    This patches maplibregl.Map.prototype.resize (before any page script
    runs) to record every call, then asserts resize() was actually invoked
    for the player's guess map by the time it's visible, and that the
    visible canvas ends up with a non-zero size - the concrete symptom of
    the original bug.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        player1 = context.new_page()
        player1.add_init_script(
            """
            window.__resizeCallCount = 0;
            let _maplibregl;
            Object.defineProperty(window, 'maplibregl', {
                configurable: true,
                get() { return _maplibregl; },
                set(value) {
                    _maplibregl = value;
                    if (value?.Map?.prototype && !value.Map.prototype.__resizePatched) {
                        const original = value.Map.prototype.resize;
                        value.Map.prototype.resize = function (...args) {
                            window.__resizeCallCount += 1;
                            return original.apply(this, args);
                        };
                        value.Map.prototype.__resizePatched = true;
                    }
                },
            });
            """
        )
        player1.goto(live_server)
        player1.click("#player1Button")
        player1.wait_for_selector("#waitView.active")

        moderator_page.click("#lockPlayerInputButton")
        player1.wait_for_selector("#photoView.active")
        # Click through to the map view right away, without waiting for the
        # basemap layer's own async load to finish first - the ordering
        # that used to leave the canvas blank.
        player1.click("#guessButton")
        player1.wait_for_selector("#mapView.active")

        player1.wait_for_function("window.__resizeCallCount > 0")

        player1.wait_for_selector("#map canvas.maplibregl-canvas")
        canvas_box = player1.eval_on_selector(
            "#map canvas.maplibregl-canvas",
            "el => ({ width: el.clientWidth, height: el.clientHeight })",
        )
        assert canvas_box["width"] > 0
        assert canvas_box["height"] > 0

        browser.close()


def test_round_result_card_shows_only_that_rounds_points_not_cumulative(live_server):
    """Regression test for #74: showRoundResult() used to be handed the
    running pointByName total instead of the round's own points, so the
    "Rundenergebnis" card showed each player's cumulative score across all
    rounds played so far, not just what they scored this round.

    Playing two rounds with the exact same (dead-on) guess - so each round
    should independently score the maximum 1000 points - and asserting the
    round-result card shows 1000 both times, not ~2000 the second time, is
    a direct, deterministic way to catch the cumulative-total regression
    without reading pointByName internals.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#lockPlayerInputButton")

        photos = context.request.get(f"{live_server}/api/round-photos").json()
        assert len(photos) >= 2

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")

        player2 = context.new_page()
        player2.goto(live_server)
        player2.click("#player2Button")

        def play_round_and_get_result(round_number):
            moderator_page.click("#lockPlayerInputButton")
            # Guess exactly the round's photo location, so both rounds score
            # the same maximum points regardless of which photo it is.
            location = photos[round_number - 1]["location"]
            for role in ("player1", "player2"):
                context.request.post(
                    f"{live_server}/api/points",
                    data={
                        "round_number": round_number,
                        "placed_by": role,
                        "coordinates": {"lat": location["lat"], "lng": location["lng"]},
                    },
                )
            moderator_page.wait_for_timeout(500)

            moderator_page.click("#mainControlButton")
            moderator_page.wait_for_selector("#continueButton.is-active")
            moderator_page.click("#continueButton")
            moderator_page.wait_for_selector("#roundResultView.is-active")

            points_text = moderator_page.eval_on_selector(
                ".result-row .result-player-points", "el => el.textContent"
            )
            moderator_page.click("#resultContinueButton")
            return points_text

        round1_points = play_round_and_get_result(1)
        round2_points = play_round_and_get_result(2)

        assert round1_points == "1000 Punkte"
        assert round2_points == round1_points, (
            f"round 2's Rundenergebnis card must show that round's own points "
            f"(same as round 1's, since both guesses were exact), not the "
            f"cumulative total across rounds - got round1={round1_points!r} "
            f"round2={round2_points!r}"
        )

        browser.close()


def test_results_screen_round_numbers_stay_sequential_after_reordering_photos(live_server):
    """Regression test for #52: the Endergebnis/Results round-by-round list
    used to number rounds by round_number (persisted server-side, equal to
    a photo's id - a number assigned once and never renumbered, see
    photo_config.py), instead of that photo's current position in
    photos.json. Reordering (or deleting an earlier) round photo makes ids
    drift out of sequence with position - e.g. after swapping round photos
    1 and 2, round 1 is now the photo whose id is 2 - so the round list
    used to show "Runde 2" then "Runde 1" instead of "Runde 1" then
    "Runde 2".

    This reorders round photos 1 and 2 via the same /api/round-photos/reorder
    endpoint /config uses (see test_moderator_still_records_guesses_after_a_
    photo_id_position_drift for why a redirected ROUND_PHOTOS_FILE wouldn't
    help here - results.js fetches the real static/config/photos.json
    directly), plays through every round, and asserts the /results screen's
    round list stays numbered 1..N in play order - not by the underlying
    (now out-of-order) photo ids. The original order is restored in
    `finally` regardless of outcome.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context()

            original_photos = context.request.get(f"{live_server}/api/round-photos").json()
            num_rounds = len(original_photos)
            assert num_rounds >= 2
            original_order = [photo["id"] for photo in original_photos]
            swapped_order = [original_order[1], original_order[0], *original_order[2:]]

            reorder_response = context.request.post(
                f"{live_server}/api/round-photos/reorder", data={"order": swapped_order}
            )
            assert reorder_response.ok

            try:
                moderator_page = context.new_page()
                moderator_page.goto(live_server)
                moderator_page.click("button[data-name='Moderator']")
                moderator_page.wait_for_selector("#lockPlayerInputButton")

                player1 = context.new_page()
                player1.goto(live_server)
                player1.click("#player1Button")

                player2 = context.new_page()
                player2.goto(live_server)
                player2.click("#player2Button")

                for round_number in range(1, num_rounds + 1):
                    moderator_page.click("#lockPlayerInputButton")
                    context.request.post(
                        f"{live_server}/api/points",
                        data={"round_number": round_number, "placed_by": "player1", "coordinates": {"lat": 49.37, "lng": 9.54}},
                    )
                    context.request.post(
                        f"{live_server}/api/points",
                        data={"round_number": round_number, "placed_by": "player2", "coordinates": {"lat": 50.0, "lng": 10.0}},
                    )
                    moderator_page.wait_for_timeout(500)

                    moderator_page.click("#mainControlButton")
                    moderator_page.wait_for_selector("#continueButton.is-active")
                    moderator_page.click("#continueButton")
                    moderator_page.wait_for_selector("#roundResultView.is-active")
                    moderator_page.click("#resultContinueButton")

                player1.wait_for_url(f"{live_server}/results")
                player1.wait_for_function(
                    f"document.querySelectorAll('#roundList .round-row').length === {num_rounds}"
                )

                round_titles = player1.eval_on_selector_all(
                    "#roundList .round-row .round-row-title span:first-child",
                    "els => els.map(el => el.textContent)",
                )
                assert round_titles == [f"Runde {n}" for n in range(1, num_rounds + 1)], (
                    f"round list must stay numbered by play order (1..{num_rounds}), not "
                    f"by the underlying (now reordered) photo ids - got {round_titles}"
                )
            finally:
                context.request.post(
                    f"{live_server}/api/round-photos/reorder", data={"order": original_order}
                )
        finally:
            browser.close()


def test_countdown_expiring_locks_input_without_auto_revealing_solution(live_server):
    """Regression test for #101/#102: when a round's countdown timer
    reached 0, the moderator screen used to jump straight to the
    "Auflösung" (solution) view automatically. maybeAutoStopTimer() must
    instead only lock player input and stop the timer - the moderator
    still has to press "Runde auflösen" themselves to reveal the solution,
    e.g. to moderate/discuss the round with guests first.

    Uses the minimum allowed countdown (5s) so the timer expires quickly,
    then asserts: the player's own view falls back to waiting (input got
    locked), but the moderator's resolution/solution view never opens on
    its own - only after a subsequent manual click does it.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        config_response = context.request.patch(
            f"{live_server}/api/round-config",
            data={"mode": "countdown", "duration_seconds": 5},
        )
        assert config_response.ok

        moderator_page = context.new_page()
        moderator_page.goto(live_server)
        moderator_page.click("button[data-name='Moderator']")
        moderator_page.wait_for_selector("#timerStartButton")

        player1 = context.new_page()
        player1.goto(live_server)
        player1.click("#player1Button")
        player1.wait_for_selector("#waitView.active")

        moderator_page.click("#timerStartButton")
        player1.wait_for_selector("#photoView.active")

        # The countdown must actually expire and auto-stop - back to
        # waiting - without the moderator lifting a finger.
        player1.wait_for_selector("#waitView.active", timeout=10000)

        # The solution view must NOT have opened itself.
        assert "is-active" not in (moderator_page.get_attribute("#resolutionView", "class") or "")
        assert "is-active" not in (moderator_page.get_attribute("#continueButton", "class") or "")

        # The moderator must still be able to reveal it manually afterwards.
        moderator_page.click("#mainControlButton")
        moderator_page.wait_for_selector("#continueButton.is-active")

        browser.close()


def test_map_config_default_build_date_is_not_hardcoded(live_server):
    """Regression test for #117: map-config.js's DEFAULTS.build_date used
    to be a hardcoded date string - this module's fallback whenever
    loadMapConfig()'s fetch to /api/map/config fails, or before it's had a
    chance to run. Protomaps only retains basemap builds for ~5 days, so
    any hardcoded date silently 404s once that window passes. The fix
    replaced it with '' ("resolve to the newest available build at build
    time"), which must never regress back to a fixed date.

    Imports map-config.js fresh on a page that never itself imports it
    (so nothing has called loadMapConfig() yet to overwrite the cache) and
    reads its default build_date directly - a plain dynamic import inside
    a real page, working around the "no JS test runner exists" gap noted
    in the coverage audit this test is part of closing.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.goto(live_server)  # the start page never imports map-config.js

        default_build_date = page.evaluate(
            "async () => { const mod = await import('/static/js/map-config.js'); "
            "return mod.getMapConfig().build_date; }"
        )

        assert default_build_date == "", (
            f"map-config.js's default build_date must stay '' (resolved to the "
            f"newest available Protomaps build at build time) - a hardcoded date "
            f"will silently 404 once Protomaps' ~5-day retention window passes, "
            f"got {default_build_date!r}"
        )

        browser.close()


def test_config_page_has_no_horizontal_overflow_on_narrow_screens(live_server):
    """Regression test for a reported bug: the "Kartendaten" region editor's
    zoom <select> (long, descriptive option text) wasn't covered by the
    `.field input` width/box-sizing rule, so on narrow screens it shrank to
    fit its content instead of its grid cell - blowing the row width past
    the white config-container and onto the page's gradient background.

    A phone-sized viewport is exactly what surfaced this, so this checks
    that the document never becomes horizontally scrollable there, both on
    initial load and after adding another region (the interaction that
    grows the region list).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
        page.goto(f"{live_server}/config")
        page.wait_for_selector("#regionList .region-row")

        def assert_no_horizontal_overflow():
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            assert scroll_width <= client_width, (
                f"page overflows horizontally: scrollWidth={scroll_width} "
                f"> clientWidth={client_width}"
            )

        assert_no_horizontal_overflow()

        page.click("#addRegionButton")
        page.wait_for_selector("#regionList .region-row:nth-child(3)")
        assert_no_horizontal_overflow()

        browser.close()


def test_config_page_reset_button_requires_typed_confirmation_phrase(live_server):
    """Coverage test for #137: the config page's "Gefahrenzone" -> "Spiel
    komplett zurücksetzen" button must not run the destructive factory
    reset (game_state.reset_to_defaults() + photo_config.clear_round_photos(),
    via POST /api/reset-to-defaults - the same reset tools/reset_state.py
    runs, see #72) on a single click. confirm-dialog.js's dialog must show
    with its confirm button disabled until the user has typed the exact
    phrase "Where2Win" into the added text input - only then may the reset
    actually run.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        # Give the game some non-default state first, so the reset visibly
        # changes something rather than the defaults already matching.
        patch_response = context.request.patch(
            f"{live_server}/api/player-config", data={"player1_name": "Someone Special"}
        )
        assert patch_response.ok

        page = context.new_page()
        page.goto(f"{live_server}/config")
        page.wait_for_selector("#resetGameButton")
        assert page.input_value("#player1Name") == "Someone Special"

        page.click("#resetGameButton")
        page.wait_for_selector(".confirm-dialog-overlay.is-active")
        assert page.is_disabled(".confirm-dialog-confirm")

        # A wrong (even case-mismatched) phrase must keep it disabled.
        page.fill(".confirm-dialog-phrase-input", "where2win")
        assert page.is_disabled(".confirm-dialog-confirm")

        # Only the exact phrase enables the confirm button.
        page.fill(".confirm-dialog-phrase-input", "Where2Win")
        assert not page.is_disabled(".confirm-dialog-confirm")

        page.click(".confirm-dialog-confirm")

        # A successful reset reloads the page - wait for that to settle,
        # then check both the reloaded UI and the server's own state.
        page.wait_for_function("document.querySelector('#player1Name')?.value === 'player1'")

        player_config = context.request.get(f"{live_server}/api/player-config").json()
        assert player_config["player1_name"] == "player1"

        browser.close()


def test_config_page_reset_cancel_leaves_game_state_untouched(live_server):
    """Follow-up to the test above: dismissing #137's confirmation dialog
    (even after typing the correct phrase) must not run the reset at all.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        patch_response = context.request.patch(
            f"{live_server}/api/player-config", data={"player1_name": "Someone Special"}
        )
        assert patch_response.ok

        page = context.new_page()
        page.goto(f"{live_server}/config")
        page.wait_for_selector("#resetGameButton")

        page.click("#resetGameButton")
        page.wait_for_selector(".confirm-dialog-overlay.is-active")
        page.fill(".confirm-dialog-phrase-input", "Where2Win")
        page.click(".confirm-dialog-cancel")
        page.wait_for_function(
            "!document.querySelector('.confirm-dialog-overlay')?.classList.contains('is-active')"
        )

        player_config = context.request.get(f"{live_server}/api/player-config").json()
        assert player_config["player1_name"] == "Someone Special"

        browser.close()
