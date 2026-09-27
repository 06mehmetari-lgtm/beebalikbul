"""Tackle rules. Species hits are exact; other fish use genus or FishBase water layer."""

from __future__ import annotations

_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
    }
)

BOTTOM_LAYERS = {"demersal", "benthic", "benthopelagic", "bathydemersal", "reef-associated"}
PELAGIC_LAYERS = {"pelagic", "pelagic-neritic", "pelagic-oceanic", "bathypelagic"}


def fold(value: str) -> str:
    return value.translate(_FOLD).casefold()


def _part(
    part_id: str,
    title: str,
    detail: str,
    gap: str = "",
    width_mm: str = "",
    height_mm: str = "",
) -> dict:
    row = {
        "id": part_id,
        "title": title,
        "detail": detail,
        "image": f"/static/assets/tackle/{part_id}.svg",
    }
    if gap:
        row["gap"] = gap
    if width_mm:
        row["width_mm"] = width_mm
    if height_mm:
        row["height_mm"] = height_mm
    return row


def _token_hit(blob: str, token: str) -> bool:
    return f" {token} " in f" {blob} "


RULES = (
    {
        "id": "carp",
        "title": "Sazan takımı",
        "scientific": {"cyprinus carpio"},
        "genera": {"cyprinus", "carassius", "tinca", "barbus", "luciobarbus", "capoeta", "vimba", "abramis", "blicca"},
        "tokens": ("sazan", "kadife", "siraz"),
        "kinds": {"freshwater", "brackish"},
        "parts": (
            _part("float", "Mantarlı şamandıra düzeni", "Şamandıra, yemi orta su ve yüzey arasında tutar."),
            _part("triple-hook", "Küspeli takım veya yaylı üçlü iğne", "Dipte küspe ya da yaylı üçlü iğne."),
            _part("corn", "Yem: mısır, solucan veya hamur", "Mısır, solucan ya da hamur."),
        ),
    },
    {
        "id": "pike",
        "title": "Turna takımı",
        "scientific": {"esox lucius"},
        "genera": {"esox"},
        "tokens": ("turna",),
        "kinds": {"freshwater", "brackish"},
        "parts": (
            _part("spin-rod", "At-çek kamış", "Kaşık ve silikon bu kamışla gezdirilir."),
            _part("steel-leader", "Çelik lider", "Turnanın dişleri düz misinayı keser; lider şart."),
            _part("spoon", "Sahte yem: kaşık veya silikon", "Kaşık ya da silikon balık."),
        ),
    },
    {
        "id": "predator",
        "title": "Yırtıcı tatlı su takımı",
        "scientific": {"sander lucioperca", "perca fluviatilis", "silurus glanis"},
        "genera": {"sander", "perca", "silurus", "lucioperca"},
        "tokens": ("sudak", "yayin", "yayın"),
        "kinds": {"freshwater", "brackish"},
        "parts": (
            _part("spin-rod", "At-çek kamış", "Kaşık, silikon veya canlı yem gezdirilir."),
            _part("steel-leader", "Kalın misina veya çelik lider", "Yayın ve iri yırtıcıda düz ince misina yetmez."),
            _part("spoon", "Sahte yem: kaşık veya silikon", "Sudak ve levrekte kaşık; yayında iri silikon."),
        ),
    },
    {
        "id": "trout",
        "title": "Alabalık takımı",
        "scientific": {"oncorhynchus mykiss"},
        "genera": {"oncorhynchus", "salmo", "salvelinus"},
        "tokens": ("alabalik", "alabalık"),
        "kinds": {"freshwater", "brackish"},
        "parts": (
            _part("spin-rod", "Hafif at-çek kamış", "Dere ve gölet kıyısında kısa atış."),
            _part("spoon", "Küçük kaşık veya sinek", "Parlak küçük kaşık, akıntıda iş görür."),
            _part("corn", "Yem: solucan veya hamur", "Doğal yemde solucan ya da alabalık hamuru."),
        ),
    },
    {
        "id": "mackerel",
        "title": "Çapari takımı",
        "scientific": {"trachurus trachurus"},
        "genera": {"trachurus", "scomber", "spicara", "engraulis", "sardina", "sardinella", "boops"},
        "tokens": ("istavrit", "uskumru", "izmarit", "hamsi", "sardalya", "kupes"),
        "kinds": {"saltwater", "brackish"},
        "parts": (
            _part("sinker", "Hafif kurşun, 25–50 g", "Sürüye inmek için hafif kurşun."),
            _part("feather-rig", "Köstekli çapari", "Yeşil, beyaz veya gümüş tüy."),
            _part("soft-bait", "Yemsiz", "Çapari tüyleri yem yerine geçer."),
        ),
    },
    {
        "id": "hunter",
        "title": "Kıyı yırtıcı takımı",
        "scientific": {"dicentrarchus labrax", "pomatomus saltatrix", "sarda sarda"},
        "genera": {"dicentrarchus", "pomatomus", "sarda", "seriola", "scomberomorus"},
        "tokens": ("levrek", "lufer", "lüfer", "palamut", "akya"),
        "kinds": {"saltwater", "brackish"},
        "parts": (
            _part("spin-rod", "At-çek kamış", "Kaşık, rapala veya silikon atılır."),
            _part("steel-leader", "Çelik veya kalın florokarbon lider", "Lüfer ve palamutta diş misinayı keser."),
            _part("spoon", "Sahte yem: kaşık veya rapala", "Parlak kaşık ya da balık taklidi."),
        ),
    },
    {
        "id": "bream",
        "title": "Dip takımı",
        "scientific": {"sparus aurata", "lithognathus mormyrus"},
        "genera": {
            "sparus",
            "lithognathus",
            "diplodus",
            "pagellus",
            "pagrus",
            "dentex",
            "mullus",
            "umbrina",
            "argyrosomus",
            "sciaena",
            "scorpaena",
            "epinephelus",
            "serranus",
            "oblada",
            "spondyliosoma",
        },
        "tokens": ("cipura", "çipura", "mirmir", "mırmır", "karagoz", "mercan", "sinarit", "barbun", "tekir", "iskorpit", "lagos", "melanur", "minekop"),
        "kinds": {"saltwater", "brackish"},
        "parts": (
            _part("bottom-rig", "Gezer kurşunlu dip takımı", "Kurşun dipte gezer, yem arkada kalır."),
            _part("double-hook", "İkili dip iğnesi", "Kısa pala, iki iğne."),
            _part("tube-worm", "Canlı yem: boru kurdu, madya veya karides", "Dip balığında canlı yem öndedir."),
        ),
    },
    {
        "id": "mullet",
        "title": "Kefal takımı",
        "scientific": set(),
        "genera": {"mugil", "chelon", "liza"},
        "tokens": (),
        "kinds": {"saltwater", "brackish", "freshwater"},
        "parts": (
            _part("float", "İnce şamandıra düzeni", "Kefal yemi yüzeyin hemen altında alır."),
            _part("corn", "Yem: ekmek içi veya hamur", "Ekmek, hamur ya da çok küçük solucan."),
            _part("sinker", "Çok hafif kurşun", "Şamandırayı batırmayacak kadar ağırlık."),
        ),
    },
)


def _genus(scientific: str) -> str:
    parts = fold(scientific).split()
    return parts[0] if parts else ""


def _match(scientific: str, names: list[str], kind: str) -> tuple[dict, str] | None:
    sci = fold(scientific)
    genus = _genus(scientific)
    blob = " ".join(fold(name) for name in names)
    blob = f" {sci} {blob} "
    for rule in RULES:
        if kind in rule["kinds"] and sci in rule["scientific"]:
            return rule, "species"
    for rule in RULES:
        if kind in rule["kinds"] and genus in rule["genera"]:
            return rule, "genus"
    for rule in RULES:
        if kind not in rule["kinds"]:
            continue
        if any(_token_hit(blob, fold(token)) for token in rule["tokens"]):
            return rule, "name"
    return None


METHODS = (
    ("float", "Şamandıralı"),
    ("spin", "At-çek"),
    ("bottom", "Dip"),
    ("feather", "Çapari"),
)

RULE_METHODS = {
    "carp": ("float", "bottom"),
    "pike": ("spin", "float"),
    "predator": ("spin", "float"),
    "trout": ("spin", "float"),
    "mackerel": ("feather", "spin", "float"),
    "hunter": ("spin", "float"),
    "bream": ("bottom",),
    "mullet": ("float",),
}


def methods_for(scientific: str, names: list[str], kind: str, layer: str | None) -> list[str]:
    found = _match(scientific, names, kind)
    if found is None:
        rule, _level = _layer_rule(kind, layer)
        rule_id = rule["id"]
    else:
        rule_id = found[0]["id"]
    return list(RULE_METHODS.get(rule_id, ("float", "bottom", "spin")))


def _layer_rule(kind: str, layer: str | None) -> tuple[dict, str]:
    pelagic = layer in PELAGIC_LAYERS
    if pelagic and kind in {"saltwater", "brackish"}:
        rule_id = "mackerel"
    elif kind == "saltwater":
        rule_id = "bream"
    else:
        rule_id = "carp"
    rule = next(item for item in RULES if item["id"] == rule_id)
    return rule, "layer"


def _sentences(rule_id: str, measured: dict) -> list[str]:
    lines = []
    cloud = measured.get("cloud_cover")
    wind = measured.get("wind_speed_kmh")
    trend = measured.get("pressure_trend")
    delta = measured.get("pressure_delta_hpa")
    wave = measured.get("wave_height_m")

    if rule_id in {"pike", "predator", "hunter"} and cloud is not None and wind is not None and cloud >= 70 and wind <= 30:
        lines.append(
            f"Bulut örtüsü %{cloud:.0f} ve rüzgar {wind:.0f} km/sa. "
            "Bu ölçümde parlak kaşık ya da açık renk silikon daha görünür."
        )
    elif rule_id in {"pike", "predator", "hunter"} and cloud is not None and cloud < 40:
        lines.append(f"Bulut örtüsü %{cloud:.0f}. Kaşığı daha yavaş gezdirin.")

    if rule_id in {"carp", "trout", "mullet"} and trend == "stable" and delta is not None:
        lines.append(f"Basınç son 6 saatte {delta:+.1f} hPa, sabit. Yem aynı kalır, bekleme daha düzenli olur.")
    elif rule_id in {"carp", "trout", "mullet"} and trend == "rising" and delta is not None:
        lines.append(f"Basınç son 6 saatte {delta:+.1f} hPa, yükseliyor. Yem aynı, bekleme uzayabilir.")

    if rule_id == "mackerel" and wave is not None:
        if wave > 1.5:
            lines.append(f"Dalga {wave:.2f} m. 25–50 g hafif gelebilir; bir boy ağır kurşun düşünün.")
        else:
            lines.append(f"Dalga {wave:.2f} m. 25–50 g kurşun bu ölçüme uyar.")

    if rule_id in {"bream", "hunter"} and wave is not None and wave > 1.5:
        lines.append(f"Dalga {wave:.2f} m. Kurşunu dipte tutacak kadar ağır seçin.")

    return lines


def _note(level: str) -> str:
    if level == "species":
        return "Bu tür için yazılmış takım. Hava cümleleri yalnızca ölçülen değerlere göre eklenir."
    if level == "genus":
        return "Bu türün cinsindeki balıklarla aynı takım ailesi kullanıldı. Hava cümleleri ölçülen değere bağlıdır."
    if level == "name":
        return "Türkçe veya İngilizce ad, bu takım ailesiyle eşleşti."
    return "Bu türe özel satır yok. FishBase su katmanına göre genel düzen seçildi."


def _clock_minutes(value: str | None) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[1]
    text = text[:5]
    if ":" not in text:
        return None
    hour_text, minute_text = text.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text[:2])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _hhmm(total: int) -> str:
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def _near(minute: int, target: int | None, window: int = 45) -> bool:
    if target is None:
        return False
    diff = abs(minute - target) % 1440
    return min(diff, 1440 - diff) <= window


def _slot(minute: int, sunrise: int | None, sunset: int | None) -> str:
    if sunrise is None and sunset is None:
        return "unknown"
    if _near(minute, sunrise) or _near(minute, sunset):
        return "twilight"
    if sunset is None:
        return "night" if sunrise is not None and minute < sunrise else "day"
    if sunrise is None:
        return "night" if minute >= sunset else "day"
    if minute < sunrise or minute >= sunset:
        return "night"
    return "day"


def _samples(start: int, end: int) -> list[tuple[int, int]]:
    if start == end:
        return [(0, start)]
    span = (end - start) % 1440
    points: list[tuple[int, int]] = []
    walked = 0
    while True:
        absolute = start + walked
        points.append((1 if absolute >= 1440 else 0, absolute % 1440))
        if walked == span:
            break
        walked = min(span, walked + 30)
    return points


def classify_window(
    start: str | None,
    end: str | None,
    sunrise: str | None,
    sunset: str | None,
    sunrise_next: str | None = None,
) -> dict:
    start_m = _clock_minutes(start)
    end_m = _clock_minutes(end)
    rise = _clock_minutes(sunrise)
    dusk = _clock_minutes(sunset)
    rise_next = _clock_minutes(sunrise_next) or rise
    if start_m is None or end_m is None or (rise is None and dusk is None):
        return {
            "start": start,
            "end": end,
            "period": "unknown",
            "label": "Saat karşılaştırılamadı",
            "summary": "Gün doğumu veya batımı olmadığı için bu aralık gece ya da gündüz diye ayrılmadı.",
        }
    labels = []
    for offset, minute in _samples(start_m, end_m):
        if offset == 0:
            labels.append(_slot(minute, rise, dusk))
        else:
            labels.append(_slot(minute, rise_next, None))
    kinds = {item for item in labels if item != "unknown"}
    if not kinds:
        period = "unknown"
    elif kinds == {"day"}:
        period = "day"
    elif kinds == {"twilight"}:
        period = "twilight"
    elif kinds <= {"night", "twilight"}:
        period = "night"
    else:
        period = "mixed"
    names = {
        "night": "Gece",
        "day": "Gündüz",
        "twilight": "Alacakaranlık",
        "mixed": "Gündüz ve gece",
        "unknown": "Saat karşılaştırılamadı",
    }
    rise_text = _hhmm(rise) if rise is not None else "yok"
    dusk_text = _hhmm(dusk) if dusk is not None else "yok"
    morning = _hhmm(rise_next) if rise_next is not None else rise_text
    summary = (
        f"{_hhmm(start_m)}–{_hhmm(end_m)}. "
        f"Gün batımı {dusk_text}, gün doğumu {morning}. "
        f"Bu aralık {names[period].casefold()}."
    )
    return {
        "start": _hhmm(start_m),
        "end": _hhmm(end_m),
        "period": period,
        "slots": sorted(kinds),
        "label": names[period],
        "summary": summary,
        "sunrise": rise_text,
        "sunset": dusk_text,
    }


def _moon_bucket(phase: float | None) -> str | None:
    if phase is None:
        return None
    if phase <= 0.08 or phase >= 0.92:
        return "dark"
    if abs(phase - 0.5) <= 0.12:
        return "bright"
    return "dim"


def _adapt(parts: list[dict], rule_id: str, period: str, moon_phase: float | None) -> tuple[list[dict], dict]:
    parts = [dict(part) for part in parts]
    first = parts[0]["title"] if parts else "Takım"
    first_id = parts[0]["id"] if parts else ""
    if period == "day":
        return parts, {
            "id": first_id,
            "title": first,
            "why": "Aralık gündüz. Fosforlu parça eklenmedi; bu ailenin gündüz takımı duruyor.",
        }
    if period == "twilight":
        return parts, {
            "id": first_id,
            "title": first,
            "why": "Aralık gün doğumu veya batımına 45 dakika yakın. Fosfor şart değil; gündüz takımı duruyor.",
        }
    if period == "unknown":
        return parts, {
            "id": first_id,
            "title": first,
            "why": "Gün doğumu ve batımı gelmediği için gece parçası seçilmedi.",
        }

    bucket = _moon_bucket(moon_phase)
    lead_id = first_id
    lead_title = first
    why = "Aralık geceye denk geliyor."

    if rule_id in {"carp", "mullet"}:
        for part in parts:
            if part["id"] == "float":
                part["id"] = "glow-float"
                part["image"] = "/static/assets/tackle/glow-float.svg"
                part["title"] = "Fosforlu şamandıra"
                part["detail"] = "Gün battıktan sonra düz mantar görünmez. Aynı düzenin gece parçası fosforlu şamandıradır."
                lead_id = "glow-float"
                lead_title = part["title"]
            elif part["id"] == "corn":
                part["detail"] = "Aynı yem durur. Karanlıkta iğneye fosforlu solucan veya fosforlu mısır takılır."
        why = "Şamandıralı düzende gece öne çıkan parça fosforlu şamandıradır; yemin yerini o gösterir."
    elif rule_id == "bream":
        bead = _part(
            "glow-bead",
            "Fosforlu boncuk veya starlight",
            "Dip yemi aynı kalır. Karanlıkta iğnenin yanında fosforlu boncuk ya da starlight durur.",
        )
        parts.insert(0, bead)
        lead_id = "glow-bead"
        lead_title = bead["title"]
        why = "Dip takımında yem değişmez. Gece eklenen parça, yemin yerini belli eden fosforlu boncuktur."
    elif rule_id == "mackerel":
        bead = _part(
            "glow-bead",
            "Fosforlu tüy veya ışık hapsi",
            "Düz tüy gece görünmez. Aynı çaparinin gece parçası fosforlu tüy veya kısa starlight'tır.",
        )
        parts.insert(0, bead)
        lead_id = "glow-bead"
        lead_title = bead["title"]
        why = "Çapari ailesinde gece öne çıkan parça fosforlu tüy veya ışık hapsidir."
    elif rule_id == "trout":
        if bucket == "bright":
            lead_id = "spoon"
            lead_title = "Küçük parlak kaşık"
            why = "Ay dolunaya yakın, gece aydınlık. Bu ailede küçük parlak kaşık durur."
        else:
            lead_id = "corn"
            lead_title = "Solucan veya hamur"
            for part in parts:
                if part["id"] == "corn":
                    part["detail"] = "Karanlıkta küçük kaşık zor seçilir. Solucan veya hamur bu ailenin gece yemidir."
            why = "Ay karanlık ya da kısmi. Alabalık ailesinde gece öne çıkan yem solucan veya hamurdur."
    elif rule_id in {"pike", "predator", "hunter"}:
        if bucket == "bright":
            lead_id = "spoon"
            lead_title = "Parlak kaşık"
            why = "Ay dolunaya yakın, gece aydınlık. Bu at-çek ailesinde parlak kaşık durur."
        elif bucket == "dark":
            lead_id = "spoon"
            lead_title = "Koyu silikon veya sesli sahte"
            for part in parts:
                if part["id"] == "spoon":
                    part["title"] = "Koyu silikon veya sesli sahte"
                    part["detail"] = "Yeni aya yakın gecede parlak kaşık zayıf kalır. Koyu silikon veya ses çıkaran sahte öne çıkar."
            why = "Ay yeni aya yakın, gece karanlık. Bu at-çek ailesinde koyu silikon veya sesli sahte öne çıkar."
        else:
            lead_id = "spoon"
            lead_title = "Koyu silikon ve kaşık"
            why = "Ay kısmen aydınlık. Kaşık ile koyu silikon birlikte kullanılır."
        if bucket is None:
            lead_title = "Koyu silikon"
            why = "Ay evresi gelmedi. Gece at-çekte parlak sahte zayıf kalır; koyu silikon bu ailenin karanlık parçasıdır."

    if period == "mixed":
        why = "Aralık gündüz saatini de kesiyor. Gün batımından sonra şu parça öne çıkar. " + why
    return parts, {"id": lead_id, "title": lead_title, "why": why}


def _setup(title: str, detail: str, pieces: list[dict]) -> dict:
    return {"title": title, "detail": detail, "pieces": pieces}


def _setups(rule_id: str, kind: str) -> list[dict]:
    fresh = kind == "freshwater"
    bank = "Kıyıdan atılır. Olta, kıyı şeridinin içinde kalır." if fresh else "Kıyıdan atılır."
    catalog = {
        "carp": [
            _setup(
                "Şamandıra takımı",
                "4–6 m kamış, 0.25 misina, mantarlı şamandıra, 6–8 numara iğne. Yem orta su ile yüzey arasında durur.",
                [
                    _part("float", "Mantarlı şamandıra", "Yemi orta su ile yüzey arasında tutar."),
                    _part("sinker", "Küçük kurşun", "Şamandırayı batırmaz, yemi indirir."),
                    _part("corn", "Mısır veya hamur", "İğnedeki yem."),
                ],
            ),
            _setup(
                "Dip takımı",
                "3.6 m dip kamışı, gezer kurşun 30–60 g, yaylı üçlü iğne. Yem dipte kalır.",
                [
                    _part("sinker", "Gezer kurşun, 30–60 g", "Olta dibe iner, kurşun ipte gezer."),
                    _part("triple-hook", "Yaylı üçlü iğne", "Üç iğne dipte durur."),
                    _part("corn", "Küspe, mısır veya solucan", "Yem dipte kalır."),
                ],
            ),
            _setup(
                "Yem takımı",
                "Aynı kamışta üç yem ayrı denenir. Av puanı değildir.",
                [
                    _part("corn", "Mısır", "Bir deneme yemi."),
                    _part("tube-worm", "Solucan", "İkinci deneme yemi."),
                    _part("soft-bait", "Hamur", "Üçüncü deneme yemi."),
                ],
            ),
        ],
        "pike": [
            _setup(
                "Kaşık takımı",
                "2.4–2.7 m at-çek kamış, çelik lider, 12–20 g kaşık.",
                [
                    _part("spin-rod", "At-çek kamış", "Kaşık bu kamışla gezdirilir."),
                    _part("steel-leader", "Çelik lider", "Diş misinayı kesmesin diye."),
                    _part("spoon", "Kaşık, 12–20 g", "Kıyı boyunca gezdirilir."),
                ],
            ),
            _setup(
                "Silikon takımı",
                "Aynı kamış, jig baş 7–14 g, 8–12 cm silikon.",
                [
                    _part("spin-rod", "At-çek kamış", "Silikon bu kamışla süzülür."),
                    _part("sinker", "Jig baş, 7–14 g", "Silikonu dip ile orta su arasında tutar."),
                    _part("soft-bait", "Silikon, 8–12 cm", "Dip sıyırmada çalışır."),
                ],
            ),
            _setup(
                "Canlı yem takımı",
                "Şamandıra veya serbest canlı yem. Çelik lider şart.",
                [
                    _part("float", "Şamandıra", "Canlı yemi istenen suda tutar."),
                    _part("steel-leader", "Çelik lider", "Diş için şart."),
                    _part("soft-bait", "Canlı yem", "Kıyı şeridinde dolaşır."),
                ],
            ),
        ],
        "predator": [
            _setup(
                "Kaşık takımı",
                "2.4–2.7 m at-çek, çelik lider, kaşık.",
                [
                    _part("spin-rod", "At-çek kamış", "Kaşık kıyı boyu gezdirilir."),
                    _part("steel-leader", "Çelik lider", "Sudak ve yayın için."),
                    _part("spoon", "Kaşık", "Parlak sahte yem."),
                ],
            ),
            _setup(
                "Silikon takımı",
                "Jig başlı silikon, dip sıyırma.",
                [
                    _part("spin-rod", "At-çek kamış", "Silikon bu kamışla atılır."),
                    _part("sinker", "Jig baş", "Dibe iner."),
                    _part("soft-bait", "Silikon", "Yayın için iri silikon."),
                ],
            ),
            _setup(
                "Canlı yem takımı",
                "Küçük balık, dip veya şamandıra. Lider durur.",
                [
                    _part("float", "Şamandıra", "Yemi orta suda tutmak için."),
                    _part("steel-leader", "Lider", "Diş misinayı kesmesin."),
                    _part("soft-bait", "Küçük balık", "Canlı yem."),
                ],
            ),
        ],
        "trout": [
            _setup(
                "Küçük kaşık",
                "1.8–2.1 m hafif kamış, 0.18 misina, 2–5 g kaşık.",
                [
                    _part("spin-rod", "Hafif kamış", "Kısa atış."),
                    _part("spoon", "Kaşık, 2–5 g", "Akıntıda gezdirilir."),
                ],
            ),
            _setup(
                "Sinek veya boncuk",
                "İnce misina, küçük sinek ya da boncuk. Yüzeye yakın.",
                [
                    _part("spin-rod", "İnce kamış", "Hafif atış."),
                    _part("glow-bead", "Sinek veya boncuk", "Yüzeye yakın gezdirilir."),
                ],
            ),
            _setup(
                "Doğal yem",
                "Küçük iğne, solucan veya hamur, hafif şamandıra.",
                [
                    _part("float", "Hafif şamandıra", "Yemi dipte bekletmez."),
                    _part("tube-worm", "Solucan veya hamur", "Küçük iğnede."),
                ],
            ),
        ],
        "mackerel": [
            _setup(
                "Çapari",
                "2.7–3.6 m kamış, 25–50 g kurşun, yeşil-beyaz-gümüş tüy.",
                [
                    _part("sinker", "Hafif kurşun, 25–50 g", "Sürüye inmek için."),
                    _part("feather-rig", "Köstekli çapari", "Yeşil, beyaz veya gümüş tüy."),
                    _part("soft-bait", "Yemsiz", "Tüyler yem yerine geçer."),
                ],
            ),
            _setup(
                "Hafif kaşık",
                "İnce at-çek, 7–15 g kaşık. Sürü yüzeye yaklaşınca.",
                [
                    _part("spin-rod", "İnce at-çek kamış", "Sürü yüzeye gelince."),
                    _part("spoon", "Kaşık, 7–15 g", "Yüzeye yakın gezdirilir."),
                ],
            ),
            _setup(
                "Sabit çapari",
                "Aynı tüyler, daha ağır kurşun. Dip ile orta su arasında.",
                [
                    _part("sinker", "Ağır kurşun", "Çapariyi orta suda tutar."),
                    _part("feather-rig", "Köstekli çapari", "Tüyler kurşunun üstünde."),
                    _part("soft-bait", "Yemsiz", "Tüy yem yerine geçer."),
                ],
            ),
        ],
        "hunter": [
            _setup(
                "Kaşık veya rapala",
                "2.7–3 m at-çek, lider, parlak kaşık ya da balık taklidi.",
                [
                    _part("spin-rod", "At-çek kamış", "Kaşık veya rapala atılır."),
                    _part("steel-leader", "Lider", "Lüferde diş misinayı keser."),
                    _part("spoon", "Kaşık veya rapala", "Parlak sahte yem."),
                ],
            ),
            _setup(
                "Silikon",
                "Jig başlı silikon, kıyı kırığında.",
                [
                    _part("spin-rod", "At-çek kamış", "Silikon bu kamışla atılır."),
                    _part("steel-leader", "Lider", "Diş için durur."),
                    _part("soft-bait", "Silikon", "Kıyı kırığında süzülür."),
                ],
            ),
            _setup(
                "Canlı yem",
                "İstavrit veya sardalya, şamandıra ya da serbest.",
                [
                    _part("float", "Şamandıra", "Canlı yemi istenen suda tutar."),
                    _part("steel-leader", "Lider", "Diş için şart."),
                    _part("soft-bait", "İstavrit veya sardalya", "Canlı yem."),
                ],
            ),
        ],
        "bream": [
            _setup(
                "Gezer dip",
                "3.6–4.2 m kamış, 40–80 g gezer kurşun, iki iğneli kısa pala.",
                [
                    _part("sinker", "Gezer kurşun, 40–80 g", "İpte gezer, dibe iner."),
                    _part("double-hook", "İki iğne", "Kısa pala, yem dipte."),
                    _part("tube-worm", "Boru kurdu veya karides", "İğnedeki yem."),
                ],
            ),
            _setup(
                "Sabit dip",
                "Kurşun sabit. Bekleme takımıdır.",
                [
                    _part("bottom-rig", "Sabit kurşun", "Kurşun ipin ucunda durur."),
                    _part("double-hook", "İki iğne", "Yem dipte bekler."),
                    _part("tube-worm", "Boru kurdu, madya veya karides", "Bekleme yemi."),
                ],
            ),
            _setup(
                "İskele dip",
                "Daha kısa kamış, aynı iki iğne. İskele kenarından dibe iner.",
                [
                    _part("sinker", "Kurşun", "İskele kenarından dibe iner."),
                    _part("double-hook", "İki iğne", "Aynı dip düzeni."),
                    _part("tube-worm", "Yem", "Boru kurdu veya karides."),
                ],
            ),
        ],
        "mullet": [
            _setup(
                "İnce şamandıra",
                "4–5 m ince kamış, çok hafif şamandıra, 12–16 numara iğne.",
                [
                    _part("float", "Çok hafif şamandıra", "Yem yüzeyin hemen altında."),
                    _part("sinker", "Çok hafif kurşun", "Şamandırayı batırmaz."),
                    _part("corn", "Küçük yem", "12–16 numara iğnede."),
                ],
            ),
            _setup(
                "Ekmek veya hamur",
                "Aynı düzen, ekmek içi veya hamur.",
                [
                    _part("float", "İnce şamandıra", "Yüzeyin hemen altı."),
                    _part("corn", "Ekmek veya hamur", "Kurşun şamandırayı batırmaz."),
                ],
            ),
            _setup(
                "Küçük solucan",
                "Çok küçük iğne, kısa solucan parçası. Kıyı kenarında.",
                [
                    _part("float", "Hafif şamandıra", "Dipte değil, kıyı kenarında."),
                    _part("tube-worm", "Kısa solucan", "Çok küçük iğnede."),
                ],
            ),
        ],
    }
    rows = catalog.get(rule_id)
    if rows is None:
        if fresh:
            rows = [
                _setup("Şamandıra", f"4–5 m kamış, şamandıra, küçük iğne. {bank}", [
                    _part("float", "Şamandıra", "Yemi orta suda tutar."),
                    _part("corn", "Mısır veya solucan", "Küçük iğnede."),
                ]),
                _setup("Dip", f"3.6 m kamış, gezer kurşun. {bank}", [
                    _part("sinker", "Gezer kurşun", "Dibe iner."),
                    _part("tube-worm", "Solucan veya hamur", "Dip iğnesinde."),
                ]),
                _setup("Hafif at-çek", f"2.1 m kamış, küçük kaşık veya silikon. {bank}", [
                    _part("spin-rod", "Hafif kamış", "Kısa atış."),
                    _part("spoon", "Küçük kaşık", "Veya silikon."),
                ]),
            ]
        else:
            rows = [
                _setup("Şamandıra", f"Kıyı kamışı, şamandıra, küçük iğne. {bank}", [
                    _part("float", "Şamandıra", "Yüzeye yakın."),
                    _part("corn", "Ekmek veya solucan", "Küçük iğnede."),
                ]),
                _setup("Dip", f"Gezer kurşun, iki iğne. {bank}", [
                    _part("sinker", "Gezer kurşun", "Dibe iner."),
                    _part("double-hook", "İki iğne", "Boru kurdu veya karides."),
                ]),
                _setup("At-çek", f"Kaşık veya silikon, liderli at-çek. {bank}", [
                    _part("spin-rod", "At-çek kamış", "Kıyıdan atılır."),
                    _part("spoon", "Kaşık veya silikon", "Lider durur."),
                ]),
            ]
    return rows



def _piece_ids(setup: dict) -> set[str]:
    return {part["id"] for part in setup.get("pieces") or []}


def _rod_step(style: str, zone: str | None, kind: str) -> dict:
    place = "fresh" if kind == "freshwater" else (zone if zone in {"harbor", "shore", "open"} else "shore")
    lengths = {
        ("float", "harbor"): ("3–4 m", "İç liman ve iskelede salınım kısadır. Kamış bu aralıkta kalır."),
        ("float", "shore"): ("4–5 m", "Kıyı şeridinde şamandıra kamışı bu aralıkta."),
        ("float", "open"): ("3.6–4.2 m", "Açıkta kamış elde daha kısa tutulur."),
        ("float", "fresh"): ("4–6 m", "Göl ve baraj kıyısında şamandıra kamışı bu aralıkta."),
        ("spin", "harbor"): ("2.1–2.7 m", "Mendirekte uzun kamış arkaya takılır. At-çek bu aralıkta."),
        ("spin", "shore"): ("2.7–3.3 m", "Kıyı at-çek kamışı bu aralıkta."),
        ("spin", "open"): ("2.4–3.0 m", "Açıkta at-çek kamışı bu aralıkta."),
        ("spin", "fresh"): ("2.4–2.7 m", "Tatlı su kıyısında at-çek bu aralıkta."),
        ("bottom", "harbor"): ("3–3.6 m", "İskele dip kamışı bu aralıkta."),
        ("bottom", "shore"): ("3.6–4.2 m", "Kıyı dip kamışı bu aralıkta."),
        ("bottom", "open"): ("3–3.6 m", "Açıkta dip kamışı bu aralıkta."),
        ("bottom", "fresh"): ("3.6 m", "Göl kıyısında dip kamışı bu boyda."),
        ("feather", "harbor"): ("2.7–3.3 m", "Liman çapari kamışı bu aralıkta."),
        ("feather", "shore"): ("3–3.6 m", "Kıyı çapari kamışı bu aralıkta."),
        ("feather", "open"): ("2.7–3.3 m", "Açıkta çapari kamışı bu aralıkta."),
        ("feather", "fresh"): ("2.4–3.0 m", "Tatlı suda bu kamış aralığı."),
    }
    names = {
        "float": "Şamandıra kamışı",
        "spin": "At-çek kamış",
        "bottom": "Dip kamışı",
        "feather": "Çapari kamışı",
    }
    length, why = lengths[(style, place)]
    icon = "spin-rod" if style in {"spin", "feather"} else "rod"
    return _part(icon, f"{names[style]}, {length}", why, "Sıranın başı")


def _bait_step(setup: dict, ids: set[str]) -> dict | None:
    name = fold(f"{setup.get('title', '')} {setup.get('detail', '')}")
    if "yemsiz" in name or ("feather-rig" in ids and "hamsi" not in name):
        return _part("feather-rig", "Yem kesilmez", "Çapari tüyü yemin yerini tutar. İğneye parça takılmaz.", "Son tüyün ucu")
    if "kasik" in name or "spoon" in ids and "hamsi" not in name and "float" not in ids and "glow-float" not in ids:
        return _part("spoon", "Kaşık kesilmez", "Sahte yem bütün durur. Liderin ucundaki halkaya bağlanır.", "Liderin ucu")
    if "canli" in name:
        return _part("soft-bait", "Yem balık, bütün", "Kesilmez. İğne sırtın önünden ya da ağızdan geçer.", "Liderin ucu")
    if "hamsi" in name:
        return _part(
            "bait-cut",
            "Hamsi parçası",
            "Enine kesilir, kılçık ayıklanır. İğne parçanın ortasından geçer.",
            "İğnenin üstü",
            "10–15",
            "6–8",
        )
    if "solucan" in name or "tube-worm" in ids:
        return _part(
            "bait-cut",
            "Solucan parçası",
            "İğne ortadan girer, iki uç yanda sarkar.",
            "İğnenin üstü",
            "20–30",
            "3–4",
        )
    if "hamur" in name or "ekmek" in name:
        return _part(
            "bait-cut",
            "Hamur",
            "Yuvarlanır. İğne ortaya gömülür, uç hafif görünür.",
            "İğnenin üstü",
            "8–12",
            "8–12",
        )
    if "misir" in name or "corn" in ids:
        return _part("corn", "Mısır, tek tane", "Kesilmez. İğne tanenin ortasından geçer.", "İğnenin üstü")
    return _part(
        "bait-cut",
        "Yem parçası",
        "Lokma boyu kesilir. İğne ortasından geçer.",
        "İğnenin üstü",
        "10–20",
        "6–8",
    )


def _style_of(setup: dict) -> str:
    ids = _piece_ids(setup)
    name = fold(setup.get("title") or "")
    if "feather-rig" in ids or "capari" in name:
        return "feather"
    if "float" in ids or "glow-float" in ids or "samandira" in name:
        return "float"
    if "bottom-rig" in ids or "double-hook" in ids or "triple-hook" in ids or "dip" in name:
        return "bottom"
    if "spoon" in ids or "spin-rod" in ids or "kasik" in name or "silikon" in name:
        return "spin"
    return "baits"


def _expand_setup(setup: dict, zone: str | None, kind: str) -> None:
    ids = _piece_ids(setup)
    style = _style_of(setup)
    name = fold(setup.get("title") or "")
    steps = [_rod_step(style if style != "baits" else "float", zone, kind)]
    if style == "float":
        float_icon = "glow-float" if "glow-float" in ids or "gece" in name else "float"
        hook_icon = "triple-hook" if "triple-hook" in ids else "hook"
        hook_title = "Üçlü kanca" if hook_icon == "triple-hook" else "İğne"
        hook_detail = (
            "Üç iğne aynı ipte. İğnelerin kendi aralığı yaklaşık 8–12 cm. Bu, derinlik değil, iğne payıdır."
            if hook_icon == "triple-hook"
            else "Tek iğne kurşunun altında durur. Derinliği, şamandıradan bırakılan ip belirler."
        )
        surface = "gece" in name or "glow-float" in ids
        drop = (
            "Yüzey takımı. Şamandıradan iğneye toplam pay çoğu zaman 20–50 cm. Bu sabit bir ölçüm değil. Yemi daha derine almak istersen bu pay metre olur."
            if surface
            else "Şamandıradan sonraki ip, yemin derinliğidir. Yüzeye yakınsa onlarca santim, derinde metre olur. Sabit bir santim ölçümü yok."
        )
        steps.extend(
            [
                _part("stop", "Üst stop", "Şamandıranın yukarı kaymasını keser.", "Ana ip kamış ucundan iner"),
                _part(float_icon, "Şamandıra", "İki stop arasında durur. Stop aralığı kısadır, yaklaşık 1 cm. Bu aralık metre değildir.", "Üst stopun hemen altı"),
                _part("stop", "Alt stop", "Şamandıra aşağı kaymasın diye stop burada durur. Pay yaklaşık 1 cm.", "Şamandıranın hemen altı"),
                _part("sinker", "Sıkıştırma kurşunu", drop, "Şamandıradan sonra"),
                _part(hook_icon, hook_title, hook_detail, "Kurşunun altı"),
            ]
        )
        bait = _bait_step(setup, ids)
        if bait:
            steps.append(bait)
    elif style == "bottom":
        hook_icon = "triple-hook" if "triple-hook" in ids else "double-hook" if "double-hook" in ids else "hook"
        steps.extend(
            [
                _part("sinker", "Kurşun", "Ana ipte gezer ya da sabittir. Yemi dibe indirir.", "Ana ipte, kamıştan sonra"),
                _part("stop", "Ara stop", "Kurşun iğneye dayanmasın diye.", "Kurşundan 30–40 cm aşağı"),
                _part(hook_icon, "İğne", "Yem dipte, kamış kıyıda bekler.", "Stopun hemen altı"),
            ]
        )
        bait = _bait_step(setup, ids)
        if bait:
            steps.append(bait)
    elif style == "feather":
        steps.extend(
            [
                _part("feather-rig", "Köstekli çapari", "Tüyler alt alta. Yeşil, beyaz veya gümüş.", "Kamıştan ana ip"),
                _part("sinker", "Kurşun", "Çapariyi sürüye indirir.", "Son tüyden 10–15 cm aşağı"),
                _part("feather-rig", "Yem kesilmez", "Tüy yemin yerini tutar.", "Kurşunun üstündeki tüyler"),
            ]
        )
    elif style == "spin":
        leader = "steel-leader" if "steel-leader" in ids else "spin-rod"
        lure = "soft-bait" if "soft-bait" in ids and "spoon" not in ids else "spoon"
        lure_title = "Silikon" if lure == "soft-bait" else "Kaşık"
        steps.extend(
            [
                _part(leader, "Lider, 30–50 cm", "Dişli balıkta çelik, diğerinde kalın florokarbon.", "Kamış ucundan 30–50 cm"),
                _part(lure, lure_title, "Kesilmez. Liderin ucundaki halkaya bağlanır.", "Liderin ucu"),
            ]
        )
    else:
        steps.extend(
            [
                _part("corn", "Mısır, tek tane", "Kesilmez. İğne tanenin ortasından geçer.", "1. iğne"),
                _part("bait-cut", "Solucan parçası", "İğne ortadan girer, iki uç yanda sarkar.", "Aynı kamış, 2. deneme", "20–30", "3–4"),
                _part("bait-cut", "Hamur", "Yuvarlanır. İğne ortaya gömülür, uç hafif görünür.", "3. deneme", "8–12", "8–12"),
            ]
        )
    setup["pieces"] = steps


def _mark_favorite(setups: list[dict], period: str, method: str | None) -> None:
    for setup in setups:
        setup["favorite"] = False
    if not setups:
        return

    def named(setup: dict) -> str:
        return fold(setup["title"])

    chosen = None
    if method == "float":
        for setup in setups:
            if "glow-float" in _piece_ids(setup) or "gece" in named(setup):
                chosen = setup
                break
        if chosen is None:
            for setup in setups:
                if "float" in _piece_ids(setup) or "samandira" in named(setup):
                    chosen = setup
                    break
    elif method == "spin":
        for setup in setups:
            if "spoon" in _piece_ids(setup):
                chosen = setup
                break
        if chosen is None:
            for setup in setups:
                ids = _piece_ids(setup)
                if "spin-rod" in ids and "float" not in ids:
                    chosen = setup
                    break
    elif method == "bottom":
        for setup in setups:
            ids = _piece_ids(setup)
            if "bottom-rig" in ids or "triple-hook" in ids or "double-hook" in ids or "dip" in named(setup):
                chosen = setup
                break
    elif method == "feather":
        for setup in setups:
            if "feather-rig" in _piece_ids(setup) or "capari" in named(setup):
                chosen = setup
                break
    elif period in {"night", "mixed"}:
        for setup in setups:
            if "gece" in named(setup) or "glow-float" in _piece_ids(setup):
                chosen = setup
                break
        if chosen is None:
            for setup in setups:
                if "float" in _piece_ids(setup):
                    chosen = setup
                    break
    if chosen is None:
        chosen = setups[0]
    chosen["favorite"] = True
    setups.sort(key=lambda setup: 0 if setup.get("favorite") else 1)


def recommend(
    scientific: str,
    names: list[str],
    kind: str,
    measured: dict,
    layer: str | None = None,
    start: str | None = None,
    end: str | None = None,
    sunrise: str | None = None,
    sunset: str | None = None,
    sunrise_next: str | None = None,
    moon_phase: float | None = None,
    method: str | None = None,
    zone: str | None = None,
) -> dict:
    found = _match(scientific, names, kind)
    if found is None:
        rule, level = _layer_rule(kind, layer)
        title = {
            "mackerel": "Genel çapari takımı",
            "bream": "Genel dip takımı",
            "carp": "Genel tatlı su takımı",
        }.get(rule["id"], rule["title"])
    else:
        rule, level = found
        title = rule["title"]
    window = classify_window(start, end, sunrise, sunset, sunrise_next)
    parts, lead = _adapt(list(rule["parts"]), rule["id"], window["period"], moon_phase)
    if moon_phase is not None and window["period"] in {"night", "mixed"}:
        lead["why"] = f"{lead['why']} Ay evresi {moon_phase:.2f}."
    setups = _setups(rule["id"], kind)
    if window["period"] in {"night", "mixed"} and kind != "freshwater" and (
        rule["id"] == "mackerel" or layer in PELAGIC_LAYERS
    ):
        setups = [
            {
                "title": "Gece liman şamandırası",
                "detail": (
                    "Şamandıra, üçlü kanca, hamsi parçası. Yem liman ışığının altında, "
                    "yüzeyin hemen altında durur. Bu takım üst suyu avlar. Av sayısı değildir."
                ),
                "pieces": [
                    _part("glow-float", "Şamandıra", "Işığın altında, yüzeyin hemen altında durur."),
                    _part("triple-hook", "Üçlü kanca", "Üç iğne aynı ipte."),
                    _part("soft-bait", "Hamsi parçası", "Her iğnede küçük hamsi parçası."),
                ],
            },
            *setups[:2],
        ]
    for setup in setups:
        _expand_setup(setup, zone, kind)
    _mark_favorite(setups, window.get("period") or "", method)
    return {
        "matched": True,
        "match_level": level,
        "rule_id": rule["id"],
        "scientific": scientific,
        "kind": kind,
        "title": title,
        "parts": parts,
        "conditions": _sentences(rule["id"], measured),
        "note": _note(level),
        "window": window,
        "lead": lead,
        "setups": setups,
        "limit": (
            "FishBase ve Open-Meteo saatlik av verimi yayınlamıyor. "
            "Öne çıkan parça, seçilen saatin gün doğumu, gün batımı ve ay evresine göre bu takım ailesinin uyarlamasıdır."
        ),
    }
