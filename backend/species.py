"""FishBase snapshot, GBIF occurrences near a point, Wikimedia fish photo."""

from __future__ import annotations

import logging
import threading
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from backend.net import USER_AGENT, client
from backend.tackle import METHODS, RULES, fold, methods_for

PINNED_SCIENTIFIC = {name for rule in RULES for name in rule["scientific"]}

CACHE_ROOT = Path(__file__).resolve().parent.parent / ".cache" / "fishbase"

log = logging.getLogger("kontrolbee.species")

S3_LIST = (
    "https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop"
    "?list-type=2&prefix=cboettig/fishbase/fb/&delimiter=/"
)
PARQUET = "https://data.source.coop/cboettig/fishbase/fb/v{version}/parquet/{table}.parquet"
FALLBACK_VERSION = "26.06"
TURKEY_CODE = "792"

LAYER_LABEL = {
    "pelagic": "Yüzey / pelajik",
    "pelagic-neritic": "Kıyı üstü su",
    "pelagic-oceanic": "Açık deniz yüzeyi",
    "demersal": "Su dibi",
    "benthopelagic": "Dibe yakın orta su",
    "benthic": "Su dibi",
    "reef-associated": "Resif",
    "bathypelagic": "Derin su",
    "bathydemersal": "Derin dip",
}

FEEDING_LABEL = {
    "hunting macrofauna (predator)": "Yırtıcı, iri av",
    "selective plankton feeding": "Seçici plankton",
    "filtering plankton": "Süzerek plankton",
    "grazing on aquatic plants": "Su bitkisi otlaması",
    "variable": "Değişken",
    "other": "Diğer",
}

CIRCADIAN_LABEL = {
    "diurnal": "Gündüz",
    "nocturnal": "Gece",
    "crepuscular": "Alacakaranlık",
    "cathemeral": "Gece ve gündüz",
}

_lock = threading.Lock()
_catalog: list[dict] | None = None
_version: str | None = None
_photo_cache: dict[str, dict | None] = {}


class SpeciesError(RuntimeError):
    pass


def _circadian(first, second, third, remark) -> tuple[str | None, str | None, str | None]:
    code = None
    for value in (first, second, third):
        if isinstance(value, str) and value.strip():
            code = value.strip()
            break
    label = None
    if code:
        label = CIRCADIAN_LABEL.get(code.casefold(), code)
    note = remark.strip() if isinstance(remark, str) and remark.strip() else None
    if note and len(note) > 240:
        note = note[:237].rstrip() + "…"
    return code, label, note


def _latest_version() -> str:
    try:
        import urllib.request

        request = urllib.request.Request(S3_LIST, headers={"User-Agent": "Kontrolbee/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            xml = response.read()
        root = ET.fromstring(xml)
        versions = []
        for node in root.iter():
            if node.tag.endswith("Prefix") and node.text and "/v" in node.text:
                token = node.text.rstrip("/").split("/")[-1]
                if token.startswith("v"):
                    versions.append(token[1:])
        if versions:
            return max(versions)
    except Exception as exc:
        log.warning("fishbase version list failed, using %s: %s", FALLBACK_VERSION, exc)
    return FALLBACK_VERSION


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool_flag(value) -> bool:
    return _as_int(value) == 1


def _pick_turkish(names: list[str]) -> str | None:
    cleaned = []
    for name in names or []:
        if isinstance(name, str) and name.strip():
            cleaned.append(name.strip())
    if not cleaned:
        return None
    short = [name for name in cleaned if len(name) <= 18]
    pool = short or cleaned

    def rank(name: str):
        turkish = sum(char in "çğıöşüÇĞİÖŞÜıİ" for char in name)
        return (len(name), -turkish, name.casefold())

    return sorted(pool, key=rank)[0]


def _local_parquet(version: str, table: str) -> str:
    folder = CACHE_ROOT / version
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{table}.parquet"
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest.as_posix()
    url = PARQUET.format(version=version, table=table)
    partial = dest.with_suffix(".part")
    log.info("downloading FishBase %s", table)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    partial.replace(dest)
    return dest.as_posix()


def _load_catalog(version: str) -> list[dict]:
    import duckdb

    paths = {table: _local_parquet(version, table) for table in ("country", "species", "comnames", "ecology")}

    def url(table: str) -> str:
        return paths[table]

    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            WITH names AS (
              SELECT SpecCode, list(ComName) AS names
              FROM read_parquet('{url("comnames")}')
              WHERE Language = 'Turkish'
              GROUP BY SpecCode
            ),
            eco AS (
              SELECT SpecCode,
                     any_value(FeedingType) AS feeding,
                     any_value(DietRemark) AS diet_remark,
                     any_value(Circadian1) AS circadian1,
                     any_value(Circadian2) AS circadian2,
                     any_value(Circadian3) AS circadian3,
                     any_value(RemarksCircadian) AS circadian_remark
              FROM read_parquet('{url("ecology")}')
              GROUP BY SpecCode
            )
            SELECT
              c.SpecCode,
              s.Genus,
              s.Species,
              s.FBname,
              s.DemersPelag,
              s.DepthRangeShallow,
              s.DepthRangeDeep,
              s.GameFish,
              c.Freshwater,
              c.Brackish,
              c.Saltwater,
              c.Status,
              names.names,
              eco.feeding,
              eco.diet_remark,
              eco.circadian1,
              eco.circadian2,
              eco.circadian3,
              eco.circadian_remark
            FROM read_parquet('{url("country")}') c
            JOIN read_parquet('{url("species")}') s ON s.SpecCode = c.SpecCode
            LEFT JOIN names ON names.SpecCode = c.SpecCode
            LEFT JOIN eco ON eco.SpecCode = c.SpecCode
            WHERE c.C_Code = '{TURKEY_CODE}'
              AND (c.Freshwater = 1 OR c.Brackish = 1 OR c.Saltwater = 1)
            """
        ).fetchall()
    finally:
        connection.close()

    catalog = []
    seen: set[int] = set()
    for row in rows:
        (
            spec_code,
            genus,
            species,
            english,
            layer,
            shallow,
            deep,
            game,
            fresh,
            brack,
            salt,
            status,
            names,
            feeding,
            diet,
            circadian1,
            circadian2,
            circadian3,
            circadian_remark,
        ) = row
        if not genus or not species:
            continue
        code = _as_int(spec_code)
        if code is not None and code in seen:
            continue
        if code is not None:
            seen.add(code)
        name_list = []
        for item in list(names or []):
            if isinstance(item, str) and item.strip():
                name_list.append(item.strip())
        feeding_text = feeding.strip() if isinstance(feeding, str) else None
        diet_text = diet.strip() if isinstance(diet, str) else None
        if diet_text and len(diet_text) > 280:
            diet_text = diet_text[:277].rstrip() + "…"
        circadian, circadian_label, circadian_note = _circadian(
            circadian1, circadian2, circadian3, circadian_remark
        )
        catalog.append(
            {
                "spec_code": code,
                "scientific": f"{genus} {species}",
                "english": english.strip() if isinstance(english, str) and english.strip() else None,
                "turkish": _pick_turkish(name_list),
                "names": name_list,
                "freshwater": _as_bool_flag(fresh),
                "brackish": _as_bool_flag(brack),
                "saltwater": _as_bool_flag(salt),
                "status": status if isinstance(status, str) else None,
                "layer": layer if isinstance(layer, str) else None,
                "layer_label": LAYER_LABEL.get(layer, layer if isinstance(layer, str) else None),
                "depth_shallow_m": _as_int(shallow),
                "depth_deep_m": _as_int(deep),
                "feeding": feeding_text,
                "feeding_label": FEEDING_LABEL.get(feeding_text, feeding_text) if feeding_text else None,
                "diet_remark": diet_text or None,
                "circadian": circadian,
                "circadian_label": circadian_label,
                "circadian_remark": circadian_note,
                "game": _as_bool_flag(game),
            }
        )
    return catalog


def get_catalog() -> tuple[str, list[dict]]:
    global _catalog, _version
    with _lock:
        if _catalog is None:
            version = _latest_version()
            log.info("loading FishBase v%s for Türkiye", version)
            try:
                loaded = _load_catalog(version)
            except Exception as exc:
                raise SpeciesError(f"FishBase tablosu okunamadı: {exc}") from exc
            if not loaded:
                raise SpeciesError("FishBase Türkiye kaydı boş döndü.")
            _version = version
            _catalog = loaded
        return _version, _catalog


def _matches(kind: str, row: dict) -> bool:
    if kind == "freshwater":
        return row["freshwater"]
    if kind == "saltwater":
        return row["saltwater"]
    if kind == "brackish":
        return row["brackish"]
    return False


def _binomial(name: str | None) -> str | None:
    if not name:
        return None
    parts = name.replace("×", " ").split()
    if len(parts) < 2:
        return None
    return f"{parts[0]} {parts[1]}"


def find_species(scientific: str) -> dict | None:
    version, catalog = get_catalog()
    target = scientific.strip().casefold()
    for row in catalog:
        if row["scientific"].casefold() == target:
            return {**row, "fishbase_version": version}
    return None


async def gbif_nearby(lat: float, lon: float) -> dict:
    delta = 0.15
    west, south, east, north = lon - delta, lat - delta, lon + delta, lat + delta
    polygon = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    try:
        response = await client().get(
            "https://api.gbif.org/v1/occurrence/search",
            params={
                "taxonKey": 204,
                "hasCoordinate": "true",
                "geometry": polygon,
                "limit": 80,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "message": f"GBIF ulaşılamadı: {exc}", "scientific_names": []}

    found = []
    seen = set()
    for record in payload.get("results") or []:
        scientific = _binomial(record.get("species") or record.get("scientificName"))
        if not scientific or scientific.casefold() in seen:
            continue
        seen.add(scientific.casefold())
        found.append(scientific)
    return {
        "ok": True,
        "count": payload.get("count", 0),
        "scientific_names": found,
        "radius_deg": delta,
    }


def zone_fit(row: dict, zone: str | None) -> tuple[bool, str | None]:
    if zone not in {"harbor", "shore", "open"}:
        return True, None
    layer = row.get("layer")
    shallow = row.get("depth_shallow_m")
    deep = row.get("depth_deep_m")
    if zone != "open" and layer in {"bathypelagic", "bathydemersal"}:
        return False, "FishBase katmanı derin su. Kıyı ve iç liman listesine alınmadı."
    if zone == "harbor" and shallow is not None and shallow > 25:
        return False, f"FishBase en sığ kaydı {shallow} m. İç liman listesi 25 m ve daha sığdan başlayan türler."
    if zone == "shore" and shallow is not None and shallow > 90:
        return False, f"FishBase en sığ kaydı {shallow} m. Kıyı listesi 90 m'ye kadar iniyor."
    if zone == "open":
        pelagic = layer in {"pelagic", "pelagic-neritic", "pelagic-oceanic", "bathypelagic"}
        if pelagic:
            return True, None
        if deep is not None and deep < 40:
            return False, f"FishBase en derin kaydı {deep} m. Açık deniz listesinde sığ kıyı türü olarak durmuyor."
        return True, None
    return True, None


def _hour_allowed(slots: list[str] | None) -> set[str] | None:
    if not slots:
        return None
    allowed: set[str] = set()
    for slot in slots:
        if slot == "day":
            allowed.update({"diurnal", "cathemeral"})
        elif slot == "night":
            allowed.update({"nocturnal", "cathemeral"})
        elif slot == "twilight":
            allowed.update({"crepuscular", "cathemeral"})
    return allowed or None


def _facets(rows: list[dict], allowed: set[str] | None) -> dict:
    layers: dict[str, dict] = {}
    favorite = 0
    for row in rows:
        label = row.get("layer_label")
        if isinstance(label, str) and label.strip():
            item = layers.setdefault(label, {"label": label, "count": 0})
            item["count"] += 1
        code = str(row.get("circadian") or "").casefold()
        if allowed and code in allowed:
            favorite += 1
    ordered = sorted(layers.values(), key=lambda item: (-item["count"], item["label"]))
    return {
        "layers": ordered,
        "favorite": {"label": "Bu saatte favori", "count": favorite} if favorite else None,
    }


NIGHT_LAYERS = {"pelagic", "pelagic-neritic"}


def _night_only(slots: list[str] | None) -> bool:
    kinds = set(slots or [])
    return "night" in kinds and "day" not in kinds


def _keeps_hour(row: dict, allowed: set[str], night_surface: bool) -> bool:
    code = str(row.get("circadian") or "").casefold()
    if night_surface:
        if code in {"nocturnal", "cathemeral"}:
            return True
        if code == "diurnal":
            return False
        return row.get("layer") in NIGHT_LAYERS
    if not code:
        return True
    return code in allowed


def _hour_note(slots: list[str] | None, blank: int, night_surface: bool, kind: str) -> str:
    names = {"day": "gündüz", "night": "gece", "twilight": "alacakaranlık"}
    bits = [names[slot] for slot in slots or [] if slot in names]
    span = " ve ".join(bits) if bits else "seçilen saat"
    if night_surface and kind != "freshwater":
        return (
            f"Saat aralığı {span}. Liste üst su türleridir. "
            "Gece liman ışığı bu balıkları yüzeye, şamandıranın hemen altına toplar. "
            "Şamandıra, üçlü kanca ve hamsi parçası o üst suyu avlar. "
            "Dip balığı bu listede yok; gece dipte kalır, bu takım oraya inmez. "
            f"{blank} tür üst su katmanında olmadığı için ayrıldı. "
            "FishBase bu saat için av sayısı yayınlamıyor."
        )
    if night_surface:
        return (
            f"Saat aralığı {span}. Liste üst su ve gece kaydı olan türlerdir. "
            "Dip türleri bu listede yok. "
            "FishBase bu saat için av sayısı yayınlamıyor."
        )
    return (
        f"Saat aralığı {span}. FishBase gün döngüsü bu saate uyan tür favoridir ve üsttedir. "
        "Döngü kaydı boş olan tür listede kalır. Kayıt yokluğu, bu saatte av olmadığı anlamına gelmez."
    )


def _zone_note(zone: str | None, omitted: list[dict], mention: bool) -> str | None:
    if zone == "harbor":
        text = "İç liman sığ ve kapalı. Listede FishBase'in 25 m ve daha sığdan kayıtlı türleri var."
    elif zone == "shore":
        text = "Kıyı ve mendirek dışı. Listede en sığ kaydı 90 m'ye kadar olan türler var. İç limanda elenen, daha derinden başlayan türler burada durabilir."
    elif zone == "open":
        text = "Açık deniz. Listede pelajik katman ve derine inen türler var. Yalnızca sığ kıyıda kalanlar çıkarıldı."
    else:
        return None
    limit = {"harbor": 25, "shore": 90}.get(zone)
    if not mention or limit is None:
        return text
    named = [
        row
        for row in omitted
        if row["scientific"].casefold() in PINNED_SCIENTIFIC
        and row.get("depth_shallow_m") is not None
        and row["depth_shallow_m"] > limit
    ]
    named.sort(key=lambda row: row["depth_shallow_m"])
    if named:
        sample = named[0]
        label = sample.get("turkish") or sample["scientific"]
        text += f" {label} ({sample['scientific']}) bu listede yok: en sığ kayıt {sample['depth_shallow_m']} m."
    return text


def list_species(
    kind: str,
    nearby: set[str],
    query: str | None = None,
    zone: str | None = None,
    hour_slots: list[str] | None = None,
    hour_only: bool = False,
    layer: str | None = None,
    method: str | None = None,
) -> dict:
    if kind == "freshwater":
        zone = None
    version, catalog = get_catalog()
    matched = [row for row in catalog if _matches(kind, row)]
    nearby_cf = {name.casefold() for name in nearby}
    needle = fold(query) if query and query.strip() else ""
    if needle:
        matched = [
            row
            for row in matched
            if needle
            in fold(
                " ".join(
                    [
                        row["scientific"],
                        row["english"] or "",
                        row["turkish"] or "",
                        *row["names"],
                    ]
                )
            )
        ]

    def rank(row: dict):
        observed = 0 if row["scientific"].casefold() in nearby_cf else 1
        pinned = 0 if row["scientific"].casefold() in PINNED_SCIENTIFIC else 1
        game = 0 if row["game"] else 1
        if hour_only and allowed is not None:
            favorite = 0 if row.get("hour_favorite") else 1
        else:
            favorite = 0 if row.get("place_favorite") else 1
        label = row["turkish"] or row["english"] or row["scientific"]
        layer_name = row.get("layer")
        upper = 0 if (not night_surface or layer_name in NIGHT_LAYERS or row.get("hour_favorite")) else 1
        if zone == "harbor":
            oceanic = 1 if layer_name == "pelagic-oceanic" else 0
            return (upper, favorite, observed, oceanic, pinned, game, label.casefold())
        if zone == "open":
            pelagic = 0 if layer_name in {"pelagic", "pelagic-neritic", "pelagic-oceanic", "bathypelagic"} else 1
            return (upper, favorite, pelagic, observed, pinned, game, label.casefold())
        return (upper, favorite, observed, pinned, game, label.casefold())

    fitted = []
    omitted = []
    for row in matched:
        fits, reason = zone_fit(row, zone)
        row = {**row, "zone_fit": fits, "zone_reason": reason}
        if fits:
            fitted.append(row)
        else:
            omitted.append(row)
    if needle:
        matched = fitted + omitted
    else:
        matched = fitted
    allowed = _hour_allowed(hour_slots)
    night_surface = bool(hour_only and _night_only(hour_slots))
    for row in matched:
        code = str(row.get("circadian") or "").casefold()
        row["hour_favorite"] = bool(allowed and code in allowed)
        row["place_favorite"] = bool(
            row.get("game")
            or row["scientific"].casefold() in PINNED_SCIENTIFIC
            or row["scientific"].casefold() in nearby_cf
        )
    hour_blank = 0
    if hour_only and allowed is not None:
        before = len(matched)
        matched = [row for row in matched if _keeps_hour(row, allowed, night_surface)]
        hour_blank = before - len(matched)
    facets = _facets(matched, allowed)
    if layer:
        matched = [row for row in matched if row.get("layer_label") == layer]
    labels = dict(METHODS)
    for row in matched:
        names = [
            row["scientific"],
            row.get("english") or "",
            row.get("turkish") or "",
            *(row.get("names") or []),
        ]
        row["methods"] = methods_for(
            row["scientific"],
            [name for name in names if name],
            kind,
            row.get("layer"),
        )
    counts = {key: 0 for key, _label in METHODS}
    for row in matched:
        for key in row["methods"]:
            if key in counts:
                counts[key] += 1
    facets["methods"] = [
        {"id": key, "label": labels[key], "count": counts[key]}
        for key, _label in METHODS
        if counts[key]
    ]
    method_note = None
    if method:
        method_note = (
            f"Takım: {labels.get(method, method)}. "
            "Liste, bu yerde bu takım ailesine giren türlerdir. Av sayısı değildir."
        )
        matched = [row for row in matched if method in row.get("methods", [])]
    matched.sort(key=rank)
    shown = matched
    public = []
    for row in shown:
        public.append(
            {
                "spec_code": row["spec_code"],
                "scientific": row["scientific"],
                "english": row["english"],
                "turkish": row["turkish"],
                "names": row["names"],
                "status": row["status"],
                "layer": row["layer"],
                "layer_label": row["layer_label"],
                "depth_shallow_m": row["depth_shallow_m"],
                "depth_deep_m": row["depth_deep_m"],
                "feeding": row["feeding"],
                "feeding_label": row["feeding_label"],
                "diet_remark": row["diet_remark"],
                "circadian": row["circadian"],
                "circadian_label": row["circadian_label"],
                "circadian_remark": row["circadian_remark"],
                "game": row["game"],
                "observed_nearby": row["scientific"].casefold() in nearby_cf,
                "hour_favorite": bool(row.get("hour_favorite")),
                "place_favorite": bool(row.get("place_favorite")),
                "zone_fit": row.get("zone_fit", True),
                "zone_reason": row.get("zone_reason"),
                "fishbase_version": version,
            }
        )
    return {
        "fishbase_version": version,
        "total": len(matched),
        "shown": len(public),
        "omitted": len(omitted) if not needle else None,
        "zone": zone,
        "zone_note": _zone_note(zone, omitted, mention=not needle),
        "hour_note": _hour_note(hour_slots, hour_blank, night_surface, kind) if hour_only and allowed is not None else None,
        "hour_blank": hour_blank if hour_only and allowed is not None else None,
        "night_surface": night_surface,
        "facets": facets,
        "method_note": method_note,
        "species": public,
        "source": f"FishBase anlık görüntüsü v{version} (Source Cooperative / rOpenSci)",
    }


def _photo_rank(title: str, scientific: str) -> int:
    low = title.casefold()
    score = 0
    for part in scientific.casefold().split():
        if part in low:
            score += 3
    if low.endswith((".jpg", ".jpeg", ".webp")):
        score += 1
    return score


def _photo_title_ok(title: str) -> bool:
    low = title.casefold()
    if not low.startswith("file:"):
        return False
    blocked = ("map", "distribution", "rangemap", "range map", "icon", "logo", "diagram", "audio")
    if any(word in low for word in blocked):
        return False
    return low.endswith((".jpg", ".jpeg", ".png", ".webp"))


async def _imageinfo(title: str) -> dict | None:
    response = await client().get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": 720,
        },
    )
    response.raise_for_status()
    pages = (response.json().get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        mime = str(info.get("mime") or "")
        if not mime.startswith("image/"):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        return {
            "url": url,
            "page": info.get("descriptionurl"),
            "title": page.get("title") or title,
            "source": "Wikimedia Commons",
        }
    return None


async def fish_photo(scientific: str) -> dict | None:
    key = scientific.strip()
    if key in _photo_cache:
        return _photo_cache[key]
    photo = None
    try:
        listed = await client().get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": f"{key} filetype:bitmap",
                "srnamespace": 6,
                "srlimit": 12,
            },
        )
        listed.raise_for_status()
        members = (listed.json().get("query") or {}).get("search") or []
        ranked = sorted(
            (member.get("title") or "" for member in members),
            key=lambda title: _photo_rank(title, key),
            reverse=True,
        )
        for title in ranked:
            if not _photo_title_ok(title):
                continue
            photo = await _imageinfo(title)
            if photo:
                break
        if photo is None:
            summary = await client().get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{key.replace(' ', '_')}"
            )
            if summary.status_code == 200:
                original = (summary.json().get("originalimage") or {}).get("source")
                thumbnail = (summary.json().get("thumbnail") or {}).get("source")
                url = thumbnail or original
                if isinstance(url, str) and "wikimedia.org" in url:
                    photo = {
                        "url": url,
                        "page": summary.json().get("content_urls", {}).get("desktop", {}).get("page"),
                        "title": key,
                        "source": "Wikimedia Commons",
                    }
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("photo lookup failed for %s: %s", key, exc)
        return None
    _photo_cache[key] = photo
    return photo
