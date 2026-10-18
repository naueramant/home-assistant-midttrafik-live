/*
 * Midttrafik Live cards for Home Assistant.
 *   custom:midttrafik-departures-card  – departure board for a stop
 *   custom:midttrafik-map-card         – live map of vehicles and stops
 * Loaded automatically by the midttrafik_live integration.
 */

const ATTRIBUTION = "Data from Midttrafik Live";
const LEAFLET_VERSION = "1.9.4";
const LEAFLET_BASE = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist`;

const TEXT = {
  en: { now: "Now", min: "min", cancelled: "Cancelled", noDepartures: "No upcoming departures", unavailable: "Entity not available", noEntities: "No Midttrafik Live entities found" },
  da: { now: "Nu", min: "min", cancelled: "Aflyst", noDepartures: "Ingen kommende afgange", unavailable: "Enheden er ikke tilgængelig", noEntities: "Ingen Midttrafik Live-enheder fundet" },
};

const t = (hass, key) => (TEXT[(hass?.language || "en").slice(0, 2)] || TEXT.en)[key];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const hhmm = (iso) => {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

const lineBadge = (item, extraClass = "") =>
  `<span class="badge ${extraClass}" style="background:${esc(item.color || "var(--primary-color)")};color:${esc(item.text_color || "#fff")}">${esc(item.line)}</span>`;

const midttrafikEntities = (hass, attr) =>
  Object.keys(hass.states).filter((id) => {
    const a = hass.states[id].attributes;
    return a.attribution === ATTRIBUTION && a[attr] !== undefined;
  });

/* ------------------------------------------------------------------ */
/* Departure board                                                     */
/* ------------------------------------------------------------------ */

class MidttrafikDeparturesCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "midttrafik_live" } } },
        { name: "title", selector: { text: {} } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "max_departures", selector: { number: { min: 1, max: 20, mode: "box" } } },
            { name: "show_scheduled", selector: { boolean: {} } },
          ],
        },
      ],
    };
  }

  static getStubConfig(hass) {
    return { entity: midttrafikEntities(hass, "departures")[0] || "", max_departures: 6 };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please choose an 'Upcoming departures' sensor");
    this._config = { max_departures: 6, show_scheduled: true, ...config };
    this._lastState = undefined;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._config.entity];
    if (state !== this._lastState) {
      this._lastState = state;
      this._render();
    }
  }

  connectedCallback() {
    // Re-render the countdowns every 15 s even when the sensor doesn't change.
    this._timer = setInterval(() => this._render(), 15000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  getCardSize() {
    return 1 + Math.ceil((this._config?.max_departures || 6) * 0.8);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _countdown(dep, now) {
    if (dep.cancelled) return `<span class="cancelled-label">${t(this._hass, "cancelled")}</span>`;
    const mins = Math.floor((new Date(dep.expected) - now) / 60000);
    if (mins <= 0) return `<span class="now">${t(this._hass, "now")}</span>`;
    if (mins < 60) return `${mins}<span class="unit"> ${t(this._hass, "min")}</span>`;
    return hhmm(dep.expected);
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const hass = this._hass;
    const state = hass?.states[this._config.entity];
    let body;
    let title = this._config.title;

    if (!state) {
      body = `<div class="empty">${hass ? t(hass, "unavailable") : ""}</div>`;
    } else {
      title = title ?? state.attributes.stop_name;
      const now = new Date();
      const deps = (state.attributes.departures || [])
        .filter((d) => new Date(d.expected) > now - 60000)
        .slice(0, this._config.max_departures);
      body = deps.length
        ? deps
            .map((d) => {
              const delayed = d.delay_minutes > 0 && !d.cancelled;
              const sched =
                this._config.show_scheduled
                  ? `<div class="sub">${delayed ? `<s>${hhmm(d.scheduled)}</s> ${hhmm(d.expected)} <span class="late">+${d.delay_minutes}</span>` : hhmm(d.scheduled)}</div>`
                  : "";
              return `
                <div class="row ${d.cancelled ? "cancelled" : ""}">
                  ${lineBadge(d)}
                  <div class="dir">
                    <div class="dest">${d.light_rail ? '<ha-icon icon="mdi:tram"></ha-icon>' : ""}${esc(d.direction)}</div>
                    ${sched}
                  </div>
                  <div class="time">
                    ${d.realtime && !d.cancelled ? '<span class="live" title="Realtime"></span>' : ""}
                    ${this._countdown(d, now)}
                  </div>
                </div>`;
            })
            .join("")
        : `<div class="empty">${t(hass, "noDepartures")}</div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 12px 16px 8px; }
        .header { font-size: 1.15em; font-weight: 500; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }
        .header ha-icon { color: var(--state-icon-color, var(--primary-color)); }
        .row { display: flex; align-items: center; gap: 12px; padding: 7px 0; border-top: 1px solid var(--divider-color); }
        .row:first-of-type { border-top: none; }
        .badge { min-width: 38px; padding: 3px 6px; border-radius: 6px; text-align: center; font-weight: 700; font-size: 0.95em; box-sizing: border-box; }
        .dir { flex: 1; min-width: 0; }
        .dest { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .dest ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); vertical-align: -2px; margin-right: 4px; }
        .sub { font-size: 0.8em; color: var(--secondary-text-color); }
        .late { color: var(--error-color, #db4437); font-weight: 600; }
        .time { font-weight: 600; font-size: 1.1em; white-space: nowrap; display: flex; align-items: center; gap: 6px; }
        .unit { font-size: 0.75em; font-weight: 400; }
        .now { color: var(--success-color, #43a047); }
        .live { width: 8px; height: 8px; border-radius: 50%; background: var(--success-color, #43a047); animation: pulse 2s infinite; }
        @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(67,160,71,.6); } 70% { box-shadow: 0 0 0 6px rgba(67,160,71,0); } 100% { box-shadow: 0 0 0 0 rgba(67,160,71,0); } }
        .cancelled .dest, .cancelled .sub { text-decoration: line-through; opacity: .6; }
        .cancelled-label { color: var(--error-color, #db4437); font-size: .85em; }
        .empty { color: var(--secondary-text-color); padding: 8px 0; }
      </style>
      <ha-card>
        ${title ? `<div class="header"><ha-icon icon="mdi:bus-stop"></ha-icon>${esc(title)}</div>` : ""}
        ${body}
      </ha-card>`;
  }
}

/* ------------------------------------------------------------------ */
/* Live map                                                            */
/* ------------------------------------------------------------------ */

let leafletPromise;
const loadLeaflet = () => {
  if (window.L) return Promise.resolve(window.L);
  leafletPromise ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${LEAFLET_BASE}/leaflet.js`;
    script.onload = () => resolve(window.L);
    script.onerror = () => {
      leafletPromise = undefined;
      reject(new Error("Could not load Leaflet"));
    };
    document.head.appendChild(script);
  });
  return leafletPromise;
};

class MidttrafikMapCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        { name: "entities", selector: { entity: { multiple: true, domain: "sensor", integration: "midttrafik_live" } } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "height", selector: { number: { min: 150, max: 1200, unit_of_measurement: "px", mode: "box" } } },
            { name: "zoom", selector: { number: { min: 8, max: 18, mode: "box" } } },
            { name: "show_home", selector: { boolean: {} } },
            { name: "dark_mode", selector: { select: { options: ["auto", "light", "dark"] } } },
          ],
        },
        { name: "tile_url", selector: { text: {} } },
      ],
    };
  }

  static getStubConfig() {
    return { height: 400 };
  }

  setConfig(config) {
    this._config = { height: 400, show_home: true, dark_mode: "auto", ...config };
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <link rel="stylesheet" href="${LEAFLET_BASE}/leaflet.css">
        <style>
          ha-card { overflow: hidden; }
          .header { font-size: 1.15em; font-weight: 500; padding: 12px 16px; }
          #map { width: 100%; z-index: 0; }
          .err { padding: 16px; color: var(--error-color); }
          #map.dark .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(0.9) contrast(0.9); }
          #map.dark { background: #1c1c1c; }
          .leaflet-popup-content-wrapper, .leaflet-popup-tip { background: var(--card-background-color, #fff); color: var(--primary-text-color, #222); }
          .leaflet-container a.leaflet-popup-close-button { color: var(--secondary-text-color, #757575); }
          #map.dark .leaflet-bar a { background: #2b2b2b; color: #eee; border-color: #444; }
          #map.dark .leaflet-control-attribution { background: rgba(30, 30, 30, 0.75); color: #bbb; }
          .veh { padding: 2px 5px; border-radius: 6px; font: 700 12px/1.2 var(--paper-font-body1_-_font-family, sans-serif);
                 white-space: nowrap; border: 2px solid #fff; box-shadow: 0 1px 4px rgba(0,0,0,.45); transform: translate(-50%, -50%); display: inline-block; }
          .veh-icon { width: 0 !important; height: 0 !important; }
          .leaflet-marker-icon.veh-icon { transition: transform 1.5s linear; }
          .leaflet-zoom-anim .leaflet-marker-icon.veh-icon { transition: none; }
          .home { font-size: 20px; transform: translate(-50%, -50%); filter: drop-shadow(0 1px 2px rgba(0,0,0,.5)); }
          .popup-title { font-weight: 600; margin-bottom: 4px; }
          .popup-row { display: flex; gap: 6px; align-items: center; margin: 3px 0; }
          .popup-row .badge { min-width: 28px; padding: 1px 4px; border-radius: 4px; text-align: center; font-weight: 700; font-size: 11px; }
        </style>
        <ha-card>
          <div class="header" hidden></div>
          <div id="map"></div>
        </ha-card>`;
    }
    const header = this.shadowRoot.querySelector(".header");
    header.hidden = !this._config.title;
    header.textContent = this._config.title || "";
    this.shadowRoot.querySelector("#map").style.height = `${this._config.height}px`;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._initMap();
    else this._update();
  }

  getCardSize() {
    return Math.ceil(this._config.height / 50);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: Math.ceil(this._config.height / 56) };
  }

  disconnectedCallback() {
    this._resizeObserver?.disconnect();
  }

  connectedCallback() {
    if (this._map) {
      this._resizeObserver?.observe(this.shadowRoot.querySelector("#map"));
      setTimeout(() => this._map.invalidateSize(), 50);
    }
  }

  _entityIds() {
    return this._config.entities?.length
      ? this._config.entities
      : [...midttrafikEntities(this._hass, "vehicles"), ...midttrafikEntities(this._hass, "stops")];
  }

  _isDark() {
    const mode = this._config.dark_mode;
    return mode === "dark" || (mode === "auto" && !!this._hass?.themes?.darkMode);
  }

  async _initMap() {
    let L;
    try {
      L = await loadLeaflet();
    } catch (err) {
      this.shadowRoot.querySelector("#map").outerHTML = `<div class="err">${esc(err.message)}</div>`;
      return;
    }
    const el = this.shadowRoot.querySelector("#map");
    const home = [this._hass.config.latitude, this._hass.config.longitude];
    this._map = L.map(el, { zoomControl: true, attributionControl: true }).setView(
      this._config.center || home,
      this._config.zoom || 13
    );
    this._vehicleLayer = L.layerGroup().addTo(this._map);
    this._stopLayer = L.layerGroup().addTo(this._map);
    this._vehicles = new Map();
    this._stops = new Map();
    this._setTiles();

    if (this._config.show_home) {
      L.marker(home, { icon: L.divIcon({ className: "veh-icon", html: '<div class="home">🏠</div>' }), interactive: false }).addTo(this._map);
    }

    this._resizeObserver = new ResizeObserver(() => this._map.invalidateSize());
    this._resizeObserver.observe(el);
    this._update();
  }

  _setTiles() {
    if (!this._tiles) {
      // OpenStreetMap by default; tile_url / tile_attribution allow another provider.
      this._tiles = window.L.tileLayer(this._config.tile_url || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution:
          this._config.tile_attribution ||
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(this._map);
    }
    // Dark mode inverts the OSM tiles with CSS; no keyed dark tile service needed.
    this.shadowRoot.querySelector("#map").classList.toggle("dark", this._isDark());
  }

  _update() {
    if (!this._map) return;
    const L = window.L;
    this._setTiles();

    const vehicles = new Map();
    const stops = new Map();
    for (const id of this._entityIds()) {
      const attrs = this._hass.states[id]?.attributes;
      if (!attrs) continue;
      for (const v of attrs.vehicles || []) vehicles.set(v.id, v);
      for (const s of attrs.stops || []) stops.set(s.number, { ...s, departures: attrs.departures || [] });
    }

    // Vehicles: move existing markers, add new ones, drop vanished ones.
    for (const [id, v] of vehicles) {
      const html = `<div class="veh" style="background:${esc(v.color || "#0077B3")};color:${esc(v.text_color || "#fff")}">${esc(v.line)}</div>`;
      const tip = `${esc(v.line)} → ${esc(v.direction)}`;
      let marker = this._vehicles.get(id);
      if (!marker) {
        marker = L.marker([v.latitude, v.longitude], { icon: L.divIcon({ className: "veh-icon", html }), zIndexOffset: 1000 })
          .bindTooltip(tip, { direction: "top", offset: [0, -10] })
          .addTo(this._vehicleLayer);
        marker._html = html;
        this._vehicles.set(id, marker);
      } else {
        marker.setLatLng([v.latitude, v.longitude]);
        if (marker._html !== html) {
          marker.setIcon(L.divIcon({ className: "veh-icon", html }));
          marker._html = html;
        }
        marker.setTooltipContent(tip);
      }
    }
    for (const [id, marker] of this._vehicles) {
      if (!vehicles.has(id)) {
        marker.remove();
        this._vehicles.delete(id);
      }
    }

    // Stops: circle markers with the next departures in a popup.
    for (const [number, s] of stops) {
      const now = new Date();
      const rows = s.departures
        .filter((d) => new Date(d.expected) > now)
        .slice(0, 5)
        .map((d) => {
          const mins = Math.max(0, Math.floor((new Date(d.expected) - now) / 60000));
          const when = d.cancelled ? t(this._hass, "cancelled") : mins < 60 ? `${mins} ${t(this._hass, "min")}` : hhmm(d.expected);
          return `<div class="popup-row">${lineBadge(d)}<span style="flex:1">${esc(d.direction)}</span><b>${when}</b></div>`;
        })
        .join("");
      const popup = `<div class="popup-title">${esc(s.name)}</div>${rows || t(this._hass, "noDepartures")}`;
      let marker = this._stops.get(number);
      if (!marker) {
        marker = L.circleMarker([s.latitude, s.longitude], {
          radius: 7, color: "#fff", weight: 2, fillColor: "#e2001a", fillOpacity: 1,
        })
          .bindPopup(popup, { minWidth: 200 })
          .bindTooltip(esc(s.name), { direction: "top" })
          .addTo(this._stopLayer);
        this._stops.set(number, marker);
      } else {
        marker.setPopupContent(popup);
      }
    }
    for (const [number, marker] of this._stops) {
      if (!stops.has(number)) {
        marker.remove();
        this._stops.delete(number);
      }
    }

    // Frame everything the first time there is something to show.
    if (!this._fitted && !this._config.center && (vehicles.size || stops.size)) {
      this._fitted = true;
      const points = [...vehicles.values(), ...stops.values()].map((p) => [p.latitude, p.longitude]);
      if (this._config.show_home) points.push([this._hass.config.latitude, this._hass.config.longitude]);
      this._map.fitBounds(points, { padding: [30, 30], maxZoom: this._config.zoom || 15 });
    }
  }
}

customElements.get("midttrafik-departures-card") || customElements.define("midttrafik-departures-card", MidttrafikDeparturesCard);
customElements.get("midttrafik-map-card") || customElements.define("midttrafik-map-card", MidttrafikMapCard);

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "midttrafik-departures-card", name: "Midttrafik departures", description: "Live departure board for a Midttrafik stop", preview: true },
  { type: "midttrafik-map-card", name: "Midttrafik live map", description: "Live map of buses, trams and stops" }
);
