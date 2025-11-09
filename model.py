from typing import List

class BmxResponse:
    _links: dict
    askAgainAfter: int
    bmx_services: List

class IconSet:
    def __init__(self, defaultAlbumArt, largeSvg, monochromePng, monochromeSvg, smallSvg):
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
