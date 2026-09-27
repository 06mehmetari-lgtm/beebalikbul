"""A cast-distance band along the shore, measured in metres from OpenStreetMap lines."""

from __future__ import annotations

import math

from backend.water import _geometry_contains

CAST_M = 90


def _scale(lat: float) -> float:
    return 111_320 * math.cos(math.radians(lat))


def _thin(ring: list, limit: int = 420) -> list:
    if len(ring) <= limit:
        return ring
    step = max(1, math.ceil(len(ring) / limit))
    thinned = ring[::step]
    if thinned and thinned[0] != thinned[-1]:
        thinned.append(thinned[0])
    return thinned


def _unit_normal(lat1: float, lon1: float, lat2: float, lon2: float, left: bool) -> tuple[float, float] | None:
    scale = _scale((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * scale
    dy = (lat2 - lat1) * 110_540
    length = math.hypot(dx, dy)
    if length < 1:
        return None
    if left:
        return -dy / length, dx / length
    return dy / length, -dx / length


def _inside_side(lat1: float, lon1: float, lat2: float, lon2: float, geometry: dict) -> bool | None:
    """True when the water lies to the left of the directed edge."""
    normal = _unit_normal(lat1, lon1, lat2, lon2, True)
    if normal is None:
        return None
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2
    scale = _scale(mid_lat)
    sample_lat = mid_lat + normal[1] * 12 / 110_540
    sample_lon = mid_lon + normal[0] * 12 / scale
    return _geometry_contains(sample_lon, sample_lat, geometry)


def _shift(lat: float, lon: float, normal: tuple[float, float], meters: float) -> list[float]:
    scale = _scale(lat)
    return [lon + normal[0] * meters / scale, lat + normal[1] * meters / 110_540]


def _quad(lat1: float, lon1: float, lat2: float, lon2: float, water_left: bool, meters: float) -> list | None:
    normal = _unit_normal(lat1, lon1, lat2, lon2, water_left)
    if normal is None:
        return None
    return [
        [lon1, lat1],
        [lon2, lat2],
        _shift(lat2, lon2, normal, meters),
        _shift(lat1, lon1, normal, meters),
        [lon1, lat1],
    ]


def _as_multi(quads: list[list]) -> dict | None:
    if not quads:
        return None
    return {"type": "MultiPolygon", "coordinates": [[ring] for ring in quads]}


def band_from_polygon(geometry: dict | None, meters: float = CAST_M) -> dict | None:
    if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    rings = []
    if geometry["type"] == "Polygon":
        outer = geometry.get("coordinates") or []
        if outer:
            rings.append(outer[0])
    else:
        for polygon in geometry.get("coordinates") or []:
            if polygon:
                rings.append(polygon[0])
    quads = []
    for ring in rings:
        ring = _thin(ring)
        if len(ring) < 4:
            continue
        for index in range(len(ring) - 1):
            lon1, lat1 = ring[index]
            lon2, lat2 = ring[index + 1]
            side = _inside_side(lat1, lon1, lat2, lon2, geometry)
            if side is None:
                continue
            quad = _quad(lat1, lon1, lat2, lon2, side, meters)
            if quad:
                quads.append(quad)
            if len(quads) >= 700:
                break
        if len(quads) >= 700:
            break
    return _as_multi(quads)


def band_from_lines(lines: list[list[dict]], meters: float = CAST_M) -> dict | None:
    """OSM coastline keeps land on the left, so the cast band sits to the right."""
    return _line_band(lines, 0, meters, 500)


def outer_band_from_lines(lines: list[list[dict]], inner_m: float, outer_m: float) -> dict | None:
    """Water beyond the shore cast, still along the same coastline."""
    return _line_band(lines, inner_m, outer_m, 400)


def _line_band(lines: list[list[dict]], inner_m: float, outer_m: float, cap: int) -> dict | None:
    quads = []
    for line in lines:
        points = []
        for point in line:
            try:
                points.append((float(point["lat"]), float(point["lon"])))
            except (KeyError, TypeError, ValueError):
                continue
        if len(points) > 80:
            step = max(1, math.ceil(len(points) / 80))
            points = points[::step]
        for index in range(len(points) - 1):
            lat1, lon1 = points[index]
            lat2, lon2 = points[index + 1]
            quad = _span_quad(lat1, lon1, lat2, lon2, False, inner_m, outer_m)
            if quad:
                quads.append(quad)
            if len(quads) >= cap:
                return _as_multi(quads)
    return _as_multi(quads)


def _span_quad(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    water_left: bool,
    inner_m: float,
    outer_m: float,
) -> list | None:
    normal = _unit_normal(lat1, lon1, lat2, lon2, water_left)
    if normal is None or outer_m <= inner_m:
        return None
    return [
        _shift(lat1, lon1, normal, inner_m),
        _shift(lat2, lon2, normal, inner_m),
        _shift(lat2, lon2, normal, outer_m),
        _shift(lat1, lon1, normal, outer_m),
        _shift(lat1, lon1, normal, inner_m),
    ]


def _bounds_of(geometries: list[dict]) -> tuple[float, float, float, float] | None:
    lats = []
    lons = []

    def walk(node) -> None:
        if isinstance(node, list) and node and isinstance(node[0], (int, float)) and len(node) >= 2:
            lons.append(float(node[0]))
            lats.append(float(node[1]))
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    for geometry in geometries:
        walk(geometry.get("coordinates"))
    if not lats:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def _cell_ring(lat: float, lon: float, meters: float) -> list[list[float]]:
    half = meters / 2
    dlat = half / 110_540
    scale = _scale(lat) or 1
    dlon = half / scale
    return [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]


def _outer_rings(geometry: dict | None) -> list[list]:
    if not geometry:
        return []
    kind = geometry.get("type")
    if kind == "Polygon":
        rings = geometry.get("coordinates") or []
        return [rings[0]] if rings else []
    if kind == "MultiPolygon":
        found = []
        for polygon in geometry.get("coordinates") or []:
            if polygon:
                found.append(polygon[0])
        return found
    return []


def _ring_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    scale = _scale((lat1 + lat2) / 2) or 1
    return math.hypot((lon2 - lon1) * scale, (lat2 - lat1) * 110_540)


def _walk(ring: list, spacing: float):
    if len(ring) < 2:
        return
    pending = spacing * 0.5
    for index in range(len(ring) - 1):
        lon1, lat1 = ring[index][0], ring[index][1]
        lon2, lat2 = ring[index + 1][0], ring[index + 1][1]
        length = _ring_meters(lat1, lon1, lat2, lon2)
        if length < 1:
            continue
        walked = 0.0
        while walked + pending <= length:
            walked += pending
            ratio = walked / length
            yield (
                lat1 + (lat2 - lat1) * ratio,
                lon1 + (lon2 - lon1) * ratio,
                lat1,
                lon1,
                lat2,
                lon2,
            )
            pending = spacing
        pending -= length - walked


def _feature(zone: str, lat: float, lon: float, size: float, index: int) -> dict:
    label = {"harbor": "İç liman", "shore": "Kıyı şeridi", "open": "Açık su"}[zone]
    return {
        "type": "Feature",
        "properties": {
            "id": index,
            "zone": zone,
            "label": label,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
        },
        "geometry": {"type": "Polygon", "coordinates": [_cell_ring(lat, lon, size)]},
    }


def _along_ring(ring: list, geometry: dict, zone: str, offset_m: float, spacing: float, limit: int) -> list[dict]:
    found = []
    for lat, lon, lat1, lon1, lat2, lon2 in _walk(ring, spacing):
        if len(found) >= limit:
            break
        side = _inside_side(lat1, lon1, lat2, lon2, geometry)
        if side is None:
            continue
        normal = _unit_normal(lat1, lon1, lat2, lon2, side)
        if normal is None:
            continue
        point = _shift(lat, lon, normal, offset_m)
        cell_lon, cell_lat = point[0], point[1]
        if not _geometry_contains(cell_lon, cell_lat, geometry):
            continue
        found.append((cell_lat, cell_lon))
    return found


def _along_coast(lines: list, offset_m: float, spacing: float, limit: int) -> list[tuple[float, float]]:
    found = []
    for line in lines or []:
        points = []
        for point in line:
            try:
                points.append([float(point["lon"]), float(point["lat"])])
            except (KeyError, TypeError, ValueError):
                continue
        if len(points) < 2:
            continue
        for lat, lon, lat1, lon1, lat2, lon2 in _walk(points, spacing):
            if len(found) >= limit:
                return found
            normal = _unit_normal(lat1, lon1, lat2, lon2, False)
            if normal is None:
                continue
            cell_lon, cell_lat = _shift(lat, lon, normal, offset_m)
            found.append((cell_lat, cell_lon))
    return found


def _spacing(length: float, detail: float = 42, cap: int = 64) -> float:
    if length <= 0:
        return detail
    count = length / detail
    if count <= cap:
        return detail
    return length / cap


def _ring_length(ring: list) -> float:
    total = 0.0
    for index in range(len(ring) - 1):
        total += _ring_meters(ring[index][1], ring[index][0], ring[index + 1][1], ring[index + 1][0])
    return total


def cells_for_place(
    harbour: dict | None = None,
    water: dict | None = None,
    coast_lines: list | None = None,
) -> dict | None:
    """Squares in the water, stepped along the bank. Same rule for harbor, lake, and coast."""
    features = []
    seen = set()

    def add(zone: str, lat: float, lon: float, size: float = 34) -> None:
        key = (round(lat, 4), round(lon, 4))
        if key in seen:
            return
        if harbour and zone != "harbor" and _geometry_contains(lon, lat, harbour):
            return
        seen.add(key)
        features.append(_feature(zone, lat, lon, size, len(features) + 1))

    for ring in _outer_rings(harbour):
        spacing = _spacing(_ring_length(ring))
        for lat, lon in _along_ring(ring, harbour, "harbor", 22, spacing, 64):
            add("harbor", lat, lon)

    for ring in _outer_rings(water):
        length = _ring_length(ring)
        spacing = _spacing(length)
        for lat, lon in _along_ring(ring, water, "shore", 22, spacing, 64):
            add("shore", lat, lon)
        for lat, lon in _along_ring(ring, water, "open", 110, _spacing(length, 80, 40), 40):
            add("open", lat, lon, 48)

    for lat, lon in _along_coast(coast_lines, 28, 42, 48):
        add("shore", lat, lon)
    for lat, lon in _along_coast(coast_lines, 140, 70, 36):
        add("open", lat, lon, 48)

    if not features:
        return None
    return {"type": "FeatureCollection", "features": features}
