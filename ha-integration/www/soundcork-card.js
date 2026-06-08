/**
 * SoundCork Lovelace Card
 *
 * Mirrors the SoundCork webui look & feel inside Home Assistant.
 * All speaker communication goes through the soundcork /api/v1 proxy.
 *
 * Config:
 *   type: custom:soundcork-card
 *   soundcork_url: http://soundcork.soundcork.svc.cluster.local:8000
 *   speakers:
 *     - media_player.soundcork_DEVICEID1
 *     - media_player.soundcork_DEVICEID2
 *   mode: player | speaker | editor   (default: player)
 */
class SoundCorkCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._presets = [];
    this._playing = null;
    this._selectedSpeakers = null;
    this._initialized = false;
    this._searchResults = [];
    this._searchLoading = false;
    this._selectedSlot = 1;
  }

  setConfig(config) {
    if (!config.soundcork_url) throw new Error("soundcork_url is required");
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      if (this._mode !== "speaker") this._loadPresets();
    }
    this._render();
  }

  get _mode() { return this._config.mode || "player"; }
  get _baseUrl() { return (this._config.soundcork_url || "").replace(/\/$/, ""); }
  get _speakers() { return this._config.speakers || []; }

  _getSpeakerEntities() {
    return this._speakers.map(id => {
      const state = this._hass && this._hass.states[id];
      return state ? { id, state } : null;
    }).filter(Boolean);
  }

  _getSpeakerIps() {
    return this._getSpeakerEntities()
      .filter(e => e.state.state !== "unavailable")
      .map(e => e.state.attributes.ip_address)
      .filter(Boolean);
  }

  _getTargetSpeakers() {
    const ids = (this._selectedSpeakers && this._selectedSpeakers.length > 0)
      ? this._selectedSpeakers
      : this._speakers;
    return ids.map(id => {
      const state = this._hass && this._hass.states[id];
      if (!state || state.state === "unavailable") return null;
      return { ip: state.attributes.ip_address, device_id: state.attributes.device_id };
    }).filter(s => s && s.ip && s.device_id);
  }

  async _loadPresets() {
    const ips = this._getSpeakerIps();
    for (const ip of ips) {
      try {
        const r = await fetch(`${this._baseUrl}/api/v1/speakers/${ip}/presets`, { signal: AbortSignal.timeout(4000) });
        if (!r.ok) continue;
        const doc = new DOMParser().parseFromString(await r.text(), "application/xml");
        const presets = [];
        doc.querySelectorAll("preset").forEach(p => {
          const ci = p.querySelector("ContentItem");
          if (ci) presets.push({
            id: parseInt(p.getAttribute("id")),
            name: ci.querySelector("itemName")?.textContent || `Preset ${p.getAttribute("id")}`,
            art: ci.querySelector("containerArt")?.textContent || "",
            source: ci.getAttribute("source") || "",
            location: ci.getAttribute("location") || "",
            type: ci.getAttribute("type") || "",
            sourceAccount: ci.getAttribute("sourceAccount") || "",
          });
        });
        if (presets.length > 0) {
          this._presets = presets;
          this._render();
          return;
        }
      } catch (e) {
        // try next speaker
      }
    }
  }

  async _playPreset(preset) {
    if (this._playing) return;
    this._playing = preset.id;
    this._render();
    const xml = `<ContentItem source="${this._esc(preset.source)}" type="${this._esc(preset.type)}" location="${this._esc(preset.location)}" sourceAccount="${this._esc(preset.sourceAccount || "")}" isPresetable="true"></ContentItem>`;
    await this._playWithZone(xml);
    this._playing = null;
    this._render();
  }

  async _playWithZone(xml) {
    const targets = this._getTargetSpeakers();
    if (!targets.length) return;
    if (targets.length === 1) {
      await fetch(`${this._baseUrl}/api/v1/speakers/${targets[0].ip}/select`, { method: "POST", headers: { "Content-Type": "application/xml" }, body: xml }).catch(() => {});
    } else {
      const master = targets[0], slaves = targets.slice(1);
      await fetch(`${this._baseUrl}/api/v1/zone/set`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ master_ip: master.ip, master_device_id: master.device_id, slaves })
      }).catch(() => {});
      await new Promise(r => setTimeout(r, 300));
      await fetch(`${this._baseUrl}/api/v1/speakers/${master.ip}/select`, { method: "POST", headers: { "Content-Type": "application/xml" }, body: xml }).catch(() => {});
    }
  }

  async _powerOff() {
    const ips = this._getSpeakerIps();
    if (ips.length > 1) {
      await fetch(`${this._baseUrl}/api/v1/zone/clear/${ips[0]}`, { method: "POST" }).catch(() => {});
      await new Promise(r => setTimeout(r, 200));
    }
    await Promise.all(ips.map(ip =>
      fetch(`${this._baseUrl}/api/v1/speakers/${ip}/power-off`, { method: "POST" }).catch(() => {})
    ));
  }

  async _setVolume(ip, vol) {
    await fetch(`${this._baseUrl}/api/v1/speakers/${ip}/volume`, {
      method: "POST", headers: { "Content-Type": "application/xml" },
      body: `<volume>${vol}</volume>`
    }).catch(() => {});
  }

  async _toggleMute(ip) {
    await fetch(`${this._baseUrl}/api/v1/speakers/${ip}/key/MUTE`, { method: "POST" }).catch(() => {});
  }

  async _searchTuneIn(query) {
    this._searchLoading = true;
    this._render();
    try {
      const r = await fetch(`${this._baseUrl}/api/v1/tunein/search?q=${encodeURIComponent(query)}`);
      const data = await r.json();
      this._searchResults = (data.body || []).flatMap(g => g.children || []).filter(c => c.type === "audio");
    } catch (e) {
      this._searchResults = [];
    }
    this._searchLoading = false;
    this._render();
  }

  async _savePreset(slot, station) {
    const ips = this._getSpeakerIps();
    if (!ips.length) return;
    const xml = `<preset id="${slot}"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/${this._esc(station.guide_id)}" isPresetable="true"><itemName>${this._esc(station.text)}</itemName><containerArt>${this._esc(station.image || "")}</containerArt></ContentItem></preset>`;
    await Promise.all(ips.map(ip =>
      fetch(`${this._baseUrl}/api/v1/speakers/${ip}/store-preset`, { method: "POST", headers: { "Content-Type": "application/xml" }, body: xml }).catch(() => {})
    ));
    await this._loadPresets();
  }

  _esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  _escHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  _proxyImage(url) {
    if (!url) return "";
    return `${this._baseUrl}/webui/api/image?url=${encodeURIComponent(url)}`;
  }

  _sourceBadge(source) {
    const s = (source || "").toUpperCase();
    if (s.includes("SPOTIFY")) return `<span class="badge badge-spotify">Spotify</span>`;
    if (s.includes("TUNEIN")) return `<span class="badge badge-tunein">TuneIn</span>`;
    if (s.includes("RADIO") || s.includes("LOCAL_INTERNET")) return `<span class="badge badge-radio">Radio</span>`;
    if (s && s !== "STANDBY") return `<span class="badge badge-product">${this._escHtml(s)}</span>`;
    return "";
  }

  _render() {
    if (!this.shadowRoot) return;
    if (this._mode === "player") this._renderPlayer();
    else if (this._mode === "speaker") this._renderSpeakers();
    else if (this._mode === "editor") this._renderEditor();
  }

  // ---------------------------------------------------------------
  // Player mode: now playing + preset grid + speaker selector
  // ---------------------------------------------------------------
  _renderPlayer() {
    const entity = this._speakers[0];
    const state = this._hass && entity && this._hass.states[entity];
    const attrs = state ? state.attributes : {};
    const isOff = !state || state.state === "off" || state.state === "unavailable";

    const artUrl = attrs.entity_picture
      ? (attrs.entity_picture.startsWith("http") ? attrs.entity_picture : "")
      : "";

    const speakerNames = this._speakers.map(id => {
      const s = this._hass && this._hass.states[id];
      return { id, name: s ? (s.attributes.friendly_name || id.split(".")[1]) : id.split(".")[1] };
    });

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="sc-card">
        <div class="now-playing">
          ${artUrl
            ? `<img class="now-playing-art" src="${artUrl}" alt="" onerror="this.style.display='none'">`
            : `<div class="now-playing-placeholder">${isOff ? "&#x23FB;" : "&#x266B;"}</div>`}
          <div class="now-playing-info">
            <div class="now-playing-track">${this._escHtml(attrs.media_title || attrs.media_station || (isOff ? "Standby" : "Playing"))}</div>
            ${attrs.media_artist ? `<div class="now-playing-artist">${this._escHtml(attrs.media_artist)}</div>` : ""}
            ${attrs.media_album_name ? `<div class="now-playing-album">${this._escHtml(attrs.media_album_name)}</div>` : ""}
            <div class="now-playing-source">${this._sourceBadge(attrs.source_type || (isOff ? "" : attrs.source))}</div>
          </div>
        </div>

        ${speakerNames.length > 1 ? `
        <div class="speaker-selector">
          ${speakerNames.map(s => {
            const sel = !this._selectedSpeakers || this._selectedSpeakers.includes(s.id);
            return `<button class="speaker-chip ${sel ? "active" : ""}" data-id="${this._escHtml(s.id)}">${this._escHtml(s.name)}</button>`;
          }).join("")}
        </div>` : ""}

        <div class="section-title">Presets</div>
        <div class="preset-grid">
          ${this._presets.map(p => `
            <button class="preset-btn ${this._playing === p.id ? "playing" : ""}" data-preset-id="${p.id}">
              ${p.art ? `<img class="preset-art" src="${this._proxyImage(p.art)}" alt="" onerror="this.style.display='none'">` : `<div class="preset-art-placeholder">&#x266B;</div>`}
              <div class="preset-label">${this._escHtml(p.name)}</div>
              <div class="preset-source">${this._sourceBadge(p.source)}</div>
            </button>
          `).join("")}
          ${this._presets.length === 0 ? `<div class="text-muted">No presets loaded</div>` : ""}
        </div>

        <div class="card-actions">
          <button class="btn btn-sm" id="btn-power-off">&#x23FB; Off</button>
          <button class="btn btn-sm" id="btn-refresh">&#x21BB; Refresh</button>
        </div>
      </div>
    `;

    this.shadowRoot.querySelectorAll(".preset-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const id = parseInt(btn.dataset.presetId);
        const preset = this._presets.find(p => p.id === id);
        if (preset) this._playPreset(preset);
      });
    });

    this.shadowRoot.querySelectorAll(".speaker-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        const id = chip.dataset.id;
        if (!this._selectedSpeakers) {
          this._selectedSpeakers = [id];
        } else if (this._selectedSpeakers.includes(id)) {
          this._selectedSpeakers = this._selectedSpeakers.filter(s => s !== id);
          if (this._selectedSpeakers.length === 0) this._selectedSpeakers = null;
        } else {
          this._selectedSpeakers.push(id);
        }
        this._render();
      });
    });

    const offBtn = this.shadowRoot.getElementById("btn-power-off");
    if (offBtn) offBtn.addEventListener("click", () => this._powerOff());

    const refBtn = this.shadowRoot.getElementById("btn-refresh");
    if (refBtn) refBtn.addEventListener("click", () => this._loadPresets());
  }

  // ---------------------------------------------------------------
  // Speaker mode: per-speaker volume controls
  // ---------------------------------------------------------------
  _renderSpeakers() {
    const entities = this._getSpeakerEntities();

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="sc-card">
        <div class="section-title">Speakers</div>
        ${entities.map(e => {
          const s = e.state;
          const a = s.attributes;
          const vol = Math.round((a.volume_level || 0) * 100);
          const muted = a.is_volume_muted;
          const isOff = s.state === "off" || s.state === "unavailable";
          return `
            <div class="speaker-row">
              <div class="speaker-info">
                <div class="speaker-name">${this._escHtml(a.friendly_name || e.id)}</div>
                <div class="speaker-status">${isOff ? "Off" : this._escHtml(a.media_title || a.source || "Playing")} ${this._sourceBadge(a.source_type)}</div>
              </div>
              <div class="volume-control">
                <button class="btn-icon ${muted ? "muted" : ""}" data-action="mute" data-ip="${a.ip_address}">
                  ${muted ? "&#x1F507;" : "&#x1F50A;"}
                </button>
                <input type="range" min="0" max="100" value="${vol}" data-ip="${a.ip_address}" ${isOff ? "disabled" : ""}>
                <span class="volume-label">${vol}</span>
              </div>
            </div>`;
        }).join("")}
        ${entities.length === 0 ? `<div class="text-muted">No speakers available</div>` : ""}
      </div>
    `;

    this.shadowRoot.querySelectorAll('input[type="range"]').forEach(slider => {
      let debounce;
      slider.addEventListener("input", () => {
        const label = slider.parentElement.querySelector(".volume-label");
        if (label) label.textContent = slider.value;
        clearTimeout(debounce);
        debounce = setTimeout(() => this._setVolume(slider.dataset.ip, parseInt(slider.value)), 200);
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="mute"]').forEach(btn => {
      btn.addEventListener("click", () => this._toggleMute(btn.dataset.ip));
    });
  }

  // ---------------------------------------------------------------
  // Editor mode: TuneIn search + preset slot saving
  // ---------------------------------------------------------------
  _renderEditor() {
    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="sc-card">
        <div class="section-title">Edit Presets</div>
        <div class="preset-grid preset-grid-small">
          ${[1,2,3,4,5,6].map(i => {
            const p = this._presets.find(x => x.id === i);
            return `<button class="preset-slot ${this._selectedSlot === i ? "selected" : ""}" data-slot="${i}">
              <span class="preset-slot-num">${i}</span>
              <span class="preset-slot-name">${p ? this._escHtml(p.name) : "Empty"}</span>
            </button>`;
          }).join("")}
        </div>

        <div class="search-section">
          <div class="search-bar">
            <input type="text" id="search-input" placeholder="Search TuneIn stations...">
            <button class="btn btn-sm btn-primary" id="search-btn">Search</button>
          </div>
          ${this._searchLoading ? `<div class="text-muted">Searching...</div>` : ""}
          <div class="search-results">
            ${this._searchResults.map(s => `
              <div class="list-item" data-guide-id="${this._escHtml(s.guide_id)}">
                ${s.image ? `<img class="list-item-thumb" src="${this._proxyImage(s.image)}" alt="" onerror="this.style.display='none'">` : `<div class="list-item-thumb-placeholder">&#x266B;</div>`}
                <div class="list-item-body">
                  <div class="list-item-title">${this._escHtml(s.text)}</div>
                  <div class="list-item-subtitle">${this._escHtml(s.subtext || "")}</div>
                </div>
                <button class="btn btn-sm" data-save-id="${this._escHtml(s.guide_id)}">Save to ${this._selectedSlot}</button>
              </div>
            `).join("")}
          </div>
        </div>
      </div>
    `;

    this.shadowRoot.querySelectorAll(".preset-slot").forEach(btn => {
      btn.addEventListener("click", () => {
        this._selectedSlot = parseInt(btn.dataset.slot);
        this._render();
      });
    });

    const searchBtn = this.shadowRoot.getElementById("search-btn");
    const searchInput = this.shadowRoot.getElementById("search-input");
    if (searchBtn && searchInput) {
      const doSearch = () => {
        const q = searchInput.value.trim();
        if (q) this._searchTuneIn(q);
      };
      searchBtn.addEventListener("click", doSearch);
      searchInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
    }

    this.shadowRoot.querySelectorAll("[data-save-id]").forEach(btn => {
      btn.addEventListener("click", () => {
        const station = this._searchResults.find(s => s.guide_id === btn.dataset.saveId);
        if (station) this._savePreset(this._selectedSlot, station);
      });
    });
  }

  // ---------------------------------------------------------------
  // Styles — adapted from the SoundCork webui
  // ---------------------------------------------------------------
  _styles() {
    return `
      :host {
        --bg-primary: var(--ha-card-background, var(--card-background-color, #fff));
        --bg-secondary: var(--secondary-background-color, #f5f5f5);
        --bg-card: var(--ha-card-background, var(--card-background-color, #fff));
        --text-primary: var(--primary-text-color, #212121);
        --text-secondary: var(--secondary-text-color, #757575);
        --text-hint: var(--disabled-text-color, #bdbdbd);
        --border-color: var(--divider-color, #e0e0e0);
        --border-light: var(--divider-color, #f0f0f0);
        --accent: var(--primary-color, #ff5722);
        --accent-hover: var(--primary-color, #e64a19);
        --accent-light: rgba(255, 87, 34, 0.12);
        --danger: var(--error-color, #f44336);
        --success: var(--success-color, #4caf50);
        --badge-spotify: #1db954;
        --badge-tunein: #2196f3;
        --badge-radio: #ff9800;
        --badge-product: #9e9e9e;
        --radius-sm: 6px;
        --radius-md: 10px;
        --radius-lg: 16px;
        --shadow-sm: 0 1px 3px rgba(0,0,0,0.08);
        --shadow-md: 0 2px 8px rgba(0,0,0,0.12);
        --transition: 0.2s ease;
        --font-mono: 'SF Mono', 'Fira Code', monospace;
      }

      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

      .sc-card {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--text-primary);
        padding: 16px;
      }

      /* Now Playing */
      .now-playing {
        border-radius: var(--radius-md);
        overflow: hidden;
        background: var(--bg-secondary);
        margin-bottom: 1rem;
      }
      .now-playing-art {
        width: 100%;
        max-width: 400px;
        aspect-ratio: 1;
        object-fit: cover;
        display: block;
        margin: 0 auto;
      }
      .now-playing-placeholder {
        width: 100%;
        max-width: 400px;
        aspect-ratio: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto;
        color: var(--text-hint);
        font-size: 3rem;
      }
      .now-playing-info { padding: 1rem; }
      .now-playing-track { font-size: 1.1rem; font-weight: 700; }
      .now-playing-artist { font-size: 0.9rem; color: var(--text-secondary); }
      .now-playing-album { font-size: 0.82rem; color: var(--text-hint); margin-top: 0.15rem; }
      .now-playing-source { margin-top: 0.3rem; }

      /* Badges */
      .badge {
        display: inline-block;
        font-size: 0.68rem;
        font-weight: 600;
        padding: 0.15rem 0.45rem;
        border-radius: 999px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        color: #fff;
        background: var(--text-hint);
      }
      .badge-spotify { background: var(--badge-spotify); }
      .badge-tunein { background: var(--badge-tunein); }
      .badge-radio { background: var(--badge-radio); }
      .badge-product { background: var(--badge-product); }

      /* Speaker selector chips */
      .speaker-selector {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        margin-bottom: 1rem;
      }
      .speaker-chip {
        font-family: inherit;
        font-size: 0.78rem;
        padding: 0.3rem 0.7rem;
        border-radius: 999px;
        border: 1px solid var(--border-color);
        background: var(--bg-secondary);
        color: var(--text-secondary);
        cursor: pointer;
        transition: all var(--transition);
      }
      .speaker-chip.active {
        background: var(--accent);
        color: #fff;
        border-color: var(--accent);
      }

      /* Section title */
      .section-title {
        font-size: 0.82rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--text-secondary);
        margin-bottom: 0.6rem;
      }

      /* Preset grid (2x3 like webui) */
      .preset-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.65rem;
        margin-bottom: 1rem;
      }
      .preset-btn {
        font-family: inherit;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-sm);
        padding: 0.6rem;
        cursor: pointer;
        text-align: left;
        transition: all var(--transition);
        overflow: hidden;
      }
      .preset-btn:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
      .preset-btn.playing { border-color: var(--accent); background: var(--accent-light); }
      .preset-art {
        width: 100%;
        aspect-ratio: 1;
        object-fit: cover;
        border-radius: 4px;
        margin-bottom: 0.4rem;
      }
      .preset-art-placeholder {
        width: 100%;
        aspect-ratio: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--bg-primary);
        border-radius: 4px;
        margin-bottom: 0.4rem;
        font-size: 1.5rem;
        color: var(--text-hint);
      }
      .preset-label { font-size: 0.82rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .preset-source { margin-top: 0.2rem; }

      /* Preset slot selector (editor) */
      .preset-grid-small { gap: 0.4rem; margin-bottom: 1rem; }
      .preset-slot {
        font-family: inherit;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 0.7rem;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-sm);
        cursor: pointer;
        transition: all var(--transition);
      }
      .preset-slot.selected { border-color: var(--accent); background: var(--accent-light); }
      .preset-slot-num { font-weight: 700; font-family: var(--font-mono); font-size: 0.9rem; }
      .preset-slot-name { font-size: 0.82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

      /* Speaker rows */
      .speaker-row {
        padding: 0.75rem 0;
        border-bottom: 1px solid var(--border-light);
      }
      .speaker-row:last-child { border-bottom: none; }
      .speaker-info { margin-bottom: 0.4rem; }
      .speaker-name { font-weight: 600; font-size: 0.92rem; }
      .speaker-status { font-size: 0.8rem; color: var(--text-secondary); }

      /* Volume */
      .volume-control { display: flex; align-items: center; gap: 0.5rem; }
      .volume-control input[type="range"] { flex: 1; accent-color: var(--accent); }
      .volume-label {
        font-size: 0.82rem; font-weight: 600;
        min-width: 2.2rem; text-align: center;
        font-family: var(--font-mono);
      }

      /* Buttons */
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.4rem;
        padding: 0.5rem 1rem;
        font-size: 0.85rem;
        font-weight: 500;
        font-family: inherit;
        border: 1px solid var(--border-color);
        border-radius: var(--radius-sm);
        background: var(--bg-secondary);
        color: var(--text-primary);
        cursor: pointer;
        transition: all var(--transition);
      }
      .btn:hover { box-shadow: var(--shadow-sm); }
      .btn-sm { padding: 0.35rem 0.7rem; font-size: 0.78rem; }
      .btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
      .btn-primary:hover { background: var(--accent-hover); }
      .btn-icon {
        background: none;
        border: none;
        font-size: 1.2rem;
        cursor: pointer;
        padding: 0.2rem;
        border-radius: 4px;
      }
      .btn-icon.muted { opacity: 0.5; }

      /* Card actions */
      .card-actions {
        display: flex;
        gap: 0.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid var(--border-light);
      }

      /* Search */
      .search-section { margin-top: 1rem; }
      .search-bar { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
      .search-bar input {
        flex: 1;
        padding: 0.5rem 0.75rem;
        font-size: 0.85rem;
        font-family: inherit;
        border: 1px solid var(--border-color);
        border-radius: var(--radius-sm);
        background: var(--bg-primary);
        color: var(--text-primary);
      }
      .search-results { max-height: 300px; overflow-y: auto; }

      /* List items */
      .list-item {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.65rem 0;
        border-bottom: 1px solid var(--border-light);
      }
      .list-item:last-child { border-bottom: none; }
      .list-item-thumb {
        width: 48px; height: 48px;
        border-radius: var(--radius-sm);
        object-fit: cover;
        background: var(--bg-secondary);
        flex-shrink: 0;
      }
      .list-item-thumb-placeholder {
        width: 48px; height: 48px;
        border-radius: var(--radius-sm);
        background: var(--bg-secondary);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.2rem;
        color: var(--text-hint);
        flex-shrink: 0;
      }
      .list-item-body { flex: 1; min-width: 0; }
      .list-item-title { font-weight: 600; font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .list-item-subtitle { font-size: 0.75rem; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

      .text-muted { color: var(--text-secondary); font-size: 0.85rem; padding: 0.5rem 0; }
    `;
  }

  static getConfigElement() { return document.createElement("soundcork-card-editor"); }
  static getStubConfig() { return { soundcork_url: "", speakers: [], mode: "player" }; }

  getCardSize() { return this._mode === "player" ? 6 : 3; }
}

customElements.define("soundcork-card", SoundCorkCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "soundcork-card",
  name: "SoundCork",
  description: "Control Bose SoundTouch speakers via SoundCork",
});
