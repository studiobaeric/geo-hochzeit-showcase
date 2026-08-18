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
