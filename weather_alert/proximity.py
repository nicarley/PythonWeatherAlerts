import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_MILES * c


def _iter_coords(node: Any) -> Iterable[Tuple[float, float]]:
    if isinstance(node, (list, tuple)):
        if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
            lon = float(node[0])
            lat = float(node[1])
            yield lat, lon
            return
        for child in node:
            yield from _iter_coords(child)


def geometry_points(geometry: Optional[Dict[str, Any]]) -> List[Tuple[float, float]]:
    if not geometry:
        return []
    return list(_iter_coords(geometry.get("coordinates")))


def _point_in_ring(lat: float, lon: float, ring: Any) -> bool:
    if not isinstance(ring, (list, tuple)) or len(ring) < 3:
        return False
    inside = False
    previous = ring[-1]
    for current in ring:
        if not (
            isinstance(previous, (list, tuple)) and len(previous) >= 2
            and isinstance(current, (list, tuple)) and len(current) >= 2
        ):
            previous = current
            continue
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        if (y1 > lat) != (y2 > lat):
            crossing_lon = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < crossing_lon:
                inside = not inside
        previous = current
    return inside


def _distance_to_segment_miles(
    lat: float,
    lon: float,
    start: Any,
    end: Any,
) -> Optional[float]:
    if not (
        isinstance(start, (list, tuple)) and len(start) >= 2
        and isinstance(end, (list, tuple)) and len(end) >= 2
    ):
        return None

    mean_lat = math.radians((float(start[1]) + float(end[1]) + lat) / 3.0)

    def project(position: Any) -> Tuple[float, float]:
        x = math.radians(float(position[0]) - lon) * math.cos(mean_lat) * EARTH_RADIUS_MILES
        y = math.radians(float(position[1]) - lat) * EARTH_RADIUS_MILES
        return x, y

    x1, y1 = project(start)
    x2, y2 = project(end)
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(x1, y1)
    fraction = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length_squared))
    return math.hypot(x1 + fraction * dx, y1 + fraction * dy)


def _distance_to_polygon_miles(lat: float, lon: float, polygon: Any) -> Optional[float]:
    if not isinstance(polygon, (list, tuple)) or not polygon:
        return None
    exterior = polygon[0]
    inside_exterior = _point_in_ring(lat, lon, exterior)
    inside_hole = any(_point_in_ring(lat, lon, hole) for hole in polygon[1:])
    if inside_exterior and not inside_hole:
        return 0.0

    distances: List[float] = []
    for ring in polygon:
        if not isinstance(ring, (list, tuple)) or len(ring) < 2:
            continue
        for index in range(len(ring) - 1):
            distance = _distance_to_segment_miles(lat, lon, ring[index], ring[index + 1])
            if distance is not None:
                distances.append(distance)
        if ring[0] != ring[-1]:
            distance = _distance_to_segment_miles(lat, lon, ring[-1], ring[0])
            if distance is not None:
                distances.append(distance)
    return min(distances) if distances else None


def distance_point_to_geometry_miles(lat: float, lon: float, geometry: Optional[Dict[str, Any]]) -> Optional[float]:
    if not geometry:
        return None
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        return _distance_to_polygon_miles(lat, lon, coordinates)
    if geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
        distances = [
            distance
            for polygon in coordinates
            if (distance := _distance_to_polygon_miles(lat, lon, polygon)) is not None
        ]
        return min(distances) if distances else None

    points = geometry_points(geometry)
    if not points:
        return None
    return min(haversine_miles(lat, lon, p_lat, p_lon) for p_lat, p_lon in points)


def rank_alerts_by_proximity(alerts: Sequence[Dict[str, Any]], lat: float, lon: float) -> List[Dict[str, Any]]:
    scored: List[Tuple[float, Dict[str, Any]]] = []
    unknown_distance: List[Dict[str, Any]] = []

    for alert in alerts:
        distance = distance_point_to_geometry_miles(lat, lon, alert.get("geometry"))
        if distance is None:
            unknown_distance.append(dict(alert))
            continue
        item = dict(alert)
        item["distance_miles"] = round(distance, 2)
        scored.append((distance, item))

    scored.sort(key=lambda pair: pair[0])
    result = [item for _, item in scored]
    result.extend(unknown_distance)
    return result
