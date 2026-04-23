"""Management API endpoints for the ueberboese-app.

These endpoints are NOT part of the Bose SoundTouch protocol. They are
custom endpoints used by the ueberboese Flutter app for speaker management,
device events, and Spotify integration.

All endpoints require HTTP Basic Auth.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from soundcork.config import Settings
from soundcork.datastore import DataStore
from soundcork.mgmt_auth import verify_credentials
from soundcork.spotify_service import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt", tags=["management"])

datastore = DataStore()
settings = Settings()
spotify = SpotifyService()


# --- Speaker Management ---


@router.get("/accounts/{account_id}/speakers")
def list_speakers(
    account_id: str,
    _user: str = Depends(verify_credentials),
):
    """List all speakers for an account.

    Returns IP addresses and basic info for each device, so the app
    can connect to them directly on port 8090.
    """
    try:
        device_ids = datastore.list_devices(account_id)
    except (StopIteration, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Account not found")

    speakers = []
    for device_id in device_ids:
        try:
            info = datastore.get_device_info(account_id, device_id)
            speakers.append(
                {
                    "ipAddress": info.ip_address,
                    "name": info.name,
                    "deviceId": info.device_id,
                    "type": info.product_code,
                }
            )
        except Exception:
            logger.warning("Failed to read device info for %s", device_id)
            continue

    return {"speakers": speakers}


# --- Device Events ---


@router.get("/devices/{device_id}/events")
def list_device_events(
    device_id: str,
    _user: str = Depends(verify_credentials),
):
    """List events for a device.

    Currently returns an empty list. Can be extended later to log
    power_on events, preset changes, etc.
    """
    return {"events": []}


# --- Spotify ---


@router.post("/spotify/init")
def spotify_init(
    request: Request,
    _user: str = Depends(verify_credentials),
):
    """Start the Spotify OAuth flow.

    Returns a redirect URL that the app should open in a browser.
    The user authorizes there, and Spotify redirects back to the
    configured redirect_uri (mobile deep link) with an authorization code.
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

    Unlike POST /spotify/init (used by the mobile app), this endpoint
    redirects the browser directly to Spotify with the server-side
    callback URL, so the entire flow happens in the browser.
    No Basic Auth required — the callback is on this server.
    """
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured (missing SPOTIFY_CLIENT_ID)",
        )

    # Use the server callback URL instead of the mobile deep link.
    # We use settings.base_url rather than request.base_url because the
    # app sits behind a TLS-terminating reverse proxy (Traefik) and
    # request.base_url returns http:// while Spotify requires the
    # registered https:// redirect URI.
    callback_url = settings.base_url.rstrip("/") + "/mgmt/spotify/callback"
    authorize_url = spotify.build_authorize_url(redirect_uri=callback_url)

    return RedirectResponse(url=authorize_url)


@router.get("/spotify/callback", response_class=HTMLResponse)
async def spotify_callback(
    request: Request,
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
):
    """Server-side OAuth callback for web/localhost flows.

    This endpoint is NOT protected by Basic Auth because Spotify
    redirects the user's browser here directly.

    After exchanging the code for tokens, it shows a success page
    that the user can close.
    """
    if error:
        return HTMLResponse(
            content=f"<html><body><h1>Spotify Authorization Failed</h1><p>Error: {error}</p></body></html>",
            status_code=400,
        )

    if not code:
        return HTMLResponse(
            content="<html><body><h1>Missing authorization code</h1></body></html>",
            status_code=400,
        )

    try:
        # The redirect_uri must match what was used in the authorize request
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
async def spotify_confirm(
    code: Annotated[str, Query()],
    _user: str = Depends(verify_credentials),
):
    """Confirm Spotify authorization with an authorization code.

    Used by the mobile app after the deep link callback delivers
    the code. Exchanges the code for tokens and stores the account.
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
def spotify_accounts(
    _user: str = Depends(verify_credentials),
):
    """List connected Spotify accounts."""
    accounts = spotify.list_accounts()
    # Strip tokens from the response — the app only needs display info
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


@router.get("/spotify/token")
def spotify_token(
    _user: str = Depends(verify_credentials),
):
    """Get a fresh Spotify access token and username.

    Used by the on-speaker boot primer to prime the ZeroConf endpoint
    without needing Spotify credentials stored on the device.
    """
    user_id = spotify.get_spotify_user_id()
    if not user_id:
        raise HTTPException(status_code=404, detail="No Spotify account linked")

    access_token = spotify.get_fresh_token_sync()
    if not access_token:
        raise HTTPException(status_code=503, detail="Failed to get Spotify token")

    return {"accessToken": access_token, "username": user_id}


@router.post("/spotify/activate-speaker")
async def activate_speaker(
    device_name: str = Query("Bose", description="Substring to match in Spotify Connect device name"),
    _user: str = Depends(verify_credentials),
):
    """Transfer the Spotify playback session to the speaker.

    After ZeroConf priming the speaker is registered with Spotify but
    idle.  This endpoint does what the Spotify desktop app does when you
    select the speaker: it calls ``PUT /v1/me/player`` to transfer the
    session, which triggers Spotify's servers to activate streaming on
    the device.  Called by the on-speaker boot primer after addUser.
    """
    try:
        result = await spotify.activate_speaker(device_name_hint=device_name)
        return result
    except Exception as e:
        logger.exception("Failed to activate speaker")
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/spotify/entity")
async def spotify_entity(
    request: Request,
    _user: str = Depends(verify_credentials),
):
    """Resolve a Spotify URI to a name and image URL.

    Used by the app when storing Spotify presets — it needs the
    track/album/playlist name and cover art to display in the UI.
    """
    body = await request.json()
    uri = body.get("uri", "")

    if not uri or not uri.startswith("spotify:"):
        raise HTTPException(status_code=400, detail={"message": "Invalid Spotify URI"})

    try:
        entity = await spotify.resolve_entity(uri)
        return entity
    except Exception as e:
        logger.exception("Failed to resolve Spotify entity: %s", uri)
        raise HTTPException(status_code=500, detail=str(e))
