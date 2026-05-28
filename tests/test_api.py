from weather_alert.api import NwsApiClient


class _FakeGeocodeRows:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient=None):
        assert orient == "records"
        return list(self._rows)


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

    class FakePgeocodeClient:
        def query_location(self, city, state_code=None):
            assert city == "St Louis"
            assert state_code == "MO"
            return _FakeGeocodeRows(
                [{"place_name": "St Louis", "latitude": 38.6270, "longitude": -90.1994}]
            )

    client.pgeocode_client = FakePgeocodeClient()
    coords = client.get_coordinates_for_location("St Louis, MO")

    assert coords == (38.6270, -90.1994)


def test_city_state_full_name_resolves(monkeypatch):
    client = NwsApiClient("test-agent")

    class FakePgeocodeClient:
        def query_location(self, city, state_code=None):
            assert city == "St Louis"
            assert state_code == "MO"
            return _FakeGeocodeRows(
                [{"place_name": "St Louis", "latitude": 38.6270, "longitude": -90.1994}]
            )

    client.pgeocode_client = FakePgeocodeClient()
    coords = client.get_coordinates_for_location("St Louis, Missouri")

    assert coords == (38.6270, -90.1994)


def test_zone_polygon_resolves_to_first_coordinate(monkeypatch):
    client = NwsApiClient("test-agent")

    def fake_get_json(url, **_kwargs):
        assert url.endswith("/zones/forecast/ILC163")
        return {
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-90.310, 38.510],
                        [-90.100, 38.520],
                        [-90.120, 38.700],
                        [-90.310, 38.510],
                    ]
                ],
            }
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)
    coords = client.get_coordinates_for_location("ILC163")

    assert coords == (38.510, -90.310)


def test_alert_query_is_encoded_and_normalized(monkeypatch):
    client = NwsApiClient("test-agent")
    called = {}

    def fake_get_json(url, **_kwargs):
        called["url"] = url
        return {
            "features": [
                {
                    "id": "alert-1",
                    "geometry": None,
                    "properties": {
                        "event": "Severe Thunderstorm Warning",
                        "headline": "Severe storms moving east",
                        "description": "Damaging winds are possible.",
                        "severity": "Severe",
                        "urgency": "Immediate",
                        "certainty": "Observed",
                        "effective": "2026-05-28T10:00:00-05:00",
                        "expires": "2026-05-28T11:00:00-05:00",
                    },
                }
            ]
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)
    alerts = client.get_alerts(38.51, -90.31)

    assert "point=38.51%2C-90.31" in called["url"]
    assert alerts[0]["headline"] == "Severe storms moving east"
    assert alerts[0]["severity"] == "Severe"
