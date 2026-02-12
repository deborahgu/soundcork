import logging
import os
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.responses import FileResponse
from fastapi_etag import Etag

from soundcork.bmx import (
    play_custom_stream,
    tunein_playback,
    tunein_playback_podcast,
    tunein_podcast_info,
)
from soundcork.config import Settings
from soundcork.constants import ACCOUNT_RE, DEVICE_RE
from soundcork.datastore import DataStore
from soundcork.devices import (
    add_device,
    get_bose_devices,
    read_device_info,
    read_recents,
)
from soundcork.marge import (
    account_full_xml,
    add_device_to_account,
    add_recent,
    presets_xml,
    provider_settings_xml,
    recents_xml,
    remove_device_from_account,
    software_update_xml,
    source_providers,
    update_preset,
)
from soundcork.model import (
    BmxPlaybackResponse,
    BmxPodcastInfoResponse,
    BmxResponse,
    BoseXMLResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


datastore = DataStore()
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up soundcork")
    # datastore.discover_devices()
    logger.info("done starting up server")
    yield
    logger.debug("closing server")


description = """
This emulates the SoundTouch servers so you don't need connectivity
to use speakers.
"""

tags_metadata = [
    {
        "name": "marge",
        "description": "Communicates with the speaker.",
    },
    {
        "name": "bmx",
        "description": "Communicates with streaming radio services (eg. TuneIn).",
    },
]
app = FastAPI(
    title="SoundCork",
    description=description,
    summary="Emulates SoundTouch servers.",
    version="0.0.1",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)


# @lru_cache
# def get_settings():
#     return Settings()


startup_timestamp = int(datetime.now().timestamp() * 1000)


@app.get("/")
def read_root():
    return {"Bose": "Can't Brick Us"}


@app.post(
    "/marge/streaming/support/power_on",
    tags=["marge"],
    status_code=HTTPStatus.OK,
)
def power_on():
    # see https://github.com/fastapi/fastapi/discussions/8091 for the TODO here
    # I wonder if the endpoint will work if I return HTTPStatus.IM_A_TEAPOT
    # instead? I'd like to try it.

    return


@app.get("/marge/streaming/sourceproviders", tags=["marge"])
def streamingsourceproviders():
    return_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sourceProviders>'
    )
    for provider in source_providers():
        return_xml = (
            return_xml
            + '<sourceprovider id="'
            + str(provider.id)
            + '">'
            + "<createdOn>"
            + provider.created_on
            + "</createdOn>"
            + "<name>"
            + provider.name
            + "</name>"
            + "<updatedOn>"
            + provider.updated_on
            + "</updatedOn>"
            "</sourceprovider>"
        )
    return_xml = return_xml + "</sourceProviders>"
    response = Response(content=return_xml, media_type="application/xml")
    # TODO: move content type to constants
    response.headers["content-type"] = "application/vnd.bose.streaming-v1.2+xml"
    # sourceproviders seems to return now as its etag
    etag = int(datetime.now().timestamp() * 1000)
    response.headers["etag"] = str(etag)
    return response


def etag_for_presets(request: Request) -> str:
    return str(datastore.etag_for_presets(request.path_params.get("account")))


def etag_for_recents(request: Request) -> str:
    return str(datastore.etag_for_recents(request.path_params.get("account")))


def etag_for_account(request: Request) -> str:
    return str(datastore.etag_for_account(request.path_params.get("account")))


def etag_for_swupdate(request: Request) -> str:
    return "1663726921993"


@app.get(
    "/marge/streaming/account/{account}/device/{device}/presets",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_presets,
                weak=False,
            )
        )
    ],
)
def account_presets(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    device: Annotated[str, Path(pattern=DEVICE_RE)],
    response: Response,
):
    xml = presets_xml(datastore, account, device)
    return bose_xml_str(xml)


@app.put(
    "/marge/streaming/account/{account}/device/{device}/preset/{preset_number}",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_presets,
                weak=False,
            )
        )
    ],
)
async def put_account_preset(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    device: Annotated[str, Path(pattern=DEVICE_RE)],
    preset_number: int,
    request: Request,
):
    xml = await request.body()
    xml_resp = update_preset(datastore, account, device, preset_number, xml)
    return bose_xml_str(xml_resp)


@app.get(
    "/marge/streaming/account/{account}/device/{device}/recents",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_recents,
                weak=False,
            )
        )
    ],
)
def account_recents(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    device: Annotated[str, Path(pattern=DEVICE_RE)],
):
    xml = recents_xml(datastore, account, device)
    return bose_xml_str(xml)


@app.get(
    "/marge/streaming/account/{account}/provider_settings",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_recents,
                weak=False,
                extra_headers={"method_name": "getProviderSettings"},
            )
        )
    ],
)
def account_provider_settings(account: Annotated[str, Path(pattern=ACCOUNT_RE)]):
    xml = provider_settings_xml(account)
    return bose_xml_str(xml)


@app.get(
    "/marge/streaming/software/update/account/{account}",
    response_class=BoseXMLResponse,
    dependencies=[Depends(Etag(etag_gen=etag_for_swupdate, weak=False))],
    tags=["marge"],
)
def software_update(account: Annotated[str, Path(pattern=ACCOUNT_RE)]):
    xml = software_update_xml()
    return bose_xml_str(xml)


@app.get(
    "/marge/streaming/account/{account}/full",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_account,
                weak=False,
                extra_headers={"method_name": "getFullAccount"},
            )
        )
    ],
)
def account_full(account: Annotated[str, Path(pattern=ACCOUNT_RE)]) -> str:
    xml = account_full_xml(account, datastore)
    return bose_xml_str(xml)


@app.post(
    "/marge/streaming/account/{account}/device/{device}/recent",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[Depends(Etag(etag_gen=etag_for_recents, weak=False))],
)
async def post_account_recent(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    device: Annotated[str, Path(pattern=DEVICE_RE)],
    request: Request,
):
    xml = await request.body()
    xml_resp = add_recent(datastore, account, device, xml)
    return bose_xml_str(xml_resp)


@app.post(
    "/marge/streaming/account/{account}/device/",
    response_class=BoseXMLResponse,
    tags=["marge"],
    status_code=201,
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_account,
                weak=False,
                extra_headers={
                    "method_name": "addDevice",
                    "access-control-expose-headers": "Credentials",
                },
            )
        )
    ],
)
async def post_account_device(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    request: Request,
    response: Response,
):
    xml = await request.body()
    device_id, xml_resp = add_device_to_account(datastore, account, xml)
    response.headers["Credentials"] = f"{request.headers.get('authorization')}"
    response.headers["location"] = (
        f"{settings.base_url}/marge/account/{account}/device/{device_id}"
    )
    return bose_xml_str(xml_resp)


@app.delete("/marge/streaming/account/{account}/device/{device}", tags=["marge"])
async def delete_account_device(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    device: Annotated[str, Path(pattern=DEVICE_RE)],
    response: Response,
):
    xml_resp = remove_device_from_account(datastore, account, device)
    response.headers["method_name"] = "removeDevice"
    response.headers["location"] = (
        f"{settings.base_url}/marge/account/{account}/device/{device}"
    )
    response.body = ""
    response.status_code = 200
    return response


@app.get("/bmx/registry/v1/services", response_model_exclude_none=True, tags=["bmx"])
def bmx_services() -> BmxResponse:

    with open("bmx_services.json", "r") as file:
        bmx_response_json = file.read()
        bmx_response_json = bmx_response_json.replace(
            "{MEDIA_SERVER}", f"{settings.base_url}/media"
        ).replace("{BMX_SERVER}", settings.base_url)
        # TODO:  we're sending askAgainAfter hardcoded, but that value actually
        # varies.
        bmx_response = BmxResponse.model_validate_json(bmx_response_json)
        return bmx_response


@app.get(
    "/bmx/tunein/v1/playback/station/{station_id}",
    response_model_exclude_none=True,
    tags=["bmx"],
)
def bmx_playback(station_id: str) -> BmxPlaybackResponse:
    return tunein_playback(station_id)


@app.get(
    "/bmx/tunein/v1/playback/episodes/{episode_id}",
    response_model_exclude_none=True,
    tags=["bmx"],
)
def bmx_podcast_info(episode_id: str, request: Request) -> BmxPodcastInfoResponse:
    encoded_name = request.query_params.get("encoded_name", "")
    return tunein_podcast_info(episode_id, encoded_name)


@app.get(
    "/bmx/tunein/v1/playback/episode/{episode_id}",
    response_model_exclude_none=True,
    tags=["bmx"],
)
def bmx_playback_podcast(episode_id: str, request: Request) -> BmxPlaybackResponse:
    return tunein_playback_podcast(episode_id)


@app.get("/core02/svc-bmx-adapter-orion/prod/orion/station", tags=["bmx"])
def custom_stream_playback(request: Request) -> BmxPlaybackResponse:
    data = request.query_params.get("data", "")
    return play_custom_stream(data)


@app.get("/media/{filename}", tags=["bmx"])
def bmx_media_file(filename: str) -> FileResponse:
    sanitized_filename = "".join(
        x for x in filename if x.isalnum() or x == "." or x == "-" or x == "_"
    )
    file_path = os.path.join("media", sanitized_filename)
    if os.path.isfile(file_path):
        return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="not found")


@app.get("/updates/soundtouch", tags=["swupdate"])
def sw_update() -> Response:
    with open("swupdate.xml", "r") as file:
        sw_update_response = file.read()
        response = Response(content=sw_update_response, media_type="application/xml")
        return response


def bose_xml_str(xml: ET.Element) -> str:
    # ET.tostring won't allow you to set standalone="yes"
    return_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{ET.tostring(xml, encoding="unicode")}'

    return return_xml


################## configuration ############3


@app.get("/scan_recents", tags=["setup"])
def test_scan_recents():
    devices = get_bose_devices()
    recents = []
    for device in devices:
        recents.append(read_recents(device))
    return recents


@app.get("/scan", tags=["setup"])
def scan_devices():
    devices = get_bose_devices()
    device_infos = {}
    for device in devices:
        info_elem = ET.fromstring(read_device_info(device))
        device_infos[device.udn] = {
            "device_id": info_elem.attrib.get("deviceID", ""),
            "name": info_elem.find("name").text,
            "type": info_elem.find("type").text,
            "marge URL": info_elem.find("margeURL").text,
            "account": info_elem.find("margeAccountUUID").text,
        }
    return device_infos


@app.post("/add_device/{device_id}", tags=["setup"])
def add_device_to_datastore(device_id: str):
    devices = get_bose_devices()
    for device in devices:
        info_elem = ET.fromstring(read_device_info(device))
        if info_elem.attrib.get("deviceID", "") == device_id:
            success = add_device(device)
            return {device_id: success}
