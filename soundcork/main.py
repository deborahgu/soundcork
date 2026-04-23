import logging
import os
import re
import secrets as _secrets_mod
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi_etag import Etag

from soundcork.admin import get_admin_router
from soundcork.bmx import (
    play_custom_stream,
    tunein_navigate_profile_v1,
    tunein_navigate_v1,
    tunein_playback,
    tunein_playback_podcast,
    tunein_podcast_info,
    tunein_search_v1,
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

from soundcork.speaker_allowlist import SpeakerAllowlist
from soundcork.spotify_service import SpotifyService

spotify_service = SpotifyService()

_speaker_allowlist: SpeakerAllowlist | None = None


def get_speaker_allowlist() -> SpeakerAllowlist:
    """Return the global speaker allowlist (lazy-init, patchable for tests)."""
    global _speaker_allowlist
    if _speaker_allowlist is None:
        _speaker_allowlist = SpeakerAllowlist(datastore)
    return _speaker_allowlist


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up soundcork")

    # Refuse to start with default credentials
    if settings.mgmt_password == "change_me!":
        raise RuntimeError(
            "MGMT_PASSWORD is still the default 'change_me!'. "
            "Set a strong password via environment variable or .env.private."
        )

    # Initialise speaker allowlist at startup
    get_speaker_allowlist()
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
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
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

from fastapi.staticfiles import StaticFiles as _StaticFiles

_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", _StaticFiles(directory=_static_dir), name="static")

from soundcork.mgmt import router as mgmt_router
from soundcork.proxy import ProxyMiddleware

app.include_router(mgmt_router)

from fastapi.staticfiles import StaticFiles

from soundcork.oidc import router as oidc_router
from soundcork.webui.routes import router as webui_router

app.include_router(webui_router)
app.include_router(oidc_router)
app.mount(
    "/webui/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "webui", "static")),
    name="webui_static",
)

app.add_middleware(ProxyMiddleware)


@app.middleware("http")
async def log_unknown_requests(request: Request, call_next):
    """Log unknown endpoints (404s) for API research.

    When LOG_REQUEST_BODY / LOG_REQUEST_HEADERS are enabled, body and
    headers are included in the log line — but only for 404s.  Known
    endpoints are not logged here (they have their own logging).
    """
    body = b""
    if settings.log_request_body or settings.log_request_headers:
        body = await request.body()

    response = await call_next(request)

    if response.status_code == 404:
        query = str(request.url.query)
        query_str = f"?{query}" if query else ""
        body_str = ""
        if settings.log_request_body and body:
            body_str = " body=" + body[:2000].decode("utf-8", errors="replace")
        headers_str = ""
        if settings.log_request_headers:
            headers_str = (
                " headers={"
                + ", ".join(f"{k}: {v}" for k, v in request.headers.items() if k.lower() not in ("host",))
                + "}"
            )
        logger.info(
            "UNKNOWN %s %s%s [404]%s%s",
            request.method,
            request.url.path,
            query_str,
            headers_str,
            body_str,
        )

    return response


# --- Speaker IP restriction middleware ---
# Bose protocol endpoints are only accessible from registered speaker IPs.
# Paths starting with /webui, /mgmt, /docs, /openapi.json, or / (root) are exempt.

_EXEMPT_PREFIXES = ("/webui", "/mgmt", "/docs", "/openapi.json", "/auth")


@app.middleware("http")
async def speaker_ip_restriction(request: Request, call_next):
    """Block Bose protocol requests from unknown IPs."""
    path = request.url.path

    # Exempt paths: webui (browser), mgmt (has its own auth), docs, root health
    if path == "/" or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return await call_next(request)

    # Determine client IP from X-Forwarded-For (behind ingress/proxy).
    # Take the LAST value: the reverse proxy (Traefik) appends the real client
    # IP as the rightmost entry.  Earlier entries are attacker-controlled.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[-1].strip()
    else:
        client_ip = request.client.host if request.client else ""

    allowlist = get_speaker_allowlist()
    if not allowlist.is_allowed(client_ip):
        logger.warning(
            "Blocked %s %s from %s (not a registered speaker)",
            request.method,
            path,
            client_ip,
        )
        return JSONResponse(
            {"detail": "Forbidden: unknown speaker IP"},
            status_code=403,
        )

    return await call_next(request)


# --- WebUI session auth middleware ---
# All /webui/* paths (except login page and static assets) require a session cookie.
from soundcork.webui.auth import is_webui_path_public
from soundcork.webui.routes import _SESSION_COOKIE, _session_store


@app.middleware("http")
async def webui_auth(request: Request, call_next):
    """Require session auth for all webui endpoints."""
    path = request.url.path

    # Only apply to /webui paths
    if not path.startswith("/webui"):
        return await call_next(request)

    # Public paths (login page, login endpoint, static assets)
    if is_webui_path_public(path):
        return await call_next(request)

    # Check session cookie
    session_id = request.cookies.get(_SESSION_COOKIE, "")
    csrf_token = _session_store.validate(session_id)
    if csrf_token is None:
        # API/WS requests get 401, HTML requests get redirect to login
        if path.startswith("/webui/api/") or path.startswith("/webui/ws/"):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return RedirectResponse(url="/webui/login", status_code=302)

    # CSRF check for mutating methods
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # Login endpoint is exempt (no session yet to have a CSRF token)
        if path != "/webui/api/login":
            csrf_header = request.headers.get("x-csrf-token", "")
            if not _secrets_mod.compare_digest(csrf_header, csrf_token):
                return JSONResponse({"detail": "CSRF token invalid"}, status_code=403)

    return await call_next(request)


startup_timestamp = int(datetime.now().timestamp() * 1000)


@app.get("/")
def read_root():
    return {"Bose": "Can't Brick Us"}


@app.post(
    "/marge/streaming/support/power_on",
    tags=["marge"],
)
async def power_on(request: Request, response: Response) -> Response:
    # Spotify priming is handled by the on-speaker boot primer
    # (/mnt/nv/spotify-boot-primer) which fetches a token from
    # GET /mgmt/spotify/token and primes locally via ZeroConf.
    # No server-side priming needed.
    logger.info("power_on from %s", request.headers.get("x-forwarded-for", "unknown"))
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


@app.post(
    "/v1/scmudc/{device_id}",
    tags=["analytics"],
    status_code=HTTPStatus.OK,
)
async def scmudc_telemetry(device_id: str, request: Request):
    """Device telemetry event stream (analytics).

    The speaker posts real-time events here: power state changes,
    playback state, volume changes, source switches, art updates, etc.
    This is Bose's analytics/telemetry endpoint — equivalent to
    POST /v1/stapp/{deviceId} used by the mobile app (Stockholm).

    The speaker sends events regardless of whether the server accepts
    them (fire-and-forget).  Returning 200 OK silences the 404 noise.

    See: https://github.com/gesellix/Bose-SoundTouch/blob/main/docs/reference/CLOUD-API.md
    """
    body = await request.body()
    logger.debug("scmudc event from %s: %s", device_id, body[:500])
    return Response(status_code=200)


##############################################################################
# Telemetry / analytics stubs
#
# These endpoints receive fire-and-forget data from the speaker.  The real
# Bose servers stored it; we just return 200 OK to prevent 404 log noise.
##############################################################################


@app.post(
    "/v1/stapp/{device_id}",
    tags=["analytics"],
    status_code=HTTPStatus.OK,
)
async def stapp_telemetry(device_id: str, request: Request):
    """SoundTouch app analytics — equivalent to scmudc but used by the mobile app.

    Request format: same JSON envelope/payload as scmudc (already documented in #200).
    Response: bare 200 OK, no body.  Fire-and-forget.
    """
    body = await request.body()
    logger.debug("stapp event from %s: %s", device_id, body[:500])
    return Response(status_code=200)


@app.post(
    "/streaming/stats/usage",
    tags=["analytics"],
    status_code=HTTPStatus.OK,
)
async def streaming_stats_usage(request: Request):
    """Device usage statistics (play time, source stats, etc.).

    Real server (streaming.bose.com) still alive — returns 400 "Invalid
    version in header(SOf)" without proper headers.  Request format is
    XML or JSON with deviceId, accountId, timestamp, eventType, parameters.
    Response: bare 200 OK, no body.

    Logging enabled to capture actual speaker payloads.
    """
    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "")
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        logger.info(
            "STUB stats/usage content-type=%s headers=%s body=%s",
            content_type,
            headers,
            body[:2000].decode("utf-8", errors="replace"),
        )
    return Response(status_code=200)


@app.post(
    "/streaming/stats/error",
    tags=["analytics"],
    status_code=HTTPStatus.OK,
)
async def streaming_stats_error(request: Request):
    """Device error statistics (connection failures, codec errors, etc.).

    Request format: XML or JSON with deviceId, errorCode, errorMessage,
    timestamp, details.  Response: bare 200 OK, no body.

    Logging enabled to capture actual speaker payloads.
    """
    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "")
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        logger.info(
            "STUB stats/error content-type=%s headers=%s body=%s",
            content_type,
            headers,
            body[:2000].decode("utf-8", errors="replace"),
        )
    return Response(status_code=200)


@app.post(
    "/bmx/tunein/v1/report",
    tags=["analytics"],
    status_code=HTTPStatus.OK,
)
async def bmx_tunein_report(request: Request):
    """TuneIn playback reporting (listen time, station stats).

    Real server (content.api.bose.io) still alive — returns 403
    "Invalid client id".  Request format unknown.

    Logging enabled to capture actual speaker payloads.
    """
    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "")
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        logger.info(
            "STUB bmx/tunein/report content-type=%s headers=%s body=%s",
            content_type,
            headers,
            body[:2000].decode("utf-8", errors="replace"),
        )
    return Response(status_code=200)


##############################################################################
# Customer / account profile
#
# Response format aligned with gesellix/Bose-SoundTouch Go implementation:
# root element <customer>, Content-Type: application/xml.
# Real Bose server (streaming.bose.com) still returns 406 with ETag —
# alive but wants a specific Accept header.
##############################################################################


@app.get(
    "/customer/account/{account}",
    tags=["customer"],
)
def customer_account_profile(account: str):
    """Returns account profile.  XML root: <customer>."""
    profile = ET.Element("customer")
    ET.SubElement(profile, "accountID").text = account
    ET.SubElement(profile, "email").text = "user@example.com"
    ET.SubElement(profile, "firstName").text = "SoundTouch"
    ET.SubElement(profile, "lastName").text = "User"
    ET.SubElement(profile, "countryCode").text = "US"
    ET.SubElement(profile, "languageCode").text = "en"
    ET.SubElement(profile, "street")
    ET.SubElement(profile, "city")
    ET.SubElement(profile, "postalCode")
    ET.SubElement(profile, "state")
    ET.SubElement(profile, "phone")
    ET.SubElement(profile, "marketingOptIn").text = "false"
    xml_str = bose_xml_str(profile)
    return Response(content=xml_str, media_type="application/xml")


@app.post(
    "/customer/account/{account}",
    tags=["customer"],
    status_code=HTTPStatus.OK,
)
async def update_customer_account_profile(account: str, request: Request):
    """Accept account profile update.  Request format unknown — logging."""
    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "")
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        logger.info(
            "STUB customer/account/%s (update) content-type=%s headers=%s body=%s",
            account,
            content_type,
            headers,
            body[:2000].decode("utf-8", errors="replace"),
        )
    return Response(status_code=200)


@app.post(
    "/customer/account/{account}/password",
    tags=["customer"],
    status_code=HTTPStatus.OK,
)
async def change_customer_password(account: str, request: Request):
    """Accept password change.  Request format unknown — logging."""
    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "")
        logger.info(
            "STUB customer/account/%s/password content-type=%s body=%s",
            account,
            content_type,
            body[:2000].decode("utf-8", errors="replace"),
        )
    return Response(status_code=200)


##############################################################################
# Additional marge stubs
#
# Endpoints the speaker calls that were missing from soundcork but present
# in the Go implementation (gesellix/Bose-SoundTouch).
##############################################################################


@app.post(
    "/marge/streaming/support/customersupport",
    tags=["marge"],
    status_code=HTTPStatus.OK,
)
async def customer_support_upload(request: Request):
    """Accept customer support diagnostic upload.

    Go implementation expects <device-data> XML with device info and
    diagnostic-data (RSSI, gateway IP, MAC addresses, etc.).
    Response: 200 OK, Content-Type: application/vnd.bose.streaming-v1.2+xml.

    Logging enabled to capture actual speaker payloads.
    """
    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "")
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        logger.info(
            "STUB customersupport content-type=%s headers=%s body=%s",
            content_type,
            headers,
            body[:2000].decode("utf-8", errors="replace"),
        )
    return Response(
        status_code=200,
        media_type="application/vnd.bose.streaming-v1.2+xml",
    )


@app.get(
    "/marge/streaming/device_setting/account/{account}/device/{device}/device_settings",
    tags=["marge"],
)
def get_device_settings(account: str, device: str):
    """Returns device settings.  XML root: <deviceSettings>."""
    device_settings = ET.Element("deviceSettings")
    setting = ET.SubElement(device_settings, "deviceSetting")
    ET.SubElement(setting, "name").text = "CLOCK_FORMAT"
    ET.SubElement(setting, "value").text = "24HR"
    xml_str = bose_xml_str(device_settings)
    return Response(content=xml_str, media_type="application/xml")


@app.post(
    "/marge/streaming/device_setting/account/{account}/device/{device}/device_settings",
    tags=["marge"],
    status_code=HTTPStatus.OK,
)
async def update_device_settings(account: str, device: str, request: Request):
    """Accept device settings update.  Request format unknown — logging."""
    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "")
        logger.info(
            "STUB device_settings/%s/%s (update) content-type=%s body=%s",
            account,
            device,
            content_type,
            body[:2000].decode("utf-8", errors="replace"),
        )
    return Response(status_code=200)


@app.get(
    "/marge/streaming/account/{account}/emailaddress",
    tags=["marge"],
)
def get_email_address(account: str):
    """Returns the account email address.  XML root: <emailAddress>."""
    xml_str = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><emailAddress>user@example.com</emailAddress>'
    return Response(content=xml_str, media_type="application/xml")


@app.post(
    "/oauth/device/{device_id}/music/musicprovider/{provider_id}/token/{token_type}",
    tags=["oauth"],
    status_code=HTTPStatus.OK,
)
def oauth_token_refresh(device_id: str, provider_id: str, token_type: str):
    """Spotify OAuth token refresh endpoint.

    Intercepts the speaker's token refresh requests that would normally
    go to streamingoauth.bose.com.  The speaker calls this when it needs
    a fresh Spotify access token for playback.

    Only handles provider 15 (Spotify).  Other providers return 404.
    """
    if provider_id != "15":
        logger.info(
            "OAuth token request for unsupported provider %s (device=%s)",
            provider_id,
            device_id,
        )
        return Response(status_code=404)

    token = spotify_service.get_fresh_token_sync()
    if not token:
        logger.warning(
            "OAuth token refresh failed — no Spotify token available (device=%s)",
            device_id,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "no_token",
                "error_description": "No Spotify account linked",
            },
        )

    logger.info("OAuth token refresh for device %s (provider=Spotify)", device_id)
    return JSONResponse(
        content={
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": (
                "streaming user-read-email user-read-private"
                " playlist-read-private playlist-read-collaborative user-library-read"
                " user-read-playback-state user-modify-playback-state"
                " user-read-currently-playing user-read-recently-played"
            ),
        }
    )


@app.get(
    "/marge/streaming/device/{device}/streaming_token",
    response_class=BoseXMLResponse,
    tags=["marge"],
)
def streaming_token(device: str, request: Request):
    """Streaming token endpoint.

    Returns a local bearer token matching the gesellix/Bose-SoundTouch
    Go implementation's st-local-token-{timestamp} pattern. The speaker
    accepts this for local operation.
    """
    token_value = f"st-local-token-{int(datetime.now().timestamp())}"
    bearer = f"Bearer {token_value}"
    logger.info("streaming_token request for device %s (returning local token)", device)
    xml_str = f'<?xml version="1.0" encoding="UTF-8"?><bearertoken value="{bearer}"/>'
    response = Response(
        content=xml_str,
        status_code=200,
        media_type="application/vnd.bose.streaming-v1.2+xml",
    )
    response.headers["Authorization"] = bearer
    return response


@app.get("/marge/streaming/sourceproviders", tags=["marge"])
def streamingsourceproviders():
    return_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sourceProviders>'
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
    response.headers["ETag"] = str(etag)
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
    remove_device_from_account(datastore, account, device)
    response.headers["method_name"] = "removeDevice"
    response.headers["location"] = f"{settings.base_url}/marge/account/{account}/device/{device}"
    response.body = b""
    response.status_code = HTTPStatus.OK
    return response


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

    account_str = ET.tostring(account_elem, encoding="unicode")
    return_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{account_str}'
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
    response.headers["location"] = f"{settings.base_url}/marge/account/{account}/source/{source_id}"
    response.body = b""
    response.status_code = HTTPStatus.OK
    return response


@app.get("/bmx/registry/v1/services", response_model_exclude_none=True, tags=["bmx"])
def bmx_services() -> BmxResponse:

    with open("bmx_services.json", "r") as file:
        bmx_response_json = file.read()
        bmx_response_json = bmx_response_json.replace("{MEDIA_SERVER}", f"{settings.base_url}/media").replace(
            "{BMX_SERVER}", settings.base_url
        )
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
    encoded_uri: str = "",
    subsection: int | None = None,
) -> BmxNavResponse:
    return tunein_navigate_v1(encoded_uri, subsection)


@app.get(
    "/bmx/tunein/v1/navigate/profiles/{profile_type}/{program_id}/{encoded_uri}",
    response_model_exclude_none=True,
    tags=["bmx"],
)
def bmx_tunein_navigate_profile(
    encoded_uri: str = "",
    profile_type: str | None = None,
    program_id: str | None = None,
) -> BmxNavResponse:
    # the profile_type and program_id i think can be ignored in favor of the encoded_uri?
    return tunein_navigate_profile_v1(encoded_uri)


@app.get(
    "/bmx/tunein/v1/search",
    response_model_exclude_none=True,
    tags=["bmx"],
)
def bmx_tunein_search_v1(request: Request) -> BmxNavResponse:
    return tunein_search_v1(request.query_params.get("q", ""))


@app.get("/core02/svc-bmx-adapter-orion/prod/orion/station", tags=["bmx"])
def custom_stream_playback(request: Request) -> BmxPlaybackResponse:
    data = request.query_params.get("data", "")
    return play_custom_stream(data)


# BMX Orion alias — Go registers this as POST, device may use GET or POST
@app.post("/bmx/orion/v1/playback/station/{data}", tags=["bmx"])
@app.get("/bmx/orion/v1/playback/station/{data}", tags=["bmx"])
def bmx_orion_playback(data: str) -> BmxPlaybackResponse:
    return play_custom_stream(data)


@app.get("/media/{filename}", tags=["bmx"])
def bmx_media_file(filename: str) -> FileResponse:
    sanitized_filename = "".join(x for x in filename if x.isalnum() or x == "." or x == "-" or x == "_")
    file_path = os.path.join("media", sanitized_filename)
    if os.path.isfile(file_path):
        return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="not found")


@app.get("/updates/soundtouch", tags=["swupdate"])
@app.get("/marge/updates/soundtouch", tags=["swupdate"])
def sw_update() -> Response:
    with open("swupdate.xml", "r") as file:
        sw_update_response = file.read()
        response = Response(content=sw_update_response, media_type="application/xml")
        return response


def bose_xml_str(xml: ET.Element) -> str:
    # ET.tostring won't allow you to set standalone="yes"
    return_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{ET.tostring(xml, encoding="unicode")}'

    return return_xml


##############################################################################
# Root-level aliases (without /marge or /bmx prefix)
#
# The Go implementation registers every marge/bmx endpoint twice — once
# under the prefix and once at the root.  This supports direct-domain
# calls where the speaker hits streaming.bose.com/accounts/... without
# the /marge path segment.
#
# We use FastAPI's add_api_route to point the alias paths at the same
# handler functions already defined above.
##############################################################################

# --- BMX root-level aliases ---
app.add_api_route("/registry/v1/services", bmx_services, methods=["GET"], tags=["bmx-alias"])
app.add_api_route(
    "/tunein/v1/playback/station/{station_id}",
    bmx_playback,
    methods=["GET"],
    tags=["bmx-alias"],
)
app.add_api_route(
    "/tunein/v1/playback/episodes/{episode_id}",
    bmx_podcast_info,
    methods=["GET"],
    tags=["bmx-alias"],
)
app.add_api_route(
    "/tunein/v1/playback/episode/{episode_id}",
    bmx_playback_podcast,
    methods=["GET"],
    tags=["bmx-alias"],
)
app.add_api_route(
    "/orion/v1/playback/station/{data}",
    bmx_orion_playback,
    methods=["GET", "POST"],
    tags=["bmx-alias"],
)

# --- Marge root-level aliases ---
app.add_api_route(
    "/streaming/sourceproviders",
    streamingsourceproviders,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/full",
    account_full,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route("/streaming/support/power_on", power_on, methods=["POST"], tags=["marge-alias"])
app.add_api_route(
    "/streaming/device/{device}/streaming_token",
    streaming_token,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/device/{device}/presets",
    account_presets,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/device/{device}/preset/{preset_number}",
    put_account_preset,
    methods=["PUT"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/device/{device}/recents",
    account_recents,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/provider_settings",
    account_provider_settings,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/software/update/account/{account}",
    software_update,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/device/{device}/recent",
    post_account_recent,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/device/",
    post_account_device,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/device/{device}",
    delete_account_device,
    methods=["DELETE"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/support/customersupport",
    customer_support_upload,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/device_setting/account/{account}/device/{device}/device_settings",
    get_device_settings,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/device_setting/account/{account}/device/{device}/device_settings",
    update_device_settings,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/streaming/account/{account}/emailaddress",
    get_email_address,
    methods=["GET"],
    tags=["marge-alias"],
)

# --- Marge /accounts/ style aliases (gesellix/Bose-SoundTouch path format) ---
# The Go project registers these shorter paths alongside /streaming/account/ paths.
# Both path styles should work for maximum speaker firmware compatibility.
app.add_api_route(
    "/marge/accounts/{account}/full",
    account_full,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route("/accounts/{account}/full", account_full, methods=["GET"], tags=["marge-alias"])
app.add_api_route(
    "/marge/accounts/{account}/devices/{device}/presets",
    account_presets,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/accounts/{account}/devices/{device}/presets",
    account_presets,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/marge/accounts/{account}/devices/{device}/presets/{preset_number}",
    put_account_preset,
    methods=["PUT"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/accounts/{account}/devices/{device}/presets/{preset_number}",
    put_account_preset,
    methods=["PUT"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/marge/accounts/{account}/devices/{device}/recents",
    account_recents,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/accounts/{account}/devices/{device}/recents",
    account_recents,
    methods=["GET"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/marge/accounts/{account}/devices/{device}/recents",
    post_account_recent,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/accounts/{account}/devices/{device}/recents",
    post_account_recent,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/marge/accounts/{account}/devices",
    post_account_device,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/accounts/{account}/devices",
    post_account_device,
    methods=["POST"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/marge/accounts/{account}/devices/{device}",
    delete_account_device,
    methods=["DELETE"],
    tags=["marge-alias"],
)
app.add_api_route(
    "/accounts/{account}/devices/{device}",
    delete_account_device,
    methods=["DELETE"],
    tags=["marge-alias"],
)

# --- Customer root-level aliases (already at /customer/..., no prefix to strip) ---
# These are already at root level, no aliases needed.


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
