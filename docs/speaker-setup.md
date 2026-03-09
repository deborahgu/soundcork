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

## Warnings

> **Port 17000 (TAP Console)**: The speaker exposes a diagnostic console on
> port 17000. On firmware 27.x, most commands have been removed. **Do NOT send
> exploratory commands** — the `demo enter` command puts the speaker into
> factory/demo mode which may be difficult to recover from.

> **Read-only filesystem**: The speaker's root filesystem is read-only by
> default. Always run `rw` before editing files. The filesystem reverts to
> read-only on reboot.
