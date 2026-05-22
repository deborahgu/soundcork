"""Management API endpoints for soundcork.

These endpoints are NOT part of the Bose SoundTouch protocol. They
provide a JSON API for managing soundcork configuration, listing
speakers, and optionally linking Spotify accounts.


Spotify endpoints are only available when SPOTIFY_CLIENT_ID and
SPOTIFY_CLIENT_SECRET are configured.
"""

# TODO:  move functionality into /admin section
# TODO:  move oauth application configuration (client_id and client_secret)
#        out of Settings and into a per-account configuration that can
#        be modified from the admin UI

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from soundcork.config import Settings
from soundcork.datastore import DataStore
from soundcork.spotify_service import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt", tags=["management"])

datastore = DataStore()
settings = Settings()
spotify = SpotifyService(settings)


# --- Spotify ---


@router.post("/spotify/init")
def spotify_init(request: Request):
    """Start the Spotify OAuth flow.

    Returns a redirect URL that the caller should open in a browser.
    After authorization, Spotify redirects to the configured redirect_uri
    with an authorization code.
    """
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured (missing SPOTIFY_CLIENT_ID)",
        )

    authorize_url = spotify.build_authorize_url()
    return {"redirectUrl": authorize_url}


@router.get("/spotify/init")
def spotify_init_browser(request: Request):
    """Start the Spotify OAuth flow via browser redirect.

    Unlike POST /spotify/init, this endpoint redirects the browser
    directly to Spotify with the server-side callback URL, so the
    entire flow happens in the browser.

    No Basic Auth required -- the callback is on this server.
    """
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured (missing SPOTIFY_CLIENT_ID)",
        )

    # Use the server callback URL. We use settings.base_url rather than
    # request.base_url because the app may sit behind a TLS-terminating
    # reverse proxy and request.base_url would return http://.
    callback_url = settings.base_url.rstrip("/") + "/mgmt/spotify/callback"
    authorize_url = spotify.build_authorize_url(redirect_uri=callback_url)

    return RedirectResponse(url=authorize_url)


@router.get("/spotify/callback", response_class=HTMLResponse)
async def spotify_callback(
    request: Request,
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
):
    """Server-side OAuth callback.

    This endpoint is NOT protected by Basic Auth because Spotify
    redirects the user's browser here directly.
    """
    if error:
        return HTMLResponse(
            content=f"<html><body><h1>Spotify Authorization Failed</h1>"
            f"<p>Error: {error}</p></body></html>",
            status_code=400,
        )

    if not code:
        return HTMLResponse(
            content="<html><body><h1>Missing authorization code</h1></body></html>",
            status_code=400,
        )

    try:
        callback_url = settings.base_url.rstrip("/") + "/mgmt/spotify/callback"
        account = await spotify.exchange_code_and_store(code, redirect_uri=callback_url)
        return HTMLResponse(
            content=f"<html><body>"
            f"<h1>Spotify Connected</h1>"
            f"<p>Linked account: {account['displayName']} ({account['spotifyUserId']})</p>"
            f"<p>You can close this window.</p>"
            f"</body></html>"
        )
    except Exception as e:
        logger.exception("Spotify callback failed")
        return HTMLResponse(
            content=f"<html><body><h1>Error</h1><p>{e}</p></body></html>",
            status_code=500,
        )


@router.post("/spotify/confirm")
async def spotify_confirm(code: Annotated[str, Query()]):
    """Confirm Spotify authorization with an authorization code.

    Used by mobile apps after a deep link callback delivers the code.
    Exchanges the code for tokens and stores the account.
    """
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured",
        )

    try:
        await spotify.exchange_code_and_store(code)
    except Exception as e:
        logger.exception("Spotify confirm failed")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


@router.get("/spotify/accounts")
def spotify_accounts():
    """List connected Spotify accounts (tokens stripped)."""
    accounts = spotify.list_accounts()
    return {
        "accounts": [
            {
                "displayName": a["displayName"],
                "createdAt": a["createdAt"],
                "spotifyUserId": a["spotifyUserId"],
            }
            for a in accounts
        ]
    }
