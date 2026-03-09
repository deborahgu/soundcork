# Spotify on SoundTouch

## Two Different Spotify Systems

There are two completely separate ways Spotify works on a SoundTouch speaker. This is a common source of confusion.

### 1. Spotify Connect (Works — Recommended)

- The speaker advertises itself as a Spotify Connect device on your local network
- Open the Spotify app on your phone or computer
- Tap the speaker/device icon and select your SoundTouch speaker (e.g., "Bose-Woonkamer")
- Audio streams directly from Spotify's CDN to the speaker
- **No Bose servers involved** — this is purely between the Spotify app, Spotify's servers, and the speaker
- **No soundcork involvement** — Spotify Connect operates independently
- Works before and after the Bose shutdown

### 2. SoundTouch Spotify Integration (Broken Without Workaround)

- This is what the SoundTouch app used for browsing Spotify and setting Spotify presets
- Relies on Bose's own Spotify client ID for OAuth token management via the marge server
- The SoundTouch app can **no longer reconnect or configure** Spotify accounts
- Spotify presets may show as "unplayable" after redirecting to soundcork

## Fixing Spotify Presets

If your Spotify preset fails after setting up soundcork, you'll see these symptoms in the traffic logs:

- `type: "DO_NOT_RESUME"`, `location: "Unplayable location string"`, `playStatus: "STOP_STATE"`
- `source: "INVALID_SOURCE"`, `playStatus: "BUFFERING_STATE"`

### The Fix: Kick-Start via Spotify Connect

1. Open the **Spotify app** on your phone (not the SoundTouch app)
2. Play any song
3. Tap the speaker/device icon at the bottom of the Now Playing screen
4. Select your SoundTouch speaker
5. Wait for the music to start playing (confirms Spotify Connect is active)
6. Now press your Spotify preset button on the speaker — **it should work**

### Why This Works

When you cast via Spotify Connect, the Spotify app authenticates the speaker's **embedded Spotify client** directly over the local network using ZeroConf/mDNS. This gives the speaker a fresh Spotify session.

Key details:

- The Spotify session lives in the speaker's **RAM** — the OAuth token stored in `Sources.xml` doesn't change
- The preset can reuse the active Spotify session established by Spotify Connect
- **You may need to repeat this after a speaker reboot**, since the in-memory session is lost on restart
- Spotify playback traffic never appears in soundcork's traffic logs because it doesn't go through soundcork

### What We Observed (Traffic Analysis)

From our real traffic logs:

**Before Spotify Connect** (speaker trying to play preset on its own):

```
source-state: "SPOTIFY"
contentItem type: "DO_NOT_RESUME"
location: "Unplayable location string"
playStatus: "STOP_STATE"
```

**After casting one song via Spotify Connect** (from the Spotify app):

```
track: "Beachball - Vocal Radio Edit"
artist: "Nalin & Kane"
source: "SPOTIFY"
playStatus: "PLAY_STATE"
```

**Then pressing Spotify preset** (Clouseau):

```
artist: "Clouseau"
album: "Hoezo?"
source: "SPOTIFY"
playStatus: "PLAY_STATE"  ← works!
```

## Managing Presets

The official SoundTouch app can no longer configure presets pointing to TuneIn stations. If you need to add or change presets, use the [Bose CLI](https://github.com/timvw/bose), which talks directly to the speaker's local API on port 8090:

```bash
# Install via Homebrew
brew install timvw/tap/bose

# View current presets
bose preset

# Get a specific preset
bose preset 1

# View speaker status
bose status
```

The speaker's local API (port 8090) is completely independent of the cloud servers and will continue to work indefinitely.
