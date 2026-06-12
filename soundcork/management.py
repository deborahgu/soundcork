"""Management API endpoints for soundcork.

These endpoints are NOT part of the Bose SoundTouch protocol. They
provide a JSON API for managing soundcork configuration, listing
speakers, and optionally linking Spotify accounts.


Spotify endpoints are only available when SPOTIFY_CLIENT_ID and
SPOTIFY_CLIENT_SECRET are configured.
"""

# TODO:  move functionality into /admin section
# TODO:  move oauth application configuration (client_id and client_secret)
#        out of Settings and into a per-account configuration that can
#        be modified from the admin UI

import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from soundcork.config import Settings
from soundcork.datastore import DataStore
from soundcork.devices import (
    get_bose_devices,
    hostname_for_device,
    read_device_info,
    read_runtime_sources,
)
from soundcork.model import DeviceInfo
from soundcork.spotify_service import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt", tags=["management"])

datastore = DataStore()
settings = Settings()
spotify = SpotifyService()

BOSE_MARGE_URL = "https://streaming.bose.com"
RADIO_SOURCE_KEYS = ("LOCAL_INTERNET_RADIO", "TUNEIN")


class ManagementDevice(BaseModel):
    """Sanitized management view of a SoundTouch speaker."""

    device_id: str
    account_id: str | None = None
    reported_account_id: str | None = None
    name: str | None = None
    product_code: str | None = None
    ip_address: str | None = None
    stored_ip_address: str | None = None
    reported_ip_address: str | None = None
    in_soundcork: bool
    rest_reachable: bool
    marge_url: str | None = None
    marge_server: str
    uses_this_soundcork: bool
    source_statuses: dict[str, str] = Field(default_factory=dict)
    internet_radio_ready: bool | None = None
    playback_capability: str = "Unknown"
    playback_capability_detail: str | None = None
    source: str
    error: str | None = None


class ManagementDevicesResponse(BaseModel):
    devices: list[ManagementDevice]


@dataclass
class SpeakerInfo:
    device_id: str
    name: str | None = None
    product_code: str | None = None
    ip_address: str | None = None
    account_id: str | None = None
    marge_url: str | None = None


def _element_text(element: ET.Element, path: str) -> str | None:
    child = element.find(path)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    if not text:
        return None
    return text


def _speaker_info_from_xml(info_xml: str) -> SpeakerInfo | None:
    if not info_xml:
        return None

    try:
        root = ET.fromstring(info_xml)
    except ET.ParseError:
        return None

    device_id = root.attrib.get("deviceID", "").strip()
    if not device_id:
        return None

    product_parts = [
        part
        for part in (
            _element_text(root, "type"),
            _element_text(root, "moduleType"),
        )
        if part
    ]

    ip_address = None
    for network_info in root.findall("networkInfo"):
        if network_info.attrib.get("type") == "SCM":
            ip_address = _element_text(network_info, "ipAddress")
            break
    if ip_address is None:
        ip_address = _element_text(root, "networkInfo/ipAddress")

    return SpeakerInfo(
        device_id=device_id,
        name=_element_text(root, "name"),
        product_code=" ".join(product_parts) or None,
        ip_address=ip_address,
        account_id=_element_text(root, "margeAccountUUID"),
        marge_url=_element_text(root, "margeURL"),
    )


def _marge_server(marge_url: str | None, base_url: str) -> str:
    if not marge_url:
        return "Unknown"
    if marge_url == BOSE_MARGE_URL:
        return "Bose"
    if marge_url.rstrip("/") == f"{base_url.rstrip('/')}/marge":
        return "Soundcork"
    return "Other"


def _source_statuses_from_xml(sources_xml: str) -> tuple[dict[str, str], str | None]:
    if not sources_xml:
        return {}, "Unable to fetch /sources"

    try:
        root = ET.fromstring(sources_xml)
    except ET.ParseError:
        return {}, "Unable to parse /sources"

    statuses: dict[str, str] = {}
    for source_item in root.findall("sourceItem"):
        source = source_item.attrib.get("source", "").strip()
        status = source_item.attrib.get("status", "").strip()
        if not source:
            continue
        if statuses.get(source) == "READY":
            continue
        statuses[source] = status or "UNKNOWN"

    return statuses, None


def _radio_sources_ready(source_statuses: dict[str, str]) -> bool:
    return any(source_statuses.get(source) == "READY" for source in RADIO_SOURCE_KEYS)


def _radio_source_summary(source_statuses: dict[str, str]) -> str:
    parts = [
        f"{source}={source_statuses.get(source, 'missing')}"
        for source in RADIO_SOURCE_KEYS
    ]
    return ", ".join(parts)


def _playback_capability(
    marge_server: str,
    rest_reachable: bool,
    source_statuses: dict[str, str],
    sources_error: str | None = None,
) -> tuple[str, str]:
    if not rest_reachable:
        return "Unknown", "REST /info is not reachable."
    if sources_error:
        return "Unknown", sources_error

    radio_ready = _radio_sources_ready(source_statuses)
    source_summary = _radio_source_summary(source_statuses)

    if marge_server == "Soundcork":
        if radio_ready:
            return "Soundcork-ready", f"Radio sources are ready: {source_summary}."
        return (
            "Needs repair",
            "Speaker points at this Soundcork, but radio sources are not ready: "
            f"{source_summary}.",
        )

    if marge_server == "Bose":
        if radio_ready:
            return (
                "Legacy-ready",
                "Speaker still points at Bose, but radio sources are currently "
                f"ready: {source_summary}. This may only last until reboot.",
            )
        return (
            "Needs repair",
            "Speaker points at Bose and radio sources are not ready: "
            f"{source_summary}.",
        )

    if radio_ready:
        return "Legacy-ready", f"Radio sources are ready: {source_summary}."

    return "Unknown", f"Radio source state is inconclusive: {source_summary}."


def _device_from_stored_info(
    account_id: str,
    stored: DeviceInfo,
) -> ManagementDevice:
    return ManagementDevice(
        device_id=stored.device_id,
        account_id=account_id,
        name=stored.name,
        product_code=stored.product_code,
        ip_address=stored.ip_address,
        stored_ip_address=stored.ip_address,
        in_soundcork=True,
        rest_reachable=False,
        marge_server="Unknown",
        uses_this_soundcork=False,
        playback_capability="Unknown",
        playback_capability_detail="REST /info is not reachable.",
        source="datastore",
    )


def _merge_fresh_info(
    device: ManagementDevice,
    speaker_info: SpeakerInfo,
    base_url: str,
    source: str | None = None,
) -> ManagementDevice:
    if source:
        device.source = source

    device.rest_reachable = True
    device.reported_account_id = speaker_info.account_id
    device.reported_ip_address = speaker_info.ip_address
    device.marge_url = speaker_info.marge_url
    device.marge_server = _marge_server(speaker_info.marge_url, base_url)
    device.uses_this_soundcork = device.marge_server == "Soundcork"

    if speaker_info.name:
        device.name = speaker_info.name
    if speaker_info.product_code:
        device.product_code = speaker_info.product_code
    if speaker_info.ip_address:
        device.ip_address = speaker_info.ip_address

    if speaker_info.device_id != device.device_id:
        device.error = (
            f"Stored device ID {device.device_id} differs from "
            f"speaker-reported device ID {speaker_info.device_id}"
        )

    return device


def _merge_fresh_sources(
    device: ManagementDevice,
    hostname: str,
    fetch_sources: Callable[[str], str],
) -> ManagementDevice:
    try:
        sources_xml = fetch_sources(hostname)
    except Exception as e:
        logger.info("Failed to fetch speaker sources from %s: %s", hostname, e)
        sources_xml = ""

    source_statuses, sources_error = _source_statuses_from_xml(sources_xml)
    if sources_error:
        sources_error = f"{sources_error} from {hostname}"

    device.source_statuses = source_statuses
    device.internet_radio_ready = _radio_sources_ready(source_statuses)
    (
        device.playback_capability,
        device.playback_capability_detail,
    ) = _playback_capability(
        device.marge_server,
        device.rest_reachable,
        source_statuses,
        sources_error,
    )
    return device


def _fetch_speaker_info(
    hostname: str,
    fetch_info: Callable[[str], str],
) -> tuple[SpeakerInfo | None, str | None]:
    try:
        info_xml = fetch_info(hostname)
    except Exception as e:
        logger.info("Failed to fetch speaker info from %s: %s", hostname, e)
        return None, f"Unable to fetch /info from {hostname}"

    if not info_xml:
        return None, None

    speaker_info = _speaker_info_from_xml(info_xml)
    if speaker_info is None:
        return None, f"Unable to parse /info from {hostname}"

    return speaker_info, None


def list_management_devices(
    store: DataStore,
    config: Settings,
    account_filter: str | None = None,
    include_discovered: bool = False,
    refresh: bool = True,
    fetch_info: Callable[[str], str] | None = None,
    fetch_sources: Callable[[str], str] | None = None,
    discover_devices: Callable[[], Iterable] | None = None,
) -> ManagementDevicesResponse:
    """Return a sanitized device inventory for management clients."""
    if fetch_info is None:
        fetch_info = read_device_info
    if fetch_sources is None:
        fetch_sources = read_runtime_sources
    if discover_devices is None:
        discover_devices = get_bose_devices

    devices: dict[str, ManagementDevice] = {}
    base_url = config.base_url

    accounts = [account_filter] if account_filter else store.list_accounts()
    for account_id in accounts:
        if not account_id:
            continue
        for device_id in store.list_devices(account_id):
            if not device_id:
                continue
            stored = store.get_device_info(account_id, device_id)
            device = _device_from_stored_info(account_id, stored)
            devices[device_id] = device

            if refresh and stored.ip_address:
                fresh, error = _fetch_speaker_info(stored.ip_address, fetch_info)
                if fresh:
                    _merge_fresh_info(device, fresh, base_url)
                    _merge_fresh_sources(
                        device, fresh.ip_address or stored.ip_address, fetch_sources
                    )
                elif error:
                    device.error = error

    if include_discovered:
        for discovered_device in discover_devices():
            try:
                hostname = hostname_for_device(discovered_device)
            except AttributeError:
                continue
            if not hostname:
                continue

            fresh, _error = _fetch_speaker_info(hostname, fetch_info)
            if not fresh:
                continue
            if account_filter and fresh.account_id != account_filter:
                continue

            device = devices.get(fresh.device_id)
            if device:
                _merge_fresh_info(device, fresh, base_url, source="datastore+discovery")
                _merge_fresh_sources(device, hostname, fetch_sources)
                continue

            marge_server = _marge_server(fresh.marge_url, base_url)
            device = ManagementDevice(
                device_id=fresh.device_id,
                account_id=fresh.account_id,
                in_soundcork=False,
                rest_reachable=True,
                marge_server=marge_server,
                uses_this_soundcork=marge_server == "Soundcork",
                source="discovery",
            )
            _merge_fresh_info(device, fresh, base_url, source="discovery")
            _merge_fresh_sources(device, hostname, fetch_sources)
            devices[fresh.device_id] = device

    return ManagementDevicesResponse(devices=sorted(devices.values(), key=_device_key))


def _device_key(device: ManagementDevice) -> tuple[str, str]:
    return (device.account_id or "", device.name or device.device_id)


@router.get("/devices", response_model=ManagementDevicesResponse)
def management_devices(
    include_discovered: Annotated[
        bool,
        Query(description="Also include speakers found through local UPnP discovery."),
    ] = False,
    refresh: Annotated[
        bool,
        Query(description="Refresh stored speakers through their HTTP /info endpoint."),
    ] = True,
):
    """List SoundTouch speakers without exposing raw Bose account XML."""
    return list_management_devices(
        datastore,
        settings,
        include_discovered=include_discovered,
        refresh=refresh,
    )


@router.get("/accounts/{account}/devices", response_model=ManagementDevicesResponse)
def management_account_devices(
    account: str,
    include_discovered: Annotated[
        bool,
        Query(description="Also include speakers found through local UPnP discovery."),
    ] = False,
    refresh: Annotated[
        bool,
        Query(description="Refresh stored speakers through their HTTP /info endpoint."),
    ] = True,
):
    """List SoundTouch speakers for one Soundcork account."""
    if not datastore.account_exists(account):
        raise HTTPException(status_code=404, detail=f"Account {account} not found")

    return list_management_devices(
        datastore,
        settings,
        account_filter=account,
        include_discovered=include_discovered,
        refresh=refresh,
    )


# --- Spotify ---


@router.post("/spotify/init")
def spotify_init(request: Request):
    """Start the Spotify OAuth flow.

    Returns a redirect URL that the caller should open in a browser.
    After authorization, Spotify redirects to the configured redirect_uri
    with an authorization code.
    """
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured (missing SPOTIFY_CLIENT_ID)",
        )

    authorize_url = spotify.build_authorize_url()
    return {"redirectUrl": authorize_url}


@router.get("/spotify/init")
def spotify_init_browser(request: Request):
    """Start the Spotify OAuth flow via browser redirect.

    Unlike POST /spotify/init, this endpoint redirects the browser
    directly to Spotify with the server-side callback URL, so the
    entire flow happens in the browser.

    No Basic Auth required -- the callback is on this server.
    """
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured (missing SPOTIFY_CLIENT_ID)",
        )

    # Use the server callback URL. We use settings.base_url rather than
    # request.base_url because the app may sit behind a TLS-terminating
    # reverse proxy and request.base_url would return http://.
    callback_url = settings.base_url.rstrip("/") + "/mgmt/spotify/callback"
    authorize_url = spotify.build_authorize_url(redirect_uri=callback_url)

    return RedirectResponse(url=authorize_url)


@router.get("/spotify/callback", response_class=HTMLResponse)
async def spotify_callback(
    request: Request,
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
):
    """Server-side OAuth callback.

    This endpoint is NOT protected by Basic Auth because Spotify
    redirects the user's browser here directly.
    """
    if error:
        return HTMLResponse(
            content=f"<html><body><h1>Spotify Authorization Failed</h1>"
            f"<p>Error: {error}</p></body></html>",
            status_code=400,
        )

    if not code:
        return HTMLResponse(
            content="<html><body><h1>Missing authorization code</h1></body></html>",
            status_code=400,
        )

    try:
        callback_url = settings.base_url.rstrip("/") + "/mgmt/spotify/callback"
        account = await spotify.exchange_code_and_store(code, redirect_uri=callback_url)
        return HTMLResponse(
            content=f"<html><body>"
            f"<h1>Spotify Connected</h1>"
            f"<p>Linked account: {account['displayName']} ({account['spotifyUserId']})</p>"
            f"<p>You can close this window.</p>"
            f"</body></html>"
        )
    except Exception as e:
        logger.exception("Spotify callback failed")
        return HTMLResponse(
            content=f"<html><body><h1>Error</h1><p>{e}</p></body></html>",
            status_code=500,
        )


@router.post("/spotify/confirm")
async def spotify_confirm(code: Annotated[str, Query()]):
    """Confirm Spotify authorization with an authorization code.

    Used by mobile apps after a deep link callback delivers the code.
    Exchanges the code for tokens and stores the account.
    """
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured",
        )

    try:
        await spotify.exchange_code_and_store(code)
    except Exception as e:
        logger.exception("Spotify confirm failed")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


@router.get("/spotify/accounts")
def spotify_accounts():
    """List connected Spotify accounts (tokens stripped)."""
    accounts = spotify.list_accounts()
    return {
        "accounts": [
            {
                "displayName": a["displayName"],
                "createdAt": a["createdAt"],
                "spotifyUserId": a["spotifyUserId"],
            }
            for a in accounts
        ]
    }
