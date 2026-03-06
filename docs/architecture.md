# Architecture

## The Problem

Bose SoundTouch speakers depend on 4 cloud servers for network features like TuneIn radio presets, account management, and firmware updates. Bose announced the shutdown of these servers on **May 6, 2026** (extended from the original February 18 date).

Reference: [Bose SoundTouch EOL page](https://www.bose.co.uk/en_gb/landing_pages/soundtouch-eol.html)

Bose has published official API documentation to support community developers: [SoundTouch Web API (PDF)](https://assets.bosecreative.com/m/496577402d128874/original/SoundTouch-Web-API.pdf)

## The Four Bose Servers

| Server | Internal Name | Purpose | Status (Feb 2026) |
|--------|--------------|---------|-------------------|
| `streaming.bose.com` | marge | Account data, presets, recents, software updates, streaming tokens | Alive (shutdown not until May 6) |
| `content.api.bose.io` | bmx | TuneIn radio playback URLs, service registry, analytics | API removed early — server responds but returns 404 for all endpoints |
| `worldwide.bose.com` | updates | Firmware update checks | API removed early — returns 404 |
| `events.api.bosecm.com` | stats | Telemetry, device blacklist | Not proxied — telemetry only, safe to ignore |

Note: BMX and updates APIs are already returning 404s even though the official shutdown date hasn't passed. This suggests Bose is deprecating APIs incrementally.

## How SoundCork Replaces Them

```
Speaker → soundcork → local handlers (XML data files)
```

1. Edit the speaker's config file (`SoundTouchSdkPrivateCfg.xml`) to point all server URLs to your soundcork instance
2. SoundCork serves all responses locally from your extracted XML data files
3. No traffic reaches Bose servers

## Operating Modes

### Local Mode (Recommended)

`SOUNDCORK_MODE=local` (default)

All responses served from local data store. Zero traffic to Bose. This is recommended because:

- Complete independence from Bose servers
- No risk of unwanted firmware updates (marge has a `/streaming/software/update/` endpoint)
- No data sent to Bose
- Works identically whether Bose servers are up or down

### Proxy Mode

`SOUNDCORK_MODE=proxy`

Tries upstream Bose servers first, falls back to local handlers on failure. Useful during initial setup to:

- Verify your speaker is correctly talking to soundcork
- Capture real server responses for analysis
- Compare local handler behavior against real servers

**Not recommended for production** — the marge server's software update endpoint could potentially trigger a firmware update.

## Circuit Breaker (Proxy Mode)

When in proxy mode, a circuit breaker tracks upstream health per-server:

- **Closed** (healthy): Requests forwarded to upstream normally
- **Open** (down): Upstream failed recently — skip directly to local fallback. Opens on:
  - Connection errors or timeouts (10 second timeout)
  - HTTP 404 responses (API removed but server alive)
  - HTTP 5xx responses (server errors)
- **Half-open** (probing): After 5-minute cooldown, allows one request through to probe upstream health

The circuit breaker is per-worker (gunicorn runs 2 workers), so at most 2 upstream probes per cooldown window per dead server.

## Data Flows

### Power-on Sequence

Speaker boots and calls (in order):

1. `POST /marge/streaming/support/power_on` — device registration
2. `GET /marge/streaming/sourceproviders` — available source types
3. `GET /marge/streaming/account/{id}/full` — full account with devices, presets, recents
4. `GET /marge/streaming/account/{id}/device/{id}/presets` — preset list
5. `GET /marge/streaming/software/update/account/{id}` — check for firmware updates (soundcork returns "no updates")

All served locally by soundcork's marge handlers.

### Playing a TuneIn Preset

1. Speaker sends preset button press event
2. Speaker requests `GET /bmx/tunein/v1/playback/station/{stationId}`
3. SoundCork returns the stream URL (e.g., `http://icecast.vrtcdn.be/mnm.aac`)
4. Speaker connects directly to the radio stream — no further server involvement

### Spotify

Spotify playback does **not** go through soundcork or Bose servers. See [Spotify Guide](spotify.md) for details.

## Traffic Logging

In proxy mode, all traffic is logged to `SOUNDCORK_LOG_DIR/traffic.jsonl` in JSON Lines format. Each entry contains:

- Timestamp
- Request: method, path, query, headers, body
- Upstream URL (or "local" if handled locally)
- Response: status, headers, body
- Fallback reason (if applicable): `circuit_open`, `upstream_error`, `upstream_http_404`, etc.

Useful for debugging and understanding speaker behavior. Not active in local mode.
