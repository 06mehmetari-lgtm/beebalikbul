"""Open-Meteo weather, marine, moon phase, and a transparent activity index."""

from __future__ import annotations

import httpx

from backend.net import client

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

COMPASS = (
    "kuzey",
    "kuzey-kuzeydoğu",
    "kuzeydoğu",
    "doğu-kuzeydoğu",
    "doğu",
    "doğu-güneydoğu",
    "güneydoğu",
    "güney-güneydoğu",
    "güney",
    "güney-güneybatı",
    "güneybatı",
    "batı-güneybatı",
    "batı",
    "batı-kuzeybatı",
    "kuzeybatı",
    "kuzey-kuzeybatı",
)


class ConditionsError(RuntimeError):
    pass


def wind_label(degrees: float | None) -> str | None:
    if degrees is None:
        return None
    index = int((float(degrees) % 360) / 22.5 + 0.5) % 16
    return COMPASS[index]


def moon_name(phase: float | None) -> str | None:
    if phase is None:
        return None
    value = float(phase) % 1
    if value <= 0.03 or value >= 0.97:
        return "Yeni ay"
    if value < 0.22:
        return "Büyüyen hilal"
    if value < 0.28:
        return "İlk dördün"
    if value < 0.47:
        return "Şişkin ay"
    if value < 0.53:
        return "Dolunay"
    if value < 0.72:
        return "Küçülen şişkin ay"
    if value < 0.78:
        return "Son dördün"
    return "Küçülen hilal"


def _number(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _at_hour(hourly: dict, key: str, index: int):
    series = hourly.get(key) or []
    if index < 0 or index >= len(series):
        return None
    return series[index]


def _pressure_delta(hourly: dict, index: int) -> float | None:
    current = _number(_at_hour(hourly, "pressure_msl", index))
    earlier = _number(_at_hour(hourly, "pressure_msl", index - 6))
    if current is None or earlier is None:
        return None
    return current - earlier


def _activity(current: dict, moon_phase: float | None, marine: dict | None) -> dict:
    components = []
    score = 40
    components.append(
        {
            "key": "base",
            "points": 40,
            "text": "Taban 40. Üstüne yalnızca gelen ölçümler eklenir.",
        }
    )

    delta = current.get("pressure_delta_hpa")
    if delta is not None:
        if abs(delta) <= 1.5:
            points = 22
            text = f"Basınç son 6 saatte {delta:+.1f} hPa, neredeyse sabit."
        elif -6 <= delta < -1.5:
            points = 14
            text = f"Basınç son 6 saatte {delta:+.1f} hPa, yavaş düşüyor."
        elif delta < -6:
            points = 4
            text = f"Basınç son 6 saatte {delta:+.1f} hPa, hızlı düşüyor."
        elif delta > 4:
            points = -8
            text = f"Basınç son 6 saatte {delta:+.1f} hPa, yükseliyor."
        else:
            points = 6
            text = f"Basınç son 6 saatte {delta:+.1f} hPa."
        score += points
        components.append({"key": "pressure", "points": points, "text": text})

    cloud = current.get("cloud_cover")
    if cloud is not None:
        if cloud >= 70:
            points = 12
            text = f"Bulut örtüsü %{cloud:.0f}."
        elif cloud >= 40:
            points = 8
            text = f"Bulut örtüsü %{cloud:.0f}, parçalı."
        else:
            points = 3
            text = f"Bulut örtüsü %{cloud:.0f}, açık."
        score += points
        components.append({"key": "cloud", "points": points, "text": text})

    wind = current.get("wind_speed_kmh")
    if wind is not None:
        if 6 <= wind <= 28:
            points = 12
            text = f"Rüzgar {wind:.0f} km/sa, hafif."
        elif wind < 6:
            points = 4
            text = f"Rüzgar {wind:.0f} km/sa, çok zayıf."
        elif wind > 40:
            points = -10
            text = f"Rüzgar {wind:.0f} km/sa, sert."
        else:
            points = 2
            text = f"Rüzgar {wind:.0f} km/sa."
        score += points
        components.append({"key": "wind", "points": points, "text": text})

    if moon_phase is not None:
        distance = min(abs(moon_phase), abs(moon_phase - 0.5), abs(1 - moon_phase))
        name = moon_name(moon_phase)
        if distance <= 0.08:
            points = 14
            text = f"Ay evresi {name} ({moon_phase:.2f})."
        else:
            points = 4
            text = f"Ay evresi {name} ({moon_phase:.2f})."
        score += points
        components.append({"key": "moon", "points": points, "text": text})

    wave = None if marine is None else marine.get("wave_height_m")
    if wave is not None:
        if 0.3 <= wave <= 1.6:
            points = 8
            text = f"Dalga yüksekliği {wave:.2f} m."
        elif wave > 2.2:
            points = -8
            text = f"Dalga yüksekliği {wave:.2f} m, yüksek."
        else:
            points = 2
            text = f"Dalga yüksekliği {wave:.2f} m."
        score += points
        components.append({"key": "wave", "points": points, "text": text})

    score = max(8, min(92, score))
    return {
        "score": score,
        "label": "Aktivite indeksi",
        "note": "Bu bir yakalama garantisi değildir. Puan, yukarıdaki canlı ölçümlerin toplamıdır ve 8 ile 92 arasında sınırlanır.",
        "components": components,
    }


async def _get_json(url: str, params: dict) -> dict:
    try:
        response = await client().get(url, params=params)
    except httpx.HTTPError as exc:
        raise ConditionsError(f"Open-Meteo ulaşılamadı: {exc}") from exc
    if response.status_code >= 400:
        raise ConditionsError(f"Open-Meteo HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ConditionsError("Open-Meteo JSON okunamadı") from exc


async def lookup_conditions(lat: float, lon: float, marine: bool) -> dict:
    forecast = await _get_json(
        FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,cloud_cover,wind_speed_10m,wind_direction_10m,pressure_msl",
            "hourly": "pressure_msl,temperature_2m,cloud_cover,wind_speed_10m",
            "daily": "moon_phase,moonrise,moonset,sunrise,sunset",
            "timezone": "auto",
            "forecast_days": 2,
            "wind_speed_unit": "kmh",
        },
    )
    current_raw = forecast.get("current") or {}
    hourly = forecast.get("hourly") or {}
    times = hourly.get("time") or []
    current_time = current_raw.get("time")
    hour_index = times.index(current_time) if current_time in times else 0
    if hour_index == 0 and times:
        hour_prefix = str(current_time or "")[:13]
        for index, stamp in enumerate(times):
            if str(stamp).startswith(hour_prefix):
                hour_index = index
                break

    current = {
        "time": current_time,
        "temperature_c": _number(current_raw.get("temperature_2m")),
        "cloud_cover": _number(current_raw.get("cloud_cover")),
        "wind_speed_kmh": _number(current_raw.get("wind_speed_10m")),
        "wind_direction_deg": _number(current_raw.get("wind_direction_10m")),
        "pressure_hpa": _number(current_raw.get("pressure_msl")),
        "pressure_delta_hpa": _pressure_delta(hourly, hour_index),
    }
    current["wind_label"] = wind_label(current["wind_direction_deg"])
    if current["pressure_delta_hpa"] is not None:
        delta = current["pressure_delta_hpa"]
        if abs(delta) <= 1.5:
            current["pressure_trend"] = "stable"
        elif delta < 0:
            current["pressure_trend"] = "falling"
        else:
            current["pressure_trend"] = "rising"
    else:
        current["pressure_trend"] = None

    daily = forecast.get("daily") or {}
    phase = _number((daily.get("moon_phase") or [None])[0])
    moon = {
        "phase": phase,
        "name": moon_name(phase),
        "moonrise": (daily.get("moonrise") or [None])[0],
        "moonset": (daily.get("moonset") or [None])[0],
    }
    sunrises = daily.get("sunrise") or []
    sunsets = daily.get("sunset") or []
    sun = {
        "sunrise": sunrises[0] if sunrises else None,
        "sunset": sunsets[0] if sunsets else None,
        "sunrise_next": sunrises[1] if len(sunrises) > 1 else None,
        "sunset_next": sunsets[1] if len(sunsets) > 1 else None,
    }
    temperatures = hourly.get("temperature_2m") or []
    clouds = hourly.get("cloud_cover") or []
    winds = hourly.get("wind_speed_10m") or []
    pressures = hourly.get("pressure_msl") or []
    hours = []
    for index, stamp in enumerate(times):
        hours.append(
            {
                "time": stamp,
                "temperature_c": _number(temperatures[index] if index < len(temperatures) else None),
                "cloud_cover": _number(clouds[index] if index < len(clouds) else None),
                "wind_speed_kmh": _number(winds[index] if index < len(winds) else None),
                "pressure_hpa": _number(pressures[index] if index < len(pressures) else None),
            }
        )

    marine_block = None
    if marine:
        marine_block = await _marine(lat, lon, current_time)

    return {
        "source": "Open-Meteo",
        "timezone": forecast.get("timezone"),
        "current": current,
        "hours": hours,
        "moon": moon,
        "sun": sun,
        "marine": marine_block,
        "activity": _activity(current, phase, marine_block if isinstance(marine_block, dict) and marine_block.get("available") else None),
        "attribution": "Hava, deniz ve ay verisi Open-Meteo (CC BY 4.0)",
    }


async def _marine(lat: float, lon: float, current_time: str | None) -> dict:
    try:
        payload = await _get_json(
            MARINE_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": "wave_height,sea_surface_temperature,ocean_current_velocity,ocean_current_direction,sea_level_height_msl",
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
    except ConditionsError as exc:
        return {"available": False, "message": str(exc)}

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    index = 0
    if current_time and current_time in times:
        index = times.index(current_time)
    elif current_time:
        hour_prefix = str(current_time)[:13]
        for position, stamp in enumerate(times):
            if str(stamp).startswith(hour_prefix):
                index = position
                break

    wave = _number(_at_hour(hourly, "wave_height", index))
    sst = _number(_at_hour(hourly, "sea_surface_temperature", index))
    current_speed = _number(_at_hour(hourly, "ocean_current_velocity", index))
    current_dir = _number(_at_hour(hourly, "ocean_current_direction", index))
    tide = _number(_at_hour(hourly, "sea_level_height_msl", index))
    if all(value is None for value in (wave, sst, current_speed, tide)):
        return {
            "available": False,
            "message": "Bu koordinat için Open-Meteo deniz modeli değer döndürmedi.",
        }
    return {
        "available": True,
        "time": times[index] if times else None,
        "wave_height_m": wave,
        "sea_surface_temperature_c": sst,
        "current_velocity_kmh": current_speed,
        "current_direction_deg": current_dir,
        "current_direction_label": wind_label(current_dir),
        "sea_level_height_msl_m": tide,
    }
