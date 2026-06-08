"""SoundCork media player entities."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    FIELD_ART_URL,
    FIELD_NAME,
    FIELD_PRESET,
    FIELD_STATION_ID,
    FIELD_STREAM_URL,
    SERVICE_PLAY_PRESET,
    SERVICE_STORE_PRESET_RADIO,
    SERVICE_STORE_PRESET_TUNEIN,
    SOURCE_STANDBY,
)
from .coordinator import SoundCorkCoordinator

LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY_MEDIA
)

PLAY_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(FIELD_PRESET): vol.All(int, vol.Range(min=1, max=6)),
    }
)

STORE_PRESET_TUNEIN_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(FIELD_PRESET): vol.All(int, vol.Range(min=1, max=6)),
        vol.Required(FIELD_STATION_ID): cv.string,
        vol.Required(FIELD_NAME): cv.string,
        vol.Optional(FIELD_ART_URL, default=""): cv.string,
    }
)

STORE_PRESET_RADIO_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(FIELD_PRESET): vol.All(int, vol.Range(min=1, max=6)),
        vol.Required(FIELD_STREAM_URL): cv.string,
        vol.Required(FIELD_NAME): cv.string,
        vol.Optional(FIELD_ART_URL, default=""): cv.string,
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SoundCork media player entities from a config entry."""
    coordinator: SoundCorkCoordinator = hass.data[DOMAIN][entry.entry_id]

    await coordinator.async_config_entry_first_refresh()

    entities = [
        SoundCorkMediaPlayer(coordinator, speaker)
        for speaker in coordinator.speakers
    ]
    async_add_entities(entities)

    async def handle_play_preset(call: ServiceCall) -> None:
        preset_num = call.data[FIELD_PRESET]
        for entity_id in call.data["entity_id"]:
            entity = next(
                (e for e in entities if e.entity_id == entity_id), None
            )
            if entity:
                await entity.async_play_preset(preset_num)

    async def handle_store_preset_tunein(call: ServiceCall) -> None:
        preset_num = call.data[FIELD_PRESET]
        station_id = call.data[FIELD_STATION_ID]
        name = call.data[FIELD_NAME]
        art_url = call.data.get(FIELD_ART_URL, "")
        for entity_id in call.data["entity_id"]:
            entity = next(
                (e for e in entities if e.entity_id == entity_id), None
            )
            if entity:
                await entity.async_store_preset_tunein(preset_num, station_id, name, art_url)

    async def handle_store_preset_radio(call: ServiceCall) -> None:
        preset_num = call.data[FIELD_PRESET]
        stream_url = call.data[FIELD_STREAM_URL]
        name = call.data[FIELD_NAME]
        art_url = call.data.get(FIELD_ART_URL, "")
        for entity_id in call.data["entity_id"]:
            entity = next(
                (e for e in entities if e.entity_id == entity_id), None
            )
            if entity:
                await entity.async_store_preset_radio(preset_num, stream_url, name, art_url)

    if not hass.services.has_service(DOMAIN, SERVICE_PLAY_PRESET):
        hass.services.async_register(
            DOMAIN, SERVICE_PLAY_PRESET, handle_play_preset, schema=PLAY_PRESET_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_STORE_PRESET_TUNEIN):
        hass.services.async_register(
            DOMAIN, SERVICE_STORE_PRESET_TUNEIN, handle_store_preset_tunein, schema=STORE_PRESET_TUNEIN_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_STORE_PRESET_RADIO):
        hass.services.async_register(
            DOMAIN, SERVICE_STORE_PRESET_RADIO, handle_store_preset_radio, schema=STORE_PRESET_RADIO_SCHEMA
        )


class SoundCorkMediaPlayer(CoordinatorEntity, MediaPlayerEntity):

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: SoundCorkCoordinator,
        speaker: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._speaker = speaker
        self._ip = speaker["ipAddress"]
        self._device_id = speaker["deviceId"]
        self._speaker_name = speaker["name"]
        self._speaker_type = speaker.get("type", "SoundTouch")

        self._attr_unique_id = f"soundcork_{self._device_id}"
        self._attr_supported_features = SUPPORTED_FEATURES

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._speaker_name,
            manufacturer="Bose",
            model=self._speaker_type,
        )

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._ip, {})

    @property
    def _now_playing(self) -> dict[str, Any]:
        return self._data.get("now_playing", {})

    @property
    def _volume_data(self) -> dict[str, Any]:
        return self._data.get("volume", {})

    @property
    def _presets(self) -> list[dict[str, Any]]:
        return self._data.get("presets", [])

    # --- State ---

    @property
    def state(self) -> MediaPlayerState:
        source = self._now_playing.get("source", SOURCE_STANDBY)
        if source == SOURCE_STANDBY or not source:
            return MediaPlayerState.OFF
        play_status = self._now_playing.get("play_status", "")
        if play_status == "PAUSE_STATE":
            return MediaPlayerState.PAUSED
        if play_status == "BUFFERING_STATE":
            return MediaPlayerState.BUFFERING
        return MediaPlayerState.PLAYING

    # --- Volume ---

    @property
    def volume_level(self) -> float:
        return self._volume_data.get("actual", 0) / 100.0

    @property
    def is_volume_muted(self) -> bool:
        return self._volume_data.get("muted", False)

    # --- Media info ---

    @property
    def media_title(self) -> str | None:
        return self._now_playing.get("title") or None

    @property
    def media_artist(self) -> str | None:
        return self._now_playing.get("artist") or None

    @property
    def media_album_name(self) -> str | None:
        return self._now_playing.get("album") or None

    @property
    def media_image_url(self) -> str | None:
        return self._now_playing.get("art_url") or None

    @property
    def media_content_type(self) -> str:
        return MediaType.MUSIC

    # --- Source ---

    @property
    def source(self) -> str | None:
        location = self._now_playing.get("location", "")
        for preset in self._presets:
            if preset.get("location") == location:
                return preset["name"]
        source = self._now_playing.get("source", "")
        station = self._now_playing.get("station_name", "")
        return station or source or None

    @property
    def source_list(self) -> list[str]:
        return [p["name"] for p in self._presets if p.get("name")]

    # --- Extra state attributes ---

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {
            "ip_address": self._ip,
            "device_id": self._device_id,
            "source_type": self._now_playing.get("source"),
        }
        for p in self._presets:
            attrs[f"preset_{p['id']}_name"] = p["name"]
            attrs[f"preset_{p['id']}_source"] = p["source"]
        return attrs

    # --- Commands (all proxied through soundcork /api/v1) ---

    async def async_turn_on(self) -> None:
        await self._post(f"/api/v1/speakers/{self._ip}/power-on")

    async def async_turn_off(self) -> None:
        await self._post(f"/api/v1/speakers/{self._ip}/power-off")

    async def async_set_volume_level(self, volume: float) -> None:
        vol_int = max(0, min(100, int(volume * 100)))
        body = f"<volume>{vol_int}</volume>".encode()
        await self._post(
            f"/api/v1/speakers/{self._ip}/volume",
            data=body,
            content_type="application/xml",
        )
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        press = b'<key state="press" sender="Gabbo">MUTE</key>'
        release = b'<key state="release" sender="Gabbo">MUTE</key>'
        await self._post(f"/api/v1/speakers/{self._ip}/key", data=press, content_type="application/xml")
        await self._post(f"/api/v1/speakers/{self._ip}/key", data=release, content_type="application/xml")
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        for preset in self._presets:
            if preset["name"] == source:
                await self._select_content_item(preset)
                await self.coordinator.async_request_refresh()
                return
        LOGGER.warning("Source '%s' not found in presets for %s", source, self._speaker_name)

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        if media_id.isdigit():
            await self.async_play_preset(int(media_id))
        else:
            LOGGER.warning("play_media media_id '%s' not supported", media_id)

    # --- Custom service handlers ---

    async def async_play_preset(self, preset_num: int) -> None:
        for preset in self._presets:
            if preset["id"] == preset_num:
                await self._select_content_item(preset)
                await self.coordinator.async_request_refresh()
                return
        LOGGER.warning("Preset %d not found for speaker %s", preset_num, self._speaker_name)

    async def async_store_preset_tunein(
        self, preset_num: int, station_id: str, name: str, art_url: str = ""
    ) -> None:
        xml = (
            f'<preset id="{preset_num}">'
            f'<ContentItem source="TUNEIN" type="stationurl" '
            f'location="/v1/playback/station/{station_id}" '
            f'isPresetable="true">'
            f"<itemName>{name}</itemName>"
            f"<containerArt>{art_url}</containerArt>"
            f"</ContentItem></preset>"
        )
        await self._post(
            f"/api/v1/speakers/{self._ip}/store-preset",
            data=xml.encode(),
            content_type="application/xml",
        )
        await self.coordinator.async_request_refresh()

    async def async_store_preset_radio(
        self, preset_num: int, stream_url: str, name: str, art_url: str = ""
    ) -> None:
        xml = (
            f'<preset id="{preset_num}">'
            f'<ContentItem source="LOCAL_INTERNET_RADIO" type="stationurl" '
            f'location="{stream_url}" '
            f'isPresetable="true">'
            f"<itemName>{name}</itemName>"
            f"<containerArt>{art_url}</containerArt>"
            f"</ContentItem></preset>"
        )
        await self._post(
            f"/api/v1/speakers/{self._ip}/store-preset",
            data=xml.encode(),
            content_type="application/xml",
        )
        await self.coordinator.async_request_refresh()

    # --- Helpers ---

    async def _select_content_item(self, preset: dict[str, Any]) -> None:
        xml = (
            f'<ContentItem source="{preset["source"]}" '
            f'type="{preset["type"]}" '
            f'location="{preset["location"]}" '
            f'sourceAccount="{preset.get("source_account", "")}" '
            f'isPresetable="true">'
            f"</ContentItem>"
        )
        await self._post(
            f"/api/v1/speakers/{self._ip}/select",
            data=xml.encode(),
            content_type="application/xml",
        )

    async def _post(
        self,
        path: str,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> None:
        url = f"{self.coordinator.base_url}{path}"
        headers = {"Content-Type": content_type} if data else {}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        LOGGER.error(
                            "SoundCork POST %s returned %d: %s", path, resp.status, text
                        )
        except aiohttp.ClientError as err:
            LOGGER.error("SoundCork POST %s failed: %s", path, err)
