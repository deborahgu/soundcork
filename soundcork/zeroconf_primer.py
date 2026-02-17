"""Spotify ZeroConf primer for SoundTouch speakers.

After Bose's cloud servers shut down, speakers can no longer obtain
Spotify credentials via the marge /full account response.  Instead,
we prime speakers by sending a valid Spotify access token directly
to their ZeroConf endpoint (port 8200) using the addUser action.

This is the same mechanism the Spotify desktop app uses: a plain
access token is sent as the blob parameter (no DH encryption).

Speakers are tracked dynamically: when a speaker contacts any marge
endpoint, its account/device ID is captured and its IP is looked up
from the datastore.  This avoids the need to scan directories and
ensures newly added speakers are primed automatically.

The primer runs:
  - On speaker boot (triggered by the power_on endpoint), with retry
  - When a new speaker is seen for the first time
  - Periodically to keep sessions alive before tokens expire (1 hour)

Configuration:
  - SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set
  - A Spotify account must be linked via the management API
  - Speaker IP addresses are read from the datastore (DeviceInfo)
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from soundcork.config import Settings
from soundcork.datastore import DataStore
from soundcork.spotify_service import SpotifyService

logger = logging.getLogger(__name__)

ZEROCONF_PORT = 8200
PERIODIC_CHECK_SECONDS = 45 * 60  # 45 minutes
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

    # --- Speaker registration ---

    def register_speaker(self, account_id: str, device_id: str):
        """Register a speaker that contacted a marge endpoint.

        Called from marge request handlers.  If this is a new speaker,
        resolves its IP and primes it in the background.
        """
        if not self._settings.spotify_client_id:
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
                    "New speaker registered: %s (account=%s, ip=%s)",
                    device_id,
                    account_id,
                    ip,
                )
            else:
                # Update account_id in case it changed
                self._speakers[device_id].account_id = account_id

        if is_new:
            speaker = self._speakers[device_id]
            if speaker.ip_address:
                threading.Thread(
                    target=self._prime_if_needed,
                    args=(speaker,),
                    daemon=True,
                ).start()

    def on_power_on(self, source_ip: str | None = None):
        """Called when a speaker sends power_on.

        Primes all known speakers with retry/backoff, since the
        speaker's ZeroConf port may not be ready immediately.
        If no speakers are registered yet, discovers from datastore.
        """
        if not self._settings.spotify_client_id:
            return

        threading.Thread(
            target=self._power_on_prime,
            args=(source_ip,),
            daemon=True,
        ).start()

    # --- Periodic ---

    def start_periodic(self):
        """Start the periodic re-prime background task."""
        if not self._settings.spotify_client_id:
            logger.info("Spotify not configured — periodic primer disabled")
            return

        # Seed the registry from the datastore on startup
        self._seed_from_datastore()

        self._schedule_next()
        logger.info(
            "Periodic Spotify primer started (every %d minutes)",
            PERIODIC_CHECK_SECONDS // 60,
        )

    def stop_periodic(self):
        """Stop the periodic re-prime background task."""
        if self._timer:
            self._timer.cancel()
            self._timer = None

    # --- Internal ---

    def _seed_from_datastore(self):
        """Populate the speaker registry from the datastore on startup."""
        import os

        data_dir = self._settings.data_dir
        if not data_dir or not os.path.isdir(data_dir):
            return

        for account_id in os.listdir(data_dir):
            account_path = os.path.join(data_dir, account_id)
            if not os.path.isdir(account_path):
                continue

            try:
                device_ids = self._datastore.list_devices(account_id)
            except (StopIteration, FileNotFoundError):
                continue

            for device_id in device_ids:
                if not device_id:
                    continue
                ip = self._resolve_speaker_ip(account_id, device_id)
                if ip:
                    with self._lock:
                        if device_id not in self._speakers:
                            self._speakers[device_id] = TrackedSpeaker(
                                account_id=account_id,
                                device_id=device_id,
                                ip_address=ip,
                            )

        count = len(self._speakers)
        if count:
            logger.info("Seeded %d speaker(s) from datastore", count)

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

        token = self._spotify.get_fresh_token_sync()
        if not token:
            logger.warning("Could not get Spotify access token")
            return None

        self._cached_token = token
        self._token_expires_at = now + 3600  # tokens last 1 hour
        return token, user_id

    def _prime_if_needed(self, speaker: TrackedSpeaker) -> bool:
        """Check activeUser and prime only if empty."""
        if not speaker.ip_address:
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
                return True
        except Exception:
            logger.debug("Could not check activeUser for %s", speaker.ip_address)

        return self._prime_speaker(speaker)

    def _prime_speaker(self, speaker: TrackedSpeaker) -> bool:
        """Send addUser to a speaker."""
        if not speaker.ip_address:
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
            time.sleep(2)
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
            else:
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
        with self._lock:
            speakers = list(self._speakers.values())

        if not speakers:
            logger.info("No speakers registered — nothing to prime")
            return

        for delay in BOOT_RETRY_DELAYS:
            logger.info(
                "Speaker booted — waiting %ds before priming %d speaker(s)...",
                delay,
                len(speakers),
            )
            time.sleep(delay)

            all_ok = True
            for speaker in speakers:
                if not speaker.ip_address:
                    continue
                if not self._prime_if_needed(speaker):
                    all_ok = False

            if all_ok:
                logger.info("All speakers primed successfully")
                return

        logger.warning("Some speakers failed to prime after all retries")

    def _schedule_next(self):
        """Schedule the next periodic check."""
        self._timer = threading.Timer(PERIODIC_CHECK_SECONDS, self._periodic_tick)
        self._timer.daemon = True
        self._timer.start()

    def _periodic_tick(self):
        """Periodic task: check and re-prime all speakers if needed."""
        try:
            logger.info("Periodic Spotify primer check running...")
            with self._lock:
                speakers = list(self._speakers.values())

            for speaker in speakers:
                self._prime_if_needed(speaker)

            # Remove speakers that have failed too many times in a row.
            # They get re-added automatically when they contact marge
            # or send a power_on event.
            with self._lock:
                to_remove = [
                    did
                    for did, s in self._speakers.items()
                    if s.prime_failures >= MAX_CONSECUTIVE_FAILURES
                ]
                for did in to_remove:
                    s = self._speakers.pop(did)
                    logger.warning(
                        "Removed unreachable speaker %s (%s) after %d consecutive failures",
                        did,
                        s.ip_address,
                        s.prime_failures,
                    )

        except Exception:
            logger.exception("Error during periodic Spotify primer")
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
