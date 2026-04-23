"""Spotify OAuth and Web API integration.

Handles the authorization code flow, token management, and entity
resolution for the ueberboese-app's Spotify features.
"""

import asyncio
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone

import httpx

from soundcork.config import Settings

logger = logging.getLogger(__name__)

SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# Scopes needed for streaming playback, user profile, and entity resolution
SPOTIFY_SCOPES = "streaming user-read-private user-read-email user-read-playback-state user-modify-playback-state"


class SpotifyService:
    def __init__(self):
        self._settings = Settings()
        self._accounts_file = os.path.join(self._settings.data_dir, "spotify", "accounts.json")

    def _ensure_spotify_dir(self):
        """Create the spotify data directory if it doesn't exist."""
        spotify_dir = os.path.dirname(self._accounts_file)
        os.makedirs(spotify_dir, exist_ok=True)

    def _load_accounts(self) -> list[dict]:
        """Load stored Spotify accounts from disk."""
        if not os.path.isfile(self._accounts_file):
            return []
        try:
            with open(self._accounts_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read Spotify accounts file")
            return []

    def _save_accounts(self, accounts: list[dict]):
        """Save Spotify accounts to disk."""
        self._ensure_spotify_dir()
        with open(self._accounts_file, "w") as f:
            json.dump(accounts, f, indent=2)

    def build_authorize_url(self, redirect_uri: str | None = None) -> str:
        """Build the Spotify authorization URL for the OAuth flow.

        Args:
            redirect_uri: Override the default redirect URI (e.g. for
                server-side callback vs mobile deep link).
        """
        params = {
            "client_id": self._settings.spotify_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri or self._settings.spotify_redirect_uri,
            "scope": SPOTIFY_SCOPES,
        }
        return f"{SPOTIFY_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code_and_store(self, code: str, redirect_uri: str | None = None) -> dict:
        """Exchange an authorization code for tokens and store the account.

        Args:
            code: The authorization code from Spotify.
            redirect_uri: The redirect URI that was used in the authorize
                request. Must match exactly or Spotify rejects it.

        Returns the stored account dict.
        """
        # Exchange code for tokens
        token_data = await self._exchange_code(code, redirect_uri)

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)

        # Fetch user profile
        profile = await self._get_user_profile(access_token)

        account = {
            "displayName": profile.get("display_name", "Unknown"),
            "spotifyUserId": profile["id"],
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "tokenExpiresAt": int(time.time()) + expires_in,
        }

        # Upsert into accounts list (replace if same user ID exists)
        accounts = self._load_accounts()
        accounts = [a for a in accounts if a["spotifyUserId"] != account["spotifyUserId"]]
        accounts.append(account)
        self._save_accounts(accounts)

        logger.info("Spotify account linked: %s", account["displayName"])
        return account

    async def _exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Exchange an authorization code for access and refresh tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri or self._settings.spotify_redirect_uri,
                },
                auth=(
                    self._settings.spotify_client_id,
                    self._settings.spotify_client_secret,
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            error_detail = response.text
            logger.error("Spotify token exchange failed: %s", error_detail)
            raise RuntimeError(f"Spotify token exchange failed: {error_detail}")

        return response.json()

    async def _refresh_access_token(self, refresh_token: str) -> dict:
        """Refresh an expired access token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                auth=(
                    self._settings.spotify_client_id,
                    self._settings.spotify_client_secret,
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            raise RuntimeError(f"Spotify token refresh failed: {response.text}")

        return response.json()

    async def _get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Uses the first stored account's tokens.
        """
        accounts = self._load_accounts()
        if not accounts:
            raise RuntimeError("No Spotify accounts linked")

        account = accounts[0]
        now = int(time.time())

        # Refresh if token is expired or about to expire (60s buffer)
        if now >= account.get("tokenExpiresAt", 0) - 60:
            refresh_token = account.get("refreshToken", "")
            if not refresh_token:
                raise RuntimeError("No refresh token available")

            token_data = await self._refresh_access_token(refresh_token)
            account["accessToken"] = token_data["access_token"]
            account["tokenExpiresAt"] = now + token_data.get("expires_in", 3600)
            # Spotify may return a new refresh token
            if "refresh_token" in token_data:
                account["refreshToken"] = token_data["refresh_token"]
            self._save_accounts(accounts)

        return account["accessToken"]

    def get_fresh_token_sync(self) -> str | None:
        """Get a valid Spotify access token synchronously.

        Used by the marge endpoints (which are sync) to inject fresh
        tokens into the /full account response for the speaker.

        Returns None if no Spotify account is linked or refresh fails.
        """
        accounts = self._load_accounts()
        if not accounts:
            return None

        if not self._settings.spotify_client_id:
            return None

        account = accounts[0]
        now = int(time.time())

        # Refresh if token is expired or about to expire (60s buffer)
        if now >= account.get("tokenExpiresAt", 0) - 60:
            refresh_token = account.get("refreshToken", "")
            if not refresh_token:
                logger.warning("No Spotify refresh token available")
                return None

            try:
                response = httpx.post(
                    SPOTIFY_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    auth=(
                        self._settings.spotify_client_id,
                        self._settings.spotify_client_secret,
                    ),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code != 200:
                    logger.error("Spotify token refresh failed: %s", response.text)
                    return None

                token_data = response.json()
                account["accessToken"] = token_data["access_token"]
                account["tokenExpiresAt"] = now + token_data.get("expires_in", 3600)
                if "refresh_token" in token_data:
                    account["refreshToken"] = token_data["refresh_token"]
                self._save_accounts(accounts)
                logger.info("Spotify token refreshed for speaker injection")
            except Exception:
                logger.exception("Failed to refresh Spotify token")
                return None

        return account["accessToken"]

    def get_spotify_user_id(self) -> str | None:
        """Get the Spotify user ID of the first linked account."""
        accounts = self._load_accounts()
        if not accounts:
            return None
        return accounts[0].get("spotifyUserId")

    async def _get_user_profile(self, access_token: str) -> dict:
        """Fetch the current user's Spotify profile."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch Spotify profile: {response.text}")

        return response.json()

    def list_accounts(self) -> list[dict]:
        """List all stored Spotify accounts (with tokens stripped)."""
        return self._load_accounts()

    async def resolve_entity(self, uri: str) -> dict:
        """Resolve a Spotify URI to a name and image URL.

        Supports: spotify:track:ID, spotify:album:ID,
        spotify:playlist:ID, spotify:artist:ID
        """
        parts = uri.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid Spotify URI format: {uri}")

        entity_type = parts[1]  # track, album, playlist, artist
        entity_id = parts[2]

        valid_types = {"track", "album", "playlist", "artist"}
        if entity_type not in valid_types:
            raise ValueError(f"Unsupported Spotify entity type: {entity_type}")

        # Pluralize for the API path (track -> tracks, etc.)
        api_type = entity_type + "s"

        access_token = await self._get_valid_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/{api_type}/{entity_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code == 404:
            raise ValueError("Spotify entity not found")

        if response.status_code != 200:
            raise RuntimeError(f"Spotify API error: {response.text}")

        data = response.json()
        name = data.get("name", "Unknown")

        # Extract image URL — location varies by entity type
        image_url = None
        images = data.get("images", [])
        if not images and entity_type == "track":
            # Tracks store images on the album
            album_images = data.get("album", {}).get("images", [])
            if album_images:
                image_url = album_images[0].get("url")
        elif images:
            image_url = images[0].get("url")

        return {"name": name, "imageUrl": image_url}

    async def activate_speaker(
        self,
        device_name_hint: str = "Bose",
        max_retries: int = 5,
        retry_delay: float = 5.0,
    ) -> dict:
        """Transfer the Spotify playback session to a speaker.

        After ZeroConf priming the speaker is registered with Spotify's
        servers but idle.  Transferring playback via the Web API triggers
        Spotify to push an activation command to the speaker over its AP
        connection, which is exactly what the Spotify desktop/web app does
        when you select the speaker as playback device.

        Without this step the speaker's embedded Spotify SDK cannot
        initiate playback for SoundTouch presets (stuck in BUFFERING_STATE).

        Args:
            device_name_hint: Substring to match in the Spotify Connect
                device name (case-insensitive).
            max_retries: How many times to poll for the device to appear
                in the Spotify device list after ZeroConf priming.
            retry_delay: Seconds between retries.

        Returns:
            Dict with ``id``, ``name``, and ``activated`` flag.
        """
        access_token = await self._get_valid_token()

        speaker = None
        devices: list[dict] = []
        for attempt in range(1, max_retries + 1):
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{SPOTIFY_API_BASE}/me/player/devices",
                    headers={"Authorization": f"Bearer {access_token}"},
                )

            if response.status_code != 200:
                raise RuntimeError(f"Failed to list Spotify devices: {response.text}")

            devices = response.json().get("devices", [])
            speaker = next(
                (d for d in devices if device_name_hint.lower() in d.get("name", "").lower()),
                None,
            )
            if speaker:
                break

            if attempt < max_retries:
                logger.info(
                    "Speaker not found yet (attempt %d/%d, hint='%s'), retrying in %ds...",
                    attempt,
                    max_retries,
                    device_name_hint,
                    int(retry_delay),
                )
                await asyncio.sleep(retry_delay)

        if not speaker:
            available = [d.get("name") for d in devices]
            raise RuntimeError(f"Speaker not found (hint='{device_name_hint}'). Available: {available}")

        # Transfer playback to the speaker without starting audio.
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{SPOTIFY_API_BASE}/me/player",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"device_ids": [speaker["id"]], "play": False},
            )

        if response.status_code not in (200, 204):
            raise RuntimeError(f"Failed to transfer playback: {response.text}")

        logger.info(
            "Playback transferred to speaker '%s' (id=%s)",
            speaker["name"],
            speaker["id"],
        )
        return {"id": speaker["id"], "name": speaker["name"], "activated": True}
