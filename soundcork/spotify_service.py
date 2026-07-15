"""Spotify OAuth and Web API integration.

Handles the authorization code flow, token management, and entity
resolution for Spotify-connected speakers.

All Spotify functionality is optional -- if SPOTIFY_CLIENT_ID is not
configured, the management API gracefully disables Spotify endpoints.
"""

import asyncio
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone

# TODO pick one of httpx or requests, and use consistently across the app. If there's no features of httpx
# in particular this uses, switch to requests.
import httpx

from soundcork.config import Settings

logger = logging.getLogger(__name__)

# TODO move to constants
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# Scopes needed for user profile, entity resolution, and Web Playback SDK tokens.
SPOTIFY_SCOPES_MINIMAL = "streaming user-read-email user-read-private"
SPOTIFY_SCOPES = SPOTIFY_SCOPES_MINIMAL

# full set of permissions that bose returned; included in case they're
# needed in the future (like for browse)
SPOTIFY_SCOPES_FULL = (
    "streaming user-read-email user-read-private playlist-read-private"
    " playlist-read-collaborative user-library-read user-read-playback-state"
    " user-modify-playback-state user-read-currently-playing user-read-recently-played"
)


class SpotifyService:
    """TODO refactor so instead of writing to disk, it relies on either the datastore or storing in memory."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._accounts_file = os.path.join(
            self._settings.data_dir, "spotify", "accounts.json"
        )

    @property
    def spotify_scopes(self) -> str:
        return self._settings.spotify_scopes or SPOTIFY_SCOPES_MINIMAL

    def _ensure_spotify_dir(self):
        """Create the spotify data directory if it doesn't exist.

        TODO: handle the exceptions on failure
        """
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
            "scope": self.spotify_scopes,
        }
        return f"{SPOTIFY_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code_and_store(
        self, code: str, redirect_uri: str | None = None
    ) -> dict:
        """Exchange an authorization code for tokens and store the account.

        Args:
            code: The authorization code from Spotify.
            redirect_uri: The redirect URI that was used in the authorize
                request. Must match exactly or Spotify rejects it.

        Returns the stored account dict.
        """
        token_data = await self._exchange_code(code, redirect_uri)

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)

        profile = await self._get_user_profile(access_token)

        account = {
            "displayName": profile.get("display_name", "Unknown"),
            "spotifyUserId": profile["id"],
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "tokenExpiresAt": int(time.time()) + expires_in,
            "scope": token_data.get("scope", self.spotify_scopes),
        }

        # Upsert: replace if same user ID already exists
        accounts = self._load_accounts()
        accounts = [
            a for a in accounts if a["spotifyUserId"] != account["spotifyUserId"]
        ]
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

    async def _get_valid_token(self) -> dict:
        """Get a valid access token, refreshing if necessary."""
        accounts = self._load_accounts()
        if not accounts:
            raise RuntimeError("No Spotify accounts linked")

        account = accounts[0]
        now = int(time.time())

        if now >= account.get("tokenExpiresAt", 0) - 60:
            refresh_token = account.get("refreshToken", "")
            if not refresh_token:
                raise RuntimeError("No refresh token available")

            token_data = await self._refresh_access_token(refresh_token)
            account["accessToken"] = token_data["access_token"]
            account["tokenExpiresAt"] = now + token_data.get("expires_in", 3600)
            if "refresh_token" in token_data:
                account["refreshToken"] = token_data["refresh_token"]
            account["scope"] = token_data.get(
                "scope", account.get("scope", self.spotify_scopes)
            )
            self._save_accounts(accounts)

        return {
            "access_token": account["accessToken"],
            "token_type": "Bearer",
            "expires_in": account["tokenExpiresAt"] - now,
            "scope": account.get("scope", self.spotify_scopes),
        }

    def get_fresh_token_sync(self) -> dict:
        return asyncio.run(self._get_valid_token())

    def get_spotify_user_id(self) -> str:
        accounts = self._load_accounts()
        if not accounts:
            return ""
        return accounts[0].get("spotifyUserId") or accounts[0].get("id", "")

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
        """List all stored Spotify accounts."""
        return self._load_accounts()
