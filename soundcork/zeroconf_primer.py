"""Spotify ZeroConf primer for SoundTouch speakers.

After Bose's cloud servers shut down, some SoundTouch speakers no longer request
a Spotify OAuth token during cold boot.  They can remain unable to play Spotify
presets until a Spotify Connect client sets the speaker's active user via the
local ZeroConf endpoint.

This is the same mechanism the Spotify desktop app uses: a plain access token
is sent as the blob parameter (no DH encryption).

Speakers are tracked dynamically: when a speaker contacts any marge endpoint,
its account/device ID is captured and its IP is looked up from the datastore.
The registry is also seeded from the datastore on startup and after speaker boot
events.

The primer runs:
  - On speaker boot (triggered by the power_on endpoint), with retry
  - When a new allowlisted speaker is seen for the first time
  - Periodically at the configured interval
  - Immediately before Miniapp playback, forcing addUser for that target speaker

Configuration:
  - SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set
  - A Spotify account must be linked via the management API
  - Speaker IP addresses are read from the datastore (DeviceInfo)
  - SPOTIFY_ZEROCONF_PRIME_DEVICES must explicitly allow devices
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from soundcork.config import Settings
from soundcork.datastore import DataStore
from soundcork.spotify_service import SpotifyService

logger = logging.getLogger(__name__)

ZEROCONF_PORT = 8200
BOOT_RETRY_DELAYS = [5, 10, 20]  # seconds between retries after power_on
MAX_CONSECUTIVE_FAILURES = 5  # remove speaker from registry after this many


@dataclass
class TrackedSpeaker:
    """A speaker that has been seen by soundcork."""

    account_id: str
    device_id: str
    ip_address: str | None = None
    last_primed: float = 0.0  # timestamp of last successful prime
    prime_failures: int = 0


class ZeroConfPrimer:
    def __init__(
        self,
        spotify: SpotifyService,
        datastore: DataStore,
        settings: Settings,
    ):
        self._spotify = spotify
        self._datastore = datastore
        self._settings = settings
        self._timer: threading.Timer | None = None
        self._speakers: dict[str, TrackedSpeaker] = {}  # device_id -> TrackedSpeaker
        self._lock = threading.Lock()
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def enabled(self) -> bool:
        return self._settings.spotify_zeroconf_primer_enabled

    # --- Speaker registration ---

    def register_speaker(self, account_id: str, device_id: str):
        """Register a speaker that contacted a marge endpoint.

        Called from marge request handlers.  If this is a new allowlisted
        speaker, resolves its IP and primes it in the background.
        """
        if not self._can_prime():
            return

        is_new = False
        with self._lock:
            if device_id not in self._speakers:
                ip = self._resolve_speaker_ip(account_id, device_id)
                self._speakers[device_id] = TrackedSpeaker(
                    account_id=account_id,
                    device_id=device_id,
                    ip_address=ip,
                )
                is_new = True
                logger.info(
                    "New speaker registered for Spotify primer: %s (account=%s, ip=%s)",
                    device_id,
                    account_id,
                    ip,
                )
            else:
                speaker = self._speakers[device_id]
                # Update account_id in case it changed
                speaker.account_id = account_id
                if not speaker.ip_address:
                    speaker.ip_address = self._resolve_speaker_ip(account_id, device_id)

            speaker = self._speakers[device_id]

        if is_new and speaker.ip_address and self._speaker_allowed(speaker):
            threading.Thread(
                target=self._prime_if_needed,
                args=(speaker,),
                daemon=True,
                name="spotify-zeroconf-prime",
            ).start()

    def on_power_on(self, source_ip: str | None = None):
        """Called when a speaker sends power_on.

        Primes known allowlisted speakers with retry/backoff, since the
        speaker's ZeroConf port may not be ready immediately.
        If no speakers are registered yet, discovers from datastore.
        """
        if not self._can_prime():
            return

        threading.Thread(
            target=self._power_on_prime,
            args=(source_ip,),
            daemon=True,
            name="spotify-zeroconf-power-on",
        ).start()

    def prime_before_play(
        self,
        device_id: str,
        account_id: str | None = None,
        force: bool = True,
        wait_seconds: float = 1.0,
    ) -> bool:
        """Synchronously prime a target speaker before Miniapp playback.

        This path intentionally defaults to forcing addUser so playback can
        recover when another Spotify account is currently the speaker's
        activeUser.  Background boot and periodic priming still use
        _prime_if_needed and keep their activeUser skip behavior.
        """
        if not self._can_prime():
            return False

        speaker = self._get_or_register_speaker(device_id, account_id)
        if not speaker:
            logger.debug(
                "Could not find speaker %s for Spotify pre-play primer", device_id
            )
            return False

        if force:
            return self._prime_speaker(speaker, wait_seconds=wait_seconds)
        return self._prime_if_needed(speaker)

    # --- Periodic ---

    def start_periodic(self):
        """Start the periodic re-prime background task if configured."""
        if not self.enabled:
            logger.info("Spotify ZeroConf primer disabled")
            return
        if (
            not self._settings.spotify_client_id
            or not self._settings.spotify_client_secret
        ):
            logger.info("Spotify not configured; ZeroConf primer disabled")
            return
        if not self._allowed_devices():
            logger.warning(
                "Spotify ZeroConf primer enabled without an allowlist; no speakers will be primed"
            )
            return

        interval = self._periodic_interval_seconds()
        if interval <= 0:
            logger.info("Spotify ZeroConf periodic primer disabled by interval")
            return

        # Seed the registry from the datastore on startup
        self._seed_from_datastore()
        self._schedule_next()
        logger.info(
            "Periodic Spotify ZeroConf primer started (every %d seconds)",
            interval,
        )

    def stop_periodic(self):
        """Stop the periodic re-prime background task."""
        if self._timer:
            self._timer.cancel()
            self._timer = None

    # --- Internal ---

    def _is_configured(self) -> bool:
        return bool(
            self.enabled
            and self._settings.spotify_client_id
            and self._settings.spotify_client_secret
        )

    def _can_prime(self) -> bool:
        return self._is_configured() and bool(self._allowed_devices())

    def _allowed_devices(self) -> set[str]:
        return {
            device.strip().lower()
            for device in self._settings.spotify_zeroconf_prime_devices.split(",")
            if device.strip()
        }

    def _speaker_allowed(self, speaker: TrackedSpeaker) -> bool:
        allowed_devices = self._allowed_devices()
        if not allowed_devices:
            return False
        if "*" in allowed_devices:
            return True

        speaker_keys = {
            speaker.device_id.lower(),
            f"{speaker.account_id}/{speaker.device_id}".lower(),
        }
        if speaker.ip_address:
            speaker_keys.add(speaker.ip_address.lower())

        return bool(speaker_keys & allowed_devices)

    def _get_or_register_speaker(
        self, device_id: str, account_id: str | None
    ) -> TrackedSpeaker | None:
        """Return a tracked speaker, resolving it from the datastore if needed."""
        if not device_id:
            return None

        with self._lock:
            speaker = self._speakers.get(device_id)

        if not speaker and not account_id:
            self._seed_from_datastore()
            with self._lock:
                speaker = self._speakers.get(device_id)

        if not speaker and account_id:
            ip = self._resolve_speaker_ip(account_id, device_id)
            speaker = TrackedSpeaker(account_id, device_id, ip)
            with self._lock:
                self._speakers[device_id] = speaker
            logger.info(
                "Speaker registered for Spotify pre-play primer: %s (account=%s, ip=%s)",
                device_id,
                account_id,
                ip,
            )

        if speaker and account_id:
            speaker.account_id = account_id

        if speaker and not speaker.ip_address and speaker.account_id:
            speaker.ip_address = self._resolve_speaker_ip(
                speaker.account_id, speaker.device_id
            )

        if speaker and not self._speaker_allowed(speaker):
            logger.debug(
                "Speaker %s is not allowlisted for Spotify pre-play primer",
                speaker.device_id,
            )
            return None

        return speaker

    def _periodic_interval_seconds(self) -> int:
        return self._settings.spotify_zeroconf_primer_interval_seconds

    def _seed_from_datastore(self):
        """Populate the speaker registry from the datastore on startup."""
        try:
            account_ids = self._datastore.list_accounts()
        except (FileNotFoundError, StopIteration):
            logger.debug("Could not list accounts while seeding Spotify primer")
            return

        for account_id in account_ids:
            if not account_id:
                continue

            try:
                device_ids = self._datastore.list_devices(account_id)
            except (FileNotFoundError, StopIteration):
                continue

            for device_id in device_ids:
                if not device_id:
                    continue
                ip = self._resolve_speaker_ip(account_id, device_id)
                if not ip:
                    continue
                with self._lock:
                    if device_id not in self._speakers:
                        self._speakers[device_id] = TrackedSpeaker(
                            account_id=account_id,
                            device_id=device_id,
                            ip_address=ip,
                        )

        count = len(self._speakers)
        if count:
            logger.info("Seeded %d speaker(s) for Spotify ZeroConf primer", count)

    def _resolve_speaker_ip(self, account_id: str, device_id: str) -> str | None:
        """Look up a speaker's IP address from the datastore."""
        try:
            info = self._datastore.get_device_info(account_id, device_id)
            return info.ip_address
        except Exception:
            logger.debug("Could not resolve IP for %s/%s", account_id, device_id)
            return None

    def _get_token(self) -> tuple[str, str] | None:
        """Get a valid Spotify access token and user ID.

        Caches the token to avoid refreshing for every speaker.
        Returns (token, user_id) or None.
        """
        user_id = self._spotify.get_spotify_user_id()
        if not user_id:
            logger.warning("No Spotify user ID configured")
            return None

        now = time.time()
        if self._cached_token and now < self._token_expires_at - 120:
            return self._cached_token, user_id

        token_dict = self._spotify.get_fresh_token_sync()
        token = token_dict.get("access_token", "")

        if not token:
            logger.warning("Could not get Spotify access token")
            return None

        self._cached_token = token
        self._token_expires_at = now + int(token_dict.get("expires_in", 3600))
        return token, user_id

    def _prime_if_needed(self, speaker: TrackedSpeaker) -> bool:
        """Check activeUser and prime only if empty."""
        if not speaker.ip_address or not self._speaker_allowed(speaker):
            return False

        try:
            active_user = self._get_active_user(speaker.ip_address)
            if active_user:
                logger.debug(
                    "Speaker %s already primed (activeUser=%s)",
                    speaker.ip_address,
                    active_user,
                )
                speaker.last_primed = time.time()
                speaker.prime_failures = 0
                return True
        except Exception:
            logger.debug("Could not check activeUser for %s", speaker.ip_address)

        return self._prime_speaker(speaker)

    def _prime_speaker(
        self, speaker: TrackedSpeaker, wait_seconds: float = 2.0
    ) -> bool:
        """Send addUser to a speaker."""
        if not speaker.ip_address or not self._speaker_allowed(speaker):
            return False

        creds = self._get_token()
        if not creds:
            return False
        token, user_id = creds

        try:
            result = self._send_add_user(speaker.ip_address, user_id, token)
            status = result.get("status", -1)
            if status != 101:
                logger.warning(
                    "addUser to %s returned status %s: %s",
                    speaker.ip_address,
                    status,
                    result.get("statusString", ""),
                )
                speaker.prime_failures += 1
                return False

            logger.info("addUser accepted by %s (status 101)", speaker.ip_address)

            # Verify activeUser was set
            time.sleep(wait_seconds)
            active_user = self._get_active_user(speaker.ip_address)
            if active_user:
                logger.info(
                    "Speaker %s primed for Spotify (activeUser=%s)",
                    speaker.ip_address,
                    active_user,
                )
                speaker.last_primed = time.time()
                speaker.prime_failures = 0
                return True

            logger.warning(
                "Speaker %s returned 101 but activeUser still empty",
                speaker.ip_address,
            )
            speaker.prime_failures += 1
            return False

        except Exception:
            logger.exception("Failed to prime speaker %s", speaker.ip_address)
            speaker.prime_failures += 1
            return False

    def _power_on_prime(self, source_ip: str | None):
        """Prime speakers after boot with retry/backoff."""
        self._seed_from_datastore()
        with self._lock:
            speakers = [
                speaker
                for speaker in self._speakers.values()
                if self._speaker_allowed(speaker)
            ]

        if source_ip:
            source_speakers = [
                speaker for speaker in speakers if speaker.ip_address == source_ip
            ]
            if source_speakers:
                speakers = source_speakers

        if not speakers:
            logger.info("No allowlisted speakers registered for Spotify primer")
            return

        for delay in BOOT_RETRY_DELAYS:
            logger.info(
                "Speaker booted; waiting %ds before priming %d speaker(s)",
                delay,
                len(speakers),
            )
            time.sleep(delay)

            all_ok = True
            for speaker in speakers:
                if not self._prime_if_needed(speaker):
                    all_ok = False

            if all_ok:
                logger.info("All allowlisted speakers primed successfully")
                return

        logger.warning("Some allowlisted speakers failed to prime after all retries")

    def _schedule_next(self):
        """Schedule the next periodic check."""
        interval = self._periodic_interval_seconds()
        if interval <= 0:
            return
        self._timer = threading.Timer(interval, self._periodic_tick)
        self._timer.daemon = True
        self._timer.start()

    def _periodic_tick(self):
        """Periodic task: check and re-prime all allowlisted speakers if needed."""
        try:
            logger.info("Periodic Spotify ZeroConf primer check running")
            with self._lock:
                speakers = [
                    speaker
                    for speaker in self._speakers.values()
                    if self._speaker_allowed(speaker)
                ]

            for speaker in speakers:
                self._prime_if_needed(speaker)

            # Remove speakers that have failed too many times in a row.
            # They get re-added automatically when they contact marge
            # or send a power_on event.
            with self._lock:
                to_remove = [
                    device_id
                    for device_id, speaker in self._speakers.items()
                    if speaker.prime_failures >= MAX_CONSECUTIVE_FAILURES
                ]
                for device_id in to_remove:
                    speaker = self._speakers.pop(device_id)
                    logger.warning(
                        "Removed unreachable speaker %s (%s) after %d consecutive failures",
                        device_id,
                        speaker.ip_address,
                        speaker.prime_failures,
                    )

        except Exception:
            logger.exception("Error during periodic Spotify ZeroConf primer")
        finally:
            self._schedule_next()

    @staticmethod
    def _send_add_user(speaker_ip: str, user_id: str, token: str) -> dict:
        """Send addUser to the speaker's ZeroConf endpoint."""
        post_data = urllib.parse.urlencode(
            {
                "action": "addUser",
                "userName": user_id,
                "blob": token,
                "clientKey": "",
                "tokenType": "accesstoken",
            }
        ).encode()

        url = f"http://{speaker_ip}:{ZEROCONF_PORT}/zc"
        req = urllib.request.Request(
            url,
            data=post_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _get_active_user(speaker_ip: str) -> str:
        """Check the speaker's activeUser via ZeroConf getInfo."""
        url = f"http://{speaker_ip}:{ZEROCONF_PORT}/zc?action=getInfo"
        with urllib.request.urlopen(url, timeout=5) as resp:
            info = json.loads(resp.read())
        return info.get("activeUser", "")
