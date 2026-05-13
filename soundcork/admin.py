"""
Endpoints for an admin UI.

"""

import logging
from datetime import datetime, timezone
from http import HTTPStatus

from bosesoundtouchapi.soundtouchclient import (  # type: ignore
    SoundTouchClient,
    SoundTouchDevice,
)
from bosesoundtouchapi.soundtouchdiscovery import SoundTouchDiscovery  # type: ignore
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from soundcork.datastore import DataStore
from soundcork.devices import (
    add_device_by_ip,
    addr_is_reachable,
    override_speaker_config,
    override_speaker_config_non_rooted,
    reboot_speaker,
)
from soundcork.model import ConfiguredSource
from soundcork.ui.speakers import CombinedDevice, Speakers

router = APIRouter(tags=["admin"])

logger = logging.getLogger(__name__)


def get_admin_router(datastore: DataStore, speakers: Speakers):
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory="templates")

    router = APIRouter(tags=["admin"])

    class CombinedAccount(BaseModel):
        id: str
        devices: list[CombinedDevice]
        in_soundcork: bool

    @router.get("/admin/", response_class=HTMLResponse)
    async def admin(request: Request):
        combined_devices = speakers.all_devices()

        unassociated_devices = []
        account_ids = datastore.list_accounts()
        accounts = {}

        for account_id in account_ids:
            if account_id:
                account = CombinedAccount(id=account_id, devices=[], in_soundcork=True)
                accounts[account_id] = account

        # sort devices from speakers.all_devices() into accounts. also check
        # to see if they are reachable via ssh (which really only matters in
        # an admin context)
        sorted_keys = sorted(combined_devices)
        for key in sorted_keys:
            dev = combined_devices[key]
            # assign to account
            account_id = dev.account
            if account_id:
                found_account = accounts.get(account_id, None)
                if not found_account:
                    found_account = CombinedAccount(
                        id=account_id, devices=[], in_soundcork=False
                    )
                    accounts[account_id] = found_account

                found_account.devices.append(dev)
            else:
                unassociated_devices.append(dev)
            # also check to see if it's available via ssh
            dev.reachable = addr_is_reachable(dev.ip)

        return templates.TemplateResponse(
            request=request,
            name="admin/index.html",
            context={"accounts": accounts, "unassociated": unassociated_devices},
        )

    @router.post("/admin/switchToSoundcork/{device_id}")
    async def switch_device(device_id: str):
        logger.info(f"switch {device_id} to soundcork")
        combined_device = speakers.all_devices().get(device_id)
        if combined_device:
            st_device = combined_device.st_device
            if st_device:
                hostname = st_device.Host
                success = await override_speaker_config_non_rooted(hostname)
                logger.info(
                    f"override speaker config on {hostname} success = {success}"
                )
                # reboot = reboot_speaker(hostname)
                # logger.info(f"reboot {hostname} result {reboot}")
                # speakers.clear_device(device_id)
                return RedirectResponse("/admin", status_code=HTTPStatus.FOUND)
        return RedirectResponse(
            url=f"/admin/wait/{device_id}/0", status_code=HTTPStatus.FOUND
        )

    @router.get("/admin/wait/{device_id}/{elapsed}")
    async def wait_switch_device(request: Request, device_id: str, elapsed: int):
        logger.debug(f"checking for restart for {{device_id}}")
        # only wait up to 120 seconds
        if elapsed >= 120:
            return RedirectResponse(url=f"/admin/", status_code=HTTPStatus.FOUND)

        combined_device = speakers.all_devices().get(device_id)
        if combined_device:
            st_device = combined_device.st_device
            if st_device:
                return RedirectResponse(url=f"/admin/", status_code=HTTPStatus.FOUND)

        return templates.TemplateResponse(
            request=request,
            name="admin/wait.html",
            context={"elapsed": elapsed, "device_id": device_id},
        )

    @router.post("/admin/addDevice/{device_id}")
    async def add_device_to_soundcork(device_id: str):
        logger.info(f"add device {device_id} to soundcork")
        combined_device = speakers.all_devices().get(device_id)
        if combined_device:
            st_device = combined_device.st_device
            if st_device:
                hostname = st_device.Host
                success = add_device_by_ip(hostname)
                logger.info(f"added account from {hostname} success = {success}")

        return RedirectResponse(url=f"/admin/", status_code=HTTPStatus.FOUND)

    @router.post("/admin/addAccount")
    async def add_account(request: Request):
        logger.info("adding new account")
        account_id = "1234567"
        account_name = "New Account"
        now = datetime.fromtimestamp(
            datetime.now().timestamp(), timezone.utc
        ).isoformat(timespec="milliseconds")
        account = datastore.create_account(account_id, account_name)
        datastore.save_configured_sources(
            account_id,
            [
                ConfiguredSource(
                    display_name="AUX IN",
                    id="112345",
                    secret="",
                    secret_type="",
                    source_key_type="AUX",
                    source_key_account="AUX",
                    created_on=now,
                    updated_on=now,
                ),
                ConfiguredSource(
                    display_name="INTERNET RADIO",
                    id="112346",
                    secret="",
                    secret_type="token",
                    source_key_type="INTERNET_RADIO",
                    source_key_account="",
                    created_on=now,
                    updated_on=now,
                ),
                ConfiguredSource(
                    display_name="",
                    id="112347",
                    secret="",
                    secret_type="token",
                    source_key_type="TUNEIN",
                    source_key_account="",
                    created_on=now,
                    updated_on=now,
                ),
            ],
        )
        datastore.save_presets(account_id, "", [])
        datastore.save_recents(account_id, "", [])

        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    @router.post("/admin/{device_id}/setAccount")
    async def set_account(request: Request, device_id: str):
        success = speakers.set_account(device_id, "3380435")
        logger.info(f"success={success}")
        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    @router.post("/admin/{device_id}/setName")
    async def set_name(request: Request, device_id: str):
        speakers.set_name(device_id, "Test Name")

        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    @router.post("/admin/{device_id}")
    async def telnet_add_account_unrooted(request: Request, device_id: str):
        logger.info("")

        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    return router
