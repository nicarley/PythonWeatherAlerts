import pandas

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


def test_get_forecast_urls_includes_grid_data(monkeypatch):
    client = NwsApiClient("test-agent")

    def fake_get_json(_url, **_kwargs):
        return {
            "properties": {
                "forecastHourly": "https://api.weather.gov/gridpoints/XXX/1,1/forecast/hourly",
                "forecast": "https://api.weather.gov/gridpoints/XXX/1,1/forecast",
                "forecastGridData": "https://api.weather.gov/gridpoints/XXX/1,1",
            }
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)
    urls = client.get_forecast_urls(38.6270, -90.1994)

    assert urls == {
        "hourly": "https://api.weather.gov/gridpoints/XXX/1,1/forecast/hourly",
        "daily": "https://api.weather.gov/gridpoints/XXX/1,1/forecast",
        "grid": "https://api.weather.gov/gridpoints/XXX/1,1",
    }


def test_city_state_abbreviation_resolves(monkeypatch):
    client = NwsApiClient("test-agent")

    def fake_query_location(city, state_code=None):
        assert city == "St Louis"
        assert state_code == "MO"
        return pandas.DataFrame(
            [{"place_name": "St Louis", "latitude": 38.6270, "longitude": -90.1994}]
        )

    monkeypatch.setattr(client.pgeocode_client, "query_location", fake_query_location)
    coords = client.get_coordinates_for_location("St Louis, MO")

    assert coords == (38.6270, -90.1994)


def test_city_state_full_name_resolves(monkeypatch):
    client = NwsApiClient("test-agent")

    def fake_query_location(city, state_code=None):
        assert city == "St Louis"
        assert state_code == "MO"
        return pandas.DataFrame(
            [{"place_name": "St Louis", "latitude": 38.6270, "longitude": -90.1994}]
        )

    monkeypatch.setattr(client.pgeocode_client, "query_location", fake_query_location)
    coords = client.get_coordinates_for_location("St Louis, Missouri")

    assert coords == (38.6270, -90.1994)
