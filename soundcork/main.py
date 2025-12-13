import json
import logging
import os
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from soundcork.bmx import play_custom_stream, tunein_playback
from soundcork.config import Settings
from soundcork.datastore import DataStore
from soundcork.marge import (
    account_full_xml,
    add_recent,
    etag_configured_sources,
    presets_xml,
    provider_settings_xml,
    recents_xml,
    software_update_xml,
    source_providers,
)
from soundcork.model import (
    Asset,
    Audio,
    BmxPlaybackResponse,
    BmxResponse,
    IconSet,
    Id,
    Service,
    Stream,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


datastore = DataStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up soundcork")
    datastore.discover_devices()
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


@lru_cache
def get_settings():
    return Settings()


startup_timestamp = int(datetime.now().timestamp() * 1000)


@app.get("/")
def read_root():
    return {"Bose": "Can't Brick Us"}


@app.post(
    "/marge/streaming/support/power_on",
    tags=["marge"],
    status_code=HTTPStatus.OK,
)
def power_on(settings: Annotated[Settings, Depends(get_settings)]):
    # see https://github.com/fastapi/fastapi/discussions/8091 for the TODO here
    # I wonder if the endpoint will work if I return HTTPStatus.IM_A_TEAPOT
    # instead? I'd like to try it.

    return


@app.get("/marge/streaming/sourceproviders", tags=["marge"])
def streamingsourceproviders(settings: Annotated[Settings, Depends(get_settings)]):
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
    response.headers["etag"] = str(startup_timestamp)
    return response


@app.get("/marge/streaming/account/{account}/device/{device}/presets", tags=["marge"])
def account_presets(
    settings: Annotated[Settings, Depends(get_settings)], account: str, device: str
):
    xml = presets_xml(settings, account, device)
    return bose_xml_response(xml)


@app.get("/marge/streaming/account/{account}/device/{device}/recents", tags=["marge"])
def account_recents(
    settings: Annotated[Settings, Depends(get_settings)], account: str, device: str
):
    validate_params(account, device)

    xml = recents_xml(settings, account, device)
    return bose_xml_response(xml)


@app.get("/marge/streaming/account/{account}/provider_settings", tags=["marge"])
def account_provider_settings(
    settings: Annotated[Settings, Depends(get_settings)], account: str
):
    xml = provider_settings_xml(settings, account)
    return bose_xml_response(xml, startup_timestamp, "getProviderSettings")


@app.get("/marge/streaming/software/update/account/{account}", tags=["marge"])
def software_update(settings: Annotated[Settings, Depends(get_settings)], account: str):
    xml = software_update_xml()
    return bose_xml_response(xml)


@app.get("/marge/streaming/account/{account}/full", tags=["marge"])
def account_full(settings: Annotated[Settings, Depends(get_settings)], account: str):
    xml = account_full_xml(settings, account, datastore)
    return bose_xml_response(xml, startup_timestamp, "getFullAccount")


@app.post("/marge/streaming/account/{account}/device/{device}/recent", tags=["marge"])
async def post_account_recent(
    settings: Annotated[Settings, Depends(get_settings)],
    account: str,
    device: str,
    request: Request,
):
    validate_params(account)
    xml = await request.body()
    xml_resp = add_recent(settings, account, device, xml)
    return bose_xml_response(xml_resp, startup_timestamp)


@app.get("/bmx/registry/v1/services", response_model_exclude_none=True, tags=["bmx"])
def bmx_services(settings: Annotated[Settings, Depends(get_settings)]) -> BmxResponse:

    with open("bmx_services.json", "r") as file:
        bmx_response_json = file.read()
        bmx_response_json = bmx_response_json.replace(
            "{MEDIA_SERVER}", f"{settings.base_url}/media"
        ).replace("{BMX_SERVER}", settings.base_url)
        # TODO:  we're sending askAgainAfter hardcoded, but that value actually
        # varies.
        bmx_response = BmxResponse.model_validate_json(bmx_response_json)
        return bmx_response


@app.get("/bmx/{service}/v1/playback/station/{station_id}", tags=["bmx"])
def bmx_playback(service: str, station_id: str) -> BmxPlaybackResponse:
    if service == "tunein":
        return tunein_playback(station_id)


@app.get("/core02/svc-bmx-adapter-orion/prod/orion/station", tags=["bmx"])
def custom_stream_playback(request: Request) -> BmxPlaybackResponse:
    data = request.query_params.get("data", "")
    return play_custom_stream(data)


@app.get("/media/{filename}", tags="bmx")
def bmx_media_file(filename: str) -> FileResponse:
    sanitized_filename = "".join(
        x for x in filename if x.isalnum() or x == "." or x == "-" or x == "_"
    )
    file_path = os.path.join("media", sanitized_filename)
    if os.path.isfile(file_path):
        return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="not found")


def bose_xml_response(xml: ET.Element, etag: int = 0, method: str = "") -> Response:
    # ET.tostring won't allow you to set standalone="yes"
    return_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{ET.tostring(xml, encoding="unicode")}'
    response = Response(content=return_xml, media_type="application/xml")
    # TODO: move content type to constants
    response.headers["content-type"] = "application/vnd.bose.streaming-v1.2+xml"

    if etag == 0:
        etag = startup_timestamp

    response.headers["etag"] = str(etag)
    response.headers["method_name"] = method
    return response


def validate_params(account=12345, device="ABCD3"):
    try:
        int(account)
    except ValueError:
        raise HTTPException(status_code=500, detail="invalid account")
    try:
        int(device, 16)
    except ValueError:
        raise HTTPException(status_code=500, detail="invalid device id")
