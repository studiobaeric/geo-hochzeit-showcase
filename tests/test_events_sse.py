"""Smoke tests for the /api/events Server-Sent Events stream.

This isn't a full streaming-protocol test (that'd need real concurrency);
it just checks a client gets a sane first event with the current state,
which is the thing the frontend actually relies on to sync up.
"""

import json


def test_events_stream_starts_with_current_gamestate(client):
    client.patch("/api/gamestate", json={"round": 4})

    response = client.get("/api/events")
    assert response.status_code == 200
    assert "text/event-stream" in response.content_type

    stream = response.response
    first_event = next(iter(stream))
    if isinstance(first_event, bytes):
        first_event = first_event.decode()

    assert first_event.startswith("event: gamestate")
    payload = json.loads(first_event.split("data: ", 1)[1])
    assert payload["round"] == 4

    response.close()
