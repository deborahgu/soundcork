"""REST + WebSocket API for Home Assistant and other automation clients.

Proxies commands to Bose SoundTouch speakers on the LAN via the soundcork
server, so clients never need direct LAN access to speakers.
"""

import asyncio
import json
import logging
import os
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from soundcork.config import Settings

logger = logging.getLogger(__name__)

SPEAKER_PORT = 8090
SPEAKER_WS_PORT = 8080
SPEAKER_TIMEOUT = 5.0

_settings = Settings()

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


def _speaker_url(ip: str, path: str) -> str:
    return f"http://{ip}:{SPEAKER_PORT}{path}"


def _load_speakers() -> list[dict[str, Any]]:
    path = os.path.join(_settings.data_dir, "webui_speakers.json")
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


async def _proxy_get(ip: str, path: str) -> Response:
    try:
        async with httpx.AsyncClient(timeout=SPEAKER_TIMEOUT) as client:
            r = await client.get(_speaker_url(ip, path))
            return Response(
                content=r.content,
                media_type="application/xml",
                status_code=r.status_code,
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Cannot reach speaker at {ip}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Speaker at {ip} timed out")


async def _proxy_post(ip: str, path: str, body: bytes, content_type: str = "application/xml") -> Response:
    try:
        async with httpx.AsyncClient(timeout=SPEAKER_TIMEOUT) as client:
            r = await client.post(
                _speaker_url(ip, path),
                content=body,
                headers={"Content-Type": content_type},
            )
            return Response(
                content=r.content,
                media_type="application/xml",
                status_code=r.status_code,
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Cannot reach speaker at {ip}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Speaker at {ip} timed out")


async def _key_press(client: httpx.AsyncClient, ip: str, key: str) -> httpx.Response:
    headers = {"Content-Type": "application/xml"}
    press = f'<key state="press" sender="Gabbo">{key}</key>'.encode()
    release = f'<key state="release" sender="Gabbo">{key}</key>'.encode()
    await client.post(_speaker_url(ip, "/key"), content=press, headers=headers)
    return await client.post(_speaker_url(ip, "/key"), content=release, headers=headers)


# ---------------------------------------------------------------------------
# Speakers
# ---------------------------------------------------------------------------


@router.get("/speakers")
def list_speakers():
    """List all registered speakers."""
    return _load_speakers()


# ---------------------------------------------------------------------------
# Now Playing
# ---------------------------------------------------------------------------


@router.get("/speakers/{ip}/now-playing")
async def get_now_playing(ip: str):
    return await _proxy_get(ip, "/nowPlaying")


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


@router.get("/speakers/{ip}/presets")
async def get_presets(ip: str):
    return await _proxy_get(ip, "/presets")


@router.post("/speakers/{ip}/store-preset")
async def store_preset(ip: str, request: Request):
    return await _proxy_post(ip, "/storePreset", await request.body())


# ---------------------------------------------------------------------------
# Select / Play
# ---------------------------------------------------------------------------


@router.post("/speakers/{ip}/select")
async def select_content(ip: str, request: Request):
    return await _proxy_post(ip, "/select", await request.body())


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------


@router.get("/speakers/{ip}/volume")
async def get_volume(ip: str):
    return await _proxy_get(ip, "/volume")


@router.post("/speakers/{ip}/volume")
async def set_volume(ip: str, request: Request):
    return await _proxy_post(ip, "/volume", await request.body())


# ---------------------------------------------------------------------------
# Key (press + release)
# ---------------------------------------------------------------------------


@router.post("/speakers/{ip}/key")
async def send_key(ip: str, request: Request):
    """Forward a raw key XML body (press or release) to the speaker."""
    return await _proxy_post(ip, "/key", await request.body())


@router.post("/speakers/{ip}/key/{key_value}")
async def send_key_press_release(ip: str, key_value: str):
    """Send a key press followed by release (convenience endpoint)."""
    try:
        async with httpx.AsyncClient(timeout=SPEAKER_TIMEOUT) as client:
            r = await _key_press(client, ip, key_value.upper())
            return Response(content=r.content, media_type="application/xml", status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Cannot reach speaker at {ip}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Speaker at {ip} timed out")


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------


@router.post("/speakers/{ip}/power-on")
async def power_on(ip: str):
    """Power on — only sends key if currently in STANDBY."""
    try:
        async with httpx.AsyncClient(timeout=SPEAKER_TIMEOUT) as client:
            r = await client.get(_speaker_url(ip, "/nowPlaying"))
            import xml.etree.ElementTree as ET
            xml = ET.fromstring(r.content)
            if xml.attrib.get("source", "") == "STANDBY":
                r = await _key_press(client, ip, "POWER")
            return Response(content=r.content, media_type="application/xml", status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Cannot reach speaker at {ip}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Speaker at {ip} timed out")


@router.post("/speakers/{ip}/power-off")
async def power_off(ip: str):
    """Power off — only sends key if not already in STANDBY."""
    try:
        async with httpx.AsyncClient(timeout=SPEAKER_TIMEOUT) as client:
            r = await client.get(_speaker_url(ip, "/nowPlaying"))
            import xml.etree.ElementTree as ET
            xml = ET.fromstring(r.content)
            if xml.attrib.get("source", "") != "STANDBY":
                r = await _key_press(client, ip, "POWER")
            return Response(content=r.content, media_type="application/xml", status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Cannot reach speaker at {ip}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Speaker at {ip} timed out")


# ---------------------------------------------------------------------------
# Sources & Recents
# ---------------------------------------------------------------------------


@router.get("/speakers/{ip}/sources")
async def get_sources(ip: str):
    return await _proxy_get(ip, "/sources")


@router.get("/speakers/{ip}/recents")
async def get_recents(ip: str):
    return await _proxy_get(ip, "/recents")


# ---------------------------------------------------------------------------
# Zone management (multi-room)
# ---------------------------------------------------------------------------


@router.post("/zone/set")
async def zone_set(request: Request):
    """Create a speaker zone for synchronized playback.

    Body: {"master_ip": "...", "master_device_id": "...", "slaves": [{"ip": "...", "device_id": "..."}]}
    """
    body = await request.json()
    master_ip = body["master_ip"]
    master_device_id = body["master_device_id"]
    slaves = body.get("slaves", [])

    members = "".join(
        f'<member ipaddress="{s["ip"]}">{s["device_id"]}</member>'
        for s in slaves
    )
    zone_xml = (
        f'<zone master="{master_device_id}" senderIPAddress="{master_ip}">'
        f"{members}</zone>"
    )
    return await _proxy_post(master_ip, "/setZone", zone_xml.encode())


@router.post("/zone/clear/{ip}")
async def zone_clear(ip: str):
    """Dissolve the zone on a master speaker."""
    device_id = None
    for speaker in _load_speakers():
        if speaker.get("ipAddress") == ip:
            device_id = speaker.get("deviceId")
            break
    if not device_id:
        raise HTTPException(status_code=404, detail=f"Speaker {ip} not found in registry")

    zone_xml = f'<zone master="{device_id}" senderIPAddress="{ip}"></zone>'
    return await _proxy_post(ip, "/setZone", zone_xml.encode())


# ---------------------------------------------------------------------------
# TuneIn search proxy
# ---------------------------------------------------------------------------


@router.get("/tunein/search")
async def tunein_search(q: str):
    url = f"https://opml.radiotime.com/search.ashx?query={q}&render=json&include=podcasts"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            return Response(
                content=r.content,
                media_type=r.headers.get("content-type", "application/json"),
                status_code=r.status_code,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TuneIn search failed: {e}")


@router.get("/tunein/describe")
async def tunein_describe(id: str):
    url = f"https://opml.radiotime.com/describe.ashx?id={id}&render=json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            return Response(
                content=r.content,
                media_type=r.headers.get("content-type", "application/json"),
                status_code=r.status_code,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TuneIn describe failed: {e}")


# ---------------------------------------------------------------------------
# WebSocket proxy to speaker (real-time updates)
# ---------------------------------------------------------------------------


@router.websocket("/ws/speaker/{ip}")
async def ws_speaker_proxy(websocket: WebSocket, ip: str):
    """Proxy WebSocket to a speaker for real-time nowPlaying/volume/preset updates."""
    await websocket.accept(subprotocol="gabbo")
    speaker_uri = f"ws://{ip}:{SPEAKER_WS_PORT}"
    try:
        async with websockets.connect(speaker_uri, subprotocols=["gabbo"]) as speaker_ws:

            async def client_to_speaker():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await speaker_ws.send(data)
                except WebSocketDisconnect:
                    pass

            async def speaker_to_client():
                try:
                    async for message in speaker_ws:
                        await websocket.send_text(message)
                except websockets.ConnectionClosed:
                    pass

            await asyncio.gather(client_to_speaker(), speaker_to_client())
    except (ConnectionRefusedError, OSError, websockets.InvalidURI) as e:
        logger.warning("WebSocket proxy to %s: %s", ip, e)
        await websocket.close(code=1011, reason=f"Speaker unreachable: {e}")
    except Exception as e:
        logger.error("WebSocket proxy error for %s: %s", ip, e)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
