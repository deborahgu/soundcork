"""
Handles group calls to the marge server.

Groups, in SoundTouch terminology, are ST10 devices (which are mono) paired
togeter to act as a single stereo device. If you don't have two ST10s then
you will likely never use Groups.
"""

import xml.etree.ElementTree as ET
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response

from soundcork.constants import ACCOUNT_RE, DEVICE_RE, GROUP_RE
from soundcork.marge import add_group, get_device_group_xml, modify_group
from soundcork.model import BoseXMLResponse

router = APIRouter(tags=["marge"])

BOSE_PORT = 8090
BOSE_ADDGROUP = "/addGroup"  # POST + XML
BOSE_UPDATEGROUP = "/updateGroup"  # POST + XML
BOSE_REMOVEGROUP = "/removeGroup"  # GET


def _bose_xml_str(xml: ET.Element) -> str:
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{ET.tostring(xml, encoding="unicode")}'


# ----------------------------------------------------------------------
# Factory: creates router with access to datastore (Dependency Injection)
# ----------------------------------------------------------------------
def get_groups_router(datastore):
    marge = APIRouter(tags=["marge"])

    @marge.get(
        "/marge/streaming/account/{account}/groups",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def account_groups(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    ):
        """marge group endpoint to list all groups for an account"""

        groups_elem = ET.Element("groups")
        for group in datastore.list_groups(account):
            groups_elem.append(datastore.group_to_xml(group))

        return _bose_xml_str(groups_elem)

    @marge.get(
        "/marge/streaming/account/{account}/device/{device}/group/",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    @marge.get(
        "/marge/streaming/account/{account}/device/{device}/group",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def device_group_status(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        device: Annotated[str, Path(pattern=DEVICE_RE)],
    ):
        """marge group endpoint to query group per device"""

        result = get_device_group_xml(datastore, account, device)

        return _bose_xml_str(result)

    @marge.post(
        "/marge/streaming/account/{account}/group/",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    @marge.post(
        "/marge/streaming/account/{account}/group",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def add_group_endpoint(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        request: Request,
        response: Response,
    ) -> str:

        reqxml_bytes = await request.body()
        reqxml_str = reqxml_bytes.decode("utf-8")

        result = add_group(datastore, account, reqxml_str)
        response.status_code = HTTPStatus.CREATED
        group_id = result.get("id")
        if group_id:
            base_url = str(request.base_url).rstrip("/")
            response.headers["Location"] = (
                f"{base_url}/marge/streaming/account/{account}/group/{group_id}"
            )

        return _bose_xml_str(result)

    @marge.put(
        "/marge/streaming/account/{account}/group/{group}",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    @marge.post(
        "/marge/streaming/account/{account}/group/{group}",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def mod_group_endpoint(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        group: Annotated[str, Path(pattern=GROUP_RE)],
        request: Request,
        response: Response,
    ):
        """marge group endpoint to add group"""
        try:
            body = await request.body()
            xml_str = body.decode("utf-8")
            result = modify_group(datastore, account, group, xml_str)

            return _bose_xml_str(result)

        except ET.ParseError:
            response.status_code = HTTPStatus.BAD_REQUEST
            return ("<error>Invalid XML payload</error>",)
        except UnicodeDecodeError:
            response.status_code = HTTPStatus.BAD_REQUEST
            return "<error>Invalid UTF-8 in request body</error>"

    @marge.delete(
        "/marge/streaming/account/{account}/group/",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def delete_account_groups_endpoint(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    ):
        """marge group endpoint to delete all account groups"""
        try:
            error = datastore.delete_all_groups(account)
            if error:
                return BoseXMLResponse(
                    content=f"<error>{error}</error>",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            return BoseXMLResponse(
                content="<status>Groups deleted successfully</status>"
            )
        except Exception as e:
            return BoseXMLResponse(
                content=f"<error>Unexpected error: {e}</error>", status_code=500
            )

    @marge.delete(
        "/marge/streaming/account/{account}/group/{group}",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def delete_group_endpoint(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        group: Annotated[str, Path(pattern=GROUP_RE)],
    ):
        """marge group endpoint to delete group"""
        if not datastore.account_exists(account):
            return BoseXMLResponse(
                content=f"<error>Account {account} not found</error>",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            error = datastore.delete_group(account, group)
            if error:
                return BoseXMLResponse(
                    content=f"<error>{error}</error>",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            return BoseXMLResponse(
                content=f"<status>Group {group} deleted successfully</status>"
            )
        except Exception as e:
            return BoseXMLResponse(
                content=f"<error>Unexpected error: {e}</error>", status_code=500
            )

    return marge
