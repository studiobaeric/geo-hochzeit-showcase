"""Smoke tests for the page routes in app.py.

We don't pin exact HTML content (templates change often); we just check
each page renders without blowing up and produces HTML.
"""

import pytest


@pytest.mark.parametrize(
    "path",
    ["/", "/game", "/moderator", "/results", "/end_of_game"],
)
def test_page_renders(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert b"<html" in response.data.lower()


def test_unknown_route_is_404(client):
    response = client.get("/this-page-does-not-exist")

    assert response.status_code == 404
