import logging
import os
import re
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi_etag import Etag

from soundcork.admin import get_admin_router
from soundcork.bmx import (
    play_custom_stream,
    tunein_navigate_v1,
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
    hostname_for_device,
    read_device_info,
    read_recents,
)
from soundcork.groups import get_groups_router
from soundcork.groups_service import get_groups_service_router
from soundcork.marge import (
    account_devices_xml,
    account_full_xml,
    account_sources_xml,
    add_device_to_account,
    add_recent,
    add_source_to_account,
    delete_preset,
    presets_xml,
    provider_settings_xml,
    recents_xml,
    remove_device_from_account,
    remove_source_from_account,
    rename_device,
    software_update_xml,
    source_providers,
    update_device_poweron,
    update_preset,
)
from soundcork.miniapp import get_miniapp_router
from soundcork.model import (
    BmxNavResponse,
    BmxPlaybackResponse,
    BmxPodcastInfoResponse,
    BmxResponse,
    BoseXMLResponse,
)
from soundcork.ui.speakers import Speakers
from soundcork.utils import strip_element_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

datastore = DataStore()
settings = Settings()
speakers = Speakers(datastore, settings)


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
        "name": "service",
        "description": "Communicates with user applications.",
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

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

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
)
async def power_on(request: Request, response: Response) -> Response:
    xml = await request.body()
    account = update_device_poweron(datastore, xml)
    if account:
        response.status_code = HTTPStatus.OK
        return response
    else:
        response = BoseXMLResponse()
        element = ET.Element("status")
        ET.SubElement(element, "message").text = "Device does not exist"
        ET.SubElement(element, "status-code").text = "4012"
        response.body = bose_xml_str(element).encode()
        response.headers["Content-Length"] = str(len(response.body))
        response.status_code = HTTPStatus.BAD_REQUEST
        return response


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
    return str(datastore.etag_for_presets(str(request.path_params.get("account"))))


def etag_for_recents(request: Request) -> str:
    return str(datastore.etag_for_recents(str(request.path_params.get("account"))))


def etag_for_account(request: Request) -> str:
    return str(datastore.etag_for_account(str(request.path_params.get("account"))))


def etag_for_sources(request: Request) -> str:
    return str(datastore.etag_for_sources(str(request.path_params.get("account"))))


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


@app.get(
    "/marge/streaming/account/{account}/presets/all",
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
def account_presets_all(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
):
    # TODO bose actually returns a full set of all presets that have ever
    # been set. we could support that at least for all presets that were
    # ever set in soundcork. but for now just returning the current
    # presets should be ok.
    xml = presets_xml(datastore, account)
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


@app.delete(
    "/marge/streaming/account/{account}/device/{device}/preset/{preset_number}",
    response_class=BoseXMLResponse,
    tags=["marge"],
)
def delete_account_preset(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    device: Annotated[str, Path(pattern=DEVICE_RE)],
    preset_number: int,
):
    delete_preset(datastore, account, device, preset_number)
    return None


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
                etag_gen=etag_for_sources,
                weak=False,
                extra_headers={"method_name": "getProviderSettings"},
            )
        )
    ],
)
def account_provider_settings(account: Annotated[str, Path(pattern=ACCOUNT_RE)]):
    xml = provider_settings_xml(account)
    return bose_xml_str(xml)


@app.post(
    "/marge/streaming/music/musicprovider/{provider_id}/is_eligible",
    response_class=BoseXMLResponse,
    tags=["marge"],
)
def account_provider_eligibility(provider_id: str):
    # we could parse out the payload and get the account id but why bother?
    xml = provider_settings_xml("fake", provider_id)
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


@app.get(
    "/marge/streaming/account/{account}/devices",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_account,
                weak=False,
                extra_headers={"method_name": "getDevices"},
            )
        )
    ],
)
def account_devices(account: Annotated[str, Path(pattern=ACCOUNT_RE)]) -> str:
    xml = account_devices_xml(account, datastore)
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
    status_code=HTTPStatus.CREATED,
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
):
    xml = await request.body()
    device_id, xml_resp = add_device_to_account(datastore, account, xml.decode())

    return bose_xml_str(xml_resp)


@app.put(
    "/marge/streaming/account/{account}/device/{device_id}",
    response_class=BoseXMLResponse,
    tags=["marge"],
    status_code=HTTPStatus.CREATED,
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_account,
                weak=False,
                extra_headers={
                    "method_name": "putDevice",
                },
            )
        )
    ],
)
async def put_account_device(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    device_id: Annotated[str, Path(pattern=DEVICE_RE)],
    request: Request,
):
    xml = await request.body()
    xml_resp = rename_device(datastore, account, device_id, xml.decode())

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
    response.body = b""
    response.status_code = HTTPStatus.OK
    return response


@app.get("/marge/streaming/device/{device_id}/streaming_token", tags=["marge"])
def streaming_token(device_id: str, response: Response):
    response.headers["Authorization"] = "c3dvcmRmaXNoCg=="
    etag = int(datetime.now().timestamp() * 1000)
    response.headers["ETag"] = str(etag)

    return


@app.post("/marge/streaming/account/login", tags=["marge"])
async def post_account_login(
    request: Request,
):
    xml = await request.body()
    # for now if they send in an account id as the username
    # then log in that account
    try:
        login_xml = ET.fromstring(xml)
        if login_xml:
            username = strip_element_text(login_xml.find("username"))
            # only use the beginning of the username so that we can accept
            # the account as an email address
            if len(username) > 7:
                username = username[:7]
            account_pattern = re.compile(ACCOUNT_RE)
            if account_pattern.match(username):
                account_id = username
            else:
                raise Exception
    except Exception:
        exception_xml = """<status>
        <message>Account Login failure.</message>
        <status-code>4024</status-code>
        </status>"""
        response = Response(content=exception_xml, media_type="application/xml")
        response.status_code = HTTPStatus.BAD_REQUEST
        return response

    account_elem = ET.Element("account")
    account_elem.attrib["id"] = account_id
    ET.SubElement(account_elem, "accountStatus").text = "OK"
    ET.SubElement(account_elem, "mode").text = "global"
    ET.SubElement(account_elem, "preferredLanguage").text = "en"

    return_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{ET.tostring(account_elem, encoding="unicode")}'
    response = Response(content=return_xml, media_type="application/xml")
    # TODO: move content type to constants
    response.headers["content-type"] = "application/vnd.bose.streaming-v1.2+xml"

    etag = startup_timestamp

    response.headers["etag"] = str(etag)
    # just making this up
    response.headers["Credentials"] = "3432143243243432143fdafd"
    return response


@app.get(
    "/marge/streaming/account/{account}/sources",
    response_class=BoseXMLResponse,
    tags=["marge"],
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_sources,
                weak=False,
            )
        )
    ],
)
def get_account_sources(account: Annotated[str, Path(pattern=ACCOUNT_RE)]) -> str:
    xml = account_sources_xml(account, datastore)
    return bose_xml_str(xml)


@app.post(
    "/marge/streaming/account/{account}/source",
    response_class=BoseXMLResponse,
    tags=["marge"],
    status_code=HTTPStatus.CREATED,
    dependencies=[
        Depends(
            Etag(
                etag_gen=etag_for_account,
                weak=False,
                extra_headers={
                    "method_name": "addSource",
                },
            )
        )
    ],
)
async def post_account_source(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    request: Request,
):
    xml = await request.body()
    xml_resp = add_source_to_account(datastore, account, xml.decode())

    return bose_xml_str(xml_resp)


@app.delete("/marge/streaming/account/{account}/source/{source_id}", tags=["marge"])
async def delete_account_source(
    account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    source_id: str,
    response: Response,
):
    remove_source_from_account(datastore, account, source_id)
    response.headers["method_name"] = "removeSource"
    response.headers["location"] = (
        f"{settings.base_url}/marge/account/{account}/source/{source_id}"
    )
    response.body = b""
    response.status_code = HTTPStatus.OK
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


@app.get(
    "/bmx/tunein/v1/navigate",
    response_model_exclude_none=True,
    tags=["bmx"],
)
@app.get(
    "/bmx/tunein/v1/navigate/{encoded_uri}",
    response_model_exclude_none=True,
    tags=["bmx"],
)
@app.get(
    "/bmx/tunein/v1/navigate/sub/{subsection}/{encoded_uri}",
    response_model_exclude_none=True,
    tags=["bmx"],
)
def bmx_tunein_navigate(
    encoded_uri: str = "", subsection: int | None = None
) -> BmxNavResponse:
    return tunein_navigate_v1(encoded_uri, subsection)


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


@app.post("/v1/scmudc/{deviceid}", tags=["stats"], status_code=HTTPStatus.OK)
def stats_scmudc(deviceid: str):
    """Returns 200 for the analytics endpoint.

    This isn't an endpoint we use, but it's noisy when it fails. Return 200.
    """
    return


def bose_xml_str(xml: ET.Element) -> str:
    # ET.tostring won't allow you to set standalone="yes"
    return_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{ET.tostring(xml, encoding="unicode")}'

    return return_xml


################## configuration ############


@app.get("/scan_recents", tags=["setup"])
def test_scan_recents():
    devices = get_bose_devices()
    recents = []
    for device in devices:
        recents.append(read_recents(hostname_for_device(device)))
    return recents


@app.get("/scan", tags=["setup"])
def scan_devices():
    """Unlikely to be used in production, but has been useful during development."""
    devices = get_bose_devices()
    device_infos = {}
    for device in devices:
        info_elem = ET.fromstring(read_device_info(hostname_for_device(device)))
        device_infos[device.udn] = {
            "device_id": info_elem.attrib.get("deviceID", ""),
            "name": info_elem.find("name").text,  # type: ignore
            "type": info_elem.find("type").text,  # type: ignore
            "marge URL": info_elem.find("margeURL").text,  # type: ignore
            "account": info_elem.find("margeAccountUUID").text,  # type: ignore
        }
    return device_infos


@app.post("/add_device/{device_id}", tags=["setup"])
def add_device_to_datastore(device_id: str):
    devices = get_bose_devices()
    for device in devices:
        info_elem = ET.fromstring(read_device_info(hostname_for_device(device)))
        if info_elem.attrib.get("deviceID", "") == device_id:
            success = add_device(device)
            return {device_id: success}


#####################################################################################
# include all routines for groups
app.include_router(get_groups_router(datastore))
app.include_router(get_groups_service_router(datastore))


#  include admin router
app.include_router(get_admin_router(datastore, speakers))

#  include miniapp router
app.include_router(get_miniapp_router(datastore, settings))
