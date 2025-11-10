from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI

from config import Settings
from model import (
    BmxResponse,
    Service,
    Asset,
    Id,
    IconSet,
    BmxPlaybackResponse,
    Audio,
    Stream,
)

description = """
This emulates the SoundTouch servers so you don't need connectivity
to use speakers.

## Marge

dunno yet

## Bmx

also dunno
"""

tags_metadata = [
    {
        "name": "marge",
        "description": "Oh Homie, stop bricking my speakers!",
    },
    {
        "name": "bmx",
        "description": "lord knows",
    },
]
app = FastAPI(
    title="SoundCork",
    description=description,
    summary="Emulates SoundTouch servers.",
    version="0.0.1",
    openapi_tags=tags_metadata,
)


@lru_cache
def get_settings():
    return Settings()


@app.get("/")
def read_root():
    return {"Bose": "Can't Brick Us"}


@app.post(
    "/marge/streaming/support/power_on",
    tags=["marge"],
)
def power_on(settings: Annotated[Settings, Depends(get_settings)]):
    # see https://github.com/fastapi/fastapi/discussions/8091 for the TODO here
    return (
        f'<?xml version="1.0" encoding="UTF-8" ?><device-data><device id="{settings.device_id}">'
        f"<serialnumber>{settings.device_serial_number}</serialnumber>"
        f"<firmware-version>{settings.firmware_version}</firmware-version>"
        f"<product product_code={settings.product_code} type={settings.type}>"
        f"<serialnumber>{settings.product_serial_number}</serialnumber>"
        f"</product></device><diagnostic-data><device-landscape>"
        f"<gateway-ip-address>{settings.gateway_ip_address}</gateway-ip-address>"
        f'<macaddresses><macaddress>{"</macaddress><macaddress>".join(settings.macaddresses)}</macaddress></macaddresses>'
        f"<ip-address>{settings.ip_address}</ip-address>"
        f"<network-connection-type>{settings.type}</network-connection-type>"
        "</device-landscape><network-landscape>"
        '<network-data xmlns="http://www.Bose.com/Schemas/2012-12/NetworkMonitor/" />'
        "</network-landscape></diagnostic-data></device-data>"
    )


@app.get("/bmx/registry/v1/services", tags=["bmx"])
def bmx_services(settings: Annotated[Settings, Depends(get_settings)]) -> BmxResponse:
    # not sure what this number means; could be a timestamp or something similar?
    # this probably should be read from a config file or from some other kind of storage

    assets = Asset(
        color="#000000",
        description="With TuneIn on SoundTouch, listen to more than 100,000 stations and the hottest podcasts, "
        "plus live games, concerts and shows from around the world. However, you cannot access your "
        "Favorites and Premium content on your existing TuneIn account at this time.",
        # todo: cache/copy these icons
        icons=IconSet(
            defaultAlbumArt="https://media.bose.io/bmx-icons/tunein/default-album-art.png",
            largeSvg="https://media.bose.io/bmx-icons/tunein/smallSvg.svg",
            monochromePng="https://media.bose.io/bmx-icons/tunein/monochromePng.png",
            monochromeSvg="https://media.bose.io/bmx-icons/tunein/monochromeSvg.svg",
            smallSvg="https://media.bose.io/bmx-icons/tunein/smallSvg.svg",
        ),
        name="TuneIn",
        shortDescription="",
    )
    tunein = Service(links = {
        "bmx_navigate": {"href": "/v1/navigate"},
        "bmx_token": {"href": "/v1/token"},
        "self": {"href": "/"},
        }, askAdapter = False, baseUrl = settings.base_url + "/bmx/tunein", streamTypes = ["liveRadio", "onDemand"],
        id = Id(name="TUNEIN", value=25),
        authenticationModel = {
            "anonymousAccount": {"autoCreate": True, "enabled": True}
        }, assets = assets)
    links = {"bmx_services_availability": {"href": "../servicesAvailability"}}
    response = BmxResponse(links = links, askAgainAfter = 1277728, bmx_services = [tunein])

    return response


@app.get("/bmx/{service}/v1/playback/station/{station}", tags=["bmx"])
def bmx_services(
    settings: Annotated[Settings, Depends(get_settings)], service: str, station: str
) -> BmxPlaybackResponse:
    if service == "tunein":
        stream = Stream(
            links={
                "bmx_reporting": {
                    "href": "/v1/report?stream_id=e92888046&guide_id=s24062&listen_id=1761921446&stream_type=liveRadio"
                }
            },
            bufferingTimeout=20,
            connectingTimeout=10,
            hasPlaylist=True,
            isRealtime=True,
            streamUrl="https://nebcoradio.com:8443/WXRV",
        )
        audio = Audio(
            hasPlaylist=True,
            isRealtime=True,
            maxTimeout=60,
            streamUrl="https://nebcoradio.com:8443/WXRV",
            streams=[stream],
        )

        resp = BmxPlaybackResponse(
            links={
                "bmx_favorite": {"href": "/v1/favorite/s24062"},
                "bmx_nowplaying": {
                    "href": "/v1/now-playing/station/s24062",
                    "useInternalClient": "ALWAYS",
                },
                "bmx_reporting": {
                    "href": "/v1/report?stream_id=e92888046&guide_id=s24062&listen_id=1761921446&stream_type=liveRadio"
                },
            },
            audio=audio,
            imageUrl="http://cdn-profiles.tunein.com/s24062/images/logog.png?t=636602555323000000",
            isFavorite=False,
            name="WXRV/92.5 the River",
            streamType="liveRadio",
        )
        return resp
