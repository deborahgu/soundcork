# Spotify on SoundTouch

As always, requires a Premium Spotify account to work.

## Two Different Spotify Systems

There are two completely separate ways Spotify works on a SoundTouch speaker. This is a common source of confusion.

### 1. Spotify Connect (Always Works)

- The speaker advertises itself as a Spotify Connect device on your local network
- Open the Spotify app on your phone or computer, tap the speaker/device icon, and select your SoundTouch speaker
- Audio streams directly from Spotify's CDN to the speaker
- Doesn't use Soundcork in any way.

## Spotify managed by speakers or Soundtouch software using Soundcork

Soundcork allows users to maintain Spotify presets, and continue to play Spotify streams over any Soundtouch-enabled app.

### OAuth Token Intercept (Ongoing Refresh)

The speaker requests a Spotify session from the synthetic Bose APIs (Soundcork), which negotiates for a session token with the Spotify APIs.

Once the speaker has an active Spotify session (from the ZeroConf primer or a previous Spotify Connect cast), it will periodically refresh its token by calling a Bose OAuth endpoint. Soundcork intercepts these requests and returns a valid token.

**Note:** The SoundTouch speakers don't have a separate configuration for the OAuth server. Rather, they take the marge server address and append `oauth` to the end of the first part of the hostname. So for the Bose systems, this is changing `https://streaming.bose.com`  to  `https://streamingoauth.bose.com`. For Soundcork to work with Spotify, it must be available both at a hostname and at an oauth hostname, so `soundcork.local.domain` and `soundcorkoauth.local.domain`.

**How it works:**

1. Speaker sends `POST {oauth_server}/oauth/device/{deviceId}/music/musicprovider/15/token/cs3`
2. Soundcork refreshes the token using the stored Spotify account credentials
3. Returns a fresh access token as JSON
4. The speaker uses this token for continued Spotify playback


## Setup

### Step 1: Register a Spotify App

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
   - **Redirect URI**: `{your-soundcork-url}/mgmt/spotify/callback` (e.g., `https://soundcork.local:8000/mgmt/spotify/callback`)
   - **APIs used**: Web API
3. Note the **Client ID** and **Client Secret**

### Step 2: Configure Soundcork

**NOTE: this configuration may change in the future**

Set the environment variables:

```bash
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret
```

Soundcork requests the minimal Spotify scope set needed for user identity and
Web Playback SDK tokens by default:

```bash
SPOTIFY_SCOPES="streaming user-read-email user-read-private"
```

You can override `SPOTIFY_SCOPES` if your setup needs a broader Bose-like scope
set:

```bash
SPOTIFY_SCOPES="streaming user-read-email user-read-private playlist-read-private playlist-read-collaborative user-library-read user-read-playback-state user-modify-playback-state user-read-currently-playing user-read-recently-played"
```

If you change `SPOTIFY_SCOPES` after linking an account, link the Spotify
account again. Existing refresh tokens keep the scopes that were granted during
their original OAuth flow.

### Step 3: Link Your Spotify Account

**Note: in the future we will add a web UI for account management**

Using the management API:

```bash
# Start the OAuth flow
curl -u admin:password https://your-soundcork/mgmt/spotify/auth/init

# Open the returned URL in your browser, authorize, then complete:
curl -u admin:password "https://your-soundcork/mgmt/spotify/auth/callback?code=AUTH_CODE"

# Verify the account is linked
curl -u admin:password https://your-soundcork/mgmt/spotify/accounts
```

### Step 4: Add refresh token to source configuration

**TODO**

The refresh token from Spotify must be added to the Source configuration. In the near future a web UI will do this for you. For now, you can edit your Sources.xml file directly.

```
   <source id="34" secret="{your refresh token, should start with AQ}" secretType="token_version_3">
        <sourceKey type="SPOTIFY" account="{your account id, should be a long alphanumeric string}" />
    </source>
```

After the account setup above, both `secret` and `account` information should be available in `{soundcorkdbdir}/spotify/accounts.json`.

### Step 5: Verify

After linking your Spotify account, press a Spotify preset button on the speaker. If nothing plays, check your server logs.

## Technical Details

### Token Lifecycle

- Spotify access tokens expire after 1 hour (3600 seconds)
- The speaker's firmware requests a new token via the OAuth endpoint before expiry
- Soundcork caches tokens to avoid unnecessary Spotify API calls


### Speaker ZeroConf Endpoint

Each speaker exposes a ZeroConf endpoint on port 8200:
- `GET /zc?action=getInfo` — returns speaker info including `activeUser`, `libraryVersion`
- `POST /zc` with `action=addUser` — sets the active Spotify user

### Alternative Approach: Manual Kick-Start

If you don't want to configure Spotify credentials in soundcork, you can manually prime the speaker by casting one song via the Spotify app (Spotify Connect). This gives the speaker a temporary in-memory session that enables presets. However, you'll need to repeat this after every speaker reboot.

### ZeroConf Primer (Cold Boot Activation)

The ZeroConf primer is disabled by default. Enable it only if a cold-booted
speaker can refresh Spotify tokens through Soundcork but still leaves Spotify
presets stuck until you cast to the speaker once with Spotify Connect.

On cold boot, the speaker does **not** request a Spotify token — it only fetches account data, source providers, and streaming tokens. Without an active Spotify session, presets fail silently.

The ZeroConf primer solves this by proactively pushing a fresh Spotify access token to the speaker via the ZeroConf endpoint (port 8200). This is the same mechanism the Spotify desktop app uses when you cast to a speaker.

Configuration:

```bash
SPOTIFY_ZEROCONF_PRIMER_ENABLED=true

# Required allowlist. Values can be device IDs, IP addresses,
# account/device pairs, or "*" to allow all known devices.
SPOTIFY_ZEROCONF_PRIME_DEVICES="A0B1C2D3E4F5,192.168.1.25"

# Backward-compatible alias also accepted:
SOUNDCORK_SPOTIFY_PRIME_DEVICES="A0B1C2D3E4F5"

# Default: 2700 seconds (45 minutes). Set to 0 to disable periodic priming
# while keeping boot/new-speaker priming enabled.
SPOTIFY_ZEROCONF_PRIMER_INTERVAL_SECONDS=2700
```

**When it runs:**
- On speaker boot (`power_on` event), with retry/backoff (5s, 10s, 20s delays)
- Periodically at `SPOTIFY_ZEROCONF_PRIMER_INTERVAL_SECONDS` if the interval is greater than 0
- When a new allowlisted speaker is first seen via marge requests

**Gunicorn workers:** the primer registry and timer are in-process. The default
configuration is safe because the primer is disabled and the allowlist is empty.
If you enable the primer, prefer running Soundcork with a single Gunicorn worker
for predictable behavior. With multiple workers, more than one worker may try to
prime the same allowlisted speaker.

**Boot sequence observed:**
```
power_on → bmx/services → media icons → sourceproviders → /full → streaming_token → provider_settings
```
No OAuth token request happens during boot — the ZeroConf primer is what activates Spotify.
