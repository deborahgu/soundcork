"""
Endpoints for an admin UI.

This is a DRAFT version of the admin ui. The display code is not functioning correctly yet, because the device discovery code isn't working correctly. Before it's considered working even for display-only, it will need to have:

- timeouts for device interaction
- error handling, with errors reported on the web page
- guaranteed loading of the page with a status message of some sort after only a few seconds.
"""

import logging
from http import HTTPStatus

from bosesoundtouchapi.soundtouchclient import SoundTouchDevice  # type: ignore
from bosesoundtouchapi.soundtouchdiscovery import SoundTouchDiscovery  # type: ignore
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from soundcork.datastore import DataStore
from soundcork.devices import (
    add_device_by_ip,
    addr_is_reachable,
    override_speaker_config,
    reboot_speaker,
)
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
            context={"accounts": accounts},
        )

    @router.post("/admin/switchToSoundcork/{device_id}")
    async def switch_device(device_id: str):
        logger.info(f"switch {device_id} to soundcork")
        combined_device = speakers.all_devices().get(device_id)
        if combined_device:
            st_device = combined_device.st_device
            if st_device:
                hostname = st_device.Host
                success = override_speaker_config(hostname)
                logger.info(
                    f"override speaker config on {hostname} success = {success}"
                )
                reboot = reboot_speaker(hostname)
                logger.info(f"reboot {hostname} result {reboot}")
                speakers.clear_device(device_id)
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

    return router
