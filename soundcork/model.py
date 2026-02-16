from datetime import datetime
from typing import List, Optional

from fastapi import Response
from pydantic import AliasChoices, BaseModel, Field


class BoseXMLResponse(Response):
    media_type = "application/vnd.bose.streaming-v1.2+xml"


class Link(BaseModel):
    href: str
    use_internal_client: Optional[str] = Field(
        default=None,
        alias="useInternalClient",
        serialization_alias="useInternalClient",
        validation_alias=AliasChoices("useInternalClient", "use_internal_client"),
    )


class Links(BaseModel):
    bmx_logout: Optional[Link] = None
    bmx_navigate: Optional[Link] = None
    bmx_services_availability: Optional[Link] = None
    bmx_token: Optional[Link] = None
    self: Optional[Link] = None
    bmx_availability: Optional[Link] = None
    bmx_logout: Optional[Link] = None
    bmx_reporting: Optional[Link] = None
    bmx_favorite: Optional[Link] = None
    bmx_nowplaying: Optional[Link] = None
    bmx_track: Optional[Link] = None


class IconSet(BaseModel):
    defaultAlbumArt: Optional[str] = None
    largeSvg: str
    monochromePng: str
    monochromeSvg: str
    smallSvg: str


class Asset(BaseModel):
    color: str
    description: str
    icons: IconSet
    name: str
    shortDescription: Optional[str] = None


class Id(BaseModel):
    name: str
    value: int


class Service(BaseModel):
    links: Optional[Links] = Field(
        default=None, alias="_links", serialization_alias="_links"
    )
    askAdapter: bool
    assets: Asset
    baseUrl: str
    signupUrl: Optional[str] = None
    streamTypes: list[str]
    authenticationModel: dict
    id: Id


class BmxResponse(BaseModel):
    links: Optional[Links] = Field(
        default=None, alias="_links", serialization_alias="_links"
    )
    askAgainAfter: int
    bmx_services: list[Service]


class Stream(BaseModel):
    links: Optional[Links] = Field(
        default=None, alias="_links", serialization_alias="_links"
    )
    bufferingTimeout: Optional[int] = None
    connectingTimeout: Optional[int] = None
    hasPlaylist: bool
    isRealtime: bool
    streamUrl: str


class Audio(BaseModel):
    hasPlaylist: bool
    isRealtime: bool
    maxTimeout: Optional[int] = None
    streamUrl: str
    streams: List


class BmxPlaybackResponse(BaseModel):
    links: Optional[Links] = Field(
        default=None,
        alias="_links",
        serialization_alias="_links",
        validation_alias=AliasChoices("links", "_links"),
    )
    artist: Optional[dict] = None
    audio: Audio
    imageUrl: str
    isFavorite: Optional[bool] = None
    name: str
    streamType: str
    duration: Optional[int] = None


class Track(BaseModel):
    links: dict = Field(serialization_alias="_links")
    is_selected: bool = Field(serialization_alias="isSelected")
    name: str


class BmxPodcastInfoResponse(BaseModel):
    links: dict = Field(serialization_alias="_links")
    name: str
    shuffle_disabled: bool = Field(default=False, serialization_alias="shuffleDisabled")
    repeat_disabled: bool = Field(default=False, serialization_alias="repeatDisabled")
    stream_type: str = Field(serialization_alias="streamType")
    tracks: list[Track]


class SourceProvider(BaseModel):
    id: int
    created_on: str
    name: str
    updated_on: str


class ContentItem(BaseModel):
    """ContentItem properties:

    source (int, though sent as strings): ID for a type of source.
        For example, local file storage.
    source_id (int, though sent as strings): ID for an instance of a source.
        For example, a connection to a particular UPnP server.
        Note: Not all sources will have source IDs that vary (eg. TuneIn)
    """

    id: str
    name: str
    source: Optional[str] = None
    type: str
    location: str
    source_account: Optional[str] = None
    source_id: Optional[str] = None
    is_presetable: Optional[str] = None


class Preset(ContentItem):
    container_art: str
    created_on: str
    updated_on: str


class Recent(ContentItem):
    device_id: str
    utc_time: str
    container_art: Optional[str] = None


class ConfiguredSource(BaseModel):
    display_name: str
    id: str
    secret: str
    secret_type: str
    source_key_type: str
    source_key_account: str


class DeviceInfo(BaseModel):
    device_id: str
    product_code: str
    device_serial_number: str
    product_serial_number: str
    firmware_version: str
    ip_address: str
    name: str
