"""Smoke tests for the page routes in app.py.

We don't pin exact HTML content (templates change often); we just check
each page renders without blowing up and produces HTML.
"""

import pytest


@pytest.mark.parametrize(
    "path",
    ["/", "/config", "/game", "/moderator", "/results", "/end_of_game"],
)
def test_page_renders(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert b"<html" in response.data.lower()


def test_unknown_route_is_404(client):
    response = client.get("/this-page-does-not-exist")

    assert response.status_code == 404


def test_version_endpoint_returns_the_app_version(client):
    from app import APP_VERSION

    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.get_json() == {"version": APP_VERSION}


@pytest.mark.parametrize(
    "path", ["/static/css/style.css", "/static/config/players.js"]
)
def test_css_and_js_responses_are_marked_no_cache(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-cache"


def test_html_pages_are_not_marked_no_cache_by_the_css_js_hook(client):
    response = client.get("/")

    assert response.headers.get("Cache-Control") != "no-cache"
