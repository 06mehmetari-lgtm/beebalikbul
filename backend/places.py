"""Province outline, inland waters, and the sea on a province coast."""

from __future__ import annotations

import asyncio
import math
import time

import httpx

from backend.net import client
from backend.tackle import fold
from backend.water import OVERPASS_FALLBACK, OVERPASS_PRIMARY, WaterLookupError, geojson_from_element

PROVINCES = (
    "Adana",
    "Adıyaman",
    "Afyonkarahisar",
    "Ağrı",
    "Aksaray",
    "Amasya",
    "Ankara",
    "Antalya",
    "Ardahan",
    "Artvin",
    "Aydın",
    "Balıkesir",
    "Bartın",
    "Batman",
    "Bayburt",
    "Bilecik",
    "Bingöl",
    "Bitlis",
    "Bolu",
    "Burdur",
    "Bursa",
    "Çanakkale",
    "Çankırı",
    "Çorum",
    "Denizli",
    "Diyarbakır",
    "Düzce",
    "Edirne",
    "Elazığ",
    "Erzincan",
    "Erzurum",
    "Eskişehir",
    "Gaziantep",
    "Giresun",
    "Gümüşhane",
    "Hakkari",
    "Hatay",
    "Iğdır",
    "Isparta",
    "İstanbul",
    "İzmir",
    "Kahramanmaraş",
    "Karabük",
    "Karaman",
    "Kars",
    "Kastamonu",
    "Kayseri",
    "Kilis",
    "Kırıkkale",
    "Kırklareli",
    "Kırşehir",
    "Kocaeli",
    "Konya",
    "Kütahya",
    "Malatya",
    "Manisa",
    "Mardin",
    "Mersin",
    "Muğla",
    "Muş",
    "Nevşehir",
    "Niğde",
    "Ordu",
    "Osmaniye",
    "Rize",
    "Sakarya",
    "Samsun",
    "Şanlıurfa",
    "Siirt",
    "Sinop",
    "Sivas",
    "Şırnak",
    "Tekirdağ",
    "Tokat",
    "Trabzon",
    "Tunceli",
    "Uşak",
    "Van",
    "Yalova",
    "Yozgat",
    "Zonguldak",
)

_ALIASES = {
    "Afyonkarahisar": ("Afyonkarahisar", "Afyon"),
    "Mersin": ("Mersin", "İçel"),
}

_cache: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 3600


def _area(element: dict) -> float:
    bounds = element.get("bounds") or {}
    try:
        return abs(float(bounds["maxlat"]) - float(bounds["minlat"])) * abs(
            float(bounds["maxlon"]) - float(bounds["minlon"])
        )
    except (KeyError, TypeError, ValueError):
        return 0.0


def _course_label(tags: dict, title: str) -> str | None:
    waterway = str(tags.get("waterway") or "")
    water = str(tags.get("water") or "")
    blob = fold(title)
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
    return None


def _label(tags: dict, title: str = "") -> str:
    blob = fold(title)
    if "baraj" in blob:
        return "Baraj"
    if "golet" in blob:
        return "Gölet"
    if blob.endswith(" golu") or " golu" in blob:
        return "Göl"
    course = _course_label(tags, title)
    if course:
        return course
    water = str(tags.get("water") or "")
    if water == "reservoir":
        return "Baraj"
    if water == "lake":
        return "Göl"
    if water == "pond":
        return "Gölet"
    if water == "lagoon":
        return "Lagün"
    if water == "oxbow":
        return "Menderes gölü"
    return "Su"


def _name(tags: dict) -> str | None:
    for key in ("name:tr", "name", "alt_name:tr", "alt_name"):
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _bounds_query(name: str) -> str:
    safe = name.replace('"', "")
    return f"""
[out:json][timeout:25];
relation["boundary"="administrative"]["admin_level"="4"]["name"="{safe}"];
out tags bb;
"""


def _coast_query(bounds: dict) -> str:
    south, west, north, east = bounds["south"], bounds["west"], bounds["north"], bounds["east"]
    box = f"({south},{west},{north},{east})"
    return f"""
[out:json][timeout:18];
way["natural"="coastline"]{box};
out bb;
"""


def _sea_relations_query(bounds: dict) -> str:
    south, west, north, east = bounds["south"], bounds["west"], bounds["north"], bounds["east"]
    return f"""
[out:json][timeout:20];
relation["place"="sea"]({south},{west},{north},{east});
out tags;
"""


def _side_point(lat1: float, lon1: float, lat2: float, lon2: float, meters: float, left: bool) -> tuple[float, float]:
    scale = 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    dx = (lon2 - lon1) * scale
    dy = (lat2 - lat1) * 110_540
    length = math.hypot(dx, dy) or 1.0
    if left:
        north_x, north_y = -dy / length, dx / length
    else:
        north_x, north_y = dy / length, -dx / length
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2
    return mid_lat + north_y * meters / 110_540, mid_lon + north_x * meters / scale


_AREAL_WATER = {"lake", "reservoir", "pond", "oxbow", "lagoon", "river", "basin", "stream", "canal", ""}


def _waters_query(bounds: dict) -> str:
    south, west, north, east = bounds["south"], bounds["west"], bounds["north"], bounds["east"]
    box = f"({south},{west},{north},{east})"
    return f"""
[out:json][timeout:40];
(
  way["natural"="water"]["name"]{box};
  relation["natural"="water"]["name"]{box};
);
out tags center bb;
"""


def _flows_query(bounds: dict) -> str:
    south, west, north, east = bounds["south"], bounds["west"], bounds["north"], bounds["east"]
    box = f"({south},{west},{north},{east})"
    return f"""
[out:json][timeout:25];
(
  way["waterway"="river"]["name"]{box};
  way["waterway"="stream"]["name"]{box};
  way["waterway"="canal"]["name"]{box};
);
out tags bb;
"""


def _covers(geometry: dict, bounds: dict) -> float:
    points: list[list[float]] = []

    def walk(node) -> None:
        if isinstance(node, list) and node and isinstance(node[0], (int, float)):
            points.append(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(geometry.get("coordinates"))
    if not points:
        return 0.0
    lats = [point[1] for point in points]
    lons = [point[0] for point in points]
    geom_area = abs(max(lats) - min(lats)) * abs(max(lons) - min(lons))
    province_area = abs(bounds["north"] - bounds["south"]) * abs(bounds["east"] - bounds["west"])
    if province_area <= 0:
        return 0.0
    return geom_area / province_area


def _inside(lon: float, lat: float, geometry: dict | None) -> bool:
    if not geometry:
        return True
    if geometry.get("type") == "Polygon":
        return _in_polygon(lon, lat, geometry.get("coordinates") or [])
    if geometry.get("type") == "MultiPolygon":
        return any(_in_polygon(lon, lat, polygon) for polygon in geometry.get("coordinates") or [])
    return True


def _in_polygon(lon: float, lat: float, rings: list) -> bool:
    if not rings or not _ray(lon, lat, rings[0]):
        return False
    return not any(_ray(lon, lat, hole) for hole in rings[1:])


def _ray(lon: float, lat: float, ring: list) -> bool:
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


def _shape_query(ways: list[int], relations: list[int]) -> str:
    chunks = []
    if relations:
        ids = ",".join(str(item) for item in relations)
        chunks.append(f"relation(id:{ids})->.rels;")
    body = []
    if relations:
        body.extend(["  .rels;", "  way(r.rels);"])
    if ways:
        ids = ",".join(str(item) for item in ways)
        body.append(f"  way(id:{ids});")
    lines = ["[out:json][timeout:40];", *chunks, "(", *body, ");", "out geom;"]
    return "\n".join(lines)


def _coord_bounds(geometry: dict) -> tuple[float, float, float, float] | None:
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
        return None
    lats = [point[1] for point in points]
    lons = [point[0] for point in points]
    return min(lats), max(lats), min(lons), max(lons)


def _outer_rings(geometry: dict) -> list[list]:
    if geometry.get("type") == "Polygon":
        rings = geometry.get("coordinates") or []
        return [rings[0]] if rings else []
    if geometry.get("type") == "MultiPolygon":
        return [polygon[0] for polygon in geometry.get("coordinates") or [] if polygon]
    return []


def _nearest_inside(geometry: dict, lat: float, lon: float) -> tuple[float, float] | None:
    bounds = _coord_bounds(geometry)
    best = None
    best_distance = None
    if bounds:
        min_lat, max_lat, min_lon, max_lon = bounds
        steps = 18
        for row in range(steps):
            for col in range(steps):
                plat = min_lat + (max_lat - min_lat) * (row + 0.5) / steps
                plon = min_lon + (max_lon - min_lon) * (col + 0.5) / steps
                if not _inside(plon, plat, geometry):
                    continue
                distance = (plat - lat) ** 2 + (plon - lon) ** 2
                if best is None or distance < best_distance:
                    best = (plat, plon)
                    best_distance = distance
    for ring in _outer_rings(geometry):
        if len(ring) < 4:
            continue
        mean_lon = sum(point[0] for point in ring) / len(ring)
        mean_lat = sum(point[1] for point in ring) / len(ring)
        for index in range(len(ring) - 1):
            lon1, lat1 = ring[index]
            lon2, lat2 = ring[index + 1]
            mid_lat = (lat1 + lat2) / 2
            mid_lon = (lon1 + lon2) / 2
            for step in (0.08, 0.18, 0.35):
                plat = mid_lat + (mean_lat - mid_lat) * step
                plon = mid_lon + (mean_lon - mid_lon) * step
                if not _inside(plon, plat, geometry):
                    continue
                distance = (plat - lat) ** 2 + (plon - lon) ** 2
                if best is None or distance < best_distance:
                    best = (plat, plon)
                    best_distance = distance
                break
    return best


def _water_point(geometry: dict, lat: float, lon: float) -> tuple[float, float]:
    if _inside(lon, lat, geometry):
        return lat, lon
    found = _nearest_inside(geometry, lat, lon)
    if found is None:
        return lat, lon
    return round(found[0], 6), round(found[1], 6)


async def _move_into_water(waters: list[dict]) -> None:
    chosen = [place for place in waters if place.get("area", 0) <= 0.25 and place.get("osm_id")]
    ways = [place["osm_id"] for place in chosen if place.get("osm_type") == "way"]
    relations = [place["osm_id"] for place in chosen if place.get("osm_type") == "relation"]
    if not ways and not relations:
        return
    try:
        payload = await _richest(_shape_query(ways, relations), 50)
    except WaterLookupError:
        return
    way_ids = set(ways)
    shapes: dict[tuple[str, int], dict] = {}
    for element in payload.get("elements") or []:
        kind = element.get("type")
        osm_id = element.get("id")
        if kind == "way" and osm_id not in way_ids:
            continue
        if kind not in {"way", "relation"}:
            continue
        geometry = geojson_from_element(element)
        if geometry:
            shapes[(kind, osm_id)] = geometry
    for place in chosen:
        geometry = shapes.get((place.get("osm_type"), place.get("osm_id")))
        if not geometry:
            continue
        place["lat"], place["lon"] = _water_point(geometry, place["lat"], place["lon"])


def _skip_water(tags: dict, title: str) -> bool:
    blob = fold(title)
    if any(word in blob for word in ("depo", "deposu", "tank", "su kulesi", "kanalizasyon", "atiksu", "foseptik")):
        return True
    water = str(tags.get("water") or "")
    if water in {"wastewater", "fountain", "swimming_pool", "reflecting_pool"}:
        return True
    if tags.get("leisure") == "swimming_pool":
        return True
    man_made = str(tags.get("man_made") or "")
    if man_made in {"water_tower", "reservoir_covered", "storage_tank", "wastewater_plant"}:
        return True
    return False


def _node_pair(point: dict) -> tuple[float, float] | None:
    try:
        return float(point["lat"]), float(point["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def _meters(lat: float, lon: float, lat2: float, lon2: float) -> float:
    scale = 111_320 * math.cos(math.radians((lat + lat2) / 2))
    return math.hypot((lon2 - lon) * scale, (lat2 - lat) * 110_540)


def _bounds_span(element: dict) -> tuple[float, float, float]:
    box = element.get("bounds") or {}
    try:
        south = float(box["minlat"])
        north = float(box["maxlat"])
        west = float(box["minlon"])
        east = float(box["maxlon"])
    except (KeyError, TypeError, ValueError):
        return 0.0, 0.0, 0.0
    return _meters(south, west, north, east), (south + north) / 2, (west + east) / 2


def _in_box(lat: float, lon: float, bounds: dict) -> bool:
    return bounds["south"] <= lat <= bounds["north"] and bounds["west"] <= lon <= bounds["east"]


def _flow_places_fast(elements: list[dict], bounds: dict) -> list[dict]:
    grouped: dict[str, dict] = {}
    for element in elements:
        if element.get("type") != "way":
            continue
        tags = element.get("tags") or {}
        if tags.get("waterway") not in {"river", "stream", "canal"}:
            continue
        title = _name(tags)
        if not title or _skip_water(tags, title):
            continue
        span, lat, lon = _bounds_span(element)
        if span <= 0 or not _in_box(lat, lon, bounds):
            continue
        key = fold(title)
        current = grouped.get(key)
        if current is not None and span <= current["length"]:
            continue
        grouped[key] = {
            "name": title,
            "kind_label": _label(tags, title),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "area": 0,
            "length": span,
        }
    ranked = sorted(grouped.values(), key=lambda item: item["length"], reverse=True)
    return ranked[:25]


def _flow_way_ids(elements: list[dict], geometry: dict | None, limit: int = 40) -> list[int]:
    grouped: dict[str, tuple[float, int]] = {}
    outside: dict[str, tuple[float, int]] = {}
    for element in elements:
        if element.get("type") != "way" or not element.get("id"):
            continue
        tags = element.get("tags") or {}
        if tags.get("waterway") not in {"river", "stream", "canal"}:
            continue
        title = _name(tags)
        if not title or _skip_water(tags, title):
            continue
        span, lat, lon = _bounds_span(element)
        if span <= 0:
            continue
        bucket = grouped if _inside(lon, lat, geometry) else outside
        key = fold(title)
        current = bucket.get(key)
        if current is None or span > current[0]:
            bucket[key] = (span, int(element["id"]))
    chosen = grouped or outside
    ranked = sorted(chosen.values(), key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked[:limit]]


def _flow_places(elements: list[dict], geometry: dict | None) -> list[dict]:
    grouped: dict[str, dict] = {}
    for element in elements:
        if element.get("type") != "way":
            continue
        tags = element.get("tags") or {}
        if tags.get("waterway") not in {"river", "stream", "canal"}:
            continue
        title = _name(tags)
        if not title or _skip_water(tags, title):
            continue
        nodes = []
        for point in element.get("geometry") or []:
            pair = _node_pair(point)
            if pair:
                nodes.append(pair)
        if len(nodes) < 2:
            continue
        inside = [pair for pair in nodes if _inside(pair[1], pair[0], geometry)]
        if geometry and not inside:
            continue
        use = inside or nodes
        length = 0.0
        for start, end in zip(nodes, nodes[1:]):
            length += _meters(start[0], start[1], end[0], end[1])
        lat, lon = use[len(use) // 2]
        key = fold(title)
        current = grouped.get(key)
        if current is None:
            grouped[key] = {
                "name": title,
                "kind_label": _label(tags, title),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "area": 0,
                "length": length,
                "_longest": length,
            }
            continue
        current["length"] += length
        if length >= current.get("_longest", 0):
            current["_longest"] = length
            current["lat"] = round(lat, 6)
            current["lon"] = round(lon, 6)
            current["kind_label"] = _label(tags, title)
    places = []
    for place in grouped.values():
        place.pop("_longest", None)
        place["length"] = round(place["length"])
        places.append(place)
    places.sort(key=lambda item: item["length"], reverse=True)
    return places


async def _post_overpass_payload(url: str, query: str, timeout: float) -> dict | None:
    try:
        response = await client().post(
            url,
            data={"data": query},
            timeout=httpx.Timeout(timeout, connect=8.0),
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


async def _richest(query: str, timeout: float) -> dict:
    tasks = {
        asyncio.create_task(_post_overpass_payload(url, query, timeout))
        for url in (OVERPASS_FALLBACK, OVERPASS_PRIMARY)
    }
    best = None
    best_count = -1
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                payload = task.result()
                if not isinstance(payload, dict):
                    continue
                count = len(payload.get("elements") or [])
                if count > best_count:
                    best = payload
                    best_count = count
            if best is not None and pending:
                grace = 2 if best_count > 0 else 8
                extra_done, pending = await asyncio.wait(pending, timeout=grace)
                for task in extra_done:
                    payload = task.result()
                    if not isinstance(payload, dict):
                        continue
                    count = len(payload.get("elements") or [])
                    if count > best_count:
                        best = payload
                        best_count = count
                break
    finally:
        for task in pending:
            task.cancel()
    if best is None:
        raise WaterLookupError("OpenStreetMap Overpass şu an yanıt vermiyor (Overpass yanıt vermedi).")
    return best


async def _optional_overpass(query: str, timeout: float) -> dict:
    try:
        return await _richest(query, timeout)
    except WaterLookupError:
        return {}


async def _boundary(name: str) -> dict | None:
    try:
        response = await client().get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{name}, Türkiye",
                "format": "jsonv2",
                "polygon_geojson": 1,
                "polygon_threshold": 0.015,
                "countrycodes": "tr",
                "limit": 5,
            },
        )
        response.raise_for_status()
        rows = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    wanted = fold(name)
    for row in rows:
        label = fold(f"{row.get('name') or ''} {row.get('display_name') or ''}")
        geometry = row.get("geojson")
        if wanted not in label:
            continue
        if isinstance(geometry, dict) and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            return geometry
    return None


def _coast_segments(elements: list[dict]) -> list[tuple[float, float, float, float]]:
    segments = []
    for element in elements:
        line = element.get("geometry") or []
        parsed = []
        for point in line:
            try:
                parsed.append((float(point["lat"]), float(point["lon"])))
            except (KeyError, TypeError, ValueError):
                continue
        for index in range(len(parsed) - 1):
            lat1, lon1 = parsed[index]
            lat2, lon2 = parsed[index + 1]
            segments.append((lat1, lon1, lat2, lon2))
    return segments


def _nearest_coast(lat: float, lon: float, segments: list[tuple[float, float, float, float]]) -> tuple[float, float] | None:
    scale = 111_320 * math.cos(math.radians(lat))
    best = None
    for lat1, lon1, lat2, lon2 in segments:
        dx = (lon2 - lon1) * scale
        dy = (lat2 - lat1) * 110_540
        px = (lon - lon1) * scale
        py = (lat - lat1) * 110_540
        length = dx * dx + dy * dy
        if length == 0:
            continue
        along = max(0.0, min(1.0, (px * dx + py * dy) / length))
        dist = math.hypot(px - along * dx, py - along * dy)
        # Positive cross is the land side. OpenStreetMap keeps land on the left.
        cross = dx * py - dy * px
        if best is None or dist < best[0]:
            best = (dist, cross)
    if best is None:
        return None
    return best


def _coast_samples(elements: list[dict], geometry: dict | None) -> list[tuple[float, float]]:
    segments = _coast_segments(elements)
    if not segments:
        return []
    samples = []
    for element in elements:
        line = element.get("geometry") or []
        if len(line) < 2:
            continue
        starts = [max(0, len(line) // 2 - 1)]
        if len(line) > 30:
            starts = [max(0, len(line) // 5 - 1), starts[0], max(0, (4 * len(line)) // 5 - 1)]
        for start in starts:
            if start + 1 >= len(line):
                continue
            try:
                lat1 = float(line[start]["lat"])
                lon1 = float(line[start]["lon"])
                lat2 = float(line[start + 1]["lat"])
                lon2 = float(line[start + 1]["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            land_lat, land_lon = _side_point(lat1, lon1, lat2, lon2, 50, True)
            if geometry and not _inside(land_lon, land_lat, geometry):
                continue
            sea_lat, sea_lon = _side_point(lat1, lon1, lat2, lon2, 70, False)
            nearest = _nearest_coast(sea_lat, sea_lon, segments)
            if nearest is None:
                continue
            dist, cross = nearest
            if cross >= 0 or not 20 <= dist <= 110:
                continue
            samples.append((sea_lat, sea_lon))
    return samples


async def _province_seas(bounds: dict, geometry: dict | None) -> list[dict]:
    coast_payload, named_payload = await asyncio.gather(
        _richest(_coast_query(bounds), 18),
        _richest(_sea_relations_query(bounds), 15),
        return_exceptions=True,
    )
    if isinstance(coast_payload, Exception):
        return []
    best_id = None
    best_span = 0.0
    best_point = None
    for element in coast_payload.get("elements") or []:
        if element.get("type") != "way" or not element.get("id"):
            continue
        span, lat, lon = _bounds_span(element)
        if span <= best_span:
            continue
        best_span = span
        best_id = int(element["id"])
        best_point = (lat, lon)
    if best_id is None:
        return []
    samples = []
    try:
        shaped = await _richest(_shape_query([best_id], []), 18)
        samples = _coast_samples(shaped.get("elements") or [], geometry)
    except WaterLookupError:
        samples = []
    if not samples and best_point:
        samples = [best_point]
    named = named_payload if isinstance(named_payload, dict) else {}
    titles = []
    seen_names = set()
    for element in named.get("elements") or []:
        title = _name(element.get("tags") or {})
        if not title or fold(title) in seen_names:
            continue
        seen_names.add(fold(title))
        titles.append(title)
    samples.sort(key=lambda point: point[1])
    if len(titles) > 1 and len(samples) > 8:
        span = abs(samples[-1][1] - samples[0][1]) + abs(samples[-1][0] - samples[0][0])
        chosen = [samples[0], samples[len(samples) // 2], samples[-1]] if span > 0.35 else [samples[len(samples) // 2]]
    else:
        chosen = [samples[len(samples) // 2]]
    label = titles[0] if len(titles) == 1 else "Deniz"
    seas = []
    seen = set()
    for lat, lon in chosen:
        title = label
        key = (fold(title), round(lat, 2), round(lon, 2))
        if key in seen:
            continue
        seen.add(key)
        seas.append(
            {
                "name": title,
                "kind_label": "Deniz",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "area": 0,
            }
        )
    return seas


async def province_waters(name: str) -> dict:
    if name not in PROVINCES:
        raise WaterLookupError("Bu il listede yok.")
    cached = _cache.get(name)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]

    province = None
    for candidate in _ALIASES.get(name, (name,)):
        payload = await _richest(_bounds_query(candidate), 25)
        province = next(
            (
                element
                for element in payload.get("elements") or []
                if element.get("type") == "relation" and element.get("bounds")
            ),
            None,
        )
        if province:
            break
    if not province:
        raise WaterLookupError(f"{name} için OpenStreetMap il sınırı dönmedi.")

    box = province["bounds"]
    bounds = {
        "south": box.get("minlat"),
        "north": box.get("maxlat"),
        "west": box.get("minlon"),
        "east": box.get("maxlon"),
    }
    waters_payload, flow_payload, seas = await asyncio.gather(
        _richest(_waters_query(bounds), 30),
        _optional_overpass(_flows_query(bounds), 20),
        _province_seas(bounds, None),
    )

    waters = []
    for element in waters_payload.get("elements") or []:
        tags = element.get("tags") or {}
        if tags.get("natural") != "water":
            continue
        if tags.get("leisure") == "swimming_pool":
            continue
        title = _name(tags)
        center = element.get("center") or {}
        box = element.get("bounds") or {}
        if "lat" in center and "lon" in center:
            lat, lon = float(center["lat"]), float(center["lon"])
        elif "minlat" in box and "minlon" in box:
            lat = (float(box["minlat"]) + float(box["maxlat"])) / 2
            lon = (float(box["minlon"]) + float(box["maxlon"])) / 2
        else:
            continue
        if not title or _skip_water(tags, title):
            continue
        water = str(tags.get("water") or "")
        if water not in _AREAL_WATER:
            continue
        if not _in_box(lat, lon, bounds):
            continue
        waters.append(
            {
                "name": title,
                "kind_label": _label(tags, title),
                "lat": lat,
                "lon": lon,
                "area": round(_area(element), 5),
                "osm_type": element.get("type"),
                "osm_id": element.get("id"),
            }
        )
    waters.sort(key=lambda item: item["area"], reverse=True)
    flows = _flow_places_fast((flow_payload or {}).get("elements") or [], bounds)
    flow_names = {fold(place["name"]) for place in flows}
    waters = [place for place in waters if fold(place["name"]) not in flow_names or place["kind_label"] in {"Göl", "Baraj", "Gölet"}]
    total = len(waters) + len(flows) + len(seas)
    waters = seas + waters[:30] + flows
    result = {
        "province": name,
        "bounds": bounds,
        "geometry": None,
        "waters": waters,
        "total": total,
        "source": "OpenStreetMap",
        "note": "Liste ad ve noktadır. Bir su seçilince o yerin sorgusu ayrıca yapılır. Bu bir balık taraması değildir. Göller yüzölçümüne, akarsular çizgi uzunluğuna göre sıralanır.",
    }
    _cache[name] = (time.time(), result)
    return result
