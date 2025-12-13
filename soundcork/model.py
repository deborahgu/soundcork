from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Link(BaseModel):
    href: str


class Links(BaseModel):
    bmx_logout: Optional[Link] = None
    bmx_navigate: Optional[Link] = None
    bmx_services_availability: Optional[Link] = None
    bmx_token: Optional[Link] = None
    self: Optional[Link] = None


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
        default=None, alias="_links", serialization_alias="_links"
    )
    audio: Audio
    imageUrl: str
    isFavorite: Optional[bool] = None
    name: str
    streamType: str


class SourceProvider(BaseModel):
    id: int
    created_on: str
    name: str
    updated_on: str


class ContentItem(BaseModel):
    id: str
    name: str
    source: Optional[str] = None
    type: str
    location: str
    source_account: Optional[str] = None
    source_id: Optional[str] = None


class Preset(ContentItem):
    container_art: str


class Recent(ContentItem):
    device_id: str
    utc_time: str
    is_presetable: str
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
