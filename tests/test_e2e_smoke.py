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
