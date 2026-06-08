"""
Endpoints for a miniapp UI.
"""

import asyncio
import logging
import time
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from soundcork.constants import DEFAULT_DEVICE_IMAGE, DEVICE_IMAGE_MAP
from soundcork.datastore import DataStore
from soundcork.ui.speakers import Speakers

if TYPE_CHECKING:
    from soundcork.model import Preset

logger = logging.getLogger(__name__)

NOW_PLAYING_TIMEOUT = 3.0
STARTED_OPTIMISTIC_SECONDS = 3.0


@dataclass
class NowPlaying:
    """The state of a currently playing speaker device."""

    name: str
    image: str
    status: str
    volume_actual: int
    volume_target: int
    is_muted: bool

    def is_volume_changing(self) -> bool:
        """Target and Actual values will only be different while volume is changing."""
        return self.volume_actual != self.volume_target


def encode_cookie_value(value: object) -> str:
    """Encode text for Set-Cookie's latin-1 constrained header value."""
    return quote(str(value), safe="")


def decode_cookie_value(value: str | None, default: str | None = None) -> str | None:
    if value is None:
        return default
    return unquote(value)


def get_device_image(product_code: str) -> str:
    """Map product code to device image file."""
    return DEVICE_IMAGE_MAP.get(product_code.lower(), DEFAULT_DEVICE_IMAGE)


def use_started_state(started: bool, started_at: float | None) -> bool:
    """Return True while a just-started playback action may still have stale metadata."""
    if not started or started_at is None:
        return False

    elapsed = time.time() - started_at
    return 0 <= elapsed <= STARTED_OPTIMISTIC_SECONDS


def get_miniapp_router(datastore: DataStore, speakers: Speakers):
    templates = Jinja2Templates(directory="templates")

    router = APIRouter(tags=["miniapp"])

    def play_selected_content_item(
        device_id: str,
        content_item_id: str,
        *,
        log_context: str,
    ) -> bool:
        if speakers.play_content_item(device_id, content_item_id):
            logger.info(
                f"Started playback from {log_context}: content_item {content_item_id} on device {device_id}"
            )
            return True

        logger.error(f"Failed to start playback from {log_context}")
        return False

    @router.get("/miniapp", response_class=HTMLResponse)
    async def main_page(request: Request):
        """Redirect to login or dashboard based on session."""
        account_id = request.cookies.get("soundcork_account_id")
        if account_id and datastore.account_exists(account_id):
            return RedirectResponse(url="/miniapp/dashboard", status_code=303)
        else:
            return RedirectResponse(url="/miniapp/login", status_code=303)

    @router.get("/miniapp/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        """Display login page with account selection."""
        try:
            account_ids = datastore.list_accounts()
            accounts_data = {}

            for account_id in account_ids:
                if account_id:
                    try:
                        label = datastore.get_account_info(account_id)
                        device_count = len(datastore.list_devices(account_id))
                        accounts_data[account_id] = {
                            "label": label,
                            "device_count": device_count,
                        }
                    except Exception as e:
                        logger.error(
                            f"Error getting info for account {account_id}: {e}"
                        )
                        continue

            logger.info(f"Rendering login with {len(accounts_data)} accounts")
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"accounts": accounts_data, "error": None},
            )
        except Exception as e:
            logger.error(f"Error rendering login page: {e}")
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"accounts": {}, "error": "Error loading accounts"},
            )

    @router.post("/miniapp/login")
    async def login_submit(request: Request):
        """Handle account selection and set cookie."""
        try:
            form_data = await request.form()
            account_id_raw = form_data.get("account_id")

            if not account_id_raw or not isinstance(account_id_raw, str):
                return RedirectResponse(
                    url="/miniapp/login?error=No account selected", status_code=303
                )

            account_id: str = account_id_raw

            # Verify account exists
            if not datastore.account_exists(account_id):
                return RedirectResponse(
                    url="/miniapp/login?error=Invalid account", status_code=303
                )

            # Get account label
            account_label = datastore.get_account_info(account_id)

            # Create response with redirect
            response = RedirectResponse(url="/miniapp/dashboard", status_code=303)

            # Set cookies for account
            response.set_cookie(
                key="soundcork_account_id",
                value=account_id,
                max_age=86400 * 30,  # 30 days
                httponly=True,
                samesite="strict",
            )
            response.set_cookie(
                key="soundcork_account_label",
                value=encode_cookie_value(account_label),
                max_age=86400 * 30,
                httponly=False,  # Allow JS to read for display
                samesite="strict",
            )

            logger.info(f"User logged in to account {account_id}")
            return response

        except Exception as e:
            logger.error(f"Error during login: {e}")
            return RedirectResponse(
                url="/miniapp/login?error=Login failed", status_code=303
            )

    @router.get("/miniapp/dashboard", response_class=HTMLResponse)
    async def dashboard_page(
        request: Request,
        selected_content_item_id: str | None = Query(None),
        selected_device_id: str | None = Query(None),
        started: bool = Query(False),
        started_at: float | None = Query(None),
        stopped: bool = Query(False),
    ):
        """Display dashboard with devices and presets.

        Args:
            request: The Request object

            selected_content_item_id: The playable ContentItem, if one is selected
                in the user's context.

            selected_device_id: The speaker, if one is selected
                in the user's context.

            started: If playback on the current device was just started
                by the user's request. Passing as an argument to avoid
                timing issues in the query.

            started_at: Server timestamp for the playback start redirect. Keeps
                the optimistic started state short-lived if the page is reloaded.

            stopped: If the stream on the current device was just stopped
                by the user's request. Passing as an argument to avoid
                timing issues in the query.
        """
        account_id = ""
        try:
            # Get account from cookie
            account_id = request.cookies.get("soundcork_account_id", "")
            account_label = decode_cookie_value(
                request.cookies.get("soundcork_account_label"), "Unknown Account"
            )

            if not account_id:
                return RedirectResponse(url="/miniapp/login", status_code=303)

            # Verify account still exists
            if not datastore.account_exists(account_id):
                response = RedirectResponse(url="/miniapp/login", status_code=303)
                response.delete_cookie("soundcork_account_id")
                response.delete_cookie("soundcork_account_label")
                return response

            # Get devices and speakers for this account
            combined_devices = speakers.all_devices()
            my_combined_devices = {
                device_id: cd
                for device_id, cd in combined_devices.items()
                if cd.account == account_id
            }

            devices: list[dict[str, str]] = []
            try:
                presets = datastore.get_presets(account_id)
            except Exception as e:
                logger.warning(f"Error getting presets for account {account_id}: {e}")
                presets = []
            selected_preset = next(
                (
                    preset
                    for preset in presets
                    if str(preset.id) == selected_content_item_id
                ),
                None,
            )
            show_started_state = use_started_state(started, started_at)

            for device_id in my_combined_devices.keys():
                try:
                    if stopped and device_id == selected_device_id:
                        np = NowPlaying("", "", "", 0, 0, False)
                    else:
                        np = await _get_now_playing(device_id)
                        if (
                            show_started_state
                            and device_id == selected_device_id
                            and selected_preset
                        ):
                            np = NowPlaying(
                                selected_preset.name,
                                selected_preset.container_art or "",
                                "PLAY_STATE",
                                np.volume_actual,
                                np.volume_target,
                                np.is_muted,
                            )
                    online = "offline"
                    cd = my_combined_devices[device_id]
                    device_info = datastore.get_device_info(account_id, device_id)
                    if (
                        cd.online
                        and cd.in_soundcork
                        and (cd.marge_server == "Soundcork")
                    ):
                        online = "online"
                    devices.append(
                        {
                            "name": device_info.name,
                            "product_code": device_info.product_code,
                            "device_id": device_info.device_id,
                            "online_status": online,
                            "play_state": np.status,
                            "image_file": get_device_image(device_info.product_code),
                            "now_playing": np.name,
                            "now_playing_image": np.image,
                            "now_playing_volume": str(np.volume_actual),
                            "now_playing_is_muted": str(np.is_muted),
                        }
                    )

                except Exception as e:
                    logger.error(f"Error getting device info for {device_id}: {e}")
                    continue

            logger.info(
                f"Rendering dashboard for account {account_id} with {len(devices)} devices and {len(presets)} presets"
            )

            return templates.TemplateResponse(
                request=request,
                name="dashboard.html",
                context={
                    "account_id": account_id,
                    "account_label": account_label,
                    "devices": devices,
                    "presets": presets,
                    "selected_content_item_id": selected_content_item_id,
                    "selected_device_id": selected_device_id,
                    "error": None,
                },
            )

        except Exception as e:
            logger.error(f"Error rendering dashboard: {e}")

            return templates.TemplateResponse(
                request=request,
                name="dashboard.html",
                context={
                    "account_id": account_id,
                    "account_label": "Unknown",
                    "devices": [],
                    "presets": [],
                    "selected_content_item_id": selected_content_item_id,
                    "selected_device_id": selected_device_id,
                    "error": "Error loading dashboard data",
                },
            )

    async def _get_now_playing(device_id) -> NowPlaying:
        """Get now_playing info for a device"""
        loop = asyncio.get_event_loop()
        try:
            np = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: speakers.get_now_playing_status(device_id=device_id),
                ),
                timeout=NOW_PLAYING_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Timeout getting now playing status for {device_id}")
            return NowPlaying("[Unknown]", "", "", 0, 0, False)

        try:
            volume = speakers.get_volume(device_id)
        except Exception as e:
            logger.warning(f"Error getting volume for {device_id}: {e}")
            volume = None

        if np:
            return NowPlaying(
                f"{np.StationName or np.ContentItem.Name}",
                np.ContainerArtUrl or "",
                np.PlayStatus,
                volume.Actual if volume else 0,
                volume.Target if volume else 0,
                volume.IsMuted if volume else False,
            )
        else:
            return NowPlaying(
                "",
                "",
                "",
                volume.Actual if volume else 0,
                volume.Target if volume else 0,
                volume.IsMuted if volume else False,
            )

    @router.post("/miniapp/select-content-item")
    async def select_content_item(
        request: Request, selected_device_id: str | None = Query(None)
    ):
        """Handle content_item selection."""
        try:
            form_data = await request.form()
            content_item_id = form_data.get("content_item_id")
            content_item_name = form_data.get("content_item_name")

            if (
                not isinstance(content_item_id, str)
                or not isinstance(content_item_name, str)
                or not content_item_id
                or not content_item_name
            ):
                return RedirectResponse(url="/miniapp/dashboard", status_code=303)

            params: dict[str, str] = {"selected_content_item_id": content_item_id}
            if selected_device_id:
                params["selected_device_id"] = selected_device_id
                if play_selected_content_item(
                    selected_device_id,
                    content_item_id,
                    log_context="preset click",
                ):
                    params["started"] = "true"
                    params["started_at"] = f"{time.time():.3f}"
            qs = urllib.parse.urlencode(params)
            return RedirectResponse(url=f"/miniapp/dashboard?{qs}", status_code=303)

        except Exception as e:
            logger.error(f"Error selecting content_item: {e}")
            return RedirectResponse(url="/miniapp/dashboard", status_code=303)

    @router.post("/miniapp/select-device")
    async def select_device(
        request: Request, selected_content_item_id: str | None = Query(None)
    ):
        """Handle device selection."""
        try:
            form_data = await request.form()
            device_id = form_data.get("device_id")
            device_name = form_data.get("device_name")

            if (
                not isinstance(device_id, str)
                or not isinstance(device_name, str)
                or not device_id
                or not device_name
            ):
                return RedirectResponse(url="/miniapp/dashboard", status_code=303)

            params: dict[str, str] = {"selected_device_id": str(device_id)}
            if selected_content_item_id:
                params["selected_content_item_id"] = selected_content_item_id
            qs = urllib.parse.urlencode(params)
            logger.info(f"Device selected: {device_name} ({device_id})")
            return RedirectResponse(url=f"/miniapp/dashboard?{qs}", status_code=303)

        except Exception as e:
            logger.error(f"Error selecting device: {e}")
            return RedirectResponse(url="/miniapp/dashboard", status_code=303)

    @router.post("/miniapp/play")
    async def play(
        request: Request,
        selected_content_item_id: str | None = Query(None),
        selected_device_id: str | None = Query(None),
    ):
        """Play the selected content_item on the selected device."""
        try:
            if not selected_content_item_id or not selected_device_id:
                logger.warning("Cannot play: content_item or device not selected")
                return RedirectResponse(url="/miniapp/dashboard", status_code=303)

            started = play_selected_content_item(
                selected_device_id,
                selected_content_item_id,
                log_context="play button",
            )

            params = {
                "selected_device_id": selected_device_id,
                "selected_content_item_id": selected_content_item_id,
            }
            if started:
                params["started"] = "true"
                params["started_at"] = f"{time.time():.3f}"
            return RedirectResponse(
                url=f"/miniapp/dashboard?{urllib.parse.urlencode(params)}",
                status_code=303,
            )

        except Exception as e:
            logger.error(f"Error in play endpoint: {e}")
            return RedirectResponse(url="/miniapp/dashboard", status_code=303)

    @router.post("/miniapp/stop")
    async def stop(
        request: Request,
        selected_device_id: str | None = Query(None),
        selected_content_item_id: str | None = Query(None),
    ):
        """Stop playback on the selected device."""
        try:
            if not selected_device_id:
                logger.warning("Cannot stop: device not selected")
                return RedirectResponse(url="/miniapp/dashboard", status_code=303)

            # Stop playback
            success = speakers.stop_playback(selected_device_id)
            if success:
                logger.info(f"Stopped playback on device {selected_device_id}")
            else:
                logger.error("Failed to stop playback")

            params: dict[str, str] = {
                "selected_device_id": selected_device_id,
                "stopped": "true",
            }
            if selected_content_item_id:
                params["selected_content_item_id"] = selected_content_item_id
            return RedirectResponse(
                url=f"/miniapp/dashboard?{urllib.parse.urlencode(params)}",
                status_code=303,
            )

        except Exception as e:
            logger.error(f"Error in stop endpoint: {e}")
            return RedirectResponse(url="/miniapp/dashboard", status_code=303)

    @router.post("/miniapp/logout")
    async def logout(request: Request):
        """Clear session and redirect to login."""
        response = RedirectResponse(url="/miniapp/login", status_code=303)
        response.delete_cookie("soundcork_account_id")
        response.delete_cookie("soundcork_account_label")
        logger.info("User logged out")
        return response

    return router
