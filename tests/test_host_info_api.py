"""Tests for the /api/host-info endpoint used by the config menu's
QR-code/host-connection section."""

import json
import socket
import threading
import urllib.parse
import urllib.request

from werkzeug.serving import make_server

import app as app_module


def test_get_host_info_has_expected_shape(client):
    response = client.get("/api/host-info")
    data = response.get_json()

    assert response.status_code == 200
    assert set(data) == {"ip", "port", "url"}
    assert data["port"] == app_module.PORT
    assert data["url"] == f"http://{data['ip']}:{app_module.PORT}/"


def test_get_host_info_falls_back_to_localhost_without_network(client, monkeypatch):
    def _raise_os_error(*_args, **_kwargs):
        raise OSError("network unreachable")

    monkeypatch.setattr(app_module.socket.socket, "connect", _raise_os_error)

    response = client.get("/api/host-info")
    data = response.get_json()

    assert response.status_code == 200
    assert data["ip"] == "127.0.0.1"


def test_get_host_info_url_is_well_formed_for_lan_ip(client, monkeypatch):
    """Regression check for #122: the reported `url` must be a well-formed
    http:// URL for a real LAN address, not just string-concatenated - e.g.
    scheme/host/port/path all need to survive round-tripping through a URL
    parser, which a naive f-string could get wrong for some address shapes."""
    monkeypatch.setattr(app_module.socket.socket, "connect", lambda self, addr: None)
    monkeypatch.setattr(app_module.socket.socket, "getsockname", lambda self: ("192.168.1.42", 54321))

    response = client.get("/api/host-info")
    data = response.get_json()

    assert response.status_code == 200
    assert data["ip"] == "192.168.1.42"

    parsed = urllib.parse.urlparse(data["url"])
    assert parsed.scheme == "http"
    assert parsed.hostname == "192.168.1.42"
    assert parsed.port == app_module.PORT
    assert parsed.path == "/"
    assert data["url"] == f"http://192.168.1.42:{app_module.PORT}/"


def test_host_info_port_matches_actual_listening_socket(monkeypatch):
    """Regression check for #122: `port` must reflect the port the server is
    genuinely bound to, not just an unchecked config value - this drives a
    real HTTP request against a live server and then connects to the exact
    port the response reported, proving something is actually listening
    there."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()

    monkeypatch.setattr(app_module, "PORT", free_port)
    monkeypatch.setitem(app_module.app.config, "TESTING", True)

    server = make_server("127.0.0.1", free_port, app_module.app)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/api/host-info", timeout=5) as resp:
            data = json.loads(resp.read())

        assert data["port"] == free_port

        with socket.create_connection(("127.0.0.1", data["port"]), timeout=5):
            pass
    finally:
        server.shutdown()
        thread.join(timeout=5)
