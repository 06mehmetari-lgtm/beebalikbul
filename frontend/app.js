const body = document.getElementById("sheet-body");
const hint = document.querySelector(".hint");

const map = L.map("map", { zoomControl: false, attributionControl: true }).setView([41.08, 29.02], 9);
L.control.zoom({ position: "bottomright" }).addTo(map);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 19,
  attribution: "Görüntü © Esri, Maxar, Earthstar Geographics",
}).addTo(map);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 19,
  opacity: 0.92,
}).addTo(map);

const landLayer = L.layerGroup().addTo(map);
const drawn = L.layerGroup().addTo(map);
const provinceLayer = L.layerGroup().addTo(map);
let activeProvince = "";
let provinceCache = null;
window.addEventListener("resize", () => map.invalidateSize());

const sheet = document.getElementById("sheet");
const grip = document.getElementById("sheet-grip");
let sheetDrag = null;
let sheetCollapsed = false;

function sheetOffset() {
  return sheetCollapsed ? Math.max(0, sheet.offsetHeight - 36) : 0;
}

function moveSheet(y) {
  const limit = Math.max(0, sheet.offsetHeight - 36);
  const next = Math.max(0, Math.min(limit, y));
  sheet.style.transform = `translateY(${next}px)`;
  return next;
}

function finishSheet(y) {
  sheet.classList.remove("dragging");
  sheet.style.transform = "";
  sheetCollapsed = y > sheet.offsetHeight * 0.22;
  sheet.classList.toggle("collapsed", sheetCollapsed);
  setTimeout(() => map.invalidateSize(), 280);
}

if (grip && window.matchMedia("(max-width: 719px)").matches) {
  grip.addEventListener("pointerdown", (event) => {
    if (event.button != null && event.button !== 0) return;
    sheetDrag = { y: event.clientY, base: sheetOffset() };
    sheet.classList.add("dragging");
    grip.setPointerCapture(event.pointerId);
  });
  grip.addEventListener("pointermove", (event) => {
    if (!sheetDrag) return;
    moveSheet(sheetDrag.base + (event.clientY - sheetDrag.y));
  });
  grip.addEventListener("pointerup", (event) => {
    if (!sheetDrag) return;
    const y = moveSheet(sheetDrag.base + (event.clientY - sheetDrag.y));
    sheetDrag = null;
    finishSheet(y);
  });
  grip.addEventListener("pointercancel", () => {
    if (!sheetDrag) return;
    sheetDrag = null;
    finishSheet(sheetOffset());
  });
}
let marker = null;
let approach = null;
let shoreLayer = null;
let landRequest = 0;
let waitTimer = null;
let waitToken = 0;

function showWait(title, text) {
  const token = ++waitToken;
  const panel = document.getElementById("wait");
  document.getElementById("wait-title").textContent = title;
  document.getElementById("wait-text").textContent = text;
  const clock = document.getElementById("wait-time");
  const started = performance.now();
  clock.textContent = "0 saniye oldu. Çalışıyor, bekle.";
  panel.hidden = false;
  clearInterval(waitTimer);
  waitTimer = setInterval(() => {
    const seconds = Math.max(1, Math.floor((performance.now() - started) / 1000));
    clock.textContent = `${seconds} saniye oldu. Çalışıyor, bekle.`;
  }, 1000);
  const fisheryBox = document.getElementById("fishery");
  const provinceBox = document.getElementById("province");
  if (fisheryBox) fisheryBox.disabled = true;
  if (provinceBox) provinceBox.disabled = true;
  hint.textContent = "Çalışıyor, bekle";
  return token;
}

function hideWait(token) {
  if (token !== waitToken) return;
  clearInterval(waitTimer);
  waitTimer = null;
  document.getElementById("wait").hidden = true;
  const fisheryBox = document.getElementById("fishery");
  const provinceBox = document.getElementById("province");
  if (fisheryBox) fisheryBox.disabled = false;
  if (provinceBox) provinceBox.disabled = false;
}
let fishery = "";
let accessRequest = 0;
let activeWater = null;
let selection = null;
let searchTimer = null;
let speciesRequest = 0;
let tackleRequest = 0;
let fishView = null;
let setupPick = null;
let setupTitle = "";
let layerPick = "";
let methodPick = "";
let nightSurface = false;
const clock = { all: true, start: "", end: "", chosen: false };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(typeof detail === "string" ? detail : "İstek başarısız.");
  }
  return payload;
}

function render(html) {
  body.innerHTML = html;
}

function idle() {
  render(`
    <section class="mod">
      <h2>Nasıl bakılır</h2>
      <p class="warn">Balıkçılık seçimi zorunlu. Kıyı veya açık seçilmeden il listesi gelmez.</p>
      <p class="fine">Kıyı ve ili seç, listeden bir suya dokun. Atış alanı kıyı şeridi olarak kendiliğinden gelir. Nokta seçmek gerekmez. Harita uydu görüntüsüdür; ağaç, kayalık ve sahil orada durur.</p>
    </section>`);
}

function clearPlace() {
  activeWater = null;
  selection = null;
  drawn.clearLayers();
  landLayer.clearLayers();
  if (marker) {
    marker.remove();
    marker = null;
  }
  if (approach) {
    approach.remove();
    approach = null;
  }
  if (shoreLayer) {
    shoreLayer.remove();
    shoreLayer = null;
  }
}

function provinceBackButton() {
  if (!activeProvince) return "";
  return `<button type="button" class="back" id="province-back">${esc(activeProvince)} sularına dön</button>`;
}

idle();

body.addEventListener("click", (event) => {
  if (event.target.closest("#province-back")) {
    renderProvinceList();
    return;
  }
  const place = event.target.closest(".place");
  if (!place) return;
  pick(Number(place.dataset.lat), Number(place.dataset.lon), true, place.dataset.osmType, place.dataset.osmId);
});

const fishModal = document.getElementById("fish-modal");
document.getElementById("fish-modal-close")?.addEventListener("click", closeFish);
fishModal?.addEventListener("click", (event) => {
  if (event.target === fishModal) closeFish();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && fishModal && !fishModal.hidden) closeFish();
});

function renderProvinceList() {
  const data = provinceCache;
  if (!data) return;
  clearPlace();
  const rows = (data.waters || []).map((place) => `
    <button type="button" class="place" data-lat="${place.lat}" data-lon="${place.lon}" data-osm-type="${esc(place.osm_type || "")}" data-osm-id="${esc(place.osm_id || "")}">
      <strong>${esc(place.name)}</strong>
      <span>${esc(place.kind_label)}</span>
    </button>`).join("");
  const empty = rows ? "" : '<p class="status">Bu ilde adlandırılmış göl, baraj, çay, ırmak veya deniz kıyısı dönmedi.</p>';
  const seconds = data.seconds ? `<p class="fine">Liste ${esc(data.seconds)} saniyede geldi.</p>` : "";
  render(`
    <section class="mod">
      <h2>${esc(data.province)}</h2>
      <p class="warn">Bu liste bir balık taraması değildir. Her suda balık vardır denmez. Ayrıntı, seçtiğin su için istenir.</p>
      <p class="fine">${esc(data.note || "")}</p>
      ${seconds}
      <p class="fine">${data.total} su, listede ${data.waters.length} tanesi. ${esc(data.source)}.</p>
    </section>
    <section class="mod">
      <h2>Sular</h2>
      ${rows || empty}
    </section>
  `);
  hint.textContent = data.province;
}

async function showProvince(name) {
  activeProvince = name;
  if (!name) {
    provinceCache = null;
    provinceLayer.clearLayers();
    hint.textContent = "Haritadan bir suya dokun";
    idle();
    return;
  }
  hint.textContent = "Çalışıyor, bekle";
  clearPlace();
  const token = showWait(
    `${name} listesi`,
    `${fisheryLabel() || "Balıkçılık"} ve ${name} seçildi. Su listesi hazırlanıyor. Çalışıyor, bekle.`,
  );
  render(`<section class="mod"><h2>${esc(name)}</h2><p class="status">Çalışıyor. Liste gelene kadar bekle.</p></section>`);
  let data;
  const started = performance.now();
  try {
    data = await api(`/api/province-waters?name=${encodeURIComponent(name)}`);
  } catch (error) {
    hideWait(token);
    render(`<p class="status error">${esc(error.message)}</p>`);
    hint.textContent = "Liste alınamadı";
    return;
  }
  if (activeProvince !== name) {
    hideWait(token);
    return;
  }
  data.seconds = ((performance.now() - started) / 1000).toFixed(1);
  provinceCache = data;
  provinceLayer.clearLayers();
  if (data.geometry) {
    const shape = L.geoJSON(data.geometry, {
      style: { color: "#d7c4a3", weight: 2, fillColor: "#1f8a62", fillOpacity: 0.08 },
    }).addTo(provinceLayer);
    const bounds = shape.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.04));
  } else if (data.bounds) {
    const box = L.latLngBounds(
      [data.bounds.south, data.bounds.west],
      [data.bounds.north, data.bounds.east],
    );
    L.rectangle(box, { color: "#d7c4a3", weight: 2, fillOpacity: 0.05 }).addTo(provinceLayer);
    map.fitBounds(box.pad(0.04));
  }
  for (const place of data.waters || []) {
    const spot = L.circleMarker([place.lat, place.lon], {
      radius: 7,
      color: "#f4f1ea",
      weight: 2,
      fillColor: "#0f6a45",
      fillOpacity: 0.95,
    }).addTo(provinceLayer);
    spot.bindTooltip(`${place.name} · ${place.kind_label}`);
    spot.on("click", (event) => {
      L.DomEvent.stopPropagation(event);
      pick(place.lat, place.lon, true, place.osm_type || "", place.osm_id || "");
    });
  }
  renderProvinceList();
  map.invalidateSize();
  hideWait(token);
}

const provinceSelect = document.getElementById("province");
api("/api/provinces").then((payload) => {
  for (const name of payload.provinces || []) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    provinceSelect.appendChild(option);
  }
}).catch(() => {
  hint.textContent = "İl listesi alınamadı";
});
provinceSelect.addEventListener("change", () => {
  const name = provinceSelect.value;
  activeProvince = name;
  if (!name) {
    showProvince("");
    return;
  }
  if (!fisheryMode()) {
    provinceCache = null;
    provinceLayer.clearLayers();
    clearPlace();
    hint.textContent = "Kıyı veya açık seç";
    render(`
      <section class="mod">
        <h2>Zorunlu seçim</h2>
        <p class="warn">Balıkçılık seçimi zorunlu. Kıyı veya açık seçilmeden ${esc(name)} listesi istenmez.</p>
      </section>`);
    return;
  }
  showProvince(name);
});

const fisherySelect = document.getElementById("fishery");
fisherySelect.addEventListener("change", () => {
  fishery = fisherySelect.value;
  document.getElementById("fishery-label").classList.toggle("needed", !fishery);
  syncGate();
  hint.textContent = fisheryLabel() || "Kıyı veya açık seç";
  if (fishery && provinceSelect.value && !provinceCache) {
    showProvince(provinceSelect.value);
    return;
  }
  if (activeWater) {
    activeWater.cell = null;
    loadSpecies(activeWater, "");
  }
});

map.on("click", (event) => {
  if (!fisheryMode()) return;
  if (activeWater && holdsActiveWater(event.latlng.lat, event.latlng.lng)) {
    chooseCast(activeWater, event.latlng.lat, event.latlng.lng);
    return;
  }
  pick(event.latlng.lat, event.latlng.lng);
});

async function pick(lat, lon, focus = false, osmType = "", osmId = "") {
  selection = null;
  layerPick = "";
  methodPick = "";
  clock.all = true;
  clock.chosen = false;
  hint.textContent = "Çalışıyor, bekle";
  const fromList = Boolean(osmType && osmId);
  const token = showWait(
    "Kıyı şeridi",
    "Seçilen su hazırlanıyor. Atış alanı gelene kadar bekle.",
  );
  if (focus && !fromList) {
    const zoom = map.getZoom() < 14 ? 14 : map.getZoom();
    map.flyTo([lat, lon], zoom, { duration: 0.6 });
  }
  if (marker) marker.remove();
  marker = null;
  if (approach) approach.remove();
  approach = null;
  shoreLayer = null;
  drawn.clearLayers();
  landLayer.clearLayers();
  if (!fromList) {
    marker = L.circleMarker([lat, lon], {
      radius: 8,
      color: "#f4f1ea",
      weight: 2,
      fillColor: "#0f6a45",
      fillOpacity: 1,
    }).addTo(map);
  }
  render('<section class="mod"><p class="status">Seçilen suyun kıyı şeridi isteniyor. Ayrı bir nokta seçmek gerekmez.</p></section>');
  let water;
  const started = performance.now();
  const params = new URLSearchParams({ lat: String(lat), lon: String(lon) });
  if (osmType && osmId) {
    params.set("osm_type", String(osmType));
    params.set("osm_id", String(osmId));
  }
  try {
    water = await api(`/api/water?${params.toString()}`);
  } catch (error) {
    hideWait(token);
    hint.textContent = "Su alınamadı";
    render(`${provinceBackButton()}<p class="status error">${esc(error.message)}</p>`);
    return;
  }
  water.seconds = ((performance.now() - started) / 1000).toFixed(1);
  if (!water.found) {
    hideWait(token);
    hint.textContent = "Su yok";
    render(`${provinceBackButton()}<p class="status">${esc(water.message)}</p><p class="fine">${esc(water.source)}</p>`);
    return;
  }
  if (marker && Number.isFinite(water.lat) && Number.isFinite(water.lon)) {
    marker.setLatLng([water.lat, water.lon]);
  }
  drawShore(water, focus);
  loadLandcover(water);
  hideWait(token);
  hint.textContent = water.shore_band ? "Kıyı şeridi hazır" : (fisheryLabel() || water.zone_label || water.kind_label);
  activeWater = water;
  await loadSpecies(water, "");
}

function accessHtml(access) {
  if (!access) return '<p class="status">Otopark ve olta noktası aranıyor…</p>';
  if (access.error) return `<p class="status error">${esc(access.error)}</p>`;
  if (!access.found) return `<p class="status">${esc(access.message || "Yaklaşım yok.")}</p>`;
  const photo = access.photo;
  const photoHtml = photo
    ? `<a href="${esc(photo.page || photo.url)}" target="_blank" rel="noopener">
        <img class="spot-photo" src="${esc(photo.url)}" alt="${esc(photo.label || "Yer")}">
      </a>
      <h3>${esc(photo.label || "Yer görüntüsü")}</h3>
      <p class="fine">${esc(photo.title || "")} · ${esc(photo.source || "")}</p>`
    : `<p class="fine">Bu olta noktasının yanında etiketli yer fotoğrafı yok.</p>`;
  const steps = (access.steps || []).map((step, index) => `
    <li>
      <b>${index + 1}</b>
      <div>
        <strong>${esc(step.title)}${step.place ? " · " + esc(step.place) : ""}</strong>
        <span>${esc(step.text || "")}</span>
      </div>
    </li>`).join("");
  return `
    <section class="access">
      ${photoHtml}
      <ol class="steps">${steps}</ol>
      <p class="fine">${esc(access.note || "")}</p>
    </section>`;
}

function refreshAccessSlot() {
  const slot = document.getElementById("access-slot");
  if (!slot || !activeWater) return;
  slot.innerHTML = accessHtml(activeWater.access);
}

async function loadAccess(water) {
  const request = ++accessRequest;
  water.access = null;
  try {
    const response = await fetch("/api/access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        lat: water.lat,
        lon: water.lon,
        geometry: water.geometry || water.harbour_geometry || null,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail;
      throw new Error(typeof detail === "string" ? detail : "İstek başarısız.");
    }
    water.access = payload;
  } catch (error) {
    water.access = { found: false, error: error.message };
  }
  if (request !== accessRequest || activeWater !== water) return;
  refreshAccessSlot();
}

function drawShore(water, focus) {
  const outline = water.geometry || (water.zone === "harbor" ? water.harbour_geometry : null);
  const onCast = (event) => {
    L.DomEvent.stop(event);
    chooseCast(water, event.latlng.lat, event.latlng.lng);
  };
  if (outline) {
    const layer = L.geoJSON(outline, {
      style: { color: "#f7f3ea", weight: 3, fillOpacity: 0 },
    }).addTo(drawn);
    layer.on("click", onCast);
    const bounds = layer.getBounds();
    if (focus && bounds.isValid()) map.fitBounds(bounds.pad(0.08), { maxZoom: 14 });
  }
  if (water.shore_band) {
    const band = L.geoJSON(water.shore_band, {
      style: { color: "#fff4e5", weight: 1.5, fillColor: "#c9842a", fillOpacity: 0.55 },
    }).addTo(drawn);
    band.on("click", onCast);
    band.bindTooltip(`Kıyıdan ${water.shore_cast_m || 90} m. Buraya tıkla, bu noktanın balığı gelsin`);
    if (focus) {
      const bounds = band.getBounds();
      if (bounds.isValid()) map.fitBounds(bounds.pad(0.12), { maxZoom: 15 });
    }
  }
}

function metersBetween(lat, lon, lat2, lon2) {
  const scale = 111320 * Math.cos(((lat + lat2) / 2) * Math.PI / 180);
  return Math.hypot((lon2 - lon) * scale, (lat2 - lat) * 110540);
}

function segmentMeters(lat, lon, lat1, lon1, lat2, lon2) {
  const scale = 111320 * Math.cos(lat * Math.PI / 180);
  const x1 = (lon1 - lon) * scale;
  const y1 = (lat1 - lat) * 110540;
  const x2 = (lon2 - lon) * scale;
  const y2 = (lat2 - lat) * 110540;
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (dx === 0 && dy === 0) return Math.hypot(x1, y1);
  const t = Math.max(0, Math.min(1, -((x1 * dx) + (y1 * dy)) / ((dx * dx) + (dy * dy))));
  return Math.hypot(x1 + (t * dx), y1 + (t * dy));
}

function shoreRings(geometry) {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return geometry.coordinates || [];
  if (geometry.type === "MultiPolygon") return (geometry.coordinates || []).flat();
  return [];
}

function distanceToShore(lat, lon, geometry) {
  let best = null;
  for (const ring of shoreRings(geometry)) {
    for (let index = 0; index < ring.length - 1; index += 1) {
      const distance = segmentMeters(lat, lon, ring[index][1], ring[index][0], ring[index + 1][1], ring[index + 1][0]);
      if (best == null || distance < best) best = distance;
    }
  }
  return best == null ? null : Math.round(best);
}

function pointInRing(lon, lat, ring) {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const [x1, y1] = ring[previous];
    const [x2, y2] = ring[index];
    if ((y1 > lat) === (y2 > lat)) continue;
    const cross = ((x2 - x1) * (lat - y1)) / ((y2 - y1) || 1e-12) + x1;
    if (lon < cross) inside = !inside;
  }
  return inside;
}

function holdsActiveWater(lat, lon) {
  const shape = activeWater?.geometry || activeWater?.harbour_geometry;
  if (!shape) return false;
  const rings = shoreRings(shape).filter((ring) => ring.length >= 4);
  if (rings.some((ring) => pointInRing(lon, lat, ring))) return true;
  const shore = distanceToShore(lat, lon, shape);
  return shore != null && shore <= (activeWater.shore_cast_m || 90) + 30;
}

function chooseCast(water, lat, lon) {
  const shape = water.geometry || water.harbour_geometry;
  const shoreM = distanceToShore(lat, lon, shape);
  water.cast = { lat, lon, shoreM };
  if (marker) marker.remove();
  marker = L.circleMarker([lat, lon], {
    radius: 8,
    color: "#fff4e5",
    weight: 2,
    fillColor: "#14352a",
    fillOpacity: 1,
  }).addTo(drawn);
  marker.bindTooltip(shoreM == null ? "Seçilen atış" : `Kıyıdan ${shoreM} m`);
  hint.textContent = shoreM == null ? "Atış seçildi" : `Kıyıdan ${shoreM} m`;
  loadSpecies(water, document.getElementById("fish-search")?.value || "");
}

function castAdvice(fish, water) {
  if (!water.cast) return "";
  const maxM = water.shore_cast_m || 90;
  const shoreM = water.cast.shoreM;
  const place = shoreM == null ? "seçtiğin yer" : `kıyıdan ${shoreM} m`;
  const layer = fish.layer_label || "";
  const bottom = /dip|dibi|bentik/i.test(layer);
  const surface = /yüzey|pelajik|kıyı üstü/i.test(layer);
  let where;
  if (nightSurface && surface) {
    where = `Gece bu balık üst suda, liman ışığının hemen altında durur. Şamandıra, üçlü kanca ve hamsi parçası yemi ${place} noktasında yüzeyde tutar. Şerit en fazla ${maxM} m.`;
  } else if (bottom) where = `Dip türü. Yemi ${place} noktasında, şeridin dışına doğru ve en fazla ${maxM} m içinde dibe bırak.`;
  else if (surface) where = `Üst su türü. Yemi ${place} noktasında, kıyıya daha yakın ve yüzeyde tut. Şerit en fazla ${maxM} m.`;
  else if (nightSurface) where = `Gece kaydı olan tür. Dip balığı bu saatte dipte kalır; şamandıra takımı oraya inmez. Yem ${place} noktasında durur.`;
  else where = `Orta su. Yem ${place} noktasında durur. Şerit en fazla ${maxM} m.`;
  const shallow = fish.depth_shallow_m;
  const deep = fish.depth_deep_m;
  const depth = shallow == null && deep == null
    ? "Bu türün FishBase derinlik kaydı yok. Seçilen noktanın tabanı ölçülmedi."
    : `FishBase derinlik kaydı ${shallow ?? "?"}–${deep ?? "?"} m. Bu türün yaşam aralığıdır. Seçilen noktanın taban ölçümü değildir.`;
  return `${where} ${depth}`;
}

const COVER_STYLE = {
  tree: { color: "#d8ffe4", weight: 1.5, fillColor: "#1f8a45", fillOpacity: 0.38 },
  beach: { color: "#fff4d2", weight: 1.5, fillColor: "#e2c27a", fillOpacity: 0.5 },
  rock: { color: "#f4f1ea", weight: 1.5, fillColor: "#6e675f", fillOpacity: 0.48 },
  wet: { color: "#d5fff8", weight: 1.5, fillColor: "#2f7d86", fillOpacity: 0.4 },
  scrub: { color: "#e7f5c8", weight: 1.5, fillColor: "#7d9144", fillOpacity: 0.38 },
};

async function loadLandcover(water) {
  const request = ++landRequest;
  landLayer.clearLayers();
  const shape = water.geometry || water.harbour_geometry;
  if (!shape) return;
  const bounds = L.geoJSON(shape).getBounds();
  if (!bounds.isValid()) return;
  const pad = 0.004;
  const params = new URLSearchParams({
    south: String(bounds.getSouth() - pad),
    west: String(bounds.getWest() - pad),
    north: String(bounds.getNorth() + pad),
    east: String(bounds.getEast() + pad),
  });
  let cover;
  try {
    cover = await api(`/api/landcover?${params.toString()}`);
  } catch {
    return;
  }
  if (request !== landRequest || !cover?.features) return;
  L.geoJSON(cover, {
    style: (feature) => COVER_STYLE[feature.properties?.kind] || COVER_STYLE.scrub,
    onEachFeature: (feature, layer) => {
      const label = feature.properties?.label;
      if (label) layer.bindTooltip(label);
    },
  }).addTo(landLayer);
  if (drawn.bringToFront) drawn.bringToFront();
  water.landNote = cover.note || "";
  const note = document.getElementById("land-note");
  if (note) note.textContent = water.landNote;
}

function syncGate() {
  document.querySelector(".app")?.classList.toggle("needs-choice", !fisheryMode());
}

function fisheryMode() {
  return document.getElementById("fishery")?.value || "";
}

function fisheryLabel() {
  if (fisheryMode() === "shore") return "Kıyı balıkçılığı";
  if (fisheryMode() === "open") return "Açık balıkçılık";
  return "";
}

function cellsForMode(water) {
  const mode = fisheryMode();
  return (water?.cast_cells?.features || []).filter((feature) => {
    const zone = feature.properties?.zone;
    if (mode === "open") return zone === "open";
    if (mode === "shore") return zone === "harbor" || zone === "shore";
    return false;
  });
}

function drawCells(water) {
  if (shoreLayer) {
    shoreLayer.remove();
    shoreLayer = null;
  }
  const features = cellsForMode(water);
  if (!features.length) return;
  const selected = water.cell?.id;
  shoreLayer = L.geoJSON(
    { type: "FeatureCollection", features },
    {
      style: (feature) => {
        const on = feature.properties.id === selected;
        return {
          color: on ? "#1c2416" : "#c9842a",
          weight: on ? 3 : 1.5,
          fillColor: "#c9842a",
          fillOpacity: on ? 0.78 : 0.42,
        };
      },
      onEachFeature: (feature, layer) => {
        layer.bindTooltip(`${feature.properties.label}. Atış karesi`);
        layer.on("click", (event) => {
          L.DomEvent.stopPropagation(event);
          water.cell = feature.properties;
          layerPick = "";
          methodPick = "";
          clock.all = true;
          if (marker) marker.setLatLng([feature.properties.lat, feature.properties.lon]);
          drawCells(water);
          loadSpecies(water, "");
        });
      },
    },
  ).addTo(drawn);
}

async function loadSpecies(water, query) {
  const token = ++speciesRequest;
  const searching = Boolean(document.getElementById("fish-search"));
  const mode = fisheryMode();
  if (!mode) {
    if (!searching) {
      render(waterHtml(water) + '<p class="status">Balık listesi için önce kıyı veya açık balıkçılığını seç. Seçim, ilin yanında.</p>');
    }
    return;
  }
  if (!searching) {
    render(waterHtml(water) + '<p class="status">Balık listesi hazırlanıyor…</p>');
  }
  const spot = water.cast || water.cell || water;
  const zone = water.kind === "freshwater" ? "" : (water.cell?.zone || water.zone || mode);
  const params = new URLSearchParams({
    lat: String(spot.lat),
    lon: String(spot.lon),
    kind: water.kind,
  });
  if (zone) params.set("zone", zone);
  if (clock.chosen && clock.start && clock.end) {
    if (!water.conditions && !water.conditionsError) {
      try {
        const marine = water.kind !== "freshwater";
        water.conditions = await api(`/api/conditions?lat=${spot.lat}&lon=${spot.lon}&marine=${marine ? "true" : "false"}`);
      } catch (error) {
        water.conditionsError = error.message;
      }
    }
    const sun = water.conditions?.sun || {};
    params.set("start", clock.start);
    params.set("end", clock.end);
    if (sun.sunrise) params.set("sunrise", sun.sunrise);
    if (sun.sunset) params.set("sunset", sun.sunset);
    if (sun.sunrise_next) params.set("sunrise_next", sun.sunrise_next);
    if (!clock.all) params.set("hour_only", "true");
  }
  if (layerPick) params.set("layer", layerPick);
  if (methodPick) params.set("method", methodPick);
  if (query && query.trim()) params.set("q", query.trim());
  let species;
  try {
    species = await api(`/api/species?${params.toString()}`);
  } catch (error) {
    if (token !== speciesRequest) return;
    render(waterHtml(water) + `<p class="status error">${esc(error.message)}</p>`);
    return;
  }
  if (token !== speciesRequest) return;
  species.query = query || "";
  paintSpecies(water, species);
  if (searching) {
    const search = document.getElementById("fish-search");
    search.focus();
    const end = search.value.length;
    search.setSelectionRange(end, end);
  }
}

function castHtml(water) {
  const maxM = water.shore_cast_m || 90;
  if (!water.cast) {
    return `<p class="fine">Turuncu alandan bir yere tıkla. Atış, seçili ${esc(water.water_label || "su")} içinde kalır. Kıyıdan metre, balık ve takım o nokta için yazılır.</p>`;
  }
  const shore = water.cast.shoreM == null ? "kıyı mesafesi hesaplanamadı" : `kıyıdan ${water.cast.shoreM} metre`;
  return `<p class="fine">Seçilen atış bu suyun içinde, ${shore}. Şerit en fazla ${maxM} metre. Saat ve katman süzgeci bu listeyi düzenler. Noktanın taban derinliği ölçülmedi. Metre kaydı, balığın FishBase aralığıdır.</p>`;
}

function waterHtml(water) {
  const klass = water.kind === "saltwater" ? "salt" : water.kind === "brackish" ? "brack" : "";
  const title = water.name || water.water_label || "Su";
  const alt = water.alt_name ? `<p class="fine">Diğer ad: ${esc(water.alt_name)}</p>` : "";
  return `
    <article class="water-card">
      ${provinceBackButton()}
      <h2>${esc(title)}</h2>
      ${alt}
      <div class="meta">
        <span class="pill ${klass}">${esc(water.kind_label)}</span>
        <span class="pill quiet">${esc(water.water_label)}</span>
        ${water.zone_label ? `<span class="pill">${esc(water.zone_label)}</span>` : ""}
      </div>
      ${water.zone_note ? `<p class="fine">${esc(water.zone_note)}</p>` : ""}
      <p class="warn">Turuncu alan bu suyun kıyısıdır. Oraya tıklayınca yeni bir yer aranmaz. Seçtiğin noktanın kıyıdan metresi, balıkları ve takımı yazılır. Saat süzgeci aynı listeyi düzenler.</p>
      ${castHtml(water)}
      <ul class="legend">
        <li><i class="swatch cast"></i> Olta alanı</li>
        <li><i class="swatch tree"></i> Ağaç</li>
        <li><i class="swatch rock"></i> Kayalık</li>
        <li><i class="swatch beach"></i> Sahil</li>
      </ul>
      <p class="fine" id="land-note"></p>
      ${water.seconds ? `<p class="fine">Yer kaydı ${esc(water.seconds)} saniyede geldi.</p>` : ""}
      <p class="source">${esc(water.source)}. ${esc(water.attribution || "")}</p>
    </article>`;
}

function paintSpecies(water, payload) {
  nightSurface = Boolean(payload.night_surface);
  const gbif = payload.gbif || {};
  let gbifText;
  if (!gbif.ok) {
    gbifText = gbif.message || "GBIF gözlemleri alınamadı.";
  } else if (!gbif.count) {
    gbifText = "Bu yerin yakınında GBIF balık gözlemi yok. Liste, FishBase'in Türkiye ve bu su tipi kaydıdır.";
  } else {
    gbifText = `GBIF bu yerin yakınında ${gbif.count} kemikli balık kaydı saydı. Eşleşen türler öne alındı.`;
  }
  const cards = (payload.species || []).map((fish) => {
    const title = fish.turkish || fish.english || fish.scientific;
    const badge = fish.observed_nearby ? '<span class="pill observe">Yakında gözlemlendi</span>' : "";
    return `
      <button class="card" type="button" data-scientific="${esc(fish.scientific)}">
        <strong>${esc(title)}</strong>
        <em>${esc(fish.scientific)}</em>
        <span class="tags">
          <span class="pill quiet">${esc(fish.layer_label || "Katman kaydı yok")}</span>
          ${fish.zone_fit === false ? `<em>${esc(fish.zone_reason || "Bu zona uymaz")}</em>` : ""}
          ${badge}
          ${fish.hour_favorite && !clock.all ? '<span class="pill observe">Bu saatte favori</span>' : ""}
          ${clock.all && fish.place_favorite ? '<span class="pill observe">Favori</span>' : ""}
          ${fish.circadian_label ? `<span class="pill quiet">${esc(fish.circadian_label)}</span>` : ""}
        </span>
        ${water.cast ? `<span class="cast-line">${esc(castAdvice(fish, water))}</span>` : ""}
      </button>`;
  }).join("");
  const empty = payload.species?.length
    ? ""
    : '<p class="status">Bu süzgeçte FishBase kaydı yok.</p>';
  const cellLine = water.cell
    ? `<p class="fine">Seçilen kare: ${esc(water.cell.label)}. Liste bu yerin kaydı.</p>`
    : "";
  render(`
    ${waterHtml(water)}
    <section class="mod">
      <h2>Bu yerin balıkları</h2>
      <p class="fine">${esc(payload.source)}. Gösterilen ${payload.shown} / ${payload.total} tür.</p>
      ${payload.zone_note ? `<p class="fine">${esc(payload.zone_note)}</p>` : ""}
      <p class="fine">${esc(gbifText)}</p>
      <input id="fish-search" class="search" type="search" placeholder="Tür ara, örneğin turna" value="${esc(payload.query || "")}" enterkeyhint="search">
      ${hourHtml(payload)}
      ${layerHtml(payload)}
      ${cellLine}
      ${payload.hour_note ? `<p class="fine">${esc(payload.hour_note)}</p>` : ""}
      ${payload.method_note ? `<p class="fine">${esc(payload.method_note)}</p>` : ""}
      <div class="cards">${cards}</div>
      ${empty}
    </section>
  `);
  const search = document.getElementById("fish-search");
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const value = search.value;
    searchTimer = setTimeout(() => loadSpecies(water, value), 350);
  });
  bindHours(water);
  bindLayers(water);
  body.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", () => {
      const scientific = card.getAttribute("data-scientific");
      const fish = payload.species.find((item) => item.scientific === scientific);
      body.querySelectorAll(".card").forEach((node) => node.classList.remove("selected"));
      card.classList.add("selected");
      openFish(water, fish);
    });
  });
}

function hourHtml() {
  if (!clock.start || !clock.end) {
    const now = new Date();
    const hour = now.getHours();
    clock.start = `${String(hour).padStart(2, "0")}:00`;
    clock.end = `${String((hour + 2) % 24).padStart(2, "0")}:00`;
  }
  return `
    <div class="drops stack">
      <label>Saat
        <select id="hour-mode">
          <option value="all"${clock.all ? " selected" : ""}>Tüm saatler</option>
          <option value="hour"${clock.all ? "" : " selected"}>Bu saat aralığı</option>
        </select>
      </label>
      <label>Başlangıç
        <input id="list-start" type="time" value="${esc(clock.start)}">
      </label>
      <label>Bitiş
        <input id="list-end" type="time" value="${esc(clock.end)}">
      </label>
    </div>`;
}

function layerHtml(payload) {
  const layers = payload?.facets?.layers || [];
  const methods = payload?.facets?.methods || [];
  const layerOptions = layers.map((item) => `
    <option value="${esc(item.label)}"${layerPick === item.label ? " selected" : ""}>${esc(item.label)} (${item.count})</option>
  `).join("");
  const methodOptions = methods.map((item) => `
    <option value="${esc(item.id)}"${methodPick === item.id ? " selected" : ""}>${esc(item.label)} (${item.count})</option>
  `).join("");
  return `
    <div class="drops stack">
      <label>Katman
        <select id="layer-pick">
          <option value=""${layerPick ? "" : " selected"}>Tümü</option>
          ${layerOptions}
        </select>
      </label>
      <label>Takım
        <select id="method-pick">
          <option value=""${methodPick ? "" : " selected"}>Tümü</option>
          ${methodOptions}
        </select>
      </label>
    </div>`;
}

function bindLayers(water) {
  const searchValue = () => document.getElementById("fish-search")?.value || "";
  document.getElementById("layer-pick")?.addEventListener("change", (event) => {
    layerPick = event.target.value || "";
    loadSpecies(water, searchValue());
  });
  document.getElementById("method-pick")?.addEventListener("change", (event) => {
    methodPick = event.target.value || "";
    loadSpecies(water, searchValue());
  });
}

function bindHours(water) {
  const mode = document.getElementById("hour-mode");
  const start = document.getElementById("list-start");
  const end = document.getElementById("list-end");
  const searchValue = () => document.getElementById("fish-search")?.value || "";
  mode?.addEventListener("change", () => {
    clock.all = mode.value !== "hour";
    clock.chosen = !clock.all;
    layerPick = "";
    loadSpecies(water, searchValue());
  });
  const onTime = () => {
    clock.start = start.value || clock.start;
    clock.end = end.value || clock.end;
    if (!clock.start || !clock.end) return;
    if (!clock.all) loadSpecies(water, searchValue());
  };
  start?.addEventListener("change", onTime);
  end?.addEventListener("change", onTime);
}

function ensureClock(conditions) {
  if (clock.start && clock.end) return;
  const match = String(conditions?.current?.time || "").match(/T(\d{2}):/);
  const hour = match ? Number(match[1]) : 20;
  const endHour = (hour + 2) % 24;
  clock.start = `${String(hour).padStart(2, "0")}:00`;
  clock.end = `${String(endHour).padStart(2, "0")}:00`;
}

function hourSample(conditions, hhmm) {
  const hours = conditions?.hours || [];
  const now = String(conditions?.current?.time || "");
  const matches = hours.filter((item) => String(item.time || "").slice(11, 16) === hhmm);
  if (!matches.length) return null;
  return matches.find((item) => String(item.time) >= now) || matches[matches.length - 1];
}

function shiftStamp(stamp, hoursBack) {
  const match = String(stamp).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]));
  date.setHours(date.getHours() - hoursBack);
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function pressureWindow(conditions, sample) {
  if (!sample?.time || sample.pressure_hpa == null) return {};
  const earlierStamp = shiftStamp(sample.time, 6);
  const earlier = (conditions?.hours || []).find((item) => String(item.time || "").startsWith(earlierStamp || "\0"));
  if (!earlier || earlier.pressure_hpa == null) return {};
  const delta = sample.pressure_hpa - earlier.pressure_hpa;
  let trend = "rising";
  if (Math.abs(delta) <= 1.5) trend = "stable";
  else if (delta < 0) trend = "falling";
  return { pressure_trend: trend, pressure_delta_hpa: delta };
}

function placeText(fish, water) {
  const layer = fish.layer_label || "Su katmanı kaydı yok";
  const shallow = fish.depth_shallow_m;
  const deep = fish.depth_deep_m;
  const depth = shallow == null && deep == null ? "" : `, ${shallow ?? "?"}–${deep ?? "?"} m`;
  let rhythm = "FishBase'te bu tür için gece veya gündüz aktivite kaydı yok. Saatlik yüzey veya dip çizelgesi de yok.";
  if (fish.circadian_label) {
    rhythm = `FishBase sirkadiyen kaydı: ${fish.circadian_label}.`;
    if (fish.circadian_remark) rhythm += ` ${fish.circadian_remark}`;
  }
  const cast = water?.cast ? ` ${castAdvice(fish, water)}` : "";
  return `Kayıtlı yer: ${layer}${depth}. Bu, FishBase'in genel yaşam katmanıdır. ${rhythm}${cast}`;
}

function closeFish() {
  const modal = document.getElementById("fish-modal");
  if (!modal) return;
  modal.hidden = true;
  selection = null;
  document.querySelectorAll(".card.selected").forEach((node) => node.classList.remove("selected"));
}

function openModal() {
  const modal = document.getElementById("fish-modal");
  if (!modal) return;
  modal.hidden = false;
  const panel = modal.querySelector(".modal-panel");
  if (panel) panel.scrollTop = 0;
}

async function openFish(water, fish) {
  const detail = document.getElementById("fish-modal-body");
  const mine = fish.scientific;
  selection = mine;
  setupPick = null;
  setupTitle = "";
  openModal();
  let conditions = water.conditions || null;
  let conditionsError = water.conditionsError || null;
  ensureClock(conditions);
  fishView = { water, fish, conditions, conditionsError };
  detail.innerHTML = detailHtml(fish, conditions, conditionsError, { found: false, message: "Fotoğraf yükleniyor…" }, water);
  bindClock();
  refreshTackle();
  const marine = water.kind !== "freshwater";
  const spotLat = water.cast?.lat || water.lat;
  const spotLon = water.cast?.lon || water.lon;
  const weatherJob = conditions || conditionsError
    ? Promise.resolve()
    : api(`/api/conditions?lat=${spotLat}&lon=${spotLon}&marine=${marine ? "true" : "false"}`)
      .then((payload) => {
        conditions = payload;
        water.conditions = payload;
      })
      .catch((error) => {
        conditionsError = error.message;
        water.conditionsError = error.message;
      });
  const photoJob = api(`/api/photo?scientific=${encodeURIComponent(mine)}`)
    .catch(() => ({ found: false, message: "Fotoğraf isteği başarısız." }));
  const [, photo] = await Promise.all([weatherJob, photoJob]);
  if (selection !== mine) return;
  ensureClock(conditions);
  fishView = { water, fish, conditions, conditionsError };
  detail.innerHTML = detailHtml(fish, conditions, conditionsError, photo, water);
  bindClock();
  refreshTackle();
}

function bindClock() {
  const start = document.getElementById("time-start");
  const end = document.getElementById("time-end");
  if (!start || !end) return;
  const onChange = () => {
    clock.start = start.value || clock.start;
    clock.end = end.value || clock.end;
    refreshTackle();
  };
  start.addEventListener("change", onChange);
  end.addEventListener("change", onChange);
}

async function refreshTackle() {
  const view = fishView;
  const slot = document.getElementById("tackle-slot");
  if (!view || !slot || selection !== view.fish.scientific) return;
  const request = ++tackleRequest;
  slot.innerHTML = '<p class="status">Takım bu saate göre hazırlanıyor…</p>';
  const sample = hourSample(view.conditions, clock.start) || view.conditions?.current || {};
  const trend = pressureWindow(view.conditions, sample);
  const marineBlock = view.conditions?.marine;
  const sun = view.conditions?.sun || {};
  const moon = view.conditions?.moon || {};
  const params = new URLSearchParams({
    scientific: view.fish.scientific,
    kind: view.water.kind,
  });
  if (sample.cloud_cover != null) params.set("cloud_cover", String(sample.cloud_cover));
  if (sample.wind_speed_kmh != null) params.set("wind_speed_kmh", String(sample.wind_speed_kmh));
  if (trend.pressure_trend) params.set("pressure_trend", trend.pressure_trend);
  if (trend.pressure_delta_hpa != null) params.set("pressure_delta_hpa", String(trend.pressure_delta_hpa));
  if (marineBlock?.available && marineBlock.wave_height_m != null) {
    params.set("wave_height_m", String(marineBlock.wave_height_m));
  }
  if (clock.start) params.set("start", clock.start);
  if (clock.end) params.set("end", clock.end);
  if (sun.sunrise) params.set("sunrise", sun.sunrise);
  if (sun.sunset) params.set("sunset", sun.sunset);
  if (sun.sunrise_next) params.set("sunrise_next", sun.sunrise_next);
  if (moon.phase != null) params.set("moon_phase", String(moon.phase));
  if (methodPick) params.set("method", methodPick);
  const zone = view.water.cell?.zone || view.water.zone;
  if (zone) params.set("zone", zone);
  let tackle;
  let tackleError = null;
  try {
    tackle = await api(`/api/tackle?${params.toString()}`);
  } catch (error) {
    tackleError = error.message;
  }
  if (request !== tackleRequest || selection !== view.fish.scientific) return;
  const waveNote = marineBlock?.available && sample.time && sample.time !== view.conditions?.current?.time
    ? "Dalga yüksekliği şu anki deniz ölçümüdür."
    : "";
  paintTackle(slot, tackleError ? null : tackle, sample, waveNote, tackleError);
}

function paintTackle(slot, tackle, sample, waveNote, tackleError) {
  if (tackleError) {
    slot.innerHTML = `<p class="status error">${esc(tackleError)}</p>`;
    return;
  }
  slot.innerHTML = tackleHtml(tackle, sample, waveNote);
  slot.querySelectorAll("[data-setup]").forEach((button) => {
    button.addEventListener("click", () => {
      setupTitle = button.getAttribute("data-setup") || "";
      setupPick = setupTitle;
      paintTackle(slot, tackle, sample, waveNote, null);
    });
  });
}

function detailHtml(fish, conditions, conditionsError, photo, water) {
  const title = fish.turkish || fish.english || fish.scientific;
  const depth = depthText(fish);
  const photoHtml = photo?.found
    ? `<img src="${esc(photo.url)}" alt="${esc(title)}">`
    : `<div class="nophoto">${esc(photo?.message || "Fotoğraf yok")}</div>`;
  const nightLine = fish.circadian === "nocturnal" ? `<p class="fine">FishBase bu türü gece aktif kaydetmiş.</p>` : "";
  const weather = conditions || conditionsError
    ? `${conditionsError ? `<p class="status error">${esc(conditionsError)}</p>` : weatherHtml(conditions)}`
    : `<p class="status">Hava yükleniyor…</p>`;
  return `
    <section class="detail">
      <div class="hero">
        ${photoHtml}
        <div>
          <h2 id="fish-modal-title">${esc(title)}</h2>
          <p class="fine">${esc(fish.scientific)}${fish.english ? " · " + esc(fish.english) : ""}</p>
          <p class="fine">${esc(depth)}</p>
          <p class="fine">${esc(fish.feeding_label || "Beslenme kaydı yok")}</p>
        </div>
      </div>
      ${nightLine}
      <p class="fine">${esc(placeText(fish, water))}</p>
      ${fish.diet_remark ? `<p class="fine">FishBase diyet notu: ${esc(fish.diet_remark)}</p>` : ""}
      <div class="clock">
        <label>Başlangıç<input id="time-start" type="time" value="${esc(clock.start)}"></label>
        <label>Bitiş<input id="time-end" type="time" value="${esc(clock.end)}"></label>
      </div>
      ${weather}
      <div id="tackle-slot"><p class="status">Takım bu saate göre hazırlanıyor…</p></div>
    </section>`;
}

function depthText(fish) {
  const shallow = fish.depth_shallow_m;
  const deep = fish.depth_deep_m;
  const layer = fish.layer_label || "Su katmanı kaydı yok";
  if (shallow == null && deep == null) return layer;
  return `${layer} · ${shallow ?? "?"}–${deep ?? "?"} m`;
}

function weatherHtml(conditions) {
  if (!conditions) return "";
  const current = conditions.current || {};
  const moon = conditions.moon || {};
  const marine = conditions.marine;
  const activity = conditions.activity || {};
  const cells = [
    ["Sıcaklık", current.temperature_c != null ? `${current.temperature_c.toFixed(1)} °C` : "yok"],
    ["Bulut", current.cloud_cover != null ? `%${Math.round(current.cloud_cover)}` : "yok"],
    ["Rüzgar", current.wind_speed_kmh != null ? `${Math.round(current.wind_speed_kmh)} km/sa ${current.wind_label || ""}` : "yok"],
    ["Basınç", current.pressure_hpa != null ? `${current.pressure_hpa.toFixed(0)} hPa` : "yok"],
    ["Ay", moon.name || "yok"],
    ["Gün", conditions.sun?.sunrise ? `${shortTime(conditions.sun.sunrise)}–${shortTime(conditions.sun.sunset)}` : "yok"],
  ];
  if (marine?.available) {
    if (marine.wave_height_m != null) cells.push(["Dalga", `${marine.wave_height_m.toFixed(2)} m`]);
    if (marine.sea_surface_temperature_c != null) cells.push(["Deniz suyu", `${marine.sea_surface_temperature_c.toFixed(1)} °C`]);
    if (marine.sea_level_height_msl_m != null) cells.push(["Su seviyesi", `${marine.sea_level_height_msl_m.toFixed(2)} m`]);
  }
  const boxes = cells.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
  const marineNote = !marine
    ? ""
    : marine.available
      ? ""
      : `<p class="fine">${esc(marine.message || "Deniz verisi yok.")}</p>`;
  const items = (activity.components || []).map((item) =>
    `<li><span>${esc(item.text)}</span><b>${item.points > 0 ? "+" : ""}${esc(item.points)}</b></li>`
  ).join("");
  return `
    <div class="wx">${boxes}</div>
    ${marineNote}
    <div class="score">
      <div class="score-row"><span>${esc(activity.label || "Aktivite")}</span><span>%${esc(activity.score)}</span></div>
      <div class="bar"><span style="width:${Number(activity.score) || 0}%"></span></div>
      <p class="fine">${esc(activity.note || "")}</p>
      <ul class="components">${items}</ul>
    </div>
    <p class="source">${esc(conditions.attribution || "")} · ${esc(current.time || "")}</p>`;
}

function shortTime(value) {
  const text = String(value);
  const match = text.match(/T(\d{2}:\d{2})/);
  return match ? match[1] : text;
}

function forecastLine(sample) {
  if (!sample?.time) return "";
  const bits = [shortTime(sample.time)];
  if (sample.temperature_c != null) bits.push(`${Number(sample.temperature_c).toFixed(1)} °C`);
  if (sample.cloud_cover != null) bits.push(`bulut %${Math.round(sample.cloud_cover)}`);
  if (sample.wind_speed_kmh != null) bits.push(`rüzgar ${Math.round(sample.wind_speed_kmh)} km/sa`);
  return `Seçilen saatin tahmini: ${bits.join(", ")}.`;
}

function measureDrawing(part) {
  const width = esc(part.width_mm);
  const height = esc(part.height_mm);
  return `
    <svg class="measure" viewBox="0 0 168 112" role="img" aria-label="Genişlik ${width} milimetre, yükseklik ${height} milimetre">
      <rect x="36" y="18" width="78" height="42" fill="#f4e2b0" stroke="#14352a" stroke-width="2"/>
      <line x1="36" y1="76" x2="114" y2="76" stroke="#14352a" stroke-width="1.4"/>
      <path d="M36 72v8M114 72v8" stroke="#14352a" stroke-width="1.4"/>
      <text x="75" y="94" text-anchor="middle" fill="#14352a" font-size="12" font-family="Segoe UI, sans-serif">${width} mm</text>
      <text x="75" y="106" text-anchor="middle" fill="#5c6758" font-size="10" font-family="Segoe UI, sans-serif">genişlik</text>
      <line x1="132" y1="18" x2="132" y2="60" stroke="#14352a" stroke-width="1.4"/>
      <path d="M128 18h8M128 60h8" stroke="#14352a" stroke-width="1.4"/>
      <text x="140" y="42" fill="#14352a" font-size="11" font-family="Segoe UI, sans-serif">${height}</text>
      <text x="140" y="54" fill="#5c6758" font-size="10" font-family="Segoe UI, sans-serif">mm</text>
    </svg>`;
}

function tackleHtml(tackle, sample, waveNote) {
  if (!tackle) return "";
  if (!tackle.matched) {
    return `<p class="status">${esc(tackle.message || "Takım kuralı yok.")}</p>`;
  }
  const leadId = tackle.lead?.id || "";
  const parts = (tackle.parts || []).map((part) => `
    <article class="part${part.id === leadId ? " lead" : ""}">
      <img src="${esc(part.image)}" alt="">
      <div>
        <h3>${esc(part.title)}</h3>
        <p>${esc(part.detail)}</p>
      </div>
    </article>`).join("");
  const rows = tackle.setups || [];
  const favorite = rows.find((setup) => setup.favorite);
  if (!setupTitle && favorite) setupTitle = favorite.title;
  const chosen = rows.find((setup) => setup.title === setupTitle) || null;
  const setups = rows.map((setup, index) => `
    <button type="button" class="setup${setup.title === setupTitle ? " on" : ""}" data-setup="${esc(setup.title)}">
      <span>${index + 1}. ${esc(setup.title)}</span>
      ${setup.favorite ? '<span class="pill">Favori</span>' : ""}
    </button>`).join("");
  const pieceHtml = (list) => (list || []).map((part) => `
    <div class="step">
      ${part.gap ? `<p class="gap">${esc(part.gap)}</p>` : ""}
      <article class="part${part.width_mm ? " measured" : ""}">
        ${part.width_mm && part.height_mm ? measureDrawing(part) : `<img src="${esc(part.image)}" alt="">`}
        <div>
          <h3>${esc(part.title)}</h3>
          <p>${esc(part.detail)}</p>
        </div>
      </article>
    </div>`).join("");
  const chosenHtml = chosen
    ? `<div class="parts">${pieceHtml(chosen.pieces && chosen.pieces.length ? chosen.pieces : [])}</div>
      <p class="fine">${esc(chosen.detail)}</p>
      <p class="fine">Santim aralığı bu takımın kurulumudur. Seçilen noktanın ölçülmüş derinliği değildir.</p>`
    : rows.length
      ? `<p class="fine">Bir takıma dokun. Seçtiğinin parçası burada açılır.</p>`
      : `<h2>${esc(tackle.title)}</h2><div class="parts">${parts}</div>`;
  const advice = (tackle.conditions || []).map((line) => `<p class="advice">${esc(line)}</p>`).join("");
  const window = tackle.window || {};
  const forecast = forecastLine(sample);
  const choices = rows.length ? `<h2>Üç takım</h2><div class="setups">${setups}</div>` : "";
  return `
    <div class="nightbox">
      <h2>${esc(window.label || "Saat")}</h2>
      <p>${esc(window.summary || "")}</p>
      ${forecast ? `<p>${esc(forecast)}</p>` : ""}
      ${waveNote ? `<p>${esc(waveNote)}</p>` : ""}
      <p>${esc(tackle.limit || "")}</p>
    </div>
    ${choices}
    ${favorite ? `<p class="fine">Favori, bu saat ve takım süzgecine göre öne alınan düzendir. Av sayısı değildir.</p>` : ""}
    ${chosenHtml}
    ${advice}
    <p class="fine">${esc(tackle.note || "")}</p>`;
}
