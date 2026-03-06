from weather_alert.api import NwsApiClient


def test_parse_lat_lon_input_support():
    client = NwsApiClient("test-agent")
    coords = client.get_coordinates_for_location("38.6270,-90.1994")
    assert coords is not None
    assert round(coords[0], 3) == 38.627


def test_validate_location_uses_resolution(monkeypatch):
    client = NwsApiClient("test-agent")

    def fake_resolve(_):
        return 10.0, 20.0

    monkeypatch.setattr(client, "get_coordinates_for_location", fake_resolve)
    valid, msg = client.validate_location("anything")
    assert valid is True
    assert "Valid" in msg
