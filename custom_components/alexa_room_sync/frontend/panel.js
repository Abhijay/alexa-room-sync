const STATE_LABEL = {
  in_sync: "In sync",
  create: "Will be created",
  update: "Will be updated",
  no_devices: "No Alexa devices matched",
};
const APPLIED_LABEL = { ...STATE_LABEL, create: "Created", update: "Updated" };

const STYLE = `
  :host { display: block; padding: 16px; max-width: 1100px; margin: 0 auto; color: var(--primary-text-color); }
  .toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
  .toolbar h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; }
  .badge { padding: 2px 10px; border-radius: 12px; font-size: 12px; background: var(--secondary-background-color); }
  .badge.error { background: var(--error-color); color: #fff; }
  .badge.dry { background: var(--warning-color); color: #000; }
  .badge.applied, .badge.in_sync { background: var(--success-color); color: #fff; }
  button { background: var(--primary-color); color: var(--text-primary-color); border: 0; border-radius: 4px; padding: 8px 14px; cursor: pointer; font: inherit; }
  button.secondary { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .card { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); padding: 16px; margin-bottom: 16px; }
  .card h2 { margin: 0 0 4px; font-size: 16px; font-weight: 500; display: flex; align-items: center; gap: 8px; }
  .muted { color: var(--secondary-text-color); font-size: 13px; }
  .error-text { color: var(--error-color); white-space: pre-wrap; font-family: monospace; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }
  th { text-align: left; font-weight: 500; color: var(--secondary-text-color); padding: 6px 8px; border-bottom: 1px solid var(--divider-color); }
  td { padding: 6px 8px; border-bottom: 1px solid var(--divider-color); vertical-align: top; }
  tr:last-child td { border-bottom: 0; }
  .same { color: var(--secondary-text-color); }
  ul { margin: 6px 0 0; padding-left: 18px; }
  .section { font-size: 13px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; color: var(--secondary-text-color); margin: 24px 0 8px; }
`;

class AlexaRoomSyncPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._busy = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
    const status = hass.states["sensor.alexa_room_sync_status"];
    const stamp = status && status.last_updated;
    if (stamp && stamp !== this._stamp) {
      this._stamp = stamp;
      this._load();
    }
  }

  async _load() {
    try {
      this._data = await this._hass.connection.sendMessagePromise({ type: "alexa_room_sync/overview" });
      this._error = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._render();
  }

  async _call(domain, service, entityId) {
    this._busy = true;
    this._render();
    await this._hass.callService(domain, service, { entity_id: entityId });
    this._busy = false;
    setTimeout(() => this._load(), 1500);
  }

  _render() {
    const d = this._data;
    const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const dryRun = d && d.dry_run;
    const labels = d && d.status === "applied" ? APPLIED_LABEL : STATE_LABEL;
    const statusClass = d ? (d.status === "error" ? "error" : d.status === "dry_run" ? "dry" : d.status) : "";
    const areaCard = (a) => {
      const rows = a.members
        .map(
          (m) => `<tr><td>${esc(m.ha_name)}<div class="muted">${esc(m.ha_id)}</div></td><td class="${m.ha_name.toLowerCase() === m.alexa_name.toLowerCase() ? "same" : ""}">${esc(m.alexa_name)}</td></tr>`
        )
        .join("");
      const unmanaged = a.unmanaged.length
        ? `<div class="muted">Also in this Alexa room, not managed by Home Assistant: ${a.unmanaged.map(esc).join(", ")}</div>`
        : "";
      const aliases = a.aliases.length ? `<span class="muted">also ${a.aliases.map(esc).join(", ")}</span>` : "";
      const target = a.alexa_group && a.alexa_group !== a.name ? `<span class="muted">→ Alexa "${esc(a.alexa_group)}"</span>` : "";
      return `<div class="card">
        <h2>${esc(a.name)} ${aliases} ${target} <span class="badge ${a.state}">${labels[a.state] || esc(a.state)}</span></h2>
        ${rows ? `<table><tr><th>Home Assistant</th><th>Alexa</th></tr>${rows}</table>` : `<div class="muted">Name a device in Alexa the same as an entity or device in this area and it will appear here.</div>`}
        ${unmanaged}
      </div>`;
    };
    const homeCard = (h) => {
      const unmanaged = h.unmanaged.length
        ? `<div class="muted">Also in this Alexa group, not managed by Home Assistant: ${h.unmanaged.map(esc).join(", ")}</div>`
        : "";
      const target = h.alexa_group && h.alexa_group !== h.name ? `<span class="muted">→ Alexa "${esc(h.alexa_group)}"</span>` : "";
      return `<h3 class="section">Home</h3><div class="card">
        <h2>${esc(h.name)} ${target} <span class="badge ${h.state}">${labels[h.state] || esc(h.state)}</span></h2>
        <div class="muted">Every matched device · ${h.member_count} device(s). Rename under Settings → System → General.</div>
        ${unmanaged}
      </div>`;
    };
    const floorCard = (f) => {
      const unmanaged = f.unmanaged.length
        ? `<div class="muted">Also in this Alexa group, not managed by Home Assistant: ${f.unmanaged.map(esc).join(", ")}</div>`
        : "";
      const target = f.alexa_group && f.alexa_group !== f.name ? `<span class="muted">→ Alexa "${esc(f.alexa_group)}"</span>` : "";
      return `<div class="card">
        <h2>${esc(f.name)} ${target} <span class="badge ${f.state}">${labels[f.state] || esc(f.state)}</span></h2>
        <div class="muted">${f.areas.length ? `${f.areas.map(esc).join(", ")} · ${f.member_count} matched device(s)` : "No areas on this floor."}</div>
        ${unmanaged}
      </div>`;
    };
    const list = (title, items, hint) =>
      items.length
        ? `<div class="card"><h2>${title} <span class="badge">${items.length}</span></h2><div class="muted">${hint}</div><ul>${items.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`
        : "";

    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar">
        <h1>Alexa Rooms</h1>
        ${d ? `<span class="badge ${statusClass}">${esc(d.status)}</span>` : ""}
        ${d ? `<span class="muted">last run ${d.last_run ? new Date(d.last_run).toLocaleString() : "never"}</span>` : ""}
        <button class="secondary" id="dry" ${this._busy ? "disabled" : ""}>${dryRun ? "Dry run: on" : "Dry run: off"}</button>
        <button id="sync" ${this._busy ? "disabled" : ""}>Sync now</button>
      </div>
      ${this._error ? `<div class="card error-text">${esc(this._error)}</div>` : ""}
      ${d && d.last_error ? `<div class="card"><h2>Last run failed</h2><div class="error-text">${esc(d.last_error)}</div></div>` : ""}
      ${d && d.home ? homeCard(d.home) : ""}
      ${d && d.floors.length ? `<h3 class="section">Floors</h3>${d.floors.map(floorCard).join("")}<h3 class="section">Areas</h3>` : ""}
      ${d ? d.areas.map(areaCard).join("") : `<div class="card muted">Loading…</div>`}
      ${d ? list("Alexa devices with no match in Home Assistant", d.unmatched, "Rename them in Alexa, or add an alias in Home Assistant with the Alexa name.") : ""}
      ${d ? list("Echo devices with no match", d.unmatched_echos, "Echos only join a room when a Home Assistant device or entity carries the same name or alias.") : ""}
    `;
    this.shadowRoot.getElementById("sync").onclick = () => this._call("button", "press", "button.alexa_room_sync_sync_now");
    this.shadowRoot.getElementById("dry").onclick = () =>
      this._call("switch", dryRun ? "turn_off" : "turn_on", "switch.alexa_room_sync_dry_run");
  }
}

customElements.define("alexa-room-sync-panel", AlexaRoomSyncPanel);
