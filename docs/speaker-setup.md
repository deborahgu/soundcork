# Speaker Setup Guide

How to set up your Bose SoundTouch speaker to work with SoundCork. This guide
covers enabling SSH access, extracting the data SoundCork needs, and redirecting
your speaker's cloud traffic to your SoundCork server.

## Prerequisites

- Bose SoundTouch speaker (tested on SoundTouch 20, firmware 27.0.6)
- Clean FAT32-formatted USB stick
- Ethernet cable (recommended for initial setup)
- Computer on the same network as the speaker

## Step 1: Enable SSH Access

### Firmware 27.x (Current)

The old `remote_services on` TAP command (port 17000) was **removed** in
firmware 27.x. You must use the USB stick method instead:

1. Format a USB stick as FAT32.
2. Create a single empty file called `remote_services` (no file extension).
3. **Critical for macOS users** — remove the junk files that macOS creates
   automatically:
   ```sh
   mdutil -i off /Volumes/YOUR_USB_NAME
   rm -rf /Volumes/YOUR_USB_NAME/.fseventsd
   rm -rf /Volumes/YOUR_USB_NAME/.Spotlight-V100
   rm -f /Volumes/YOUR_USB_NAME/._*
   ```
   These hidden files can prevent the speaker from detecting the
   `remote_services` file.
4. Power off the speaker completely.
5. Insert the USB stick into the USB port on the back of the speaker.
6. Power on the speaker.
7. Wait approximately 60 seconds.

> **A note on connectivity**: During our testing, we initially failed with WiFi
> and a USB stick containing macOS junk files. We succeeded after cleaning the
> USB AND switching to Ethernet. We changed both variables simultaneously, so we
> cannot confirm which was the actual fix. If WiFi doesn't work for you, try
> connecting the speaker via Ethernet cable as well.

Then SSH in:

```sh
ssh root@<speaker-ip>
```

No password is required.

> **Security warning**: SSH access is **passwordless root**. Once enabled (via
> USB or the persistent `/mnt/nv/remote_services` flag), anyone on the same
> network can gain full control of the speaker. This includes reading all stored
> credentials (Spotify/TuneIn tokens in `Sources.xml`, the Bose cloud auth
> token) and modifying the speaker's configuration. Only enable SSH on trusted
> networks. See [Security Model](architecture.md#bose-soundtouch-security-model)
> for details.

### Make SSH Persistent Across Reboots

By default, SSH access is lost when the speaker reboots. To make it permanent:

```sh
ssh root@<speaker-ip>
touch /mnt/nv/remote_services
```

This creates a persistent flag file on the speaker's non-volatile storage. You
can now remove the USB stick and SSH will survive reboots.

### Finding Your Speaker's IP Address

There are a few ways to find the speaker's IP:

- Check your router's DHCP client list for a device named "SoundTouch".
- If you have the [Bose CLI](https://github.com/timvw/bose): `bose status`
- The Bose SoundTouch app shows the speaker's IP in device settings.

## Step 2: Extract Speaker Data

SoundCork needs 4 XML files from your speaker. Some are available via the
speaker's local web API (port 8090), others require SSH.

### From the speaker's web API (port 8090)

```sh
curl http://<speaker-ip>:8090/presets > Presets.xml
curl http://<speaker-ip>:8090/recents > Recents.xml
curl http://<speaker-ip>:8090/info > DeviceInfo.xml
```

> **Note**: Port 8090 requires **no authentication**. Anyone on the same network
> can query these endpoints and read the speaker's `margeAccountUUID`, device ID,
> serial numbers, MAC addresses, and firmware version. This is by design in
> Bose's firmware — not a SoundCork addition.

### From SSH (requires root access)

`Sources.xml` contains authentication tokens that are not exposed via the web
API. You must retrieve it over SSH:

```sh
ssh root@<speaker-ip>
cat /mnt/nv/BoseApp-Persistence/1/Sources.xml
```

Copy the output and save it as `Sources.xml`.

### Get Your Account UUID

From the `DeviceInfo.xml` you just downloaded, find the `margeAccountUUID`
field. Alternatively, via SSH:

```sh
cat /opt/Bose/etc/SoundTouchSdkPrivateCfg.xml
```

Look for the account UUID in the marge URL.

### Store Files in SoundCork's Data Directory

Place the extracted files in the following structure:

```
data/
  <accountId>/
    Presets.xml
    Recents.xml
    Sources.xml
    devices/
      <deviceId>/
        DeviceInfo.xml
```

Where:
- `<accountId>` is your `margeAccountUUID`
- `<deviceId>` is the `deviceID` attribute from `DeviceInfo.xml`

See the [`examples/`](../examples/) directory in this repository for the
expected XML format.

## Step 3: Redirect Speaker to SoundCork

### Make the filesystem writable

The speaker's root filesystem is read-only by default. You must switch it to
read-write mode before editing any files:

```sh
ssh root@<speaker-ip>
rw
```

### Edit the server configuration

```sh
vi /opt/Bose/etc/SoundTouchSdkPrivateCfg.xml
```

Change all 4 server URLs to point to your SoundCork instance:

| Server  | Before                              | After                         |
|---------|-------------------------------------|-------------------------------|
| marge   | `https://streaming.bose.com`        | `https://your-soundcork-server` |
| bmx     | `https://content.api.bose.io`       | `https://your-soundcork-server` |
| updates | `https://worldwide.bose.com`        | `https://your-soundcork-server` |
| stats   | `https://events.api.bosecm.com`     | `https://your-soundcork-server` |

Reboot the speaker for changes to take effect. The speaker will now send all
cloud traffic to your SoundCork server.

## Step 4: Harden SSH Access (Recommended)

By default, SSH uses passwordless root access. Anyone on your network can log in.
You should restrict SSH to key-based authentication only.

### Prerequisites

- An SSH key pair on your workstation (e.g., `~/.ssh/id_rsa` / `id_rsa.pub`)
- The speaker runs OpenSSH 6.6 which only supports the `ssh-rsa` signature
  algorithm for RSA keys. Modern SSH clients (OpenSSH 8.8+) disable `ssh-rsa`
  by default, so you need an SSH config entry (see step 3 below).

### 1. Upload your public key

```sh
# Remount the rootfs as read-write
ssh root@<speaker-ip> mount -o remount,rw /

# Create the .ssh directory in root's home (/home/root on SoundTouch)
ssh root@<speaker-ip> 'mkdir -p /home/root/.ssh && chmod 700 /home/root/.ssh'

# Upload your public key
cat ~/.ssh/id_rsa.pub | ssh root@<speaker-ip> \
    'cat > /home/root/.ssh/authorized_keys && chmod 600 /home/root/.ssh/authorized_keys'
```

### 2. Create the hardened sshd config

```sh
ssh root@<speaker-ip> 'cat > /mnt/nv/sshd_config' << 'EOF'
# Hardened sshd_config for Bose SoundTouch
# Stored on /mnt/nv/ (persistent), applied at boot via rc.local
UsePrivilegeSeparation no
PasswordAuthentication no
PermitEmptyPasswords no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PermitRootLogin without-password
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
PermitTunnel no
AllowTcpForwarding no
HostKey /etc/ssh/ssh_host_rsa_key
HostKey /etc/ssh/ssh_host_dsa_key
EOF
```

### 3. Add SSH config entry on your workstation

The speaker's OpenSSH 6.6 only supports the `ssh-rsa` (SHA-1) signature
algorithm, which modern clients disable by default. Add this to your
`~/.ssh/config`:

```
Host bose-woonkamer
    Hostname <speaker-ip>
    User root
    PubkeyAcceptedAlgorithms +ssh-rsa
```

### 4. Make it persistent via rc.local

Add the following to `/mnt/nv/rc.local` (before any other commands):

```sh
# Harden SSH: restart sshd with key-only auth config
if [ -f /mnt/nv/sshd_config ]; then
    sleep 2
    kill $(cat /var/run/sshd.pid 2>/dev/null) 2>/dev/null
    sleep 1
    /usr/sbin/sshd -f /mnt/nv/sshd_config
fi
```

This kills the default (permissive) sshd that starts at boot and replaces it
with the hardened instance.

### 5. Reboot and verify

```sh
# Reboot the speaker
echo "sys reboot" | nc -w 5 <speaker-ip> 17000

# Wait ~30 seconds, then test key auth
ssh bose-woonkamer 'echo "Key auth works"'

# Verify password auth is rejected (should fail)
ssh -o IdentitiesOnly=yes -o IdentityFile=/dev/null \
    -o PubkeyAcceptedAlgorithms=+ssh-rsa root@<speaker-ip> 'echo fail'
```

### Reverting

- **Reboot only**: The rootfs reverts to read-only, but `/mnt/nv/sshd_config`
  and `rc.local` persist — hardened SSH stays active.
- **Factory reset**: Wipes all of `/mnt/nv/` including `remote_services`,
  `sshd_config`, `rc.local`, and `authorized_keys`. SSH is fully disabled
  after a factory reset and must be re-enabled from scratch.
- **Emergency recovery**: Use the TAP console on port 17000 to reboot
  (`echo "sys reboot" | nc <speaker-ip> 17000`). The `/home/root/.ssh/`
  directory is on the rootfs (UBIFS) and persists across reboots, so the key
  file remains available for the next boot cycle.

## Step 5: Install Spotify Boot Primer (Optional)

If you use Spotify presets, the speaker needs an active Spotify session to play
them. Normally, SoundCork's server-side ZeroConf primer handles this (see
[Spotify Guide](spotify.md#zeroconf-primer-cold-boot-activation)). As an
alternative, you can install a script directly on the speaker that primes
Spotify at boot by fetching a token from your SoundCork server.

This is useful if you want the speaker to self-prime without relying on
SoundCork's periodic ZeroConf pushes, or as a belt-and-suspenders approach
alongside the server-side primer.

### Prerequisites

- SoundCork running with a linked Spotify account (Steps 1-3 above complete)
- The `GET /mgmt/spotify/token` endpoint on your SoundCork server
- Management API credentials (`MGMT_USERNAME` / `MGMT_PASSWORD`)

### 1. Create the config file

```sh
ssh root@<speaker-ip>

cat > /mnt/nv/BoseApp-Persistence/1/spotify-primer.conf << 'EOF'
SOUNDCORK_URL=https://soundcork.example.com
SOUNDCORK_USER=admin
SOUNDCORK_PASS=secret
EOF
chmod 600 /mnt/nv/BoseApp-Persistence/1/spotify-primer.conf
```

Replace the URL and credentials with your SoundCork server details. The file is
`chmod 600` so only root can read it.

> **Note**: No Spotify credentials are stored on the speaker — only the
> SoundCork connection info. SoundCork handles all Spotify OAuth logic
> server-side.

### 2. Install the boot primer script

From your local machine, copy the script to the speaker:

```sh
cat scripts/spotify-boot-primer | ssh root@<speaker-ip> \
    "mkdir -p /mnt/nv/bin && cat > /mnt/nv/bin/spotify-boot-primer && chmod +x /mnt/nv/bin/spotify-boot-primer"
```

The script is also available in the
[`scripts/`](../scripts/) directory of this repository and as a
[GitHub Gist](https://gist.github.com/timvw/84ef8768ff876ef6805012b3eb4015b0).

### 3. Update rc.local

If you already have an `rc.local` from Step 4 (SSH hardening), add the primer
to the end:

```sh
ssh root@<speaker-ip> 'cat >> /mnt/nv/rc.local' << 'EOF'

# Spotify boot primer — backgrounds and waits for port 8200
/mnt/nv/bin/spotify-boot-primer &
EOF
```

If you don't have an `rc.local` yet, create one:

```sh
ssh root@<speaker-ip> 'cat > /mnt/nv/rc.local' << 'EOF'
#!/bin/bash
/mnt/nv/bin/spotify-boot-primer &
EOF
ssh root@<speaker-ip> chmod +x /mnt/nv/rc.local
```

### 4. Set up PATH for interactive SSH (optional)

This lets you run `spotify-boot-primer` directly from an SSH session:

```sh
ssh root@<speaker-ip> 'cat > /mnt/nv/.profile' << 'EOF'
export PATH="/mnt/nv/bin:$PATH"
EOF
```

### 5. Test it

```sh
# Manual test (speaker must be running):
ssh root@<speaker-ip> /mnt/nv/bin/spotify-boot-primer

# Check logs:
ssh root@<speaker-ip> 'logread | grep spotify-primer'

# Full test — reboot and verify:
echo "sys reboot" | nc -w 5 <speaker-ip> 17000
# Wait ~30 seconds, then:
ssh root@<speaker-ip> 'logread | grep spotify-primer'
ssh root@<speaker-ip> 'curl -s "http://localhost:8200/zc?action=getInfo"'
# Look for "activeUser" in the output
```

### Example boot log

```
spotify-primer[1735]: Config loaded (server=https://soundcork.example.com)
spotify-primer[1735]: Waiting for ZeroConf endpoint (max 120s)...
spotify-primer[1735]: ZeroConf endpoint is up (waited 21s)
spotify-primer[1735]: Speaker 'Bose-Woonkamer' has no active Spotify user — priming...
spotify-primer[1735]: Requesting Spotify token from soundcork...
spotify-primer[1735]: Got token for user {username} (BQDUAb0_2h...)
spotify-primer[1735]: addUser accepted (status 101) — verifying...
spotify-primer[1735]: Speaker primed successfully (activeUser={username})
```

### File layout on the speaker

```
/mnt/nv/
  rc.local                                      boot hook (S97)
  .profile                                      PATH setup for interactive SSH
  bin/
    spotify-boot-primer                         main script
  BoseApp-Persistence/1/
    spotify-primer.conf                         soundcork credentials (mode 600)
    Sources.xml, Presets.xml, ...               existing speaker data
```

### How it works

The speaker's init system runs `shelby_local` at S97, which has a built-in
hook: `[ -x /mnt/nv/rc.local ] && /mnt/nv/rc.local`. SoundTouch itself starts
at S99. The primer script backgrounds and waits for the ZeroConf endpoint
(port 8200) to come up (~20 seconds after boot), then:

1. Fetches a fresh Spotify access token from SoundCork (`GET /mgmt/spotify/token`)
2. Pushes it to the speaker via `POST localhost:8200/zc` (`addUser`)
3. Verifies the speaker accepted it (`getInfo` shows `activeUser`)

The script is idempotent — if the speaker is already primed, it exits
immediately.

### Standalone primer script

For one-off priming from your workstation (without the boot automation), use
the `scripts/spotify-prime-speaker` script:

```sh
./scripts/spotify-prime-speaker 192.168.1.143 BQDj...your_access_token...
```

This requires `curl` and `jq` on your workstation. It discovers the Spotify
username from the token, checks the speaker's current status, and primes it if
needed.

## Warnings

> **Port 17000 (TAP Console)**: The speaker exposes a diagnostic console on
> port 17000. On firmware 27.x, most commands have been removed. **Do NOT send
> exploratory commands** — the `demo enter` command puts the speaker into
> factory/demo mode which may be difficult to recover from.

> **Read-only filesystem**: The speaker's root filesystem is read-only by
> default. Always run `rw` before editing files. The filesystem reverts to
> read-only on reboot.
