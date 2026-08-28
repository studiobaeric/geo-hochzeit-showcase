"""Tests for the /api/host-info endpoint used by the config menu's
QR-code/host-connection section."""

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
