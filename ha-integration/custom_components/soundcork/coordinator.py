"""DataUpdateCoordinator for SoundCork.

Polls SoundCork's /api/v1 REST endpoints every 30 seconds and maintains
a WebSocket connection per speaker (proxied through soundcork) for
real-time updates.

All network traffic goes through the soundcork server — the HA pod never
needs direct LAN access to speakers.
"""
from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL_SECONDS

LOGGER = logging.getLogger(__name__)

_WS_RETRY_MIN = 5
_WS_RETRY_MAX = 60


# ---------------------------------------------------------------------------
# XML parsers
# ---------------------------------------------------------------------------


def _parse_now_playing_elem(root: ET.Element) -> dict[str, Any]:
    source = root.attrib.get("source", "STANDBY")
    play_status = root.findtext("playStatus") or ""
    track = root.findtext("track") or ""
    artist = root.findtext("artist") or ""
    album = root.findtext("album") or ""
    station_name = root.findtext("stationName") or ""

    art_elem = root.find("art")
    art_url = ""
    if art_elem is not None and art_elem.text:
        art_url = art_elem.text

    content_item = root.find("ContentItem")
    location = ""
    item_name = ""
    if content_item is not None:
        if not art_url:
            art_url = content_item.findtext("containerArt") or ""
        location = content_item.attrib.get("location", "")
        item_name = content_item.findtext("itemName") or ""

    return {
        "source": source,
        "play_status": play_status,
        "title": track or item_name or station_name,
        "artist": artist,
        "album": album,
        "station_name": station_name,
        "art_url": art_url,
        "location": location,
        "item_name": item_name,
    }


def _parse_now_playing(xml_text: str) -> dict[str, Any]:
    try:
        return _parse_now_playing_elem(ET.fromstring(xml_text))
    except ET.ParseError as err:
        LOGGER.warning("Failed to parse nowPlaying XML: %s", err)
        return {
            "source": "STANDBY", "play_status": "", "title": "", "artist": "",
            "album": "", "station_name": "", "art_url": "", "location": "", "item_name": "",
        }


def _parse_volume(xml_text: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
        return {
            "actual": int(root.findtext("actualvolume") or "0"),
            "target": int(root.findtext("targetvolume") or "0"),
            "muted": (root.findtext("muteenabled") or "false").lower() == "true",
        }
    except (ET.ParseError, ValueError) as err:
        LOGGER.warning("Failed to parse volume XML: %s", err)
        return {"actual": 0, "target": 0, "muted": False}


def _parse_presets_elem(root: ET.Element) -> list[dict[str, Any]]:
    presets = []
    for preset_elem in root.findall("preset"):
        preset_id = preset_elem.attrib.get("id", "0")
        content = preset_elem.find("ContentItem")
        if content is not None:
            presets.append({
                "id": int(preset_id),
                "source": content.attrib.get("source", ""),
                "type": content.attrib.get("type", ""),
                "location": content.attrib.get("location", ""),
                "source_account": content.attrib.get("sourceAccount", ""),
                "name": content.findtext("itemName") or f"Preset {preset_id}",
                "art_url": content.findtext("containerArt") or "",
            })
    return presets


def _parse_presets(xml_text: str) -> list[dict[str, Any]]:
    try:
        return _parse_presets_elem(ET.fromstring(xml_text))
    except ET.ParseError as err:
        LOGGER.warning("Failed to parse presets XML: %s", err)
        return []


def _ws_url_for_speaker(base_url: str, ip: str) -> str:
    """Build the WebSocket URL for a speaker through soundcork's proxy.

    Converts http(s)://host:port to ws(s)://host:port/api/v1/ws/speaker/{ip}
    """
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/api/v1/ws/speaker/{ip}"


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class SoundCorkCoordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.speakers: list[dict[str, Any]] = []
        self._session: aiohttp.ClientSession | None = None
        self._ws_tasks: dict[str, asyncio.Task] = {}

        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_shutdown(self) -> None:
        for ip, task in self._ws_tasks.items():
            if not task.done():
                task.cancel()
        if self._ws_tasks:
            await asyncio.gather(*self._ws_tasks.values(), return_exceptions=True)
        self._ws_tasks.clear()

        if self._session and not self._session.closed:
            await self._session.close()

        await super().async_shutdown()

    # ------------------------------------------------------------------
    # REST helpers — all go through soundcork /api/v1
    # ------------------------------------------------------------------

    async def _fetch_speakers(self) -> list[dict[str, Any]]:
        session = await self._get_session()
        async with session.get(
            f"{self.base_url}/api/v1/speakers",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _fetch_now_playing(self, ip: str) -> dict[str, Any]:
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/api/v1/speakers/{ip}/now-playing",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return _parse_now_playing(await resp.text())
        except Exception as err:
            LOGGER.debug("now-playing fetch failed for %s: %s", ip, err)
            return {
                "source": "STANDBY", "play_status": "", "title": "", "artist": "",
                "album": "", "station_name": "", "art_url": "", "location": "", "item_name": "",
            }

    async def _fetch_volume(self, ip: str) -> dict[str, Any]:
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/api/v1/speakers/{ip}/volume",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return _parse_volume(await resp.text())
        except Exception as err:
            LOGGER.debug("volume fetch failed for %s: %s", ip, err)
            return {"actual": 0, "target": 0, "muted": False}

    async def _fetch_presets(self, ip: str) -> list[dict[str, Any]]:
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/api/v1/speakers/{ip}/presets",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return _parse_presets(await resp.text())
        except Exception as err:
            LOGGER.debug("presets fetch failed for %s: %s", ip, err)
            return []

    # ------------------------------------------------------------------
    # WebSocket listener (proxied through soundcork)
    # ------------------------------------------------------------------

    def _start_ws_listeners(self) -> None:
        for speaker in self.speakers:
            ip = speaker["ipAddress"]
            existing = self._ws_tasks.get(ip)
            if existing is None or existing.done():
                LOGGER.debug("Starting WebSocket listener for %s (via soundcork proxy)", ip)
                self._ws_tasks[ip] = asyncio.ensure_future(
                    self._speaker_ws_listener(ip)
                )

    async def _speaker_ws_listener(self, ip: str) -> None:
        ws_url = _ws_url_for_speaker(self.base_url, ip)
        retry_delay = _WS_RETRY_MIN

        while True:
            try:
                session = await self._get_session()
                async with session.ws_connect(
                    ws_url,
                    protocols=["gabbo"],
                    heartbeat=30,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as ws:
                    LOGGER.info("WebSocket connected to speaker %s via %s", ip, ws_url)
                    retry_delay = _WS_RETRY_MIN

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_ws_message(ip, msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            break

            except asyncio.CancelledError:
                return
            except Exception as err:
                LOGGER.debug("WebSocket disconnected from %s: %s", ip, err)

            LOGGER.debug("WebSocket reconnecting to %s in %ds", ip, retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, _WS_RETRY_MAX)

    async def _handle_ws_message(self, ip: str, xml_text: str) -> None:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return

        if ip not in (self.data or {}):
            return

        updated = False

        np_updated = root.find("nowPlayingUpdated")
        if np_updated is not None:
            np_elem = np_updated.find("nowPlaying")
            if np_elem is not None:
                self.data[ip]["now_playing"] = _parse_now_playing_elem(np_elem)
            else:
                self.data[ip]["now_playing"] = await self._fetch_now_playing(ip)
            updated = True

        if root.find("volumeUpdated") is not None:
            self.data[ip]["volume"] = await self._fetch_volume(ip)
            updated = True

        presets_updated = root.find("presetsUpdated")
        if presets_updated is not None:
            presets_elem = presets_updated.find("presets")
            if presets_elem is not None:
                self.data[ip]["presets"] = _parse_presets_elem(presets_elem)
            else:
                self.data[ip]["presets"] = await self._fetch_presets(ip)
            updated = True

        if updated:
            self.async_set_updated_data(self.data)

    # ------------------------------------------------------------------
    # Main poll (30s safety net)
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self.speakers:
                self.speakers = await self._fetch_speakers()

            data: dict[str, Any] = {}
            for speaker in self.speakers:
                ip = speaker["ipAddress"]
                now_playing, volume, presets = await asyncio.gather(
                    self._fetch_now_playing(ip),
                    self._fetch_volume(ip),
                    self._fetch_presets(ip),
                )
                data[ip] = {
                    "speaker": speaker,
                    "now_playing": now_playing,
                    "volume": volume,
                    "presets": presets,
                }

            self._start_ws_listeners()

            return data

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with SoundCork: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating SoundCork data: {err}") from err
