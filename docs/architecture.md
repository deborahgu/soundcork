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

## Bose SoundTouch Security Model

A summary of the speaker's security posture, based on firmware analysis, traffic
capture, and reverse-engineering the Bose SoundTouch Android app
(`com.bose.soundtouch.apk`).

### LAN Exposure (No Authentication)

The speaker exposes several unauthenticated services on the local network:

| Port | Protocol | What's Exposed |
|------|----------|----------------|
| **8090** | HTTP | Device info (`/info`): `margeAccountUUID`, device ID, serial numbers, MAC addresses, firmware version. Also: `/presets`, `/recents`, `/now_playing`, `/volume`, `/sources` (source types only, no credentials). |
| **8080** | WebSocket (`gabbo`) | Real-time control and device info. The Bose app uses this for the ownership check — it reads `margeAccountUUID` from the device info XML. |
| **8200** | HTTP (Spotify ZeroConf) | `GET /zc?action=getInfo` returns the active Spotify user ID (but **not** the access token). `POST /zc` with `action=addUser` pushes a Spotify token to the speaker — anyone on the LAN could hijack the Spotify session. |

Anyone on the same WiFi network can reach all of these without credentials.

**What is NOT exposed on the LAN:**
- `Sources.xml` (music service tokens: Spotify, TuneIn, Pandora) — only accessible via SSH at `/mnt/nv/BoseApp-Persistence/1/Sources.xml`
- The Bose cloud auth token — stored on the speaker's filesystem, only transmitted over HTTPS to `streaming.bose.com`
- Spotify access tokens — write-only via port 8200 `addUser`, never returned by `getInfo`

### SSH Root Access

When SSH is enabled (via USB stick or the persistent `/mnt/nv/remote_services`
flag), the speaker accepts `ssh root@<ip>` with **no password**. This grants
access to everything on the filesystem, including:

- `/mnt/nv/BoseApp-Persistence/1/Sources.xml` — Spotify/TuneIn/Pandora OAuth tokens
- `/opt/Bose/etc/SoundTouchSdkPrivateCfg.xml` — server URLs, account UUID
- The Bose cloud auth token (stored on disk, used in `Authorization` headers)

### Bose Cloud Authentication (from APK analysis)

The original Bose cloud (`streaming.bose.com`) used a session-based model:

1. **User login**: The Bose app sends `POST /streaming/account/login` with
   `<login><username>email</username><password>pass</password></login>`.
   The server returns the account ID in the response body (`<account id="...">`)
   and an auth token in the `Credentials` response header.

2. **Device pairing**: The app pushes both the account ID and auth token to the
   speaker via a WebSocket message on port 8080:
   `<PairDeviceWithAccount><accountId>...</accountId><userAuthToken>...</userAuthToken></PairDeviceWithAccount>`.
   The speaker stores these and uses them for all subsequent cloud requests.

3. **Ongoing API calls**: Every request to `streaming.bose.com` includes the
   auth token in the `Authorization` header, along with `GUID`, `ClientType`,
   version headers, and a static `MARGE_SERVER_KEY`.

4. **Ownership check** (client-side only): The Bose app discovers speakers via
   mDNS (`_soundtouch._tcp.local.`) and SSDP, connects via WebSocket, reads the
   speaker's `margeAccountUUID`, and only shows speakers whose account ID matches
   the logged-in user. This is a client-side UI filter — the speaker itself does
   not gate access.

### Implications

- The `margeAccountUUID` is always visible to anyone on the LAN (port 8090, no auth)
- The Bose cloud auth token is only accessible via SSH or by intercepting HTTPS traffic
- Without the auth token, the cloud would reject requests — the account ID alone was not sufficient
- SoundCork adds its own security layer (IP allowlist, management API basic auth, WebUI session auth) that the original Bose protocol did not have
