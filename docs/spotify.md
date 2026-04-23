# Spotify on SoundTouch

## Two Different Spotify Systems

There are two completely separate ways Spotify works on a SoundTouch speaker. This is a common source of confusion.

### 1. Spotify Connect (Always Works)

- The speaker advertises itself as a Spotify Connect device on your local network
- Open the Spotify app on your phone or computer, tap the speaker/device icon, and select your SoundTouch speaker
- Audio streams directly from Spotify's CDN to the speaker
- **No Bose servers involved** — purely between the Spotify app, Spotify's servers, and the speaker
- **No soundcork involvement** — Spotify Connect operates independently

### 2. SoundTouch Spotify Integration (Presets)

- This is what the SoundTouch app used for setting Spotify presets (buttons 1-6)
- Originally relied on Bose's OAuth token management via the marge server
- After the Bose shutdown, this path is broken **unless soundcork handles the token refresh**

## Automatic Spotify Support

Soundcork can keep Spotify presets working automatically. There are two mechanisms that serve different purposes, and both run together:

### ZeroConf Primer (Cold Boot Activation)

On cold boot, the speaker does **not** request a Spotify token — it only fetches account data, source providers, and streaming tokens. Without an active Spotify session, presets fail silently.

The ZeroConf primer solves this by proactively pushing a fresh Spotify access token to the speaker via the ZeroConf endpoint (port 8200). This is the same mechanism the Spotify desktop app uses when you cast to a speaker.

There are two ways to run the ZeroConf primer:

**Server-side** (default): SoundCork pushes tokens to the speaker over the
network. No installation on the speaker needed.

- On speaker boot (`power_on` event), with retry/backoff (5s, 10s, 20s delays)
- Periodically every 45 minutes (tokens expire after 1 hour)
- When a new speaker is first seen via marge requests

**On-speaker**: A boot script on the speaker itself fetches a token from
SoundCork and primes locally. See the
[Speaker Setup Guide](speaker-setup.md#step-5-install-spotify-boot-primer-optional)
for installation instructions.

**Boot sequence observed:**
```
power_on → bmx/services → media icons → sourceproviders → /full → streaming_token → provider_settings
```
No OAuth token request happens during boot — the ZeroConf primer is what activates Spotify.

### OAuth Token Intercept (Ongoing Refresh)

Once the speaker has an active Spotify session (from the ZeroConf primer or a previous Spotify Connect cast), it will periodically refresh its token by calling an OAuth endpoint. Soundcork intercepts these requests and returns a valid token.

**How it works:**
1. Speaker sends `POST /oauth/device/{deviceId}/music/musicprovider/15/token/cs3`
2. Soundcork refreshes the token using the stored Spotify account credentials
3. Returns a fresh access token as JSON
4. The speaker uses this token for continued Spotify playback

This is transparent — the speaker manages its own refresh cycle, just like it did with `streamingoauth.bose.com`. No extra DNS configuration needed — the speaker already sends these requests to the same server as marge.

## Setup

### Step 1: Register a Spotify App

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
   - **Redirect URI**: `{your-soundcork-url}/mgmt/spotify/callback` (e.g., `https://soundcork.local:8000/mgmt/spotify/callback`)
   - **APIs used**: Web API
3. Note the **Client ID** and **Client Secret**

### Step 2: Configure Soundcork

Set the environment variables:

```bash
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret
```

### Step 3: Link Your Spotify Account

Using the management API:

```bash
# Start the OAuth flow
curl -u admin:password https://your-soundcork/mgmt/spotify/auth/init

# Open the returned URL in your browser, authorize, then complete:
curl -u admin:password "https://your-soundcork/mgmt/spotify/auth/callback?code=AUTH_CODE"

# Verify the account is linked
curl -u admin:password https://your-soundcork/mgmt/spotify/accounts
```

Or use the [companion app](https://github.com/timvw/ueberboese-app) which handles this flow automatically.

### Step 4: Verify

After linking your Spotify account:
- The OAuth intercept works immediately — the speaker will get fresh tokens on its next refresh cycle
- The ZeroConf primer (if enabled) will prime the speaker within a few minutes
- Press a Spotify preset button on the speaker — it should play

## Technical Details

### Token Lifecycle

- Spotify access tokens expire after **1 hour** (3600 seconds)
- The speaker's firmware requests a new token via the OAuth endpoint before expiry
- The ZeroConf primer re-primes every **45 minutes** as an additional safety net
- Soundcork caches tokens to avoid unnecessary Spotify API calls

### What `cs3` / `token_version_3` Means

The speaker requests tokens with `tokenType=cs3` in the URL. This corresponds to `token_version_3` in the XML credential format — it's Bose's internal versioning for their OAuth credential schema. The actual value is a standard Spotify access token.

### Speaker ZeroConf Endpoint

Each speaker exposes a ZeroConf endpoint on port 8200:
- `GET /zc?action=getInfo` — returns speaker info including `activeUser`, `libraryVersion`
- `POST /zc` with `action=addUser` — sets the active Spotify user

### Alternative Approach: Manual Kick-Start

If you don't want to configure Spotify credentials in soundcork, you can manually prime the speaker by casting one song via the Spotify app (Spotify Connect). This gives the speaker a temporary in-memory session that enables presets. However, you'll need to repeat this after every speaker reboot.

## Managing Presets

The official SoundTouch app can no longer configure presets after the cloud
shutdown. There are two ways to manage presets:

### Web UI

The SoundCork Web UI (`/webui/`) lets you manage all 6 presets visually. You
can set presets from three source types:

- **Spotify** — paste a Spotify URI or URL (playlist, album, artist, track),
  select your linked Spotify account, and save. The UI previews the entity
  (artwork + name) before saving.
- **TuneIn** — search for radio stations by name, preview station details
  (logo, description, genre, location), and save.
- **Internet Radio** — enter a stream URL manually with an optional station
  name and cover art URL. Use this for stations not in TuneIn's directory.

### Bose CLI

The [Bose CLI](https://github.com/timvw/bose) manages presets directly via the
speaker's local API (port 8090):

```bash
brew install timvw/tap/bose
bose preset       # view presets
bose preset 1     # get a specific preset
bose status       # speaker status
```
