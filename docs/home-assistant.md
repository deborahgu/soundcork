# Home Assistant Integration

SoundCork integrates with Home Assistant through a custom integration and Lovelace card. Each Bose SoundTouch speaker appears as a `media_player` entity with real-time state updates.

## Architecture

```
┌─────────────┐     REST /api/v1/*      ┌──────────────┐    port 8090    ┌──────────────┐
│   Home      │ ◄──────────────────────► │  SoundCork   │ ◄────────────► │ Bose Speaker │
│  Assistant  │     WS /api/v1/ws/*      │   Server     │    port 8080   │  (LAN)       │
└─────────────┘                          └──────────────┘                └──────────────┘
```

All communication between Home Assistant and Bose speakers is **proxied through the SoundCork server**. Home Assistant never connects directly to speakers on the LAN. This means:

- HA doesn't need `hostNetwork: true` or special network access
- Works in any container orchestrator (k8s, Docker, etc.)
- Speaker IPs are used as identifiers in API paths, but soundcork resolves them

### Data flow

1. **REST polling** (every 30 seconds): HA coordinator fetches speaker state via `/api/v1/speakers/{ip}/now-playing`, `/volume`, and `/presets`
2. **WebSocket** (real-time): HA connects to `ws://{soundcork}/api/v1/ws/speaker/{ip}` which proxies to the Bose speaker's gabbo WebSocket on port 8080. Volume changes, track changes, and preset updates are pushed instantly.
3. **Commands**: Volume, power, preset selection, and content playback are sent as POST requests to `/api/v1/speakers/{ip}/*`, which proxy to the speaker's port 8090 API.

## Components

### Server: `/api/v1` router

The SoundCork server exposes a REST + WebSocket API under `/api/v1/` for machine-to-machine use. This is the same speaker proxy pattern used by the webui, without browser-specific concerns (CORS, sessions, image proxying).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/speakers` | GET | List registered speakers (from `webui_speakers.json`) |
| `/api/v1/speakers/{ip}/now-playing` | GET | Current playback state (XML) |
| `/api/v1/speakers/{ip}/volume` | GET | Current volume (XML) |
| `/api/v1/speakers/{ip}/volume` | POST | Set volume (XML body: `<volume>25</volume>`) |
| `/api/v1/speakers/{ip}/presets` | GET | Speaker presets (XML) |
| `/api/v1/speakers/{ip}/store-preset` | POST | Save a preset (XML body) |
| `/api/v1/speakers/{ip}/select` | POST | Play a content item (XML body) |
| `/api/v1/speakers/{ip}/key` | POST | Send raw key XML (press/release) |
| `/api/v1/speakers/{ip}/key/{key}` | POST | Press + release a named key |
| `/api/v1/speakers/{ip}/power-on` | POST | Power on (only if in standby) |
| `/api/v1/speakers/{ip}/power-off` | POST | Power off (only if not in standby) |
| `/api/v1/speakers/{ip}/sources` | GET | Available sources (XML) |
| `/api/v1/speakers/{ip}/recents` | GET | Recently played items (XML) |
| `/api/v1/zone/set` | POST | Create multi-room zone (JSON body) |
| `/api/v1/zone/clear/{ip}` | POST | Dissolve a zone |
| `/api/v1/tunein/search?q=...` | GET | Search TuneIn stations |
| `/api/v1/tunein/describe?id=...` | GET | Get TuneIn station details |
| `/api/v1/ws/speaker/{ip}` | WS | Real-time speaker updates (gabbo protocol) |

### HA Custom Integration

Located in `ha-integration/custom_components/soundcork/`. Creates `media_player` entities with:

- **State**: playing, paused, buffering, off (from nowPlaying source)
- **Volume**: level (0.0–1.0) and mute state
- **Media info**: title, artist, album, artwork URL
- **Source**: current preset name or raw source type
- **Source list**: preset names for source selection dropdown
- **Extra attributes**: `ip_address`, `device_id`, `source_type`, per-preset info

Custom services:

| Service | Description |
|---------|-------------|
| `soundcork.play_preset` | Play preset 1–6 by number |
| `soundcork.store_preset_tunein` | Save a TuneIn station to a preset slot |
| `soundcork.store_preset_radio` | Save a direct stream URL to a preset slot |

### Lovelace Card

Located in `ha-integration/www/soundcork-card.js`. Three modes:

- **`player`** (default): Now-playing display with album art, 2×3 preset grid, multi-speaker selector, power off
- **`speaker`**: Per-speaker volume sliders and mute toggles
- **`editor`**: TuneIn search to save stations to preset slots

The card's visual design matches the SoundCork webui (same color scheme, badges, typography, layout).

## Installation

### Prerequisites

- SoundCork server running with speakers registered in the webui
- Home Assistant 2024.1+ with access to the SoundCork server URL

### 1. Deploy SoundCork with the API router

The `/api/v1` router is included in soundcork. Verify it works:

```bash
curl http://your-soundcork:8000/api/v1/speakers
# Should return JSON array of registered speakers
```

### 2. Install the custom integration

Copy `ha-integration/custom_components/soundcork/` to your HA config directory:

```bash
# For k8s with hostPath storage:
scp -r ha-integration/custom_components/soundcork/ \
  aspire:/home/timvw/k8s-storage/home-assistant/custom_components/soundcork/

# For Docker:
cp -r ha-integration/custom_components/soundcork/ \
  /path/to/ha-config/custom_components/soundcork/
```

Restart Home Assistant.

### 3. Configure the integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **SoundCork**
3. Enter the SoundCork server URL:
   - **K8s in-cluster**: `http://soundcork.soundcork.svc.cluster.local:8000`
   - **Same host**: `http://localhost:8000`
   - **LAN**: `http://192.168.1.x:8000`

The integration validates the connection by fetching the speaker list. If speakers appear, entities are created automatically.

### 4. Install the Lovelace card

Copy the card JS to the HA `www` directory:

```bash
# For k8s:
scp ha-integration/www/soundcork-card.js \
  aspire:/home/timvw/k8s-storage/home-assistant/www/soundcork-card.js

# For Docker:
cp ha-integration/www/soundcork-card.js \
  /path/to/ha-config/www/soundcork-card.js
```

Register the resource in HA:

1. Go to **Settings → Dashboards → Resources** (or 3-dot menu → Resources)
2. Add: `/local/soundcork-card.js` as **JavaScript Module**

### 5. Add cards to a dashboard

Player card (presets + now playing):

```yaml
type: custom:soundcork-card
soundcork_url: http://soundcork.soundcork.svc.cluster.local:8000
speakers:
  - media_player.soundcork_A0F6FD743B41
  - media_player.soundcork_587A6274B5C4
mode: player
```

Volume control card:

```yaml
type: custom:soundcork-card
soundcork_url: http://soundcork.soundcork.svc.cluster.local:8000
speakers:
  - media_player.soundcork_A0F6FD743B41
  - media_player.soundcork_587A6274B5C4
mode: speaker
```

Preset editor card:

```yaml
type: custom:soundcork-card
soundcork_url: http://soundcork.soundcork.svc.cluster.local:8000
speakers:
  - media_player.soundcork_A0F6FD743B41
mode: editor
```

## Kubernetes Deployment Notes

When both SoundCork and Home Assistant run on the same k8s cluster:

- Use the **in-cluster service URL** (`http://soundcork.soundcork.svc.cluster.local:8000`) for the integration config
- The soundcork pod needs LAN access to speakers (it runs on a node with LAN connectivity, using hostPath storage)
- HA does **not** need `hostNetwork: true` — all speaker access is proxied through soundcork
- The Lovelace card makes browser-side requests to soundcork, so use the **external URL** (`https://soundcork.apps.timvw.be`) for `soundcork_url` in the card config

### Card URL vs Integration URL

The integration (server-side) and the card (browser-side) may need different URLs:

| Component | Runs in | URL to use |
|-----------|---------|------------|
| Integration (`config_flow`) | HA pod | In-cluster: `http://soundcork.soundcork.svc.cluster.local:8000` |
| Lovelace card (`soundcork_url`) | Browser | External: `https://soundcork.apps.timvw.be` |

## Troubleshooting

**Integration can't connect**: Verify `curl http://soundcork-url/api/v1/speakers` returns a JSON array. Check HA logs for `soundcork` entries.

**No speakers found**: Make sure speakers are registered in the soundcork webui first (visit `/webui/` and add them).

**WebSocket disconnects**: Check HA logs for `WebSocket disconnected from {ip}` messages. The coordinator reconnects automatically with exponential backoff (5s → 60s max).

**Volume/preset changes are delayed**: Real-time updates depend on the WebSocket connection. If it's disconnected, changes appear on the next 30-second poll cycle.

**Card shows "No presets loaded"**: The card fetches presets directly from soundcork via the browser. Ensure `soundcork_url` in the card config is reachable from your browser (not the in-cluster URL).
