"""
Endpoints for a miniapp UI.
"""

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from soundcork.constants import DEFAULT_DEVICE_IMAGE, DEVICE_IMAGE_MAP
from soundcork.datastore import DataStore

logger = logging.getLogger(__name__)


def get_device_image(product_code: str) -> str:
    """Map product code to device image file."""
    logger.info(f"Mapping product code '{product_code.lower()}' to device image")
    logger.info(f"{DEVICE_IMAGE_MAP.get(product_code.lower(), "foo")}")
    return DEVICE_IMAGE_MAP.get(product_code.lower(), DEFAULT_DEVICE_IMAGE)


def get_miniapp_router(datastore: DataStore, settings):
    templates = Jinja2Templates(directory="templates")

    router = APIRouter(tags=["miniapp"])

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
                value=account_label,
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
    async def dashboard_page(request: Request):
        """Display dashboard with devices and presets."""
        try:
            # Get account from cookie
            account_id = request.cookies.get("soundcork_account_id")
            account_label = request.cookies.get(
                "soundcork_account_label", "Unknown Account"
            )

            if not account_id:
                return RedirectResponse(url="/miniapp/login", status_code=303)

            # Verify account still exists
            if not datastore.account_exists(account_id):
                response = RedirectResponse(url="/miniapp/login", status_code=303)
                response.delete_cookie("soundcork_account_id")
                response.delete_cookie("soundcork_account_label")
                return response

            # Get devices for this account
            device_ids = datastore.list_devices(account_id)
            devices: list[dict[str, str]] = []
            presets: list[dict[str, str]] = []

            for device_id in device_ids:
                if device_id:
                    try:
                        device_info = datastore.get_device_info(account_id, device_id)
                        logger.info(f"Product cote: {device_info.product_code}")
                        devices.append(
                            {
                                "name": device_info.name,
                                "product_code": device_info.product_code,
                                "device_id": device_info.device_id,
                                "image_file": get_device_image(
                                    device_info.product_code
                                ),
                            }
                        )

                        # Get presets for first device only
                        if not presets:
                            try:
                                device_presets = datastore.get_presets(
                                    account_id, device_id
                                )
                                presets = [
                                    {
                                        "id": p.id,
                                        "name": p.name,
                                        "container_art": p.container_art,
                                    }
                                    for p in device_presets
                                ]
                            except Exception as e:
                                logger.warning(
                                    f"Error getting presets for device {device_id}: {e}"
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
                    "error": None,
                },
            )

        except Exception as e:
            logger.error(f"Error rendering dashboard: {e}")
            return templates.TemplateResponse(
                request=request,
                name="dashboard.html",
                context={
                    "account_id": "",
                    "account_label": "Unknown",
                    "devices": [],
                    "presets": [],
                    "error": "Error loading dashboard data",
                },
            )

    @router.post("/miniapp/logout")
    async def logout(request: Request):
        """Clear session and redirect to login."""
        response = RedirectResponse(url="/miniapp/login", status_code=303)
        response.delete_cookie("soundcork_account_id")
        response.delete_cookie("soundcork_account_label")
        logger.info("User logged out")
        return response

    return router
