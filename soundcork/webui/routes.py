import asyncio
import ipaddress
import json
import logging
import os
from urllib.parse import urlparse

import httpx
import websockets
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from soundcork.config import Settings
from soundcork.webui.auth import SessionStore, verify_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webui", tags=["webui"])

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SPEAKER_PORT = 8090
SPEAKER_TIMEOUT = 10.0

# Server-side settings (loaded once at import time, same instance as main app)
_settings = Settings()

# --- Session auth ---
_session_store = SessionStore()
_SESSION_COOKIE = "webui_session"


# --- Security helpers ---

# Allowed CDN domains for the image proxy (prevents SSRF to arbitrary URLs)
_IMAGE_PROXY_ALLOWED_DOMAINS = frozenset(
    {
        "cdn-profiles.tunein.com",
        "cdn-images.tunein.com",
        "cdn-albums.tunein.com",
        "cdn-radiotime-logos.tunein.com",
        "image-cdn-ak.spotifycdn.com",
        "image-cdn-fa.spotifycdn.com",
        "i.scdn.co",
        "mosaic.scdn.co",
        "seed-mix-image.spotifycdn.com",
    }
)

# Allowed mgmt proxy paths (prevents exposing token endpoints)
_MGMT_ALLOWED_PATHS = frozenset(
    {
        "spotify/accounts",
        "spotify/entity",
        "spotify/init",
        "spotify/callback",
    }
)
# Paths that are allowed as prefixes (e.g. accounts/{id}/speakers)
_MGMT_ALLOWED_PREFIXES = ("accounts/",)


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/loopback/link-local IP."""
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False


def _is_allowed_image_url(url: str) -> bool:
    """Check if a URL is on an allowed CDN domain and not a private IP."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if _is_private_ip(hostname):
            return False
        return hostname in _IMAGE_PROXY_ALLOWED_DOMAINS
    except Exception:
        return False


def _is_allowed_mgmt_path(path: str) -> bool:
    """Check if a mgmt proxy path is on the allowlist."""
    # Normalize: strip leading slashes, reject path traversal
    clean = path.lstrip("/")
    if ".." in clean:
        return False
    if clean in _MGMT_ALLOWED_PATHS:
        return True
    return any(clean.startswith(prefix) for prefix in _MGMT_ALLOWED_PREFIXES)


def _get_speaker_allowlist():
    """Get the speaker allowlist from main (lazy import to avoid circular deps)."""
    from soundcork.main import get_speaker_allowlist

    return get_speaker_allowlist()


# --- Speaker Storage ---
# Speakers are persisted server-side in a JSON file so they survive browser clears
# and are shared across all clients.


def _speakers_file() -> str:
    return os.path.join(_settings.data_dir, "webui_speakers.json")


def _load_speakers() -> list[dict]:
    path = _speakers_file()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read webui speakers file: %s", path)
        return []


def _save_speakers(speakers: list[dict]) -> None:
    path = _speakers_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(speakers, f, indent=2)


# --- Static File Serving ---


@router.get("/")
async def webui_index():
    """Serve the web UI single-page application."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# --- Authentication Endpoints ---


@router.get("/login")
async def webui_login_page():
    """Serve the login page."""
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@router.post("/api/login")
async def webui_login(request: Request):
    """Authenticate and create a session."""
    try:
        body = await request.json()
        username = body.get("username", "")
        password = body.get("password", "")
    except Exception:
        return JSONResponse({"detail": "Invalid request"}, status_code=401)

    if not verify_login(username, password):
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    session_id, csrf_token = _session_store.create()
    response = JSONResponse({"csrf_token": csrf_token})
    response.set_cookie(
        key=_SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        path="/webui",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/api/logout")
async def webui_logout(request: Request):
    """Destroy the session and clear the cookie."""
    session_id = request.cookies.get(_SESSION_COOKIE, "")
    _session_store.destroy(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=_SESSION_COOKIE, path="/webui")
    return response


# --- Server Config (exposed to the UI, no secrets) ---


@router.get("/api/config")
async def webui_config():
    """Return server configuration that the UI needs (no credentials)."""
    return {
        "baseUrl": _settings.base_url,
        "hasSpotify": bool(_settings.spotify_client_id),
        "oidcEnabled": _settings.oidc_enabled,
    }


# --- Server-Side Speaker CRUD ---


@router.get("/api/speakers")
async def list_webui_speakers():
    """Return the saved speaker list."""
    return _load_speakers()


@router.post("/api/speakers")
async def add_webui_speaker(request: Request):
    """Add a speaker to the saved list."""
    speaker = await request.json()
    speakers = _load_speakers()
    # Deduplicate by ipAddress
    if any(s["ipAddress"] == speaker["ipAddress"] for s in speakers):
        return JSONResponse({"detail": "Speaker already exists"}, status_code=409)
    speakers.append(speaker)
    _save_speakers(speakers)
    return speaker


@router.put("/api/speakers/{ip}")
async def update_webui_speaker(ip: str, request: Request):
    """Update a speaker in the saved list."""
    updates = await request.json()
    speakers = _load_speakers()
    for s in speakers:
        if s["ipAddress"] == ip:
            s.update(updates)
            _save_speakers(speakers)
            return s
    return JSONResponse({"detail": "Speaker not found"}, status_code=404)


@router.delete("/api/speakers/{ip}")
async def delete_webui_speaker(ip: str):
    """Remove a speaker from the saved list."""
    speakers = _load_speakers()
    new_speakers = [s for s in speakers if s["ipAddress"] != ip]
    if len(new_speakers) == len(speakers):
        return JSONResponse({"detail": "Speaker not found"}, status_code=404)
    _save_speakers(new_speakers)
    return {"ok": True}


# --- Discover speakers from all accounts in the datastore ---


@router.get("/api/discover-speakers")
async def discover_speakers():
    """Discover speakers from all accounts in the soundcork datastore."""
    from soundcork.datastore import DataStore

    ds = DataStore()
    all_speakers = []
    try:
        for account_id in ds.list_accounts():
            if not account_id:
                continue
            try:
                for device_id in ds.list_devices(account_id):
                    if not device_id:
                        continue
                    try:
                        info = ds.get_device_info(account_id, device_id)
                        all_speakers.append(
                            {
                                "ipAddress": info.ip_address,
                                "name": info.name,
                                "deviceId": info.device_id,
                                "type": info.product_code,
                                "accountId": account_id,
                            }
                        )
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Failed to discover speakers: {e}")
    return {"speakers": all_speakers}


# --- Management API Proxy ---
# The UI calls these instead of calling /mgmt/* directly.
# This way the browser never needs to know the mgmt credentials.


@router.get("/api/mgmt/{path:path}")
async def proxy_mgmt_get(path: str, request: Request):
    """Proxy GET requests to the management API with server-side auth."""
    if not _is_allowed_mgmt_path(path):
        return JSONResponse({"detail": "Forbidden: mgmt path not allowed"}, status_code=403)
    params = dict(request.query_params)
    base = _settings.base_url or "http://localhost:8000"
    auth = httpx.BasicAuth(_settings.mgmt_username, _settings.mgmt_password)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base}/mgmt/{path}",
                params=params,
                auth=auth,
                timeout=SPEAKER_TIMEOUT,
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"Content-Type": resp.headers.get("content-type", "application/json")},
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning(f"Mgmt proxy error: {e}")
        return Response(content="Management API unreachable", status_code=502)


@router.post("/api/mgmt/{path:path}")
async def proxy_mgmt_post(path: str, request: Request):
    """Proxy POST requests to the management API with server-side auth."""
    if not _is_allowed_mgmt_path(path):
        return JSONResponse({"detail": "Forbidden: mgmt path not allowed"}, status_code=403)
    body = await request.body()
    content_type = request.headers.get("content-type", "application/json")
    base = _settings.base_url or "http://localhost:8000"
    auth = httpx.BasicAuth(_settings.mgmt_username, _settings.mgmt_password)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base}/mgmt/{path}",
                content=body,
                headers={"Content-Type": content_type},
                auth=auth,
                timeout=SPEAKER_TIMEOUT,
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"Content-Type": resp.headers.get("content-type", "application/json")},
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning(f"Mgmt proxy error: {e}")
        return Response(content="Management API unreachable", status_code=502)


# --- Speaker Proxy API ---
# The browser can't directly talk to speakers on the LAN (different origin = CORS).
# These endpoints proxy requests through the soundcork server.


@router.get("/api/speaker/{ip}/{path:path}")
async def proxy_speaker_get(ip: str, path: str):
    """Proxy GET requests to a speaker on the LAN."""
    if not _get_speaker_allowlist().is_registered_speaker(ip):
        return JSONResponse({"detail": "Forbidden: unregistered speaker IP"}, status_code=403)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://{ip}:{SPEAKER_PORT}/{path}",
                timeout=SPEAKER_TIMEOUT,
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"Content-Type": resp.headers.get("content-type", "text/xml")},
        )
    except httpx.ConnectError:
        return Response(content="Speaker unreachable", status_code=502)
    except httpx.TimeoutException:
        return Response(content="Speaker timeout", status_code=504)


@router.post("/api/speaker/{ip}/{path:path}")
async def proxy_speaker_post(ip: str, path: str, request: Request):
    """Proxy POST requests to a speaker on the LAN."""
    if not _get_speaker_allowlist().is_registered_speaker(ip):
        return JSONResponse({"detail": "Forbidden: unregistered speaker IP"}, status_code=403)
    body = await request.body()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://{ip}:{SPEAKER_PORT}/{path}",
                content=body,
                headers={"Content-Type": request.headers.get("content-type", "text/xml")},
                timeout=SPEAKER_TIMEOUT,
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"Content-Type": resp.headers.get("content-type", "text/xml")},
        )
    except httpx.ConnectError:
        return Response(content="Speaker unreachable", status_code=502)
    except httpx.TimeoutException:
        return Response(content="Speaker timeout", status_code=504)


# --- Image Proxy ---
# Browsers block direct requests to third-party CDNs (tracking protection,
# ad blockers, mixed-content).  Routing images through our server avoids this.


# 1x1 transparent PNG for graceful fallback when upstream image is unavailable
_TRANSPARENT_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@router.get("/api/image")
async def proxy_image(url: str):
    """Proxy an external image URL so the browser never fetches it directly."""
    if not url.startswith(("http://", "https://")):
        return Response(content="Invalid URL", status_code=400)
    if not _is_allowed_image_url(url):
        return JSONResponse({"detail": "Forbidden: URL domain not allowed"}, status_code=403)
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=SPEAKER_TIMEOUT)
        if resp.status_code >= 400:
            # Upstream refused — return transparent pixel so <img> doesn't break
            return Response(
                content=_TRANSPARENT_1X1,
                status_code=200,
                headers={
                    "Content-Type": "image/png",
                    "Cache-Control": "public, max-age=300",
                },
            )
        content_type = resp.headers.get("content-type", "application/octet-stream")
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=86400",
            },
        )
    except (httpx.ConnectError, httpx.TimeoutException):
        return Response(
            content=_TRANSPARENT_1X1,
            status_code=200,
            headers={
                "Content-Type": "image/png",
                "Cache-Control": "public, max-age=300",
            },
        )


# --- TuneIn Proxy API ---
# Avoids CORS issues when the browser needs to search TuneIn.


@router.get("/api/tunein/{path:path}")
async def proxy_tunein(path: str, request: Request):
    """Proxy GET requests to the TuneIn public API."""
    params = dict(request.query_params)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://opml.radiotime.com/{path}",
                params=params,
                timeout=SPEAKER_TIMEOUT,
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"Content-Type": resp.headers.get("content-type", "text/xml")},
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning(f"TuneIn proxy error: {e}")
        return Response(content="TuneIn unreachable", status_code=502)


# --- WebSocket Proxy ---
# Relays WebSocket connections between the browser and speaker port 8080.
# The speaker sends real-time XML updates for volume, now-playing, and zones.

SPEAKER_WS_PORT = 8080


@router.websocket("/ws/speaker/{ip}")
async def proxy_speaker_websocket(websocket: WebSocket, ip: str):
    """Proxy WebSocket connections to a speaker for real-time updates."""
    if not _get_speaker_allowlist().is_registered_speaker(ip):
        await websocket.close(code=4003, reason="Unregistered speaker IP")
        return
    await websocket.accept(subprotocol="gabbo")
    speaker_uri = f"ws://{ip}:{SPEAKER_WS_PORT}"
    try:
        async with websockets.connect(speaker_uri, subprotocols=["gabbo"]) as speaker_ws:

            async def browser_to_speaker():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await speaker_ws.send(data)
                except WebSocketDisconnect:
                    pass

            async def speaker_to_browser():
                try:
                    async for message in speaker_ws:
                        await websocket.send_text(message)
                except websockets.ConnectionClosed:
                    pass

            # Run both directions concurrently
            await asyncio.gather(
                browser_to_speaker(),
                speaker_to_browser(),
            )
    except (ConnectionRefusedError, OSError, websockets.InvalidURI) as e:
        logger.warning(f"WebSocket proxy to {ip}: {e}")
        await websocket.close(code=1011, reason=f"Speaker unreachable: {e}")
    except Exception as e:
        logger.error(f"WebSocket proxy error for {ip}: {e}")
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
