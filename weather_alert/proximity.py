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


def distance_point_to_geometry_miles(lat: float, lon: float, geometry: Optional[Dict[str, Any]]) -> Optional[float]:
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

