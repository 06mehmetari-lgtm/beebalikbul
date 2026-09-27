"""Parking, shore cast point, walking route, and a geotagged photo. No invented spots."""

from __future__ import annotations

import logging
import math
import time

import httpx

from backend.net import client
from backend.water import (
    OVERPASS_FALLBACK,
    OVERPASS_PRIMARY,
    WaterLookupError,
    _geometry_contains,
    _post_overpass,
)

log = logging.getLogger("kontrolbee.access")

OSRM_URL = "https://router.project-osrm.org/route/v1/foot/{lon1},{lat1};{lon2},{lat2}"
PANORAMAX_SEARCH = "https://api.panoramax.xyz/api/search"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

_cache: dict[tuple[float, float], tuple[float, dict]] = {}
CACHE_SECONDS = 600

ROAD_LABEL = {
    "track": "Toprak yol",
    "service": "Servis yolu",
    "unclassified": "Araç yolu",
    "residential": "Sokak",
    "living_street": "Sokak",
}


class AccessError(RuntimeError):
    pass


def _meters(lat: float, lon: float, lat2: float, lon2: float) -> float:
    scale_x = 111_320 * math.cos(math.radians(lat))
    return math.hypot((lon2 - lon) * scale_x, (lat2 - lat) * 110_540)


def _closest_point(lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float):
    scale_x = 111_320 * math.cos(math.radians(lat))
    x1 = (lon1 - lon) * scale_x
    y1 = (lat1 - lat) * 110_540
    x2 = (lon2 - lon) * scale_x
    y2 = (lat2 - lat) * 110_540
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return lat1, lon1, math.hypot(x1, y1)
    length = dx * dx + dy * dy
    t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length))
    return lat + (y1 + t * dy) / 110_540, lon + (x1 + t * dx) / scale_x, math.hypot(x1 + t * dx, y1 + t * dy)


def _rings(geometry: dict | None) -> list[list]:
    if not geometry:
        return []
    if geometry.get("type") == "Polygon":
        rings = geometry.get("coordinates") or []
        return [rings[0]] if rings else []
    if geometry.get("type") == "MultiPolygon":
        found = []
        for polygon in geometry.get("coordinates") or []:
            if polygon:
                found.append(polygon[0])
        return found
    return []


def _closest_shore(lat: float, lon: float, rings: list[list]):
    best = None
    for ring in rings:
        if len(ring) < 2:
            continue
        for index in range(len(ring) - 1):
            lon1, lat1 = ring[index][0], ring[index][1]
            lon2, lat2 = ring[index + 1][0], ring[index + 1][1]
            point = _closest_point(lat, lon, lat1, lon1, lat2, lon2)
            if best is None or point[2] < best[2]:
                best = point
    return best


def _center(element: dict) -> tuple[float, float] | None:
    if element.get("type") == "node" and "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _bbox(rings: list[list]) -> tuple[float, float, float, float] | None:
    points = [point for ring in rings for point in ring]
    if not points:
        return None
    lats = [point[1] for point in points]
    lons = [point[0] for point in points]
    pad = 0.012
    return min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad


def _feature_query(south: float, west: float, north: float, east: float) -> str:
    box = f"({south},{west},{north},{east})"
    return f"""
[out:json][timeout:25];
(
  nwr["amenity"="parking"]{box};
  node["leisure"="fishing"]{box};
  nwr["man_made"="pier"]{box};
);
out tags center;
"""


def _road_query_wide(lat: float, lon: float) -> str:
    return f"""
[out:json][timeout:20];
way(around:700,{lat},{lon})["highway"~"^(primary|secondary|tertiary|unclassified|residential|living_street|service|track)$"];
out tags geom;
"""


def _road_query(lat: float, lon: float) -> str:
    return f"""
[out:json][timeout:25];
way(around:1800,{lat},{lon})["highway"~"^(track|service|unclassified|residential|living_street)$"];
out tags geom;
"""


def _spot(element: dict, rings: list[list], geometry: dict | None) -> dict | None:
    tags = element.get("tags") or {}
    point = _center(element)
    if point is None:
        return None
    lat, lon = point
    if geometry and _geometry_contains(lon, lat, geometry):
        return None
    shore = _closest_shore(lat, lon, rings)
    if shore is None:
        return None
    name = tags.get("name:tr") or tags.get("name")
    return {
        "lat": lat,
        "lon": lon,
        "name": name.strip() if isinstance(name, str) and name.strip() else None,
        "shore_m": round(shore[2]),
        "shore_lat": shore[0],
        "shore_lon": shore[1],
        "kind": "pier" if tags.get("man_made") == "pier" else "fishing" if tags.get("leisure") == "fishing" else "parking",
    }


async def _overpass_fast(query: str) -> dict:
    for url in (OVERPASS_FALLBACK, OVERPASS_PRIMARY):
        payload = await _post_overpass(url, query, 18.0)
        if payload is not None:
            return payload
    raise AccessError("OpenStreetMap Overpass şu an yanıt vermiyor. Biraz sonra tekrar deneyin.")


async def _nearby_features(rings: list[list], geometry: dict | None) -> tuple[list[dict], list[dict]]:
    box = _bbox(rings)
    if box is None:
        return [], []
    payload = await _overpass_fast(_feature_query(*box))
    parking = []
    casts = []
    for element in payload.get("elements") or []:
        spot = _spot(element, rings, geometry)
        if spot is None or spot["shore_m"] > 1200:
            continue
        tags = element.get("tags") or {}
        if tags.get("amenity") == "parking":
            parking.append(spot)
        elif tags.get("leisure") == "fishing" or tags.get("man_made") == "pier":
            casts.append(spot)
    return parking, casts


def _road_point(element: dict, rings: list[list], geometry: dict | None) -> dict | None:
    tags = element.get("tags") or {}
    best = None
    for point in element.get("geometry") or []:
        try:
            lat = float(point["lat"])
            lon = float(point["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if geometry and _geometry_contains(lon, lat, geometry):
            continue
        shore = _closest_shore(lat, lon, rings)
        if shore is None:
            continue
        if best is None or shore[2] < best["shore_m"]:
            name = tags.get("name:tr") or tags.get("name")
            best = {
                "lat": lat,
                "lon": lon,
                "name": name.strip() if isinstance(name, str) and name.strip() else None,
                "shore_m": shore[2],
                "shore_lat": shore[0],
                "shore_lon": shore[1],
                "kind": "road",
                "highway": str(tags.get("highway") or ""),
            }
    if best is None or best["shore_m"] > 400:
        return None
    best["shore_m"] = round(best["shore_m"])
    return best


async def _nearest_road(lat: float, lon: float, rings: list[list], geometry: dict | None) -> dict | None:
    try:
        payload = await _overpass_fast(_road_query(lat, lon))
    except AccessError as exc:
        log.warning("road lookup skipped: %s", exc)
        return None
    best = None
    for element in payload.get("elements") or []:
        spot = _road_point(element, rings, geometry)
        if spot is None:
            continue
        if best is None or spot["shore_m"] < best["shore_m"]:
            best = spot
    return best


async def _walk(park: dict, cast: dict) -> dict | None:
    url = OSRM_URL.format(lon1=park["lon"], lat1=park["lat"], lon2=cast["lon"], lat2=cast["lat"])
    try:
        response = await client().get(url, params={"overview": "full", "geometries": "geojson"})
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("osrm skipped: %s", exc)
        return None
    routes = payload.get("routes") or []
    if not routes:
        return None
    route = routes[0]
    meters = route.get("distance")
    seconds = route.get("duration")
    if not isinstance(meters, (int, float)) or meters <= 0:
        return None
    if isinstance(seconds, (int, float)) and seconds > 0 and (float(meters) / float(seconds)) <= 2.2:
        minutes = max(1, round(float(seconds) / 60))
    else:
        minutes = max(1, round(float(meters) / 80))
    return {
        "meters": round(float(meters)),
        "minutes": minutes,
        "geometry": route.get("geometry"),
        "source": "OSRM yaya",
    }


def _photo_distance(lat: float, lon: float, photo: dict) -> float:
    return _meters(lat, lon, photo["lat"], photo["lon"])


async def _panoramax(lat: float, lon: float) -> list[dict]:
    pad = 0.004
    try:
        response = await client().get(
            PANORAMAX_SEARCH,
            params={"limit": 8, "bbox": f"{lon - pad},{lat - pad},{lon + pad},{lat + pad}"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("panoramax skipped: %s", exc)
        return []
    photos = []
    for feature in payload.get("features") or []:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        assets = feature.get("assets") or {}
        thumb = (assets.get("thumb") or assets.get("sd") or {}).get("href")
        if not isinstance(thumb, str):
            continue
        props = feature.get("properties") or {}
        producer = props.get("geovisio:producer")
        photos.append(
            {
                "url": thumb,
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "title": "Yer görüntüsü",
                "source": "Panoramax" + (f", {producer}" if isinstance(producer, str) and producer.strip() else ""),
                "page": thumb,
            }
        )
    return photos


async def _commons(lat: float, lon: float) -> list[dict]:
    try:
        response = await client().get(
            COMMONS_API,
            params={
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat}|{lon}",
                "gsradius": 700,
                "gslimit": 6,
                "gsnamespace": 6,
                "format": "json",
            },
        )
        response.raise_for_status()
        found = ((response.json().get("query") or {}).get("geosearch")) or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("commons geosearch skipped: %s", exc)
        return []
    titles = []
    located = []
    for item in found:
        title = item.get("title") or ""
        if not title.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        titles.append(title)
        located.append(item)
    if not titles:
        return []
    try:
        info = await client().get(
            COMMONS_API,
            params={
                "action": "query",
                "titles": "|".join(titles),
                "prop": "imageinfo",
                "iiprop": "url",
                "iiurlwidth": 800,
                "format": "json",
            },
        )
        info.raise_for_status()
        pages = ((info.json().get("query") or {}).get("pages")) or {}
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("commons imageinfo skipped: %s", exc)
        return []
    by_title = {}
    for page in pages.values():
        image = (page.get("imageinfo") or [{}])[0]
        url = image.get("thumburl") or image.get("url")
        if url:
            by_title[page.get("title")] = url
    photos = []
    for item in located:
        url = by_title.get(item.get("title"))
        if not url:
            continue
        title = str(item.get("title") or "").removeprefix("File:")
        photos.append(
            {
                "url": url,
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "title": title,
                "source": "Wikimedia Commons",
                "page": "https://commons.wikimedia.org/wiki/" + str(item.get("title") or "").replace(" ", "_"),
            }
        )
    return photos


async def _photo(lat: float, lon: float) -> dict | None:
    ground = await _panoramax(lat, lon)
    ground.sort(key=lambda item: _photo_distance(lat, lon, item))
    if ground and _photo_distance(lat, lon, ground[0]) <= 450:
        photo = ground[0]
    else:
        commons = await _commons(lat, lon)
        commons.sort(key=lambda item: _photo_distance(lat, lon, item))
        photo = commons[0] if commons and _photo_distance(lat, lon, commons[0]) <= 700 else None
        if photo is None and ground:
            photo = ground[0] if _photo_distance(lat, lon, ground[0]) <= 700 else None
    if photo is None:
        return None
    distance = round(_photo_distance(lat, lon, photo))
    photo["distance_m"] = distance
    if distance <= 80:
        photo["label"] = "Oltayı atacağın yer"
    else:
        photo["label"] = f"En yakın yer görüntüsü, olta noktasından {distance} m"
    return photo


def _straight_walk(park: dict, cast: dict, meters: float) -> dict:
    return {
        "meters": round(meters),
        "minutes": max(1, round(meters / 80)),
        "geometry": {
            "type": "LineString",
            "coordinates": [[park["lon"], park["lat"]], [cast["lon"], cast["lat"]]],
        },
        "source": "kuş uçuşu",
    }


def _make_cast(park: dict, casts: list[dict]) -> dict:
    cast_lat, cast_lon = park["shore_lat"], park["shore_lon"]
    cast_label = "Kıyı"
    cast_text = "Seçilen bırakma noktasına en yakın kıyı. OpenStreetMap su çizgisinden hesaplandı."
    if casts:
        nearest = min(casts, key=lambda item: _meters(park["lat"], park["lon"], item["lat"], item["lon"]))
        gap = _meters(park["lat"], park["lon"], nearest["lat"], nearest["lon"])
        if gap <= 700:
            cast_lat, cast_lon = nearest["lat"], nearest["lon"]
            cast_label = "İskele" if nearest["kind"] == "pier" else "Balık tutma noktası"
            cast_text = "OpenStreetMap bu noktayı iskele veya balık tutma yeri olarak işaretlemiş."
    return {"lat": cast_lat, "lon": cast_lon, "label": cast_label, "text": cast_text}


async def _pick_approach(parking: list[dict], casts: list[dict], inside: bool, lat: float, lon: float):
    if inside:
        ordered = sorted(parking, key=lambda item: item["shore_m"])
        close = [item for item in ordered if item["shore_m"] <= 300]
        pool = (close or ordered)[:5]
    else:
        near = [item for item in parking if _meters(lat, lon, item["lat"], item["lon"]) <= 1500]
        pool = sorted(near, key=lambda item: _meters(lat, lon, item["lat"], item["lon"]))[:5]
    fallback = None
    for park in pool:
        cast = _make_cast(park, casts)
        walk = await _walk(park, cast)
        straight = _meters(park["lat"], park["lon"], cast["lat"], cast["lon"])
        collapsed = bool(walk and straight >= 30 and walk["meters"] < 20)
        too_long = bool(walk and walk["meters"] > max(450, straight * 3.5))
        if collapsed and straight <= 160:
            return park, cast, _straight_walk(park, cast, straight)
        if walk and not collapsed and not too_long:
            return park, cast, walk
        if fallback is None:
            fallback = (park, cast)
    if fallback is None:
        return None, None, None
    return fallback[0], fallback[1], None


def _steps(park: dict, cast: dict, walk: dict | None) -> list[dict]:
    if park["kind"] == "parking":
        park_title = park["name"] or "Otopark"
        park_text = f"OpenStreetMap otoparkı. Kıyıya kuş uçuşu {park['shore_m']} m."
    else:
        park_title = park["name"] or ROAD_LABEL.get(park.get("highway"), "Araç yolu")
        park_text = f"Bu kıyıda otopark etiketi yok. Pin, kıyıya {park['shore_m']} m yakındaki araç yolu."
    if walk and walk.get("source") == "kuş uçuşu":
        walk_text = f"Kıyı, aracın {walk['meters']} m yanında. Bu son kısım kuş uçuşu; ayrı patika etiketi yok."
    elif walk:
        walk_text = f"Yaya rota {walk['meters']} m, yaklaşık {walk['minutes']} dakika. Kaynak: {walk['source']}."
    else:
        gap = round(_meters(park["lat"], park["lon"], cast["lat"], cast["lon"]))
        walk_text = f"Kuş uçuşu {gap} m. Çizilen yaya rota bu kıyıyı dolaştığı için konmadı."
    return [
        {"id": "park", "title": "Arabayı bırak", "place": park_title, "text": park_text},
        {"id": "walk", "title": "Yürü", "place": "Oltanın atılacağı kıyıya", "text": walk_text},
        {"id": "cast", "title": "Oltayı at", "place": cast["label"], "text": cast["text"]},
    ]


async def lookup_access(lat: float, lon: float, geometry: dict | None = None) -> dict:
    key = (round(lat, 4), round(lon, 4))
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    result = await _lookup_access(lat, lon, geometry)
    if result.get("found"):
        _cache[key] = (time.time(), result)
    return result


def _usable_geometry(geometry: dict | None) -> dict | None:
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    return geometry


def _road_near_click(element: dict, lat: float, lon: float) -> dict | None:
    tags = element.get("tags") or {}
    best = None
    for point in element.get("geometry") or []:
        try:
            plat = float(point["lat"])
            plon = float(point["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        distance = _meters(lat, lon, plat, plon)
        if best is not None and distance >= best["shore_m"]:
            continue
        name = tags.get("name:tr") or tags.get("name")
        best = {
            "lat": plat,
            "lon": plon,
            "name": name.strip() if isinstance(name, str) and name.strip() else None,
            "shore_m": distance,
            "shore_lat": lat,
            "shore_lon": lon,
            "kind": "road",
            "highway": str(tags.get("highway") or ""),
        }
    if best is None or best["shore_m"] > 500:
        return None
    best["shore_m"] = round(best["shore_m"])
    return best


async def _lookup_open_shore(lat: float, lon: float) -> dict:
    pad = 0.008
    parking = []
    try:
        payload = await _overpass_fast(_feature_query(lat - pad, lon - pad, lat + pad, lon + pad))
    except AccessError as exc:
        log.warning("open shore parking skipped: %s", exc)
        payload = {}
    for element in payload.get("elements") or []:
        tags = element.get("tags") or {}
        if tags.get("amenity") != "parking":
            continue
        point = _center(element)
        if point is None:
            continue
        distance = _meters(lat, lon, point[0], point[1])
        if distance > 800:
            continue
        name = tags.get("name:tr") or tags.get("name")
        parking.append(
            {
                "lat": point[0],
                "lon": point[1],
                "name": name.strip() if isinstance(name, str) and name.strip() else None,
                "shore_m": round(distance),
                "shore_lat": lat,
                "shore_lon": lon,
                "kind": "parking",
            }
        )
    park = min(parking, key=lambda item: item["shore_m"]) if parking else None
    road = False
    if park is None:
        try:
            roads = await _overpass_fast(_road_query_wide(lat, lon))
        except AccessError as exc:
            log.warning("open shore road skipped: %s", exc)
            roads = {}
        for element in roads.get("elements") or []:
            spot = _road_near_click(element, lat, lon)
            if spot is None:
                continue
            if park is None or spot["shore_m"] < park["shore_m"]:
                park = spot
        road = park is not None
    cast = {
        "lat": lat,
        "lon": lon,
        "label": "Kıyı",
        "text": "Olta noktası, haritada dokunduğun yer. Kıyı boyundaki suda atış buradan yapılır.",
    }
    if park is None:
        return {
            "found": False,
            "message": "Dokunduğun yer kıyı avı. Yanında otopark veya araç yolu etiketi yok. Balık listesi bu nokta için durur.",
            "source": "OpenStreetMap",
        }
    walk = await _walk(park, cast)
    straight = _meters(park["lat"], park["lon"], cast["lat"], cast["lon"])
    if not walk or walk["meters"] > max(450, straight * 3.5):
        walk = _straight_walk(park, cast, straight) if straight <= 160 else None
    photo = await _photo(cast["lat"], cast["lon"])
    if photo is None:
        photo = await _photo(park["lat"], park["lon"])
        if photo is not None:
            distance = round(_meters(cast["lat"], cast["lon"], photo["lat"], photo["lon"]))
            photo["distance_m"] = distance
            photo["label"] = (
                "Oltayı atacağın yer"
                if distance <= 80
                else f"En yakın yer görüntüsü, olta noktasından {distance} m"
            )
    return {
        "found": True,
        "park": {
            "lat": park["lat"],
            "lon": park["lon"],
            "name": park["name"],
            "kind": park["kind"],
            "shore_m": park["shore_m"],
        },
        "cast": cast,
        "walk": walk,
        "photo": photo,
        "steps": _steps(park, cast, walk),
        "road_fallback": road,
        "source": "OpenStreetMap, OSRM yaya, Panoramax veya Wikimedia Commons",
        "note": "Olta noktası dokunduğun yer. Bırakma yeri haritadaki otopark ya da yoldur. Yakalanma puanı değildir.",
    }


async def _lookup_access(lat: float, lon: float, geometry: dict | None) -> dict:
    geometry = _usable_geometry(geometry)
    rings = _rings(geometry)
    if not rings:
        return await _lookup_open_shore(lat, lon)
    try:
        parking, casts = await _nearby_features(rings, geometry)
    except (AccessError, WaterLookupError) as exc:
        return {
            "found": False,
            "message": str(exc),
            "source": "OpenStreetMap",
        }

    inside = bool(geometry and _geometry_contains(lon, lat, geometry))
    park, cast, walk = (None, None, None)
    if parking:
        park, cast, walk = await _pick_approach(parking, casts, inside, lat, lon)
    road = False
    if park is None:
        park = await _nearest_road(lat, lon, rings, geometry)
        road = park is not None
        if park is not None:
            cast = _make_cast(park, casts)
            walk = await _walk(park, cast)
            straight = _meters(park["lat"], park["lon"], cast["lat"], cast["lon"])
            if not walk or walk["meters"] > max(450, straight * 3.5):
                walk = None
    if park is None or cast is None:
        return {
            "found": False,
            "message": "Bu kıyının yanında OpenStreetMap otoparkı veya yakın araç yolu yok. Pin uydurulmadı.",
            "source": "OpenStreetMap",
        }

    photo = await _photo(cast["lat"], cast["lon"])
    if photo is None:
        photo = await _photo(park["lat"], park["lon"])
        if photo is not None:
            distance = round(_meters(cast["lat"], cast["lon"], photo["lat"], photo["lon"]))
            photo["distance_m"] = distance
            photo["label"] = (
                "Oltayı atacağın yer"
                if distance <= 80
                else f"En yakın yer görüntüsü, olta noktasından {distance} m"
            )
    return {
        "found": True,
        "park": {
            "lat": park["lat"],
            "lon": park["lon"],
            "name": park["name"],
            "kind": park["kind"],
            "shore_m": park["shore_m"],
        },
        "cast": cast,
        "walk": walk,
        "photo": photo,
        "steps": _steps(park, cast, walk),
        "road_fallback": road,
        "source": "OpenStreetMap, OSRM yaya, Panoramax veya Wikimedia Commons",
        "note": "Bırakma yeri, yürüyüş ve olta noktası haritadaki gerçek çizgilerden. Yakalanma puanı değildir.",
    }
