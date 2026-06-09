"""
Endpoints for an admin UI.

"""

import logging
import time
from http import HTTPStatus
from typing import Annotated

from bosesoundtouchapi.models.languagecodes import LanguageCodes  # type: ignore
from bosesoundtouchapi.soundtouchclient import (  # type: ignore
    SoundTouchClient,
    SoundTouchDevice,
)
from bosesoundtouchapi.soundtouchdiscovery import SoundTouchDiscovery  # type: ignore
from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from soundcork.constants import ACCOUNT_RE
from soundcork.datastore import DataStore
from soundcork.devices import (
    add_device_by_ip,
    addr_port_is_reachable,
    default_sources,
    override_speaker_config,
    override_speaker_config_non_rooted,
    reboot_speaker,
)
from soundcork.management import (
    ManagementDevice,
    list_management_devices,
    settings as management_settings,
)
from soundcork.model import ConfiguredSource
from soundcork.ui.speakers import CombinedDevice, Speakers

router = APIRouter(tags=["admin"])

logger = logging.getLogger(__name__)

SSH_PORT = 22
CLISERVER_PORT = 17000


def _management_devices_by_id(datastore: DataStore) -> dict[str, ManagementDevice]:
    return {
        device.device_id: device
        for device in list_management_devices(
            datastore,
            management_settings,
            include_discovered=False,
            refresh=True,
        ).devices
    }


def _apply_management_state(
    device: CombinedDevice,
    management_device: ManagementDevice | None,
) -> CombinedDevice:
    if not management_device:
        return device

    device.rest_reachable = management_device.rest_reachable
    device.marge_url = management_device.marge_url
    device.marge_server = management_device.marge_server
    device.state_source = management_device.source
    device.error = management_device.error
    device.in_soundcork = management_device.in_soundcork

    if management_device.account_id:
        device.account = management_device.account_id
    elif management_device.reported_account_id:
        device.account = management_device.reported_account_id

    if management_device.ip_address:
        device.ip = management_device.ip_address
    if management_device.name:
        device.name = management_device.name
    if management_device.product_code:
        logger.debug(
            "Device %s reports product %s", device.id, management_device.product_code
        )

    return device


def _refresh_device_reachability(device: CombinedDevice) -> CombinedDevice:
    device.ssh_reachable = addr_port_is_reachable(device.ip, SSH_PORT, timeout=0.5)
    device.telnet_reachable = addr_port_is_reachable(
        device.ip, CLISERVER_PORT, timeout=0.5
    )
    device.reachable = device.ssh_reachable
    device.repair_available = device.marge_server != "Soundcork" and (
        device.ssh_reachable or device.telnet_reachable
    )
    return device


def _host_for_repair(
    combined_device: CombinedDevice | None,
    management_device: ManagementDevice | None,
) -> str | None:
    if management_device:
        if management_device.ip_address:
            return management_device.ip_address
        if management_device.stored_ip_address:
            return management_device.stored_ip_address
        if management_device.reported_ip_address:
            return management_device.reported_ip_address

    if combined_device:
        if combined_device.ip:
            return combined_device.ip
        if combined_device.st_device:
            return combined_device.st_device.Host

    return None


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
        management_devices = _management_devices_by_id(datastore)

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
            _apply_management_state(dev, management_devices.get(dev.id))
            _refresh_device_reachability(dev)

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
                client = SoundTouchClient(dev.st_device)
                try:
                    # sometimes a newly loaded device doesn't have its lang set yet
                    lang = client.GetLanguage()
                    lang_code = lang.Value
                    dev.language_code = lang_code
                except:
                    dev.language_code = "0"

        return templates.TemplateResponse(
            request=request,
            name="admin/admin_main.html",
            context={
                "accounts": accounts,
                "unassociated": unassociated_devices,
                "language_codes": LanguageCodes,
            },
        )

    @router.get("/admin/create_account")
    def create_acccount_form(request: Request):
        return templates.TemplateResponse(
            request=request, name="admin/create_account.html"
        )

    @router.post("/admin/switchToSoundcork/{device_id}")
    async def switch_device(device_id: str):
        logger.info(f"switch {device_id} to soundcork")
        management_devices = _management_devices_by_id(datastore)
        management_device = management_devices.get(device_id)
        combined_device = speakers.all_devices().get(device_id)
        hostname = _host_for_repair(combined_device, management_device)

        if hostname:
            ssh_reachable = addr_port_is_reachable(hostname, SSH_PORT)
            telnet_reachable = addr_port_is_reachable(hostname, CLISERVER_PORT)

            if ssh_reachable:
                success = override_speaker_config(hostname)
                reboot = reboot_speaker(hostname)
                logger.info(f"reboot {hostname} result {reboot}")
                if success:
                    speakers.clear_device(device_id)
            elif telnet_reachable:
                success = await override_speaker_config_non_rooted(hostname)
                logger.info(
                    f"override speaker config on {hostname} success = {success}"
                )
                if success:
                    speakers.clear_device(device_id)
            else:
                logger.warning(
                    "cannot switch %s to Soundcork: no SSH or CLIServer access",
                    device_id,
                )
        else:
            logger.warning("cannot switch %s to Soundcork: no host known", device_id)

        # wait a little for the speaker to restart
        time.sleep(10)
        return RedirectResponse(
            url=f"/admin/wait/{device_id}/0", status_code=HTTPStatus.FOUND
        )

    @router.get("/admin/wait/{device_id}/{elapsed}")
    async def wait_switch_device(request: Request, device_id: str, elapsed: int):
        logger.debug(f"checking for restart for {{device_id}}")
        # only wait up to 120 seconds
        if elapsed >= 120:
            return RedirectResponse(url=f"/admin/", status_code=HTTPStatus.FOUND)

        if elapsed == 0:
            # for the first request wait 40 seconds
            time.sleep(40)
            elapsed = 40

        combined_device = speakers.all_devices().get(device_id)
        if combined_device:
            st_device = combined_device.st_device
            if st_device:
                try:
                    # a freshly rebooted device might not have its lang available yet.
                    # in this case give it a little longer to load
                    client = SoundTouchClient(st_device)
                    lang = client.GetLanguage()
                    # if it's loadable then return to the admin page
                    return RedirectResponse(
                        url=f"/admin/", status_code=HTTPStatus.FOUND
                    )
                except:
                    pass

        return templates.TemplateResponse(
            request=request,
            name="admin/wait.html",
            context={"elapsed": elapsed, "device_id": device_id},
        )

    @router.post("/admin/addDevice/{device_id}")
    async def add_device_to_soundcork(device_id: str):
        logger.debug(f"add device {device_id} to soundcork")
        combined_device = speakers.all_devices().get(device_id)
        if combined_device:
            st_device = combined_device.st_device
            if st_device:
                hostname = st_device.Host
                success = add_device_by_ip(hostname, combined_device.reachable)
                logger.debug(f"added account from {hostname} success = {success}")

        return RedirectResponse(url=f"/admin/", status_code=HTTPStatus.FOUND)

    class AccountForm(BaseModel):
        account_id: str = Field(pattern=ACCOUNT_RE)
        account_name: str

    @router.post("/admin/addAccount")
    async def add_account(form: Annotated[AccountForm, Form()]):

        logger.info(
            f"adding new account '{form.account_name}' with id {form.account_id}"
        )

        success = datastore.create_account(form.account_id, form.account_name)
        logger.info(f"created account success={success}")
        datastore.save_configured_sources(
            form.account_id,
            default_sources(),
        )
        datastore.save_presets(form.account_id, "", [])
        datastore.save_recents(form.account_id, "", [])

        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    @router.post("/admin/{device_id}/setAccount")
    async def set_account(
        request: Request, device_id: str, account_id: Annotated[str, Form()]
    ):
        success = speakers.set_account(device_id, account_id)
        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    @router.get("/admin/edit_device/{device_id}")
    def edit_device_form(request: Request, device_id: str):
        return templates.TemplateResponse(
            request=request,
            name="admin/edit_device.html",
            context={"device_id": device_id},
        )

    @router.post("/admin/{device_id}/setName")
    async def set_name(
        device_id: str, name: Annotated[str, Form()], background_tasks: BackgroundTasks
    ):
        background_tasks.add_task(speakers.set_name, device_id, name)

        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    @router.post("/admin/{device_id}/setLanguage")
    async def set_language(device_id: str, language: Annotated[str, Form()]):
        await speakers.set_language(device_id, language)

        return RedirectResponse(url="/admin/", status_code=HTTPStatus.FOUND)

    return router
