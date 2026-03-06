import asyncio
import xml.etree.ElementTree as ET
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response

from soundcork.constants import ACCOUNT_RE, DEVICE_RE, GROUP_RE
from soundcork.marge import add_group, get_device_group_xml, modify_group
from soundcork.model import BoseXMLResponse

# -- Router
router = APIRouter(tags=["marge"])

# -- Bose box endpoints
BOSE_PORT = 8090
BOSE_ADDGROUP = "/addGroup"  # POST + XML
BOSE_UPDATEGROUP = "/updateGroup"  # POST + XML
BOSE_REMOVEGROUP = "/removeGroup"  # GET


# ----------------------------------------------------------------------
# Factory: creates router with access to datastore (Dependency Injection)
# ----------------------------------------------------------------------
def get_groups_router(datastore):
    marge = APIRouter(tags=["marge"])

    from soundcork.main import bose_xml_str

    # ----------------- marge group endpoint to query group per device -----------------
    @marge.get(
        "/marge/streaming/account/{account}/device/{device}/group",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def device_group_status(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        device: Annotated[str, Path(pattern=DEVICE_RE)],
    ):

        result = get_device_group_xml(datastore, account, device)

        return bose_xml_str(result)

    # ----------------- marge group endpoint to add group  -----------------
    @marge.post(
        "/marge/streaming/account/{account}/group",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def add_group_endpoint(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        request: Request,
    ) -> str:

        reqxml_bytes = await request.body()
        reqxml_str = reqxml_bytes.decode("utf-8")

        result = add_group(datastore, account, reqxml_str)

        return bose_xml_str(result)

    # ----------------- marge group endpoint to modify group  -----------------
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
        try:
            body = await request.body()
            xml_str = body.decode("utf-8")
            result = modify_group(datastore, account, group, xml_str)

            return bose_xml_str(result)

        except ET.ParseError:
            response.status_code = HTTPStatus.BAD_REQUEST
            return ("<error>Invalid XML payload</error>",)
        except UnicodeDecodeError:
            response.status_code = HTTPStatus.BAD_REQUEST
            return "<error>Invalid UTF-8 in request body</error>"

    # ----------------- marge group endpoint to delete group  -----------------
    @marge.delete(
        "/marge/streaming/account/{account}/group/{group}",
        response_class=BoseXMLResponse,
        tags=["marge"],
    )
    async def delete_group_endpoint(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        group: Annotated[str, Path(pattern=GROUP_RE)],
    ):
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
