from weather_alert.proximity import distance_point_to_geometry_miles, rank_alerts_by_proximity


def test_distance_point_to_geometry_returns_small_distance_for_nearby_point():
    geom = {
        "type": "Polygon",
        "coordinates": [[[-89.9, 38.5], [-89.8, 38.5], [-89.8, 38.6], [-89.9, 38.6], [-89.9, 38.5]]],
    }
    dist = distance_point_to_geometry_miles(38.55, -89.85, geom)
    assert dist is not None
    assert dist < 10.0


def test_rank_alerts_by_proximity_sorts_with_distance():
    alerts = [
        {
            "id": "far",
            "geometry": {"type": "Polygon", "coordinates": [[[-90.5, 38.0], [-90.4, 38.0], [-90.4, 38.1], [-90.5, 38.1], [-90.5, 38.0]]]},
        },
        {
            "id": "near",
            "geometry": {"type": "Polygon", "coordinates": [[[-89.9, 38.5], [-89.8, 38.5], [-89.8, 38.6], [-89.9, 38.6], [-89.9, 38.5]]]},
        },
    ]
    ranked = rank_alerts_by_proximity(alerts, 38.55, -89.85)
    assert ranked[0]["id"] == "near"
    assert "distance_miles" in ranked[0]


def test_distance_is_zero_when_location_is_inside_polygon():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-91.0, 37.0], [-89.0, 37.0], [-89.0, 39.0], [-91.0, 39.0], [-91.0, 37.0]]],
    }

    assert distance_point_to_geometry_miles(38.0, -90.0, geometry) == 0.0


def test_distance_supports_multipolygon_containment():
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[-95.0, 35.0], [-94.0, 35.0], [-94.0, 36.0], [-95.0, 36.0], [-95.0, 35.0]]],
            [[[-91.0, 37.0], [-89.0, 37.0], [-89.0, 39.0], [-91.0, 39.0], [-91.0, 37.0]]],
        ],
    }

    assert distance_point_to_geometry_miles(38.0, -90.0, geometry) == 0.0
