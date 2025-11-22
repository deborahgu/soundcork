from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BmxResponse(BaseModel):
    links: dict = Field(..., serialization_alias="_links")
    askAgainAfter: int
    bmx_services: List


class IconSet(BaseModel):
    defaultAlbumArt: str
    largeSvg: str
    monochromePng: str
    monochromeSvg: str
    smallSvg: str


class Asset(BaseModel):
    color: str
    description: str
    icons: IconSet
    name: str
    shortDescription: str


class Id(BaseModel):
    name: str
    value: int


class Service(BaseModel):
    links: dict = Field(..., serialization_alias="_links")
    askAdapter: bool
    assets: Asset
    baseUrl: str
    signupUrl: Optional[str] = None
    streamTypes: List
    id: Id
    authenticationModel: dict


class Stream(BaseModel):
    links: dict = Field(..., serialization_alias="_links")
    bufferingTimeout: int
    connectingTimeout: int
    hasPlaylist: bool
    isRealtime: bool
    streamUrl: str


class Audio(BaseModel):
    hasPlaylist: bool
    isRealtime: bool
    maxTimeout: int
    streamUrl: str
    streams: List


class BmxPlaybackResponse(BaseModel):
    links: dict = Field(..., serialization_alias="_links")
    audio: Audio
    imageUrl: str
    isFavorite: bool
    name: str
    streamType: str


class SourceProvider(BaseModel):
    id: int
    created_on: str
    name: str
    updated_on: str


class Preset(BaseModel):
    id: str
    name: str
    source: str
    type: str
    location: str
    source_account: str
    is_presetable: str
    container_art: str


class ConfiguredSource(BaseModel):
    display_name: str
    secret: str
    secret_type: str
    source_key_type: str
    source_key_account: str


# TODO: Recent and Preset are almost the same; could
# make a shared parent class
class Recent(BaseModel):
    device_id: str
    utc_time: str
    id: str
    name: str
    source: str
    type: str
    location: str
    source_account: str
    is_presetable: str
