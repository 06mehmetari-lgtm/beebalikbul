"""OpenStreetMap Overpass: name and fresh / brackish / salt at a coordinate."""

from __future__ import annotations

import logging
import math
import time

import httpx

from backend.net import client

log = logging.getLogger("kontrolbee.water")

OVERPASS_PRIMARY = "https://overpass-api.de/api/interpreter"
OVERPASS_FALLBACK = "https://overpass.openstreetmap.fr/api/interpreter"

KIND_LABEL = {
    "freshwater": "Tatlı su",
    "brackish": "Acı su",
    "saltwater": "Tuzlu su",
}

WATER_LABEL = {
    "lake": "Göl",
    "reservoir": "Baraj",
    "pond": "Gölet",
    "lagoon": "Lagün",
    "river": "Irmak",
    "stream": "Dere",
    "canal": "Kanal",
    "oxbow": "Menderes gölü",
    "basin": "Havuz",
    "sea": "Deniz",
    "ocean": "Okyanus",
    "coastline": "Kıyı",
    "bay": "Koy",
    "strait": "Boğaz",
}

_nominatim_cache: dict[tuple[float, float], str | None] = {}
_water_cache: dict[tuple[float, float], tuple[float, dict]] = {}
WATER_CACHE_SECONDS = 600


class WaterLookupError(RuntimeError):
    pass


async def _post_overpass(url: str, query: str, timeout: float) -> dict | None:
    try:
        response = await client().post(
            url,
            data={"data": query},
            timeout=httpx.Timeout(timeout, connect=6.0),
        )
    except httpx.HTTPError as exc:
        log.warning("overpass failed %s: %s", url, type(exc).__name__)
        return None
    if response.status_code in {429, 502, 503, 504} or response.status_code >= 400:
        log.warning("overpass status %s: HTTP %s", url, response.status_code)
        return None
    try:
        return response.json()
    except ValueError:
        log.warning("overpass JSON failed %s", url)
        return None


async def overpass(query: str, timeout: float = 20.0) -> dict:
    """Primary instance wins, including an empty result. Fallback is used when the primary is down."""
    payload = await _post_overpass(OVERPASS_PRIMARY, query, timeout)
    if payload is not None:
        return payload
    fallback = await _post_overpass(OVERPASS_FALLBACK, query, timeout)
    if fallback is not None:
        return fallback
    raise WaterLookupError("OpenStreetMap Overpass şu an yanıt vermiyor. Biraz sonra tekrar deneyin.")


def _bounds_area(element: dict) -> float:
    bounds = element.get("bounds") or {}
    try:
        height = abs(float(bounds["maxlat"]) - float(bounds["minlat"]))
        width = abs(float(bounds["maxlon"]) - float(bounds["minlon"]))
    except (KeyError, TypeError, ValueError):
        return 1e9
    return height * width


def classify(tags: dict) -> str | None:
    water = str(tags.get("water") or "").lower()
    natural = str(tags.get("natural") or "").lower()
    place = str(tags.get("place") or "").lower()
    salt = str(tags.get("salt") or "").lower()

    if water in {"wastewater", "fountain", "swimming_pool", "reflecting_pool"} or tags.get("leisure") == "swimming_pool":
        return None
    waterway = str(tags.get("waterway") or "").lower()
    if waterway in {"river", "stream", "canal", "tidal_channel"}:
        if salt == "yes" or str(tags.get("tidal") or "").lower() == "yes":
            return "brackish"
        return "freshwater"
    if salt == "yes" or water == "lagoon":
        return "brackish"
    if place in {"sea", "ocean"} or water in {"sea", "ocean"} or natural in {"coastline", "bay", "strait"}:
        return "saltwater"
    if natural == "water" or water in {
        "lake",
        "reservoir",
        "pond",
        "river",
        "stream",
        "canal",
        "oxbow",
        "basin",
        "moat",
    }:
        return "freshwater"
    return None


def feature_name(tags: dict) -> str | None:
    for key in ("name:tr", "name", "alt_name:tr", "alt_name", "name:en"):
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def water_label(tags: dict, kind: str) -> str:
    natural = str(tags.get("natural") or "").lower()
    place = str(tags.get("place") or "").lower()
    water = str(tags.get("water") or "").lower()
    waterway = str(tags.get("waterway") or "").lower()
    title = feature_name(tags) or ""
    blob = ""
    if title:
        from backend.tackle import fold

        blob = fold(title)
    if "baraj" in blob:
        return "Baraj"
    if "golet" in blob:
        return "Gölet"
    if blob.endswith(" golu") or " golu" in blob:
        return "Göl"
    if blob.endswith(" deresi") or blob.endswith(" dere"):
        return "Dere"
    if blob.endswith(" cayi") or blob.endswith(" cay"):
        return "Çay"
    if blob.endswith(" irmagi") or blob.endswith(" irmak"):
        return "Irmak"
    if waterway == "stream" or water == "stream":
        return "Dere"
    if waterway == "river" or water == "river":
        return "Irmak"
    if waterway == "canal" or water == "canal":
        return "Kanal"
    if place in WATER_LABEL:
        return WATER_LABEL[place]
    if natural in {"bay", "strait", "coastline"}:
        return WATER_LABEL[natural]
    if water in WATER_LABEL:
        return WATER_LABEL[water]
    if kind == "saltwater":
        return "Deniz"
    if kind == "brackish":
        return "Acı su"
    return "Su kütlesi"


def _containing_query(lat: float, lon: float) -> str:
    return f"""
[out:json][timeout:25];
is_in({lat},{lon})->.a;
(
  way(pivot.a)["natural"="water"];
  relation(pivot.a)["natural"="water"];
  way(pivot.a)["water"="lake"];
  way(pivot.a)["water"="reservoir"];
  relation(pivot.a)["water"="lake"];
  relation(pivot.a)["water"="reservoir"];
  relation(pivot.a)["place"="sea"];
  relation(pivot.a)["natural"="bay"];
  relation(pivot.a)["natural"="strait"];
);
out tags bb;
"""


def _sea_box_query(lat: float, lon: float) -> str:
    south, north = lat - 0.08, lat + 0.08
    west, east = lon - 0.08, lon + 0.08
    return f"""
[out:json][timeout:15];
relation["place"="sea"]({south},{west},{north},{east});
out tags;
"""


async def _sea_relation_name(lat: float, lon: float) -> str | None:
    try:
        payload = await overpass(_sea_box_query(lat, lon), timeout=15.0)
    except WaterLookupError:
        return None
    names = []
    for element in payload.get("elements") or []:
        title = feature_name(element.get("tags") or {})
        if title and title not in names:
            names.append(title)
    if len(names) == 1:
        return names[0]
    return None


def _course_query(lat: float, lon: float) -> str:
    return f"""
[out:json][timeout:15];
(
  way(around:40,{lat},{lon})["waterway"="river"]["name"];
  way(around:40,{lat},{lon})["waterway"="stream"]["name"];
  way(around:40,{lat},{lon})["waterway"="canal"]["name"];
);
out tags center;
"""


def _shore_query(lat: float, lon: float) -> str:
    return f"""
[out:json][timeout:15];
way(around:90,{lat},{lon})["natural"="coastline"];
out tags;
"""


def _score(element: dict, origin: tuple[float, float] | None) -> float:
    center = element.get("center") or {}
    if origin and "lat" in center and "lon" in center:
        distance = abs(float(center["lat"]) - origin[0]) + abs(float(center["lon"]) - origin[1])
        if (element.get("tags") or {}).get("natural") == "coastline":
            distance += 0.02
        return distance
    return _bounds_area(element)


def _choose(elements: list[dict], origin: tuple[float, float] | None = None) -> tuple[str, dict] | None:
    ranked: list[tuple[float, str, dict]] = []
    for element in elements:
        tags = element.get("tags") or {}
        kind = classify(tags)
        if kind is None:
            continue
        ranked.append((_score(element, origin), kind, element))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    _area, kind, element = ranked[0]
    return kind, element


def _ring(geometry: list[dict], limit: int = 1600) -> list[list[float]] | None:
    coords = []
    for point in geometry or []:
        try:
            coords.append([float(point["lon"]), float(point["lat"])])
        except (KeyError, TypeError, ValueError):
            continue
    if len(coords) < 4:
        return None
    if len(coords) > limit:
        step = len(coords) / limit
        coords = [coords[int(i * step)] for i in range(limit)]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def _line_coords(geometry: list | None) -> list[list[float]]:
    coords = []
    for point in geometry or []:
        try:
            coords.append([float(point["lon"]), float(point["lat"])])
        except (KeyError, TypeError, ValueError):
            continue
    return coords


def _same_point(left: list[float], right: list[float]) -> bool:
    return abs(left[0] - right[0]) < 1e-5 and abs(left[1] - right[1]) < 1e-5


def _chain_lines(lines: list[list[list[float]]]) -> list[list[list[float]]]:
    unused = [line for line in lines if len(line) >= 2]
    rings = []
    while unused:
        ring = unused.pop(0)
        moved = True
        while moved and not _same_point(ring[0], ring[-1]):
            moved = False
            for index, line in enumerate(unused):
                if _same_point(ring[-1], line[0]):
                    ring.extend(line[1:])
                elif _same_point(ring[-1], line[-1]):
                    ring.extend(list(reversed(line))[1:])
                elif _same_point(ring[0], line[-1]):
                    ring = line[:-1] + ring
                elif _same_point(ring[0], line[0]):
                    ring = list(reversed(line))[:-1] + ring
                else:
                    continue
                unused.pop(index)
                moved = True
                break
        if len(ring) >= 4 and _same_point(ring[0], ring[-1]):
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            rings.append(ring)
    return rings


def _member_lines(element: dict, ways: dict[int, dict]) -> tuple[list, list]:
    outers = []
    inners = []
    for member in element.get("members") or []:
        if member.get("type") not in {None, "way"}:
            continue
        geometry = member.get("geometry")
        if not geometry:
            way = ways.get(member.get("ref"))
            geometry = (way or {}).get("geometry")
        coords = _line_coords(geometry)
        if len(coords) < 2:
            continue
        if member.get("role") == "inner":
            inners.append(coords)
        else:
            outers.append(coords)
    return outers, inners


def geojson_from_element(element: dict, ways: dict[int, dict] | None = None) -> dict | None:
    if element.get("type") == "way":
        ring = _ring(element.get("geometry") or [])
        if not ring:
            return None
        return {"type": "Polygon", "coordinates": [ring]}

    outers, inners = _member_lines(element, ways or {})
    outer_rings = _chain_lines(outers)
    inner_rings = _chain_lines(inners)
    if not outer_rings:
        return None
    polygons = []
    for outer in outer_rings:
        holes = [hole for hole in inner_rings if hole and _ring_contains(hole[0][0], hole[0][1], outer)]
        polygons.append([_ring_list(outer), *[_ring_list(hole) for hole in holes]])
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _ring_list(coords: list[list[float]]) -> list[list[float]]:
    ring = _ring([{"lon": point[0], "lat": point[1]} for point in coords])
    return ring or coords


async def _geometry(element: dict) -> dict | None:
    osm_type = element.get("type")
    osm_id = element.get("id")
    if osm_type not in {"way", "relation"} or not osm_id:
        return None
    if _bounds_area(element) > 1.2:
        return None
    if osm_type == "relation":
        query = f"""
[out:json][timeout:25];
relation({int(osm_id)})->.r;
(.r; way(r.r););
out geom;
"""
    else:
        query = f"""
[out:json][timeout:25];
way({int(osm_id)});
out geom;
"""
    try:
        payload = await overpass(query, timeout=15.0)
    except WaterLookupError as exc:
        log.warning("geometry skipped: %s", exc)
        return None
    elements = payload.get("elements") or []
    relation = next((item for item in elements if item.get("type") == "relation"), None)
    element = relation or (elements[0] if elements else None)
    if element is None:
        return None
    ways = {item["id"]: item for item in elements if item.get("type") == "way" and item.get("id")}
    return geojson_from_element(element, ways)


async def _nominatim_name(lat: float, lon: float) -> str | None:
    key = (round(lat, 3), round(lon, 3))
    if key in _nominatim_cache:
        return _nominatim_cache[key]
    try:
        response = await client().get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": 8,
                "accept-language": "tr",
            },
        )
        response.raise_for_status()
        address = (response.json() or {}).get("address") or {}
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("nominatim failed: %s", exc)
        _nominatim_cache[key] = None
        return None
    name = None
    for field in ("sea", "ocean", "bay", "water", "reservoir", "lake"):
        value = address.get(field)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            break
    _nominatim_cache[key] = name
    return name


def _harbour_query(lat: float, lon: float) -> str:
    return f"""
[out:json][timeout:25];
(
  relation(around:1600,{lat},{lon})["seamark:type"="harbour"];
  relation(around:1600,{lat},{lon})["leisure"="marina"];
  relation(around:1600,{lat},{lon})["landuse"="harbour"];
)->.rels;
(
  .rels;
  way(r.rels);
  way(around:1600,{lat},{lon})["leisure"="marina"];
  way(around:1600,{lat},{lon})["landuse"="harbour"];
  way(around:1600,{lat},{lon})["harbour"="yes"];
  way(around:1600,{lat},{lon})["man_made"="breakwater"];
  way(around:2000,{lat},{lon})["natural"="coastline"];
);
out geom;
"""


def _is_harbour(tags: dict) -> bool:
    if str(tags.get("seamark:type") or "") == "harbour":
        return True
    if str(tags.get("leisure") or "") == "marina":
        return True
    if str(tags.get("landuse") or "") == "harbour":
        return True
    return str(tags.get("harbour") or "") in {"yes", "basin"}


def _ring_contains(lon: float, lat: float, ring: list) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    previous = ring[-1]
    for point in ring:
        x1, y1 = previous
        x2, y2 = point
        if (y1 > lat) != (y2 > lat):
            cross = (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1
            if lon < cross:
                inside = not inside
        previous = point
    return inside


def _interior_point(geometry: dict, lat: float, lon: float) -> tuple[float, float]:
    if _geometry_contains(lon, lat, geometry):
        return lat, lon
    points: list[list[float]] = []

    def walk(node) -> None:
        if isinstance(node, list) and node and isinstance(node[0], (int, float)) and len(node) >= 2:
            points.append(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(geometry.get("coordinates"))
    if not points:
        return lat, lon
    lats = [point[1] for point in points]
    lons = [point[0] for point in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    best = None
    best_distance = None
    steps = 16
    for row in range(steps):
        for col in range(steps):
            plat = min_lat + (max_lat - min_lat) * (row + 0.5) / steps
            plon = min_lon + (max_lon - min_lon) * (col + 0.5) / steps
            if not _geometry_contains(plon, plat, geometry):
                continue
            distance = (plat - lat) ** 2 + (plon - lon) ** 2
            if best is None or distance < best_distance:
                best = (plat, plon)
                best_distance = distance
    if best is None:
        return lat, lon
    return round(best[0], 6), round(best[1], 6)


def _geometry_contains(lon: float, lat: float, geometry: dict | None) -> bool:
    if not geometry:
        return False
    if geometry.get("type") == "Polygon":
        rings = geometry.get("coordinates") or []
        if not rings or not _ring_contains(lon, lat, rings[0]):
            return False
        return not any(_ring_contains(lon, lat, hole) for hole in rings[1:])
    if geometry.get("type") == "MultiPolygon":
        return any(_geometry_contains(lon, lat, {"type": "Polygon", "coordinates": polygon}) for polygon in geometry.get("coordinates") or [])
    return False


def _segment_meters(lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    scale_x = 111_320 * math.cos(math.radians(lat))
    x1 = (lon1 - lon) * scale_x
    y1 = (lat1 - lat) * 110_540
    x2 = (lon2 - lon) * scale_x
    y2 = (lat2 - lat) * 110_540
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x1, y1)
    t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy)))
    return math.hypot(x1 + t * dx, y1 + t * dy)


def _line_points(element: dict) -> list[list[dict]]:
    if element.get("type") == "way":
        return [element.get("geometry") or []]
    lines = []
    for member in element.get("members") or []:
        geometry = member.get("geometry") or []
        if geometry:
            lines.append(geometry)
    return lines


def _nearest_meters(lat: float, lon: float, elements: list[dict]) -> float | None:
    best = None
    for element in elements:
        for line in _line_points(element):
            previous = None
            for point in line:
                try:
                    point_lat = float(point["lat"])
                    point_lon = float(point["lon"])
                except (KeyError, TypeError, ValueError):
                    previous = None
                    continue
                if previous is not None:
                    distance = _segment_meters(lat, lon, previous[0], previous[1], point_lat, point_lon)
                    if best is None or distance < best:
                        best = distance
                previous = (point_lat, point_lon)
    return best


async def _coast_context(lat: float, lon: float, sea_name: str | None) -> dict:
    try:
        payload = await overpass(_harbour_query(lat, lon), timeout=22.0)
    except WaterLookupError as exc:
        log.warning("harbour lookup skipped: %s", exc)
        return {
            "zone": None,
            "zone_label": None,
            "zone_note": "Liman ve kıyı çizgisi şu an alınamadı. Liste tüm tuzlu su kaydı.",
        }

    harbours = []
    edges = []
    coast_lines = []
    for element in payload.get("elements") or []:
        tags = element.get("tags") or {}
        if _is_harbour(tags):
            geometry = geojson_from_element(element)
            if geometry:
                harbours.append((element, geometry, feature_name(tags)))
        if tags.get("natural") == "coastline" or tags.get("man_made") == "breakwater":
            edges.append(element)
        if tags.get("natural") == "coastline":
            coast_lines.extend(_line_points(element))

    containing = []
    nearest_harbour = None
    nearest_gap = None
    for element, geometry, name in harbours:
        if _geometry_contains(lon, lat, geometry):
            containing.append((_bounds_area(element), name, geometry))
        gap = _nearest_meters(lat, lon, [element])
        if gap is not None and (nearest_gap is None or gap < nearest_gap):
            nearest_gap = gap
            nearest_harbour = (name, geometry, gap)

    from backend.shoreband import CAST_M, band_from_lines, outer_band_from_lines

    shore_band = band_from_lines(coast_lines, CAST_M)
    open_band = outer_band_from_lines(coast_lines, CAST_M, 280)
    lines = coast_lines
    shore_gap = _nearest_meters(lat, lon, edges)
    if containing:
        containing.sort(key=lambda item: item[0])
        _area, name, geometry = containing[0]
        title = name or "Liman"
        parent = f" {sea_name} üzerinde." if sea_name and sea_name != title else ""
        return {
            "zone": "harbor",
            "zone_label": "İç liman",
            "zone_note": f"Bu nokta {title} içinde.{parent} Kapalı havuz ile mendirek dışı aynı liste değildir.",
            "harbour_name": title,
            "harbour_geometry": geometry,
            "name": title,
            "water_label": "İç liman",
            "shore_band": shore_band,
            "open_band": open_band,
            "coast_lines": lines,
        }

    gap = shore_gap
    if nearest_gap is not None and (gap is None or nearest_gap < gap):
        gap = nearest_gap
    harbour_name = nearest_harbour[0] if nearest_harbour else None
    harbour_geometry = nearest_harbour[1] if nearest_harbour else None
    if gap is not None and gap <= 350:
        beside_harbour = (
            harbour_name
            and nearest_gap is not None
            and nearest_gap <= (shore_gap if shore_gap is not None else nearest_gap)
        )
        if beside_harbour:
            note = (
                f"Bu nokta {harbour_name} dışında, mendireğe {gap:.0f} m. "
                "Liste bu kıyı noktası içindir."
            )
        else:
            note = (
                f"Bu nokta kıyıdan {gap:.0f} m. "
                "Liste, buradan atılan kıyı avı içindir."
            )
        return {
            "zone": "shore",
            "zone_label": "Kıyı",
            "zone_note": note,
            "harbour_name": harbour_name,
            "harbour_geometry": harbour_geometry,
            "shore_distance_m": round(gap),
            "water_label": "Kıyı",
            "shore_band": shore_band,
            "open_band": open_band,
            "coast_lines": lines,
        }
    if gap is None:
        note = "Yakın kıyı çizgisi yok. Liste açık deniz katmanına göre."
        distance = None
    else:
        note = f"Kıyıdan {gap:.0f} m açıkta. Liste, kıyıdan atılan avdan ayrıdır."
        distance = round(gap)
    return {
        "zone": "open",
        "zone_label": "Açık deniz",
        "zone_note": note,
        "harbour_name": harbour_name,
        "harbour_geometry": harbour_geometry,
        "shore_distance_m": distance,
        "water_label": "Açık deniz",
        "shore_band": shore_band,
        "open_band": open_band,
        "coast_lines": lines,
    }


async def lookup_water(
    lat: float,
    lon: float,
    osm_type: str | None = None,
    osm_id: int | None = None,
) -> dict:
    if osm_type in {"way", "relation"} and osm_id:
        result = await _lookup_known(lat, lon, osm_type, int(osm_id))
        if result.get("found"):
            key = (round(float(result["lat"]), 4), round(float(result["lon"]), 4))
            _water_cache[key] = (time.time(), result)
        return result
    key = (round(lat, 4), round(lon, 4))
    cached = _water_cache.get(key)
    if cached and time.time() - cached[0] < WATER_CACHE_SECONDS:
        return cached[1]
    result = await _lookup_water(lat, lon)
    if result.get("found"):
        _water_cache[key] = (time.time(), result)
    return result


def _by_id_query(osm_type: str, osm_id: int) -> str:
    if osm_type == "relation":
        return f"""
[out:json][timeout:25];
relation({osm_id})->.r;
(.r; way(r.r););
out geom;
"""
    return f"""
[out:json][timeout:25];
way({osm_id});
out geom;
"""


async def _lookup_known(lat: float, lon: float, osm_type: str, osm_id: int) -> dict:
    try:
        payload = await overpass(_by_id_query(osm_type, osm_id), timeout=25.0)
    except WaterLookupError as exc:
        log.warning("known water skipped: %s", exc)
        return await _lookup_water(lat, lon)
    element = next(
        (
            item
            for item in payload.get("elements") or []
            if item.get("type") == osm_type and item.get("id") == osm_id
        ),
        None,
    )
    if element is None:
        return {
            "found": False,
            "lat": lat,
            "lon": lon,
            "message": "Seçilen suyun çizgisi şu an gelmedi. Liste noktası gölün dışında kalmış olabilir.",
            "source": "OpenStreetMap Overpass",
        }
    tags = element.get("tags") or {}
    kind = classify(tags) or "freshwater"
    ways = {
        item["id"]: item
        for item in payload.get("elements") or []
        if item.get("type") == "way" and item.get("id")
    }
    geometry = None
    if kind != "saltwater" and not tags.get("waterway"):
        geometry = geojson_from_element(element, ways)
    if geometry and not _geometry_contains(lon, lat, geometry):
        lat, lon = _interior_point(geometry, lat, lon)
    return await _finish_water(lat, lon, kind, element, geometry)


async def _lookup_water(lat: float, lon: float) -> dict:
    payload = await overpass(_containing_query(lat, lon))
    chosen = _choose(payload.get("elements") or [])
    if chosen is None:
        course = await overpass(_course_query(lat, lon))
        chosen = _choose(course.get("elements") or [], origin=(lat, lon))
    if chosen is None:
        shore = await overpass(_shore_query(lat, lon))
        chosen = _choose(shore.get("elements") or [], origin=(lat, lon))

    if chosen is None:
        return {
            "found": False,
            "lat": lat,
            "lon": lon,
            "message": "Bu noktada OpenStreetMap su kütlesi yok.",
            "source": "OpenStreetMap Overpass",
        }

    kind, element = chosen
    geometry = None
    if kind != "saltwater" and not (element.get("tags") or {}).get("waterway"):
        geometry = await _geometry(element)
    return await _finish_water(lat, lon, kind, element, geometry)


async def _finish_water(lat: float, lon: float, kind: str, element: dict, geometry: dict | None) -> dict:
    tags = element.get("tags") or {}
    name = feature_name(tags)
    label = water_label(tags, kind)
    if name is None and kind == "saltwater":
        name = await _nominatim_name(lat, lon)
    if name is None and kind == "saltwater":
        name = await _sea_relation_name(lat, lon)

    alt = tags.get("alt_name:tr") or tags.get("alt_name")
    if isinstance(alt, str) and alt.strip() == name:
        alt = None

    zone = {}
    if kind in {"saltwater", "brackish"}:
        zone = await _coast_context(lat, lon, name)
        if zone.get("name"):
            if name and name != zone["name"]:
                alt = name
            name = zone["name"]
        if zone.get("water_label"):
            label = zone["water_label"]

    from backend.shoreband import CAST_M, band_from_polygon, cells_for_place

    lake_band = band_from_polygon(geometry, CAST_M) if geometry else None
    harbour = zone.get("harbour_geometry")
    coast_band = zone.get("shore_band")
    water_shape = geometry if geometry and not tags.get("waterway") else None
    cells = cells_for_place(harbour, water_shape, zone.get("coast_lines"))
    shore_band = lake_band or coast_band or (band_from_polygon(harbour, CAST_M) if harbour else None)

    return {
        "found": True,
        "lat": lat,
        "lon": lon,
        "name": name,
        "alt_name": alt.strip() if isinstance(alt, str) and alt.strip() else None,
        "kind": kind,
        "kind_label": KIND_LABEL[kind],
        "water": tags.get("water") or tags.get("natural") or tags.get("place"),
        "water_label": label,
        "zone": zone.get("zone"),
        "zone_label": zone.get("zone_label"),
        "zone_note": zone.get("zone_note"),
        "harbour_name": zone.get("harbour_name"),
        "shore_distance_m": zone.get("shore_distance_m"),
        "osm_type": element.get("type"),
        "osm_id": element.get("id"),
        "geometry": geometry,
        "harbour_geometry": zone.get("harbour_geometry"),
        "shore_band": shore_band,
        "cast_cells": cells,
        "shore_cast_m": CAST_M if shore_band or cells else None,
        "source": "OpenStreetMap Overpass",
        "attribution": "© OpenStreetMap katkıları, ODbL",
    }


_COVER = {
    ("natural", "wood"): ("Ağaç", "tree"),
    ("landuse", "forest"): ("Ağaç", "tree"),
    ("natural", "beach"): ("Sahil", "beach"),
    ("natural", "sand"): ("Sahil", "beach"),
    ("natural", "bare_rock"): ("Kayalık", "rock"),
    ("natural", "rock"): ("Kayalık", "rock"),
    ("natural", "cliff"): ("Kayalık", "rock"),
    ("natural", "scree"): ("Kayalık", "rock"),
    ("natural", "wetland"): ("Sazlık", "wet"),
    ("natural", "scrub"): ("Çalı", "scrub"),
}


def _cover_query(south: float, west: float, north: float, east: float) -> str:
    box = f"({south},{west},{north},{east})"
    return f"""
[out:json][timeout:18];
(
  way["natural"="wood"]{box};
  way["landuse"="forest"]{box};
  way["natural"="beach"]{box};
  way["natural"="sand"]{box};
  way["natural"="bare_rock"]{box};
  way["natural"="rock"]{box};
  way["natural"="cliff"]{box};
  way["natural"="scree"]{box};
  way["natural"="wetland"]{box};
  way["natural"="scrub"]{box};
);
out tags geom;
"""


def _cover_kind(tags: dict) -> tuple[str, str] | None:
    for key, value in (("natural", tags.get("natural")), ("landuse", tags.get("landuse"))):
        found = _COVER.get((key, str(value or "")))
        if found:
            return found
    return None


async def lookup_landcover(south: float, west: float, north: float, east: float) -> dict:
    if north <= south or east <= west:
        raise WaterLookupError("Zemin kutusu geçersiz.")
    if north - south > 0.4 or east - west > 0.4:
        mid_lat = (south + north) / 2
        mid_lon = (west + east) / 2
        south, north = mid_lat - 0.2, mid_lat + 0.2
        west, east = mid_lon - 0.2, mid_lon + 0.2
    try:
        payload = await overpass(_cover_query(south, west, north, east), timeout=18.0)
    except WaterLookupError:
        return {
            "type": "FeatureCollection",
            "features": [],
            "note": "Ağaç, kayalık ve sahil etiketleri şu an gelmedi. Zemin uydu görüntüsünde duruyor.",
            "source": "OpenStreetMap",
        }
    features = []
    for element in payload.get("elements") or []:
        named = _cover_kind(element.get("tags") or {})
        if named is None:
            continue
        geometry = geojson_from_element(element)
        if not geometry:
            continue
        label, kind = named
        features.append(
            {
                "type": "Feature",
                "properties": {"label": label, "kind": kind},
                "geometry": geometry,
            }
        )
        if len(features) >= 80:
            break
    note = "Etiketler OpenStreetMap kaydıdır. Etiketsiz zemin uydu görüntüsünde durur."
    if not features:
        note = "Bu kıyıda ağaç, kayalık veya sahil etiketi yok. Zemin uydu görüntüsünde durur."
    return {
        "type": "FeatureCollection",
        "features": features,
        "note": note,
        "source": "OpenStreetMap",
    }
