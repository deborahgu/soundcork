from typing import List

from pydantic import BaseModel


class BmxResponse(BaseModel):
    _links: dict
    askAgainAfter: int
    bmx_services: List


class IconSet:
    def __init__(
        self, defaultAlbumArt, largeSvg, monochromePng, monochromeSvg, smallSvg
    ):
        self.defaultAlbumArt = defaultAlbumArt
        self.largeSvg = largeSvg
        self.monochromePng = monochromePng
        self.monochromeSvg = monochromeSvg
        self.smallSvg = smallSvg

    defaultAlbumArt: str
    largeSvg: str
    monochromePng: str
    monochromeSvg: str
    smallSvg: str


class Asset:
    def __init__(self, color, description, icons, name, shortDescription):
        self.color = color
        self.description = description
        self.icons = icons
        self.name = name
        self.shortDescription = shortDescription

    color: str
    description: str
    icons: IconSet
    name: str
    shortDescription: str


class Id:
    def __init__(self, name, value):
        self.name = name
        self.value = value

    name: str
    value: int


class Service:
    _links: dict
    askAdapter: bool
    assets: Asset
    baseUrl: str
    signupUrl: str
    streamTypes: List
    id: Id
    authenticationModel: dict


class Stream:
    def __init__(self, _links, bufferingTimeout, connectingTimeout, hasPlaylist, isRealtime, streamUrl):
        super()
        self._links = _links
        self.bufferingTimeout = bufferingTimeout
        self.connectingTimeout = connectingTimeout
        self.hasPlaylist = hasPlaylist
        self.isRealtime = isRealtime
        self.streamUrl = streamUrl

    _links: dict
    bufferingTimeout: int
    connectingTimeout: int
    hasPlaylist: bool
    isRealtime: bool
    streamUrl: str


class Audio(BaseModel):
    def __init__(self, hasPlaylist, isRealtime, maxTimeout, streamUrl, streams):
        super()
        self.hasPlaylist = hasPlaylist
        self.isRealtime = isRealtime
        self.maxTimeout = maxTimeout
        self.streamUrl = streamUrl
        self.streams = streams

    hasPlaylist: bool
    isRealtime: bool
    maxTimeout: int
    streamUrl: str
    streams: List


class BmxPlaybackResponse(BaseModel):
    def __init__(self, _links, audio, imageUrl, isFavorite, name, streamType):
        super()
        self._links = _links
        self.audio = audio
        self.imageUrl = imageUrl
        self.isFavorite = isFavorite
        self.name = name
        self.streamType = streamType

    _links: dict
    audio: Audio
    imageUrl: str
    isFavorite: bool
    name: str
    streamType: str