/* ===================================================================
   SoundCork Web UI — Main Application
   Single-page app controlling Bose SoundTouch speakers
   =================================================================== */

// ===================================================================
// Section 0: Auth-aware Fetch Wrapper
// ===================================================================

/**
 * Get the CSRF token from sessionStorage (password login) or cookie (OIDC login).
 */
function getCsrfToken() {
  const stored = sessionStorage.getItem('csrf_token');
  if (stored) return stored;
  // OIDC login stores CSRF in a non-httponly cookie
  const match = document.cookie.match(/webui_csrf=([^;]+)/);
  if (match) {
    // Move to sessionStorage for consistency
    sessionStorage.setItem('csrf_token', match[1]);
    return match[1];
  }
  return null;
}

/**
 * Wrapper around fetch() that:
 * 1. Adds X-CSRF-Token header to mutating requests (POST/PUT/DELETE/PATCH)
 * 2. Redirects to /webui/login on 401 responses
 */
const _originalFetch = window.fetch;
window.fetch = async function(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      options.headers = options.headers || {};
      if (options.headers instanceof Headers) {
        options.headers.set('X-CSRF-Token', csrfToken);
      } else {
        options.headers['X-CSRF-Token'] = csrfToken;
      }
    }
  }
  const resp = await _originalFetch.call(window, url, options);
  if (resp.status === 401 && typeof url === 'string' && url.startsWith('/webui/')) {
    // Don't redirect if we're on the login page already
    if (!window.location.pathname.startsWith('/webui/login')) {
      sessionStorage.removeItem('csrf_token');
      window.location.href = '/webui/login';
    }
  }
  return resp;
};

// ===================================================================
// Section 1: State Management
// ===================================================================

const state = {
  speakers: [],       // loaded from server
  config: {},         // loaded from server (baseUrl, hasSpotify)
  // Runtime state (not persisted)
  nowPlaying: {},
  volumes: {},
  websockets: {},
  pollTimer: null,
  _ready: false,

  async loadFromServer() {
    try {
      const [config, speakers] = await Promise.all([
        fetch('/webui/api/config').then(r => r.json()),
        fetch('/webui/api/speakers').then(r => r.json()),
      ]);
      this.config = config;
      this.speakers = speakers;
      this._ready = true;
    } catch (err) {
      console.error('Failed to load state from server:', err);
      this._ready = true; // proceed anyway
    }
  },

  async addSpeaker(speaker) {
    try {
      const resp = await fetch('/webui/api/speakers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(speaker),
      });
      if (resp.status === 409) {
        // Already exists, just make sure it's in our local list
        if (!this.speakers.find(s => s.ipAddress === speaker.ipAddress)) {
          this.speakers.push(speaker);
        }
        return;
      }
      if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
      this.speakers.push(speaker);
    } catch (err) {
      console.error('addSpeaker failed:', err);
      showToast('Failed to save speaker: ' + err.message, 'error');
    }
  },

  async removeSpeaker(ip) {
    try {
      await fetch(`/webui/api/speakers/${ip}`, { method: 'DELETE' });
      this.speakers = this.speakers.filter(s => s.ipAddress !== ip);
    } catch (err) {
      showToast('Failed to remove speaker: ' + err.message, 'error');
    }
  },

  async updateSpeaker(ip, updates) {
    try {
      await fetch(`/webui/api/speakers/${ip}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      const idx = this.speakers.findIndex(s => s.ipAddress === ip);
      if (idx >= 0) Object.assign(this.speakers[idx], updates);
    } catch (err) {
      showToast('Failed to update speaker: ' + err.message, 'error');
    }
  },
};

// ===================================================================
// Section 2: API Client
// ===================================================================

const api = {
  async speakerGet(ip, path) {
    const resp = await fetch(`/webui/api/speaker/${ip}/${path}`);
    if (!resp.ok) throw new Error(`Speaker error: ${resp.status}`);
    const text = await resp.text();
    return new DOMParser().parseFromString(text, 'text/xml');
  },

  async speakerPost(ip, path, xmlBody) {
    const resp = await fetch(`/webui/api/speaker/${ip}/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/xml' },
      body: xmlBody,
    });
    if (!resp.ok) throw new Error(`Speaker error: ${resp.status}`);
    const text = await resp.text();
    return text ? new DOMParser().parseFromString(text, 'text/xml') : null;
  },

  // Management API — proxied through the server (no browser-side auth needed)
  async mgmtGet(path) {
    // path should start with /mgmt/..., strip the /mgmt prefix since the proxy adds it
    const proxyPath = path.replace(/^\/mgmt\//, '');
    const resp = await fetch(`/webui/api/mgmt/${proxyPath}`);
    if (!resp.ok) throw new Error(`Mgmt error: ${resp.status}`);
    return resp.json();
  },

  async mgmtPost(path, body = {}) {
    const proxyPath = path.replace(/^\/mgmt\//, '');
    const resp = await fetch(`/webui/api/mgmt/${proxyPath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`Mgmt error: ${resp.status}`);
    const text = await resp.text();
    return text ? JSON.parse(text) : null;
  },

  async tuneinGet(path, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const resp = await fetch(`/webui/api/tunein/${path}${qs ? '?' + qs : ''}`);
    if (!resp.ok) throw new Error(`TuneIn error: ${resp.status}`);
    const text = await resp.text();
    return new DOMParser().parseFromString(text, 'text/xml');
  },
};

// ===================================================================
// Section 3: XML Parsers
// ===================================================================

function parseInfo(xml) {
  const info = xml.querySelector('info');
  return {
    name: info?.querySelector('name')?.textContent || '',
    type: info?.querySelector('type')?.textContent || '',
    deviceId: info?.getAttribute('deviceID') || '',
    margeUrl: info?.querySelector('margeURL')?.textContent || '',
    accountId: info?.querySelector('margeAccountUUID')?.textContent || '',
  };
}

function parseVolume(xml) {
  const vol = xml.querySelector('volume');
  return {
    targetVolume: parseInt(vol?.querySelector('targetvolume')?.textContent || '0'),
    actualVolume: parseInt(vol?.querySelector('actualvolume')?.textContent || '0'),
    muteEnabled: vol?.querySelector('muteenabled')?.textContent === 'true',
  };
}

function parseNowPlaying(xml) {
  const np = xml.querySelector('nowPlaying');
  const ci = np?.querySelector('ContentItem');
  return {
    source: np?.getAttribute('source') || '',
    sourceAccount: np?.getAttribute('sourceAccount') || '',
    track: np?.querySelector('track')?.textContent || '',
    artist: np?.querySelector('artist')?.textContent || '',
    album: np?.querySelector('album')?.textContent || '',
    art: np?.querySelector('art')?.textContent || '',
    artImageStatus: np?.querySelector('art')?.getAttribute('artImageStatus') || '',
    containerArt: ci?.querySelector('containerArt')?.textContent || '',
    itemName: ci?.querySelector('itemName')?.textContent || '',
    location: ci?.getAttribute('location') || '',
    shuffleSetting: np?.querySelector('shuffleSetting')?.textContent || '',
    repeatSetting: np?.querySelector('repeatSetting')?.textContent || '',
    playStatus: np?.querySelector('playStatus')?.textContent || '',
  };
}

function parsePresets(xml) {
  const presets = [];
  xml.querySelectorAll('preset').forEach(p => {
    const ci = p.querySelector('ContentItem');
    presets.push({
      id: p.getAttribute('id'),
      itemName: ci?.querySelector('itemName')?.textContent || '',
      containerArt: ci?.querySelector('containerArt')?.textContent || '',
      source: ci?.getAttribute('source') || '',
      location: ci?.getAttribute('location') || '',
      type: ci?.getAttribute('type') || '',
      sourceAccount: ci?.getAttribute('sourceAccount') || '',
      isPresetable: ci?.getAttribute('isPresetable') === 'true',
    });
  });
  return presets;
}

function parseRecents(xml) {
  const recents = [];
  xml.querySelectorAll('recent').forEach(r => {
    const ci = r.querySelector('ContentItem');
    recents.push({
      deviceId: r.getAttribute('deviceID') || '',
      utcTime: parseInt(r.getAttribute('utcTime') || '0'),
      id: r.getAttribute('id') || '',
      itemName: ci?.querySelector('itemName')?.textContent || '',
      containerArt: ci?.querySelector('containerArt')?.textContent || '',
      source: ci?.getAttribute('source') || '',
      location: ci?.getAttribute('location') || '',
      type: ci?.getAttribute('type') || '',
      isPresetable: ci?.getAttribute('isPresetable') === 'true',
      sourceAccount: ci?.getAttribute('sourceAccount') || '',
    });
  });
  return recents.sort((a, b) => b.utcTime - a.utcTime);
}

function parseZone(xml) {
  const zone = xml.querySelector('zone');
  if (!zone || !zone.getAttribute('master')) return null;
  const members = [];
  zone.querySelectorAll('member').forEach(m => {
    members.push({
      deviceId: m.textContent?.trim() || '',
      ipAddress: m.getAttribute('ipaddress') || '',
    });
  });
  return {
    masterId: zone.getAttribute('master'),
    members,
    senderIpAddress: zone.getAttribute('senderIPAddress') || '',
    senderIsMaster: zone.getAttribute('senderIsMaster') === 'true',
  };
}

// ===================================================================
// Section 4: Router
// ===================================================================

const routes = [
  { pattern: /^\/speakers$/, render: renderSpeakerList },
  { pattern: /^\/speaker\/([^/]+)$/, render: renderSpeakerDetail },
  { pattern: /^\/presets\/([^/]+)$/, render: renderPresets },
  { pattern: /^\/preset\/([^/]+)\/(\d+)$/, render: renderPresetDetail },
  { pattern: /^\/preset\/([^/]+)\/(\d+)\/edit-spotify$/, render: renderEditSpotifyPreset },
  { pattern: /^\/preset\/([^/]+)\/(\d+)\/edit-tunein$/, render: renderEditTuneInPreset },
  { pattern: /^\/preset\/([^/]+)\/(\d+)\/edit-radio$/, render: renderEditInternetRadioPreset },
  { pattern: /^\/recents\/([^/]+)$/, render: renderRecents },
  { pattern: /^\/remote\/([^/]+)$/, render: renderRemoteControl },
  { pattern: /^\/zones\/([^/]+)$/, render: renderZones },
  { pattern: /^\/spotify$/, render: renderSpotifyAccounts },
  { pattern: /^\/events\/([^/]+)$/, render: renderDeviceEvents },
  { pattern: /^\/config$/, render: renderConfig },
];

function navigate(hash) {
  window.location.hash = hash;
}

function handleRoute() {
  const hash = window.location.hash.slice(1) || '/speakers';
  const main = document.getElementById('main');

  // Update nav active state
  document.querySelectorAll('.nav-item').forEach(item => {
    const tab = item.dataset.tab;
    const isActive =
      hash.startsWith(`/${tab}`) ||
      (tab === 'speakers' &&
        (hash.startsWith('/speaker') ||
          hash.startsWith('/preset') ||
          hash.startsWith('/recents') ||
          hash.startsWith('/remote') ||
          hash.startsWith('/zones') ||
          hash.startsWith('/events')));
    item.classList.toggle('active', isActive);
  });

  for (const route of routes) {
    const match = hash.match(route.pattern);
    if (match) {
      const params = match.slice(1);
      main.innerHTML = '';
      main.classList.add('page-enter');
      route.render(main, ...params);
      requestAnimationFrame(() => main.classList.remove('page-enter'));
      return;
    }
  }

  main.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#x1F50D;</div><p>Page not found</p></div>';
}

window.addEventListener('hashchange', handleRoute);

// ===================================================================
// Section 5: Utility Functions
// ===================================================================

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function timeAgo(unixSeconds) {
  const seconds = Math.floor(Date.now() / 1000) - unixSeconds;
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function sourceBadge(source) {
  const colors = {
    SPOTIFY: 'badge-spotify',
    TUNEIN: 'badge-tunein',
    LOCAL_INTERNET_RADIO: 'badge-radio',
    PRODUCT: 'badge-product',
  };
  return `<span class="badge ${colors[source] || ''}">${escapeHtml(source || 'Unknown')}</span>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeXml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

// Proxy external image URLs through our server to avoid browser blocking
// (tracking protection, ad blockers, mixed-content).
function proxyImage(url) {
  if (!url) return '';
  return `/webui/api/image?url=${encodeURIComponent(url)}`;
}

function decodeSpotifyUri(location) {
  const match = location.match(/\/playback\/container\/(.+)/);
  if (!match) return null;
  try {
    return atob(match[1]);
  } catch {
    return null;
  }
}

function spotifyWebUrl(uri) {
  if (!uri) return null;
  const parts = uri.split(':');
  if (parts.length >= 3) return `https://open.spotify.com/${parts[1]}/${parts[2]}`;
  return null;
}

const EMOJIS = ['🔊', '🎵', '🎧', '📻', '🎤', '🎸', '🎹', '🏠', '🛋️', '🛏️', '🍳', '📺', '🍿', '🛁', '🚿', '🍽️', '🧸', '💿'];

/** Render an emoji picker and return the container element. onSelect is called with the chosen emoji. */
function renderEmojiPicker(selectedEmoji, onSelect) {
  const container = document.createElement('div');
  container.className = 'emoji-picker mb-2';
  EMOJIS.forEach(em => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'emoji-option' + (em === selectedEmoji ? ' selected' : '');
    btn.textContent = em;
    btn.addEventListener('click', () => {
      container.querySelectorAll('.emoji-option').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      onSelect(em);
    });
    container.appendChild(btn);
  });
  return container;
}

/** Show a confirmation dialog. Returns a promise that resolves true/false. */
function confirmDialog(title, message) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'dialog-overlay';
    overlay.innerHTML = `
      <div class="dialog">
        <h2>${escapeHtml(title)}</h2>
        <p>${escapeHtml(message)}</p>
        <div class="dialog-actions">
          <button class="btn" data-action="cancel">Cancel</button>
          <button class="btn btn-danger" data-action="confirm">Confirm</button>
        </div>
      </div>`;
    overlay.querySelector('[data-action="cancel"]').addEventListener('click', () => {
      overlay.remove();
      resolve(false);
    });
    overlay.querySelector('[data-action="confirm"]').addEventListener('click', () => {
      overlay.remove();
      resolve(true);
    });
    overlay.addEventListener('click', e => {
      if (e.target === overlay) {
        overlay.remove();
        resolve(false);
      }
    });
    document.body.appendChild(overlay);
  });
}

function showSpinner(container) {
  container.innerHTML = '<div class="spinner"></div>';
}

/** Generate a ContentItem XML string from an object */
function contentItemXml(item) {
  return `<ContentItem source="${escapeXml(item.source)}" type="${escapeXml(item.type)}" location="${escapeXml(item.location)}" sourceAccount="${escapeXml(item.sourceAccount || '')}" isPresetable="${item.isPresetable ? 'true' : 'false'}"><itemName>${escapeXml(item.itemName)}</itemName><containerArt>${escapeXml(item.containerArt || '')}</containerArt></ContentItem>`;
}

/** Create a cleanup controller for timers/listeners. Call cleanup() on hashchange. */
function createCleanup() {
  const fns = [];
  const cleanup = () => fns.forEach(fn => fn());
  const onNav = () => {
    cleanup();
    window.removeEventListener('hashchange', onNav);
  };
  window.addEventListener('hashchange', onNav);
  return {
    add(fn) { fns.push(fn); },
    cleanup,
  };
}

// ===================================================================
// Section 6: WebSocket Manager
// ===================================================================

function connectWebSocket(ip) {
  if (state.websockets[ip]) return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/webui/ws/speaker/${ip}`, ['gabbo']);
  state.websockets[ip] = ws;

  ws.onmessage = event => {
    try {
      const xml = new DOMParser().parseFromString(event.data, 'text/xml');
      const updates = xml.querySelector('updates');
      if (!updates) return;
      if (updates.querySelector('volumeUpdated')) {
        const vol = parseVolume(xml);
        state.volumes[ip] = vol;
        document.dispatchEvent(new CustomEvent('sc:volume', { detail: { ip, volume: vol } }));
      }
      if (updates.querySelector('nowPlayingUpdated')) {
        const np = parseNowPlaying(xml);
        state.nowPlaying[ip] = np;
        document.dispatchEvent(new CustomEvent('sc:nowplaying', { detail: { ip, nowPlaying: np } }));
      }
      if (updates.querySelector('zoneUpdated')) {
        document.dispatchEvent(new CustomEvent('sc:zone', { detail: { ip } }));
      }
    } catch {
      // Ignore parse errors from WebSocket
    }
  };

  ws.onclose = () => {
    delete state.websockets[ip];
    setTimeout(() => {
      if (window.location.hash.includes(ip)) connectWebSocket(ip);
    }, 3000);
  };

  ws.onerror = () => ws.close();
}

function disconnectWebSocket(ip) {
  if (state.websockets[ip]) {
    state.websockets[ip].close();
    delete state.websockets[ip];
  }
}

// ===================================================================
// Section 7: Page Renderers
// ===================================================================

// -------------------------------------------------------------------
// 7.1: Speaker List
// -------------------------------------------------------------------

function renderSpeakerList(main) {
  const cleaner = createCleanup();

  main.innerHTML = `<h1>Speakers</h1><div id="speaker-cards"></div>`;
  const cardsEl = main.querySelector('#speaker-cards');

  function renderCards() {
    if (state.speakers.length === 0) {
      cardsEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">&#x1F50A;</div>
          <p>No speakers yet. Add one to get started.</p>
        </div>`;
      return;
    }
    cardsEl.innerHTML = state.speakers
      .map(s => {
        const np = state.nowPlaying[s.ipAddress];
        const hasArt = np && np.art && np.artImageStatus === 'IMAGE_PRESENT';
        const miniArtUrl = np && (hasArt ? np.art : np.containerArt);
        const npHtml = np && np.track
          ? `<div class="mini-np">
              ${miniArtUrl ? `<img class="mini-np-art" src="${proxyImage(miniArtUrl)}" alt="" onerror="this.style.display='none'">` : ''}
              <div class="mini-np-text">${escapeHtml(np.track)}${np.artist ? ' — ' + escapeHtml(np.artist) : ''}</div>
            </div>`
          : '';
        return `
          <div class="card card-clickable" data-ip="${escapeHtml(s.ipAddress)}" data-id="${escapeHtml(s.id)}">
            <div class="card-header">
              <div class="card-emoji">${escapeHtml(s.emoji || '🔊')}</div>
              <div>
                <div class="card-title">${escapeHtml(s.name)}</div>
                <div class="card-subtitle">${escapeHtml(s.type)} &middot; <span class="mono">${escapeHtml(s.ipAddress)}</span></div>
              </div>
            </div>
            ${npHtml}
          </div>`;
      })
      .join('');

    cardsEl.querySelectorAll('.card-clickable').forEach(card => {
      card.addEventListener('click', () => navigate('#/speaker/' + card.dataset.ip));
      card.addEventListener('contextmenu', async e => {
        e.preventDefault();
        const ip = card.dataset.ip;
        const ok = await confirmDialog('Delete Speaker', `Remove ${ip} from your list?`);
        if (ok) {
          await state.removeSpeaker(ip);
          delete state.nowPlaying[ip];
          delete state.volumes[ip];
          renderCards();
        }
      });
    });
  }

  renderCards();

  // Poll now-playing for each speaker
  async function poll() {
    for (const s of state.speakers) {
      try {
        const xml = await api.speakerGet(s.ipAddress, 'nowPlaying');
        state.nowPlaying[s.ipAddress] = parseNowPlaying(xml);
      } catch {
        // Speaker might be offline
      }
    }
    renderCards();
  }
  poll();
  const timer = setInterval(poll, 8000);
  cleaner.add(() => clearInterval(timer));

  // FAB: Add Speaker
  const fab = document.createElement('button');
  fab.className = 'fab';
  fab.innerHTML = '+';
  fab.title = 'Add Speaker';
  fab.addEventListener('click', showAddSpeakerDialog);
  main.appendChild(fab);

  function showAddSpeakerDialog() {
    const overlay = document.createElement('div');
    overlay.className = 'dialog-overlay';
    overlay.innerHTML = `
      <div class="dialog">
        <h2>Add Speaker</h2>
        <div class="btn-group mb-2">
          <button class="btn btn-primary" id="add-by-ip">Add by IP</button>
          <button class="btn" id="add-from-account">Add from Account</button>
        </div>
        <div id="add-form"></div>
        <div class="dialog-actions">
          <button class="btn" id="add-cancel">Cancel</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    overlay.querySelector('#add-cancel').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

    overlay.querySelector('#add-by-ip').addEventListener('click', () => showAddByIpForm(overlay));
    overlay.querySelector('#add-from-account').addEventListener('click', () => addFromAccount(overlay));
  }

  function showAddByIpForm(overlay) {
    const form = overlay.querySelector('#add-form');
    let selectedEmoji = '🔊';
    form.innerHTML = `
      <div class="form-group"><label>Emoji</label><div id="emoji-pick"></div></div>
      <div class="form-group"><label>IP Address</label><input id="add-ip" type="text" placeholder="192.168.1.100"></div>
      <button class="btn btn-primary mt-1" id="add-ip-submit">Add</button>
      <div id="add-ip-status" class="text-sm text-muted mt-1"></div>`;
    const pickerContainer = form.querySelector('#emoji-pick');
    pickerContainer.appendChild(renderEmojiPicker(selectedEmoji, em => { selectedEmoji = em; }));

    form.querySelector('#add-ip-submit').addEventListener('click', async () => {
      const ip = form.querySelector('#add-ip').value.trim();
      if (!ip) return;
      const statusEl = form.querySelector('#add-ip-status');
      statusEl.textContent = 'Fetching speaker info...';
      try {
        const xml = await api.speakerGet(ip, 'info');
        const info = parseInfo(xml);
        const speaker = {
          id: info.deviceId || ip,
          name: info.name || ip,
          emoji: selectedEmoji,
          ipAddress: ip,
          type: info.type || 'Unknown',
          deviceId: info.deviceId || '',
        };
        await state.addSpeaker(speaker);
        showToast(`Added ${speaker.name}`, 'success');
        overlay.remove();
        renderCards();
      } catch (err) {
        statusEl.textContent = err.message;
        showToast(err.message, 'error');
      }
    });
  }

  async function addFromAccount(overlay) {
    const form = overlay.querySelector('#add-form');
    form.innerHTML = '<div class="spinner"></div>';
    try {
      // Use the server's discover endpoint which reads all accounts from the datastore
      const resp = await fetch('/webui/api/discover-speakers');
      if (!resp.ok) throw new Error('Failed to discover speakers');
      const data = await resp.json();
      const discovered = data.speakers || [];

      if (discovered.length === 0) {
        form.innerHTML = '<p class="text-muted">No speakers found in the datastore. Try adding by IP.</p>';
        return;
      }
      let added = 0;
      for (const sp of discovered) {
        const ip = sp.ipAddress;
        if (!ip) continue;
        if (state.speakers.find(s => s.ipAddress === ip)) continue;
        try {
          const xml = await api.speakerGet(ip, 'info');
          const info = parseInfo(xml);
          await state.addSpeaker({
            id: info.deviceId || ip,
            name: info.name || ip,
            emoji: '🔊',
            ipAddress: ip,
            type: info.type || 'Unknown',
            deviceId: info.deviceId || '',
          });
          added++;
        } catch {
          // Skip unreachable speakers
        }
      }
      showToast(`Added ${added} speaker(s)`, 'success');
      overlay.remove();
      renderCards();
    } catch (err) {
      form.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      showToast(err.message, 'error');
    }
  }
}

// -------------------------------------------------------------------
// 7.2: Speaker Detail
// -------------------------------------------------------------------

function renderSpeakerDetail(main, ip) {
  const cleaner = createCleanup();
  const speaker = state.speakers.find(s => s.ipAddress === ip);
  if (!speaker) {
    main.innerHTML = '<div class="empty-state"><p>Speaker not found</p></div>';
    return;
  }

  connectWebSocket(ip);
  cleaner.add(() => disconnectWebSocket(ip));

  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>${escapeHtml(speaker.emoji || '🔊')} ${escapeHtml(speaker.name)}</h1>
      <div class="actions-menu">
        <button class="btn btn-sm" id="actions-toggle">&#x22EE;</button>
        <div class="actions-dropdown" id="actions-dropdown" style="display:none"></div>
      </div>
    </div>
    <div id="now-playing-section"><div class="spinner"></div></div>
    <div id="volume-section" class="mb-2"></div>
    <h2>Presets</h2>
    <div id="presets-grid" class="grid-2x3 mb-2"></div>
    <a href="#/presets/${escapeHtml(ip)}" class="btn btn-sm mb-3">Manage Presets</a>
  `;

  main.querySelector('#back-btn').addEventListener('click', () => navigate('#/speakers'));

  // Actions dropdown
  const toggle = main.querySelector('#actions-toggle');
  const dropdown = main.querySelector('#actions-dropdown');
  dropdown.innerHTML = `
    <button class="actions-dropdown-item" data-action="edit">Edit Speaker</button>
    <button class="actions-dropdown-item" data-action="remote">Remote Control</button>
    <button class="actions-dropdown-item" data-action="recents">Recents</button>
    <button class="actions-dropdown-item" data-action="events">Device Events</button>
    <button class="actions-dropdown-item" data-action="zones">Zones</button>
    <button class="actions-dropdown-item" data-action="standby">Standby</button>
    <button class="actions-dropdown-item danger" data-action="delete">Delete Speaker</button>`;

  let dropdownOpen = false;
  toggle.addEventListener('click', e => {
    e.stopPropagation();
    dropdownOpen = !dropdownOpen;
    dropdown.style.display = dropdownOpen ? 'block' : 'none';
  });
  document.addEventListener('click', () => {
    dropdownOpen = false;
    dropdown.style.display = 'none';
  });

  dropdown.querySelectorAll('.actions-dropdown-item').forEach(btn => {
    btn.addEventListener('click', async () => {
      dropdown.style.display = 'none';
      const action = btn.dataset.action;
      if (action === 'edit') showEditSpeakerDialog(speaker);
      else if (action === 'remote') navigate('#/remote/' + ip);
      else if (action === 'recents') navigate('#/recents/' + ip);
      else if (action === 'events') navigate('#/events/' + speaker.deviceId);
      else if (action === 'zones') navigate('#/zones/' + ip);
      else if (action === 'standby') {
        const ok = await confirmDialog('Standby', 'Put this speaker in standby?');
        if (ok) {
          try {
            await api.speakerGet(ip, 'standby');
            showToast('Standby sent', 'success');
          } catch (err) { showToast(err.message, 'error'); }
        }
      } else if (action === 'delete') {
        const ok = await confirmDialog('Delete Speaker', `Remove ${speaker.name}?`);
        if (ok) {
          await state.removeSpeaker(ip);
          navigate('#/speakers');
        }
      }
    });
  });

  function showEditSpeakerDialog(spk) {
    let selectedEmoji = spk.emoji || '🔊';
    let newName = spk.name;
    const overlay = document.createElement('div');
    overlay.className = 'dialog-overlay';
    overlay.innerHTML = `
      <div class="dialog">
        <h2>Edit Speaker</h2>
        <div class="form-group"><label>Emoji</label><div id="edit-emoji-pick"></div></div>
        <div class="form-group"><label>Name</label><input id="edit-name" type="text" value="${escapeHtml(newName)}"></div>
        <div class="dialog-actions">
          <button class="btn" id="edit-cancel">Cancel</button>
          <button class="btn btn-primary" id="edit-save">Save</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#edit-emoji-pick').appendChild(
      renderEmojiPicker(selectedEmoji, em => { selectedEmoji = em; })
    );
    overlay.querySelector('#edit-cancel').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#edit-save').addEventListener('click', async () => {
      newName = overlay.querySelector('#edit-name').value.trim() || spk.name;
      await state.updateSpeaker(ip, { emoji: selectedEmoji, name: newName });
      // Also try renaming on speaker itself
      try {
        await api.speakerPost(ip, 'name', `<name>${escapeXml(newName)}</name>`);
      } catch { /* ignore */ }
      overlay.remove();
      // Re-render page
      main.innerHTML = '';
      renderSpeakerDetail(main, ip);
    });
  }

  // Fetch data in parallel
  async function loadData() {
    try {
      const [npXml, volXml, presetsXml] = await Promise.all([
        api.speakerGet(ip, 'nowPlaying'),
        api.speakerGet(ip, 'volume'),
        api.speakerGet(ip, 'presets'),
      ]);
      const np = parseNowPlaying(npXml);
      const vol = parseVolume(volXml);
      const presets = parsePresets(presetsXml);

      state.nowPlaying[ip] = np;
      state.volumes[ip] = vol;

      renderNowPlaying(np);
      renderVolumeControl(vol);
      renderPresetsGrid(presets);
    } catch (err) {
      showToast(err.message, 'error');
      main.querySelector('#now-playing-section').innerHTML =
        `<div class="empty-state"><p>Could not reach speaker at ${escapeHtml(ip)}</p></div>`;
    }
  }

  function renderNowPlaying(np) {
    const section = main.querySelector('#now-playing-section');
    const hasArt = np.art && np.artImageStatus === 'IMAGE_PRESENT';
    // Use album art if available, fall back to station/container art (album CDN may be dead)
    const artUrl = hasArt ? np.art : np.containerArt;
    const spotifyUri = np.source === 'SPOTIFY' ? decodeSpotifyUri(np.location || '') : null;
    const spotifyUrl = spotifyWebUrl(spotifyUri);
    const fallbackSrc = np.containerArt && np.containerArt !== np.art ? proxyImage(np.containerArt) : '';
    section.innerHTML = `
      <div class="now-playing">
        ${artUrl
          ? `<img class="now-playing-art" src="${proxyImage(artUrl)}" alt="Album Art"${fallbackSrc ? ` onerror="this.onerror=null;this.src='${fallbackSrc}'"` : ` onerror="this.style.display='none'"`}>`
          : `<div class="now-playing-placeholder"><span>${escapeHtml(speaker.emoji || '🔊')}</span><span class="text-sm">${escapeHtml(speaker.name)}</span></div>`}
        <div class="now-playing-info">
          <div class="now-playing-track">${escapeHtml(np.track || 'Nothing playing')}</div>
          ${np.artist ? `<div class="now-playing-artist">${escapeHtml(np.artist)}</div>` : ''}
          ${np.album ? `<div class="now-playing-album">${escapeHtml(np.album)}</div>` : ''}
          <div class="now-playing-controls">
            <button class="btn btn-icon" id="prev-btn" title="Previous Track">&#x23EE;</button>
            <button class="btn btn-icon btn-lg" id="play-pause-btn" title="Play/Pause">&#x23EF;</button>
            <button class="btn btn-icon" id="next-btn" title="Next Track">&#x23ED;</button>
          </div>
          <div class="now-playing-controls-secondary">
            <button class="btn btn-icon btn-sm ${np.shuffleSetting === 'SHUFFLE_ON' ? 'active' : ''}" id="shuffle-btn" title="Shuffle">&#x1F500;</button>
            <button class="btn btn-icon btn-sm ${np.repeatSetting !== 'REPEAT_OFF' ? 'active' : ''}" id="repeat-btn" title="Repeat">${np.repeatSetting === 'REPEAT_ONE' ? '&#x1F502;' : '&#x1F501;'}</button>
            ${sourceBadge(np.source)}
            ${spotifyUrl ? `<a href="${escapeHtml(spotifyUrl)}" target="_blank" rel="noopener" class="btn btn-sm">Open Spotify</a>` : ''}
          </div>
        </div>
      </div>`;
    async function sendKey(keyValue) {
      try {
        await api.speakerPost(ip, 'key', `<key state="press" sender="Gabbo">${keyValue}</key>`);
        await api.speakerPost(ip, 'key', `<key state="release" sender="Gabbo">${keyValue}</key>`);
      } catch (err) { showToast(err.message, 'error'); }
    }

    section.querySelector('#play-pause-btn')?.addEventListener('click', () => sendKey('PLAY_PAUSE'));
    section.querySelector('#prev-btn')?.addEventListener('click', () => sendKey('PREV_TRACK'));
    section.querySelector('#next-btn')?.addEventListener('click', () => sendKey('NEXT_TRACK'));
    section.querySelector('#shuffle-btn')?.addEventListener('click', () =>
      sendKey(np.shuffleSetting === 'SHUFFLE_ON' ? 'SHUFFLE_OFF' : 'SHUFFLE_ON'));
    section.querySelector('#repeat-btn')?.addEventListener('click', () => {
      if (np.repeatSetting === 'REPEAT_OFF') sendKey('REPEAT_ALL');
      else if (np.repeatSetting === 'REPEAT_ALL') sendKey('REPEAT_ONE');
      else sendKey('REPEAT_OFF');
    });
  }

  function renderVolumeControl(vol) {
    const section = main.querySelector('#volume-section');
    section.innerHTML = `
      <div class="card">
        <h3>Volume</h3>
        <div class="volume-control">
          <button class="btn btn-icon btn-sm" id="vol-down">&#x2212;</button>
          <input type="range" id="vol-slider" min="0" max="100" value="${vol.targetVolume}">
          <button class="btn btn-icon btn-sm" id="vol-up">+</button>
          <span class="volume-label" id="vol-label">${vol.targetVolume}</span>
          <button class="btn btn-sm" id="mute-btn">${vol.muteEnabled ? '&#x1F507;' : '&#x1F50A;'}</button>
        </div>
      </div>`;

    let debounceTimer = null;
    const slider = section.querySelector('#vol-slider');
    const label = section.querySelector('#vol-label');

    function setVolume(v) {
      v = Math.max(0, Math.min(100, v));
      slider.value = v;
      label.textContent = v;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        try {
          await api.speakerPost(ip, 'volume', `<volume>${v}</volume>`);
        } catch (err) { showToast(err.message, 'error'); }
      }, 300);
    }

    slider.addEventListener('input', () => setVolume(parseInt(slider.value)));
    section.querySelector('#vol-down').addEventListener('click', () => setVolume(parseInt(slider.value) - 5));
    section.querySelector('#vol-up').addEventListener('click', () => setVolume(parseInt(slider.value) + 5));
    section.querySelector('#mute-btn').addEventListener('click', async () => {
      try {
        await api.speakerPost(ip, 'key', '<key state="press" sender="Gabbo">MUTE</key>');
        await api.speakerPost(ip, 'key', '<key state="release" sender="Gabbo">MUTE</key>');
      } catch (err) { showToast(err.message, 'error'); }
    });

    // Listen for WS volume updates
    function onVolumeUpdate(e) {
      if (e.detail.ip === ip) {
        slider.value = e.detail.volume.targetVolume;
        label.textContent = e.detail.volume.targetVolume;
        const muteBtn = section.querySelector('#mute-btn');
        if (muteBtn) muteBtn.innerHTML = e.detail.volume.muteEnabled ? '&#x1F507;' : '&#x1F50A;';
      }
    }
    document.addEventListener('sc:volume', onVolumeUpdate);
    cleaner.add(() => document.removeEventListener('sc:volume', onVolumeUpdate));
  }

  function renderPresetsGrid(presets) {
    const grid = main.querySelector('#presets-grid');
    const slots = [];
    for (let i = 1; i <= 6; i++) {
      const p = presets.find(pr => pr.id === String(i));
      slots.push(p || { id: String(i), empty: true });
    }
    grid.innerHTML = slots
      .map(p => {
        if (p.empty) {
          return `<div class="preset-card" data-preset="${p.id}">
            <span class="preset-number">${p.id}</span>
            <div class="preset-card-placeholder">+</div>
            <div class="preset-card-name text-muted">Empty</div>
          </div>`;
        }
        return `<div class="preset-card" data-preset="${p.id}">
          <span class="preset-number">${p.id}</span>
          ${p.containerArt
            ? `<img class="preset-card-art" src="${proxyImage(p.containerArt)}" alt="">`
            : `<div class="preset-card-placeholder">${p.id}</div>`}
          <div class="preset-card-name">${escapeHtml(p.itemName)}</div>
        </div>`;
      })
      .join('');

    grid.querySelectorAll('.preset-card').forEach(card => {
      const presetId = card.dataset.preset;
      const preset = presets.find(pr => pr.id === presetId);
      card.addEventListener('click', () => {
        if (preset) {
          // Play the preset
          (async () => {
            try {
              await api.speakerPost(ip, 'select', contentItemXml(preset));
              showToast(`Playing preset ${presetId}`, 'success');
            } catch (err) { showToast(err.message, 'error'); }
          })();
        } else {
          navigate(`#/preset/${ip}/${presetId}`);
        }
      });
    });
  }

  // Listen for WS now-playing updates
  function onNpUpdate(e) {
    if (e.detail.ip === ip) renderNowPlaying(e.detail.nowPlaying);
  }
  document.addEventListener('sc:nowplaying', onNpUpdate);
  cleaner.add(() => document.removeEventListener('sc:nowplaying', onNpUpdate));

  loadData();
}

// -------------------------------------------------------------------
// 7.3: Presets (Manage)
// -------------------------------------------------------------------

function renderPresets(main, ip) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Presets</h1>
    </div>
    <div id="presets-content"><div class="spinner"></div></div>`;
  main.querySelector('#back-btn').addEventListener('click', () => navigate('#/speaker/' + ip));

  (async () => {
    try {
      const xml = await api.speakerGet(ip, 'presets');
      const presets = parsePresets(xml);
      const container = main.querySelector('#presets-content');
      const slots = [];
      for (let i = 1; i <= 6; i++) {
        const p = presets.find(pr => pr.id === String(i));
        slots.push(p || { id: String(i), empty: true });
      }
      container.innerHTML = '<div class="grid-2x3">' + slots.map(p => {
        if (p.empty) {
          return `<div class="preset-card" data-preset="${p.id}">
            <span class="preset-number">${p.id}</span>
            <div class="preset-card-placeholder" style="font-size:2rem">+</div>
            <div class="preset-card-name text-muted">Empty</div>
          </div>`;
        }
        return `<div class="preset-card" data-preset="${p.id}">
          <span class="preset-number">${p.id}</span>
          ${p.containerArt
            ? `<img class="preset-card-art" src="${proxyImage(p.containerArt)}" alt="">`
            : `<div class="preset-card-placeholder">${p.id}</div>`}
          <div class="preset-card-name">${escapeHtml(p.itemName)}</div>
          ${sourceBadge(p.source)}
        </div>`;
      }).join('') + '</div>';

      container.querySelectorAll('.preset-card').forEach(card => {
        card.addEventListener('click', () => navigate(`#/preset/${ip}/${card.dataset.preset}`));
      });
    } catch (err) {
      showToast(err.message, 'error');
      main.querySelector('#presets-content').innerHTML =
        `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
    }
  })();
}

// -------------------------------------------------------------------
// 7.4: Preset Detail
// -------------------------------------------------------------------

function renderPresetDetail(main, ip, presetId) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Preset ${escapeHtml(presetId)}</h1>
    </div>
    <div id="preset-content"><div class="spinner"></div></div>`;
  main.querySelector('#back-btn').addEventListener('click', () => navigate('#/presets/' + ip));

  (async () => {
    try {
      const xml = await api.speakerGet(ip, 'presets');
      const presets = parsePresets(xml);
      const preset = presets.find(p => p.id === presetId);
      const container = main.querySelector('#preset-content');

      if (!preset) {
        // Empty slot
        container.innerHTML = `
          <div class="empty-state mb-2">
            <div class="empty-state-icon">+</div>
            <p>This preset slot is empty</p>
          </div>
          <div class="btn-group" style="justify-content:center">
            <button class="btn btn-primary" data-edit="spotify">Set Spotify Preset</button>
            <button class="btn" data-edit="tunein">Set TuneIn Preset</button>
            <button class="btn" data-edit="radio">Set Internet Radio Preset</button>
          </div>`;
        container.querySelector('[data-edit="spotify"]').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}/edit-spotify`));
        container.querySelector('[data-edit="tunein"]').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}/edit-tunein`));
        container.querySelector('[data-edit="radio"]').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}/edit-radio`));
        return;
      }

      // Filled slot
      const spotifyUri = preset.source === 'SPOTIFY' ? decodeSpotifyUri(preset.location) : null;
      const spotifyUrl = spotifyWebUrl(spotifyUri);

      container.innerHTML = `
        ${preset.containerArt
          ? `<img class="large-art" src="${proxyImage(preset.containerArt)}" alt="">`
          : `<div class="large-art flex-center" style="font-size:3rem;color:var(--text-hint)">${presetId}</div>`}
        <h2 class="text-center mb-2">${escapeHtml(preset.itemName)}</h2>
        <div class="card">
          <div class="detail-row"><span class="detail-row-label">Preset #</span><span class="detail-row-value">${escapeHtml(presetId)}</span></div>
          <div class="detail-row"><span class="detail-row-label">Source</span><span class="detail-row-value">${sourceBadge(preset.source)}</span></div>
          <div class="detail-row"><span class="detail-row-label">Type</span><span class="detail-row-value mono">${escapeHtml(preset.type)}</span></div>
          <div class="detail-row"><span class="detail-row-label">Location</span><span class="detail-row-value mono text-sm">${escapeHtml(preset.location)}</span></div>
          ${spotifyUri ? `<div class="detail-row"><span class="detail-row-label">Spotify URI</span><span class="detail-row-value mono text-sm">${escapeHtml(spotifyUri)}</span></div>` : ''}
          ${preset.sourceAccount ? `<div class="detail-row"><span class="detail-row-label">Account</span><span class="detail-row-value mono text-sm">${escapeHtml(preset.sourceAccount)}</span></div>` : ''}
        </div>
        <div class="btn-group mt-2">
          <button class="btn btn-primary" id="preset-play">&#x25B6; Play</button>
          <button class="btn btn-danger" id="preset-delete">&#x1F5D1; Delete</button>
        </div>
        <div class="btn-group mt-1">
          <button class="btn btn-sm" data-edit="spotify">Edit (Spotify)</button>
          <button class="btn btn-sm" data-edit="tunein">Edit (TuneIn)</button>
          <button class="btn btn-sm" data-edit="radio">Edit (Radio)</button>
        </div>
        ${spotifyUrl ? `<a href="${escapeHtml(spotifyUrl)}" target="_blank" rel="noopener" class="btn btn-sm mt-1">Open in Spotify</a>` : ''}`;

      container.querySelector('#preset-play').addEventListener('click', async () => {
        try {
          await api.speakerPost(ip, 'select', contentItemXml(preset));
          showToast(`Playing preset ${presetId}`, 'success');
        } catch (err) { showToast(err.message, 'error'); }
      });

      container.querySelector('#preset-delete').addEventListener('click', async () => {
        const ok = await confirmDialog('Delete Preset', `Remove preset ${presetId}?`);
        if (ok) {
          try {
            await api.speakerPost(ip, 'removePreset', `<preset id="${presetId}"></preset>`);
            showToast('Preset removed', 'success');
            navigate('#/presets/' + ip);
          } catch (err) { showToast(err.message, 'error'); }
        }
      });

      container.querySelector('[data-edit="spotify"]').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}/edit-spotify`));
      container.querySelector('[data-edit="tunein"]').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}/edit-tunein`));
      container.querySelector('[data-edit="radio"]').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}/edit-radio`));
    } catch (err) {
      showToast(err.message, 'error');
      main.querySelector('#preset-content').innerHTML =
        `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
    }
  })();
}

// -------------------------------------------------------------------
// 7.5: Edit Spotify Preset
// -------------------------------------------------------------------

function renderEditSpotifyPreset(main, ip, presetId) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Spotify Preset ${escapeHtml(presetId)}</h1>
    </div>
    <div class="card">
      <div class="form-group">
        <label>Spotify Account</label>
        <select id="spotify-account"><option value="">Loading accounts...</option></select>
      </div>
      <div class="form-group">
        <label>Spotify URI or URL</label>
        <input id="spotify-uri" type="text" placeholder="spotify:playlist:37i9dQZF1DXcBWIGoYBM5M or https://open.spotify.com/...">
      </div>
      <div id="entity-preview"></div>
      <div class="btn-group mt-2">
        <button class="btn btn-primary" id="spotify-save" disabled>Save Preset</button>
        <a id="spotify-open-link" class="btn btn-sm" style="display:none" target="_blank" rel="noopener">Open in Spotify</a>
      </div>
    </div>`;

  main.querySelector('#back-btn').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}`));

  const accountSelect = main.querySelector('#spotify-account');
  const uriInput = main.querySelector('#spotify-uri');
  const previewEl = main.querySelector('#entity-preview');
  const saveBtn = main.querySelector('#spotify-save');
  const openLink = main.querySelector('#spotify-open-link');

  let entityData = null;
  let debounceTimer = null;

  // Load accounts
  (async () => {
    try {
      const data = await api.mgmtGet('/mgmt/spotify/accounts');
      const accounts = data.accounts || [];
      accountSelect.innerHTML = accounts.map(a =>
        `<option value="${escapeHtml(a.spotifyUserId || '')}">${escapeHtml(a.displayName || a.spotifyUserId || 'Unknown')}</option>`
      ).join('');
    } catch (err) {
      accountSelect.innerHTML = `<option value="">Error loading accounts</option>`;
      showToast(err.message, 'error');
    }
  })();

  function convertUrlToUri(input) {
    // Convert https://open.spotify.com/playlist/xyz?si=... -> spotify:playlist:xyz
    const urlMatch = input.match(/open\.spotify\.com\/(\w+)\/([a-zA-Z0-9]+)/);
    if (urlMatch) return `spotify:${urlMatch[1]}:${urlMatch[2]}`;
    return input.trim();
  }

  uriInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      const raw = uriInput.value.trim();
      if (!raw) { previewEl.innerHTML = ''; saveBtn.disabled = true; openLink.style.display = 'none'; return; }
      const uri = convertUrlToUri(raw);
      if (uri !== raw) uriInput.value = uri;

      const webUrl = spotifyWebUrl(uri);
      if (webUrl) {
        openLink.href = webUrl;
        openLink.style.display = '';
      } else {
        openLink.style.display = 'none';
      }

      previewEl.innerHTML = '<div class="spinner"></div>';
      try {
        const entity = await api.mgmtPost('/mgmt/spotify/entity', { uri });
        entity.image = entity.image || entity.imageUrl || '';
        entityData = entity;
        previewEl.innerHTML = `
          <div class="entity-preview">
            ${entity.image ? `<img src="${proxyImage(entity.image)}" alt="">` : ''}
            <div class="entity-preview-name">${escapeHtml(entity.name || uri)}</div>
          </div>`;
        saveBtn.disabled = false;
      } catch (err) {
        previewEl.innerHTML = `<p class="text-muted text-sm">${escapeHtml(err.message)}</p>`;
        entityData = null;
        saveBtn.disabled = false; // Allow saving even without entity lookup
      }
    }, 500);
  });

  saveBtn.addEventListener('click', async () => {
    const uri = uriInput.value.trim();
    const account = accountSelect.value;
    if (!uri) { showToast('Enter a Spotify URI', 'error'); return; }
    if (!account) { showToast('Select a Spotify account', 'error'); return; }
    const encodedUri = btoa(uri);
    const name = entityData?.name || uri;
    const art = entityData?.image || '';
    const xmlBody = `<preset id="${presetId}"><ContentItem source="SPOTIFY" type="tracklisturl" location="/playback/container/${escapeXml(encodedUri)}" sourceAccount="${escapeXml(account)}" isPresetable="true"><itemName>${escapeXml(name)}</itemName><containerArt>${escapeXml(art)}</containerArt></ContentItem></preset>`;
    try {
      await api.speakerPost(ip, 'storePreset', xmlBody);
      showToast('Preset saved', 'success');
      navigate(`#/preset/${ip}/${presetId}`);
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// -------------------------------------------------------------------
// 7.6: Edit TuneIn Preset
// -------------------------------------------------------------------

function renderEditTuneInPreset(main, ip, presetId) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>TuneIn Preset ${escapeHtml(presetId)}</h1>
    </div>
    <div class="card mb-2">
      <div class="form-group">
        <label>Search TuneIn</label>
        <div style="display:flex;gap:0.5rem">
          <input id="tunein-search" type="text" placeholder="Search stations...">
          <button class="btn btn-primary" id="tunein-search-btn">Search</button>
        </div>
      </div>
    </div>
    <div id="tunein-results"></div>
    <div id="tunein-detail" style="display:none"></div>`;

  main.querySelector('#back-btn').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}`));

  const searchInput = main.querySelector('#tunein-search');
  const searchBtn = main.querySelector('#tunein-search-btn');
  const resultsEl = main.querySelector('#tunein-results');
  const detailEl = main.querySelector('#tunein-detail');

  async function doSearch() {
    const query = searchInput.value.trim();
    if (!query) return;
    resultsEl.innerHTML = '<div class="spinner"></div>';
    detailEl.style.display = 'none';
    try {
      const xml = await api.tuneinGet('search.ashx', { query });
      const outlines = xml.querySelectorAll('outline[type="audio"]');
      if (outlines.length === 0) {
        resultsEl.innerHTML = '<div class="empty-state"><p>No stations found</p></div>';
        return;
      }
      resultsEl.innerHTML = '';
      outlines.forEach(o => {
        const guideId = o.getAttribute('guide_id') || '';
        const name = o.getAttribute('text') || '';
        const subtext = o.getAttribute('subtext') || '';
        const image = o.getAttribute('image') || '';
        const bitrate = o.getAttribute('bitrate') || '';

        const item = document.createElement('div');
        item.className = 'list-item';
        item.style.cursor = 'pointer';
        item.innerHTML = `
          ${image
            ? `<img class="list-item-thumb" src="${escapeHtml(image)}" alt="">`
            : `<div class="list-item-thumb-placeholder">&#x1F4FB;</div>`}
          <div class="list-item-body">
            <div class="list-item-title">${escapeHtml(name)}</div>
            <div class="list-item-subtitle">${escapeHtml(subtext)}${bitrate ? ' &middot; ' + escapeHtml(bitrate) + ' kbps' : ''}</div>
          </div>`;
        item.addEventListener('click', () => showStationDetail(guideId, name, image));
        resultsEl.appendChild(item);
      });
    } catch (err) {
      resultsEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      showToast(err.message, 'error');
    }
  }

  searchBtn.addEventListener('click', doSearch);
  searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

  async function showStationDetail(guideId, fallbackName, fallbackImage) {
    resultsEl.style.display = 'none';
    detailEl.style.display = 'block';
    detailEl.innerHTML = '<div class="spinner"></div>';

    let stationName = fallbackName;
    let stationLogo = fallbackImage;
    let stationSlogan = '';
    let stationDescription = '';
    let stationLocation = '';
    let stationGenre = '';

    try {
      const xml = await api.tuneinGet('describe.ashx', { id: guideId });
      const outline = xml.querySelector('outline');
      if (outline) {
        stationName = outline.getAttribute('text') || stationName;
        stationLogo = outline.getAttribute('image') || stationLogo;
        stationSlogan = outline.getAttribute('slogan') || '';
        stationDescription = outline.getAttribute('description') || '';
        stationLocation = outline.getAttribute('location') || '';
        stationGenre = outline.getAttribute('genre_name') || '';
      }
    } catch { /* use fallback */ }

    detailEl.innerHTML = `
      <div class="card">
        <div style="display:flex;gap:1rem;align-items:flex-start;margin-bottom:1rem">
          ${stationLogo
            ? `<img src="${escapeHtml(stationLogo)}" alt="" style="width:80px;height:80px;border-radius:var(--radius-sm);object-fit:cover">`
            : ''}
          <div>
            <h2>${escapeHtml(stationName)}</h2>
            ${stationSlogan ? `<p class="text-muted text-sm">${escapeHtml(stationSlogan)}</p>` : ''}
          </div>
        </div>
        ${stationDescription ? `<p class="mb-1 text-sm">${escapeHtml(stationDescription)}</p>` : ''}
        ${stationLocation ? `<p class="text-muted text-sm mb-1">Location: ${escapeHtml(stationLocation)}</p>` : ''}
        ${stationGenre ? `<p class="text-muted text-sm mb-2">Genre: ${escapeHtml(stationGenre)}</p>` : ''}
        <div class="btn-group">
          <button class="btn btn-primary" id="tunein-save">Save as Preset ${escapeHtml(presetId)}</button>
          <button class="btn" id="tunein-back-to-results">Back to Results</button>
        </div>
      </div>`;

    detailEl.querySelector('#tunein-back-to-results').addEventListener('click', () => {
      detailEl.style.display = 'none';
      resultsEl.style.display = '';
    });

    detailEl.querySelector('#tunein-save').addEventListener('click', async () => {
      const xmlBody = `<preset id="${presetId}"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/${escapeXml(guideId)}" isPresetable="true"><itemName>${escapeXml(stationName)}</itemName><containerArt>${escapeXml(stationLogo)}</containerArt></ContentItem></preset>`;
      try {
        await api.speakerPost(ip, 'storePreset', xmlBody);
        showToast('Preset saved', 'success');
        navigate(`#/preset/${ip}/${presetId}`);
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
}

// -------------------------------------------------------------------
// 7.7: Edit Internet Radio Preset
// -------------------------------------------------------------------

function renderEditInternetRadioPreset(main, ip, presetId) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Radio Preset ${escapeHtml(presetId)}</h1>
    </div>
    <div class="card">
      <div class="form-group">
        <label>Station Name *</label>
        <input id="radio-name" type="text" placeholder="My Radio Station">
      </div>
      <div class="form-group">
        <label>Stream URL *</label>
        <input id="radio-url" type="url" placeholder="https://stream.example.com/radio.mp3">
      </div>
      <div class="form-group">
        <label>Cover Art URL (optional)</label>
        <input id="radio-art" type="url" placeholder="https://example.com/logo.png">
      </div>
      <div id="radio-art-preview" class="mb-2"></div>
      <button class="btn btn-primary" id="radio-save">Save Preset</button>
    </div>`;

  main.querySelector('#back-btn').addEventListener('click', () => navigate(`#/preset/${ip}/${presetId}`));

  const artInput = main.querySelector('#radio-art');
  const previewEl = main.querySelector('#radio-art-preview');

  artInput.addEventListener('input', () => {
    const url = artInput.value.trim();
    if (url) {
      previewEl.innerHTML = `<img src="${proxyImage(url)}" alt="Preview" style="width:80px;height:80px;border-radius:var(--radius-sm);object-fit:cover" onerror="this.style.display='none'">`;
    } else {
      previewEl.innerHTML = '';
    }
  });

  main.querySelector('#radio-save').addEventListener('click', async () => {
    const name = main.querySelector('#radio-name').value.trim();
    const streamUrl = main.querySelector('#radio-url').value.trim();
    const containerArt = artInput.value.trim();

    if (!name) { showToast('Station name is required', 'error'); return; }
    if (!streamUrl) { showToast('Stream URL is required', 'error'); return; }

    const baseUrl = state.config.baseUrl || window.location.origin;
    const dataPayload = btoa(JSON.stringify({ name, imageUrl: containerArt, streamUrl }));
    const location = `${baseUrl}/core02/svc-bmx-adapter-orion/prod/orion/station?data=${dataPayload}`;

    const xmlBody = `<preset id="${presetId}"><ContentItem source="LOCAL_INTERNET_RADIO" type="stationurl" location="${escapeXml(location)}" isPresetable="true"><itemName>${escapeXml(name)}</itemName><containerArt>${escapeXml(containerArt)}</containerArt></ContentItem></preset>`;
    try {
      await api.speakerPost(ip, 'storePreset', xmlBody);
      showToast('Preset saved', 'success');
      navigate(`#/preset/${ip}/${presetId}`);
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// -------------------------------------------------------------------
// 7.8: Recents
// -------------------------------------------------------------------

function renderRecents(main, ip) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Recents</h1>
    </div>
    <div id="recents-list"><div class="spinner"></div></div>`;
  main.querySelector('#back-btn').addEventListener('click', () => navigate('#/speaker/' + ip));

  (async () => {
    try {
      const xml = await api.speakerGet(ip, 'recents');
      const recents = parseRecents(xml);
      const container = main.querySelector('#recents-list');

      if (recents.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#x1F4DC;</div><p>No recent items</p></div>';
        return;
      }

      container.innerHTML = '';
      recents.forEach(r => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
          ${r.containerArt
            ? `<img class="list-item-thumb" src="${proxyImage(r.containerArt)}" alt="">`
            : `<div class="list-item-thumb-placeholder">${sourceBadge(r.source)}</div>`}
          <div class="list-item-body">
            <div class="list-item-title">${escapeHtml(r.itemName)}</div>
            <div class="list-item-subtitle">${sourceBadge(r.source)} &middot; ${escapeHtml(timeAgo(r.utcTime))}</div>
          </div>
          <div class="list-item-action">
            <button class="btn btn-icon btn-sm play-btn" title="Play">&#x25B6;</button>
          </div>`;

        item.querySelector('.play-btn').addEventListener('click', async () => {
          try {
            await api.speakerPost(ip, 'select', contentItemXml(r));
            showToast(`Playing ${r.itemName}`, 'success');
          } catch (err) { showToast(err.message, 'error'); }
        });

        container.appendChild(item);
      });
    } catch (err) {
      showToast(err.message, 'error');
      main.querySelector('#recents-list').innerHTML =
        `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
    }
  })();
}

// -------------------------------------------------------------------
// 7.9: Remote Control
// -------------------------------------------------------------------

function renderRemoteControl(main, ip) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Remote Control</h1>
    </div>
    <div class="remote-grid">
      <button class="btn remote-full" data-key="POWER" data-mode="tap">&#x23FB; Power</button>
      <button class="btn remote-full" data-key="AUX_INPUT" data-mode="tap">&#x1F50C; AUX Input</button>
      <button class="btn" data-key="PRESET_1" data-mode="tap">1</button>
      <button class="btn" data-key="PRESET_2" data-mode="tap">2</button>
      <button class="btn" data-key="PRESET_3" data-mode="tap">3</button>
      <button class="btn" data-key="PRESET_4" data-mode="tap">4</button>
      <button class="btn" data-key="PRESET_5" data-mode="tap">5</button>
      <button class="btn" data-key="PRESET_6" data-mode="tap">6</button>
      <button class="btn remote-full" data-key="MUTE" data-mode="tap">&#x1F507; Mute</button>
      <button class="btn" data-key="VOLUME_DOWN" data-mode="hold">&#x2212; Vol</button>
      <button class="btn" data-key="VOLUME_UP" data-mode="hold">+ Vol</button>
      <div></div>
      <button class="btn remote-full" data-key="PLAY_PAUSE" data-mode="tap">&#x23EF; Play/Pause</button>
      <button class="btn" data-key="PREV_TRACK" data-mode="tap">&#x23EE; Prev</button>
      <div></div>
      <button class="btn" data-key="NEXT_TRACK" data-mode="tap">&#x23ED; Next</button>
    </div>`;

  main.querySelector('#back-btn').addEventListener('click', () => navigate('#/speaker/' + ip));

  main.querySelectorAll('.remote-grid .btn').forEach(btn => {
    const key = btn.dataset.key;
    const mode = btn.dataset.mode;
    if (!key) return;

    if (mode === 'hold') {
      // Volume: press on mousedown, release on mouseup
      const sendKey = async (keyState) => {
        try {
          await api.speakerPost(ip, 'key', `<key state="${keyState}" sender="Gabbo">${escapeXml(key)}</key>`);
        } catch (err) { showToast(err.message, 'error'); }
      };
      btn.addEventListener('mousedown', () => sendKey('press'));
      btn.addEventListener('mouseup', () => sendKey('release'));
      btn.addEventListener('mouseleave', () => sendKey('release'));
      btn.addEventListener('touchstart', e => { e.preventDefault(); sendKey('press'); });
      btn.addEventListener('touchend', e => { e.preventDefault(); sendKey('release'); });
    } else {
      // Tap: press then release
      btn.addEventListener('click', async () => {
        try {
          await api.speakerPost(ip, 'key', `<key state="press" sender="Gabbo">${escapeXml(key)}</key>`);
          await api.speakerPost(ip, 'key', `<key state="release" sender="Gabbo">${escapeXml(key)}</key>`);
        } catch (err) { showToast(err.message, 'error'); }
      });
    }
  });
}

// -------------------------------------------------------------------
// 7.10: Zones
// -------------------------------------------------------------------

function renderZones(main, ip) {
  const speaker = state.speakers.find(s => s.ipAddress === ip);
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Zones</h1>
    </div>
    <div id="zone-content"><div class="spinner"></div></div>`;
  main.querySelector('#back-btn').addEventListener('click', () => navigate('#/speaker/' + ip));

  const cleaner = createCleanup();

  async function loadZone() {
    const container = main.querySelector('#zone-content');
    try {
      const xml = await api.speakerGet(ip, 'getZone');
      const zone = parseZone(xml);

      if (!zone) {
        container.innerHTML = `
          <div class="empty-state mb-2">
            <div class="empty-state-icon">&#x1F517;</div>
            <p>Not in a zone</p>
          </div>
          <div class="text-center">
            <button class="btn btn-primary" id="create-zone-btn">Create Zone</button>
          </div>`;
        container.querySelector('#create-zone-btn').addEventListener('click', () => showZoneDialog('create'));
        return;
      }

      const isMaster = zone.senderIsMaster;
      container.innerHTML = `
        <div class="card mb-2">
          <h3>Zone Master</h3>
          <p class="mono text-sm">${escapeHtml(zone.masterId)}</p>
        </div>
        <h3>Members</h3>
        <div id="zone-members"></div>
        <div class="btn-group mt-2">
          ${isMaster ? '<button class="btn btn-primary" id="add-slaves-btn">Add Speakers</button>' : ''}
          ${!isMaster ? '<button class="btn btn-danger" id="leave-zone-btn">Leave Zone</button>' : ''}
        </div>`;

      const membersEl = container.querySelector('#zone-members');
      zone.members.forEach(m => {
        const memberDiv = document.createElement('div');
        memberDiv.className = 'list-item';
        const memberSpeaker = state.speakers.find(s => s.ipAddress === m.ipAddress);
        memberDiv.innerHTML = `
          <div class="list-item-body">
            <div class="list-item-title">${escapeHtml(memberSpeaker?.name || m.ipAddress)}</div>
            <div class="list-item-subtitle mono">${escapeHtml(m.ipAddress)} &middot; ${escapeHtml(m.deviceId)}</div>
          </div>
          ${isMaster && m.deviceId !== zone.masterId
            ? `<div class="list-item-action"><button class="btn btn-sm btn-danger remove-member" data-ip="${escapeHtml(m.ipAddress)}" data-device="${escapeHtml(m.deviceId)}">Remove</button></div>`
            : ''}`;
        membersEl.appendChild(memberDiv);
      });

      membersEl.querySelectorAll('.remove-member').forEach(btn => {
        btn.addEventListener('click', async () => {
          try {
            const zoneXml = `<zone master="${escapeXml(zone.masterId)}"><member ipaddress="${escapeXml(btn.dataset.ip)}">${escapeXml(btn.dataset.device)}</member></zone>`;
            await api.speakerPost(ip, 'removeZoneSlave', zoneXml);
            showToast('Member removed', 'success');
            loadZone();
          } catch (err) { showToast(err.message, 'error'); }
        });
      });

      if (isMaster) {
        container.querySelector('#add-slaves-btn')?.addEventListener('click', () => showZoneDialog('add', zone));
      }
      if (!isMaster) {
        container.querySelector('#leave-zone-btn')?.addEventListener('click', async () => {
          try {
            const myMember = zone.members.find(m => m.ipAddress === ip);
            if (myMember) {
              const zoneXml = `<zone master="${escapeXml(zone.masterId)}"><member ipaddress="${escapeXml(ip)}">${escapeXml(myMember.deviceId)}</member></zone>`;
              await api.speakerPost(ip, 'removeZoneSlave', zoneXml);
              showToast('Left zone', 'success');
              loadZone();
            }
          } catch (err) { showToast(err.message, 'error'); }
        });
      }
    } catch (err) {
      container.innerHTML = `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
      showToast(err.message, 'error');
    }
  }

  function showZoneDialog(mode, existingZone) {
    const otherSpeakers = state.speakers.filter(s => s.ipAddress !== ip);
    if (otherSpeakers.length === 0) {
      showToast('No other speakers to add', 'error');
      return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'dialog-overlay';
    overlay.innerHTML = `
      <div class="dialog">
        <h2>${mode === 'create' ? 'Create Zone' : 'Add Speakers'}</h2>
        <div id="zone-checkboxes"></div>
        <div class="dialog-actions">
          <button class="btn" id="zone-cancel">Cancel</button>
          <button class="btn btn-primary" id="zone-confirm">${mode === 'create' ? 'Create' : 'Add'}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const checkboxesEl = overlay.querySelector('#zone-checkboxes');
    otherSpeakers.forEach(s => {
      const div = document.createElement('div');
      div.className = 'form-group';
      div.innerHTML = `
        <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer">
          <input type="checkbox" value="${escapeHtml(s.ipAddress)}" data-device="${escapeHtml(s.deviceId)}" style="width:auto">
          ${escapeHtml(s.emoji || '🔊')} ${escapeHtml(s.name)} <span class="mono text-sm">(${escapeHtml(s.ipAddress)})</span>
        </label>`;
      checkboxesEl.appendChild(div);
    });

    overlay.querySelector('#zone-cancel').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

    overlay.querySelector('#zone-confirm').addEventListener('click', async () => {
      const checked = overlay.querySelectorAll('input[type="checkbox"]:checked');
      if (checked.length === 0) { showToast('Select at least one speaker', 'error'); return; }

      const masterId = speaker?.deviceId || '';
      let membersXml = `<member ipaddress="${escapeXml(ip)}">${escapeXml(masterId)}</member>`;
      checked.forEach(cb => {
        membersXml += `<member ipaddress="${escapeXml(cb.value)}">${escapeXml(cb.dataset.device)}</member>`;
      });
      const zoneXml = `<zone master="${escapeXml(masterId)}">${membersXml}</zone>`;

      try {
        if (mode === 'create') {
          await api.speakerPost(ip, 'setZone', zoneXml);
        } else {
          // For adding slaves, only include new members
          let addXml = '';
          checked.forEach(cb => {
            addXml += `<member ipaddress="${escapeXml(cb.value)}">${escapeXml(cb.dataset.device)}</member>`;
          });
          const addZoneXml = `<zone master="${escapeXml(existingZone.masterId)}">${addXml}</zone>`;
          await api.speakerPost(ip, 'addZoneSlave', addZoneXml);
        }
        showToast(mode === 'create' ? 'Zone created' : 'Speakers added', 'success');
        overlay.remove();
        loadZone();
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  // Listen for zone updates via WS
  function onZoneUpdate(e) {
    if (e.detail.ip === ip) loadZone();
  }
  document.addEventListener('sc:zone', onZoneUpdate);
  cleaner.add(() => document.removeEventListener('sc:zone', onZoneUpdate));

  loadZone();
}

// -------------------------------------------------------------------
// 7.11: Spotify Accounts
// -------------------------------------------------------------------

function renderSpotifyAccounts(main) {
  main.innerHTML = `
    <h1>Spotify Accounts</h1>
    <div id="spotify-content"><div class="spinner"></div></div>`;

  // Config is loaded from server — no client-side check needed

  (async () => {
    try {
      const data = await api.mgmtGet('/mgmt/spotify/accounts');
      const accounts = data.accounts || [];
      const container = main.querySelector('#spotify-content');

      if (accounts.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">&#x1F3B5;</div>
            <p>No Spotify accounts linked yet</p>
          </div>`;
      } else {
        container.innerHTML = '';
        accounts.forEach(a => {
          const card = document.createElement('div');
          card.className = 'card';
          card.innerHTML = `
            <div class="card-header">
              <div class="card-emoji">&#x1F3B5;</div>
              <div>
                <div class="card-title">${escapeHtml(a.displayName || a.spotifyUserId || 'Unknown')}</div>
                <div class="card-subtitle mono">${escapeHtml(a.spotifyUserId || '')}</div>
                ${a.createdAt ? `<div class="card-subtitle">Connected ${escapeHtml(timeAgo(Math.floor(new Date(a.createdAt).getTime() / 1000)))}</div>` : ''}
              </div>
            </div>`;
          container.appendChild(card);
        });
      }

      // FAB: Add Account
      const fab = document.createElement('button');
      fab.className = 'fab';
      fab.innerHTML = '+';
      fab.title = 'Add Spotify Account';
      fab.addEventListener('click', () => {
        // Use the server's base URL for the Spotify OAuth flow
        const baseUrl = state.config.baseUrl || window.location.origin;
        window.open(`${baseUrl}/mgmt/spotify/init`, '_blank');
        showToast('Complete login in the new tab, then refresh', 'info');
      });
      main.appendChild(fab);
    } catch (err) {
      showToast(err.message, 'error');
      main.querySelector('#spotify-content').innerHTML =
        `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
    }
  })();
}

// -------------------------------------------------------------------
// 7.12: Device Events
// -------------------------------------------------------------------

function renderDeviceEvents(main, deviceId) {
  main.innerHTML = `
    <div class="page-header">
      <button class="back-btn" id="back-btn">&#x2190;</button>
      <h1>Device Events</h1>
    </div>
    <p class="text-muted text-sm mb-2 mono">${escapeHtml(deviceId)}</p>
    <div id="events-list"><div class="spinner"></div></div>`;

  // Try to find speaker to navigate back
  const speaker = state.speakers.find(s => s.deviceId === deviceId);
  main.querySelector('#back-btn').addEventListener('click', () => {
    if (speaker) navigate('#/speaker/' + speaker.ipAddress);
    else navigate('#/speakers');
  });

  (async () => {
    try {
      const data = await api.mgmtGet(`/mgmt/devices/${deviceId}/events`);
      const events = data.events || [];
      const container = main.querySelector('#events-list');

      if (events.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#x1F4CB;</div><p>No events recorded</p></div>';
        return;
      }

      // Sort newest first
      const sorted = [...events].sort((a, b) => {
        const tA = new Date(a.timestamp || a.created_at || 0).getTime();
        const tB = new Date(b.timestamp || b.created_at || 0).getTime();
        return tB - tA;
      });

      container.innerHTML = '';
      sorted.forEach(ev => {
        const eventIcons = {
          preset_changed: '&#x1F3B5;',
          volume_changed: '&#x1F50A;',
          power: '&#x23FB;',
          zone_changed: '&#x1F517;',
          now_playing: '&#x25B6;',
        };
        const evType = ev.type || ev.event_type || 'event';
        const icon = eventIcons[evType] || '&#x1F4E2;';
        const ts = ev.timestamp || ev.created_at || '';
        const summary = ev.summary || ev.description || JSON.stringify(ev.data || '');

        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
          <div class="list-item-thumb-placeholder">${icon}</div>
          <div class="list-item-body">
            <div class="list-item-title">${escapeHtml(evType)}</div>
            <div class="list-item-subtitle">${escapeHtml(ts)}${summary ? ' &middot; ' + escapeHtml(String(summary).slice(0, 80)) : ''}</div>
          </div>`;
        container.appendChild(item);
      });
    } catch (err) {
      showToast(err.message, 'error');
      main.querySelector('#events-list').innerHTML =
        `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
    }
  })();
}

// -------------------------------------------------------------------
// 7.13: Config
// -------------------------------------------------------------------

function renderConfig(main) {
  const cfg = state.config;
  main.innerHTML = `
    <h1>Configuration</h1>
    <div class="card">
      <p class="text-muted text-sm mb-2">Server configuration is managed via environment variables. These values are read-only.</p>
      <div class="detail-row"><span class="detail-row-label">Server URL</span><span class="detail-row-value mono">${escapeHtml(cfg.baseUrl || window.location.origin)}</span></div>
      <div class="detail-row"><span class="detail-row-label">Spotify</span><span class="detail-row-value">${cfg.hasSpotify ? '<span class="badge badge-spotify">Connected</span>' : '<span class="badge">Not configured</span>'}</span></div>
      <div class="detail-row"><span class="detail-row-label">Speakers</span><span class="detail-row-value">${state.speakers.length} saved</span></div>
    </div>
    <div class="card mt-2">
      <h3>About</h3>
      <p class="text-sm text-muted">SoundCork Web UI — a web interface for controlling Bose SoundTouch speakers after Bose's cloud shutdown.</p>
      <p class="text-sm text-muted mt-1">Speakers and configuration are stored server-side. No browser data needed.</p>
    </div>`;
}

// ===================================================================
// Section 8: App Initialization
// ===================================================================

document.addEventListener('DOMContentLoaded', async () => {
  // Logout button handler
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      try {
        await fetch('/webui/api/logout', { method: 'POST' });
      } catch { /* ignore */ }
      sessionStorage.removeItem('csrf_token');
      window.location.href = '/webui/login';
    });
  }

  // Load config and speakers from the server before rendering
  await state.loadFromServer();

  // Auto-discover speakers on first load if none are saved
  if (state.speakers.length === 0) {
    try {
      const resp = await fetch('/webui/api/discover-speakers');
      if (resp.ok) {
        const data = await resp.json();
        const discovered = data.speakers || [];
        for (const sp of discovered) {
          if (!sp.ipAddress) continue;
          try {
            const infoResp = await fetch(`/webui/api/speaker/${sp.ipAddress}/info`);
            if (!infoResp.ok) continue;
            const text = await infoResp.text();
            const xml = new DOMParser().parseFromString(text, 'text/xml');
            const info = parseInfo(xml);
            await state.addSpeaker({
              id: info.deviceId || sp.ipAddress,
              name: info.name || sp.name || sp.ipAddress,
              emoji: '🔊',
              ipAddress: sp.ipAddress,
              type: info.type || sp.type || 'Unknown',
              deviceId: info.deviceId || sp.deviceId || '',
            });
          } catch {
            // Speaker not reachable, skip
          }
        }
      }
    } catch {
      // Discovery failed, user can add manually
    }
  }

  handleRoute();
});
