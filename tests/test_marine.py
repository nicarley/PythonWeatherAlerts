from datetime import datetime

from weather_alert.marine import (
    COOPS_MAP_URL,
    MarineDataService,
    coops_station_lat_lon,
    distance_miles_between,
    fishing_resource_links,
    max_optional,
    moon_phase_info,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append((url, timeout))
        return _FakeResponse(self.payloads.pop(0))


def test_moon_phase_info_is_stable_for_known_new_moon():
    info = moon_phase_info(datetime(2000, 1, 6, 18, 14))

    assert info["phase"] == "New Moon"
    assert round(info["illumination"], 3) == 0


def test_station_coordinate_shapes_are_supported():
    assert coops_station_lat_lon({"lat": "24.5", "lng": "-81.8"}) == (24.5, -81.8)
    assert coops_station_lat_lon({"latitude": 24.5, "longitude": -81.8}) == (24.5, -81.8)


def test_distance_and_max_helpers_ignore_missing_values():
    assert round(distance_miles_between(24.555, -81.78, 24.555, -81.78), 2) == 0
    assert max_optional([None, 4, 9.5]) == 9.5


def test_fetch_product_summary_handles_current_prediction_wrapped_in_dict():
    session = _FakeSession([
        {
            "current_predictions": {
                "cp": [
                    {
                        "Velocity_Major": "1.2",
                        "meanFloodDir": "180",
                        "Time": "2026-06-23 10:00",
                    }
                ]
            }
        }
    ])
    service = MarineDataService(session)

    summary = service.fetch_product_summary("8724580", "currents_predictions")

    assert summary["value"] == "1.2 kt 180"
    assert summary["detail"] == "2026-06-23 10:00"
    assert "product=currents_predictions" in summary["url"]


def test_fetch_nearest_marine_data_uses_closest_station_and_product_summary(monkeypatch):
    service = MarineDataService(_FakeSession([]))
    service.station_cache["watertemp"] = [
        {"id": "far", "name": "Far", "lat": "25.0", "lng": "-82.0"},
        {"id": "near", "name": "Near", "lat": "24.56", "lng": "-81.78"},
    ]

    def fake_summary(station_id, product, extra=None):
        assert station_id == "near"
        assert product == "water_temperature"
        return {"value": "84\N{DEGREE SIGN}F", "detail": "latest", "url": "https://example.test/data"}

    monkeypatch.setattr(service, "fetch_product_summary", fake_summary)
    monkeypatch.setattr(
        "weather_alert.marine.MARINE_PRODUCTS",
        [
            {
                "key": "water_temp",
                "label": "Water Temp",
                "station_type": "watertemp",
                "product": "water_temperature",
                "detail": "Closest water temperature.",
            }
        ],
    )

    data = service.fetch_nearest_marine_data(24.555, -81.78)

    assert data["water_temp"]["station"] == "Near"
    assert data["water_temp"]["value"] == "84\N{DEGREE SIGN}F"
    assert data["water_temp"]["distance_miles"] < 1


def test_fishing_resource_links_reject_non_web_station_urls():
    links = fishing_resource_links(
        (24.555, -81.78),
        {
            "water_temp": {
                "label": "Water Temp",
                "station": "Station",
                "station_url": "javascript:alert(1)",
            }
        },
    )

    assert links[0][1] == COOPS_MAP_URL
    assert any("marine.weather.gov/MapClick.php" in url for _title, url, _detail in links)
