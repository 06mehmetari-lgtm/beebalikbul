"""Single process: mobile page plus live API routes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.conditions import ConditionsError, lookup_conditions
from backend.net import close_client
from backend.species import SpeciesError, find_species, fish_photo, gbif_nearby, get_catalog, list_species
from backend.tackle import classify_window, recommend
from backend.places import PROVINCES, province_waters
from backend.access import lookup_access
from backend.water import WaterLookupError, lookup_landcover, lookup_water

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kontrolbee")

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DuckDB on Windows hangs when called from a worker thread, so the snapshot loads here.
    try:
        version, rows = get_catalog()
        log.info("FishBase v%s hazır, %s Türkiye kaydı", version, len(rows))
    except SpeciesError as exc:
        log.warning("FishBase ön yükleme başarısız: %s", exc)
    yield
    await close_client()


app = FastAPI(title="Kontrolbee", lifespan=lifespan)


@app.middleware("http")
async def no_store_api(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api") or request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store"
    return response


def _coords(lat: float, lon: float) -> None:
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise HTTPException(status_code=422, detail="Koordinat aralık dışında.")


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/provinces")
async def provinces():
    return {"provinces": list(PROVINCES)}


@app.get("/api/province-waters")
async def province(name: str = Query(..., min_length=2, max_length=40)):
    try:
        return await province_waters(name.strip())
    except WaterLookupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/water")
async def water(
    lat: float = Query(...),
    lon: float = Query(...),
    osm_type: str | None = Query(None, pattern="^(way|relation)$"),
    osm_id: int | None = Query(None, ge=1),
):
    _coords(lat, lon)
    try:
        return await lookup_water(lat, lon, osm_type, osm_id)
    except WaterLookupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/landcover")
async def landcover(
    south: float = Query(...),
    west: float = Query(...),
    north: float = Query(...),
    east: float = Query(...),
):
    _coords(south, west)
    _coords(north, east)
    try:
        return await lookup_landcover(south, west, north, east)
    except WaterLookupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class AccessIn(BaseModel):
    lat: float
    lon: float
    geometry: dict | None = Field(default=None)


@app.post("/api/access")
async def access(body: AccessIn):
    _coords(body.lat, body.lon)
    return await lookup_access(body.lat, body.lon, body.geometry)


@app.get("/api/species")
async def species(
    lat: float = Query(...),
    lon: float = Query(...),
    kind: str = Query(..., pattern="^(freshwater|saltwater|brackish)$"),
    q: str | None = Query(None, max_length=40),
    zone: str | None = Query(None, pattern="^(harbor|shore|open)$"),
    start: str | None = Query(None, max_length=8),
    end: str | None = Query(None, max_length=8),
    sunrise: str | None = Query(None, max_length=40),
    sunset: str | None = Query(None, max_length=40),
    sunrise_next: str | None = Query(None, max_length=40),
    layer: str | None = Query(None, max_length=40),
    method: str | None = Query(None, pattern="^(float|spin|bottom|feather)$"),
    hour_only: bool = Query(False),
):
    _coords(lat, lon)
    nearby = await gbif_nearby(lat, lon)
    slots = None
    hour_skip = None
    if start and end:
        window = classify_window(start, end, sunrise, sunset, sunrise_next)
        if window.get("period") == "unknown":
            hour_skip = "Gün doğumu alınamadı. Saat süzgeci uygulanmadı, liste tüm saate göre."
        else:
            slots = window.get("slots") or []
    try:
        payload = list_species(
            kind,
            set(nearby.get("scientific_names") or []),
            q,
            zone,
            slots,
            bool(hour_only and slots),
            layer,
            method,
        )
    except SpeciesError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if hour_skip:
        payload["hour_note"] = hour_skip
    payload["gbif"] = {
        "ok": nearby.get("ok", False),
        "count": nearby.get("count"),
        "matched_names": nearby.get("scientific_names") or [],
        "message": nearby.get("message"),
        "radius_deg": nearby.get("radius_deg"),
        "source": "GBIF Occurrence Search, taxonKey 204 (Actinopterygii)",
    }
    return payload


@app.get("/api/photo")
async def photo(scientific: str = Query(..., min_length=3, max_length=80)):
    image = await fish_photo(scientific.strip())
    if image is None:
        return {"found": False, "scientific": scientific, "message": "Bu tür için Wikimedia fotoğrafı yok."}
    return {"found": True, "scientific": scientific, **image}


@app.get("/api/conditions")
async def conditions(
    lat: float = Query(...),
    lon: float = Query(...),
    marine: bool = Query(False),
):
    _coords(lat, lon)
    try:
        return await lookup_conditions(lat, lon, marine)
    except ConditionsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/tackle")
async def tackle(
    scientific: str = Query(..., min_length=3, max_length=80),
    kind: str = Query(..., pattern="^(freshwater|saltwater|brackish)$"),
    cloud_cover: float | None = Query(None),
    wind_speed_kmh: float | None = Query(None),
    pressure_trend: str | None = Query(None, pattern="^(stable|falling|rising)$"),
    pressure_delta_hpa: float | None = Query(None),
    wave_height_m: float | None = Query(None),
    start: str | None = Query(None, pattern=r"^\d{2}:\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{2}:\d{2}$"),
    sunrise: str | None = Query(None, max_length=40),
    sunset: str | None = Query(None, max_length=40),
    sunrise_next: str | None = Query(None, max_length=40),
    moon_phase: float | None = Query(None, ge=0, le=1),
    method: str | None = Query(None, pattern="^(float|spin|bottom|feather)$"),
    zone: str | None = Query(None, pattern="^(harbor|shore|open)$"),
):
    try:
        row = find_species(scientific.strip())
    except SpeciesError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Bu bilimsel ad FishBase Türkiye listesinde yok.")
    names = [row["scientific"], row["english"] or "", row["turkish"] or "", *row["names"]]
    return recommend(
        row["scientific"],
        [name for name in names if name],
        kind,
        {
            "cloud_cover": cloud_cover,
            "wind_speed_kmh": wind_speed_kmh,
            "pressure_trend": pressure_trend,
            "pressure_delta_hpa": pressure_delta_hpa,
            "wave_height_m": wave_height_m,
        },
        layer=row.get("layer"),
        start=start,
        end=end,
        sunrise=sunrise,
        sunset=sunset,
        sunrise_next=sunrise_next,
        moon_phase=moon_phase,
        method=method,
        zone=zone,
    )


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
