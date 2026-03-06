import asyncio
import xml.etree.ElementTree as ET
from http import HTTPStatus
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Path, Query, Request, Response

from soundcork.constants import ACCOUNT_RE, DEVICE_RE, GROUP_RE
from soundcork.datastore import DataStore
from soundcork.marge import add_group, modify_group

# -- Router
router = APIRouter(tags=["service"])

# -- Bose box endpoints
BOSE_PORT = 8090
BOSE_ADDGROUP = "/addGroup"  # POST + XML
BOSE_UPDATEGROUP = "/updateGroup"  # POST + XML
BOSE_REMOVEGROUP = "/removeGroup"  # GET


def _xml_status(ok: bool, http_ok: int = 200, http_err: int = 500) -> Response:
    return Response(
        content=f"<status>{'GROUP_OK' if ok else 'GROUP_ERROR'}</status>",
        media_type="application/xml",
        status_code=http_ok if ok else http_err,
    )


class _BodyRequestShim:
    """Shim to reuse add/mod endpoints."""

    def __init__(self, body_bytes: bytes):
        self._body = body_bytes

    async def body(self) -> bytes:
        return self._body


async def _box_call(
    ip: str,
    method: str,
    path: str,
    xml_payload: Optional[str] = None,
    timeout: float = 4.0,
) -> tuple[int, str]:
    url = f"http://{ip}:{BOSE_PORT}{path}"
    headers = {"Accept": "*/*"}
    if xml_payload is not None:
        headers["Content-Type"] = "application/xml"

    async with httpx.AsyncClient(timeout=timeout) as client:
        m = method.upper()
        if m == "GET":
            r = await client.get(url, headers=headers)
        elif m == "POST":
            r = await client.post(
                url,
                headers=headers,
                content=(xml_payload.encode("utf-8") if xml_payload else None),
            )
        else:
            raise ValueError(f"Unsupported method {method}")
        return r.status_code, r.text


def _is_group_empty_xml(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "<group/>" in t.replace(" ", ""):
        return True
    try:
        root = ET.fromstring(t)
        return root.tag == "group" and len(list(root)) == 0
    except Exception:
        return False


def _extract_resp_text(resp_obj) -> str:
    body = getattr(resp_obj, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return body.decode("utf-8", errors="replace")
    if isinstance(resp_obj, str):
        return resp_obj
    return str(resp_obj)


def _build_group_payload_no_id(
    name: str,
    master_id: str,
    master_ip: str,
    slave_id: str,
    slave_ip: str,
) -> str:
    group = ET.Element("group")
    ET.SubElement(group, "name").text = name
    ET.SubElement(group, "masterDeviceId").text = master_id
    roles = ET.SubElement(group, "roles")

    gr1 = ET.SubElement(roles, "groupRole")
    ET.SubElement(gr1, "deviceId").text = master_id
    ET.SubElement(gr1, "role").text = "LEFT"
    ET.SubElement(gr1, "ipAddress").text = master_ip

    gr2 = ET.SubElement(roles, "groupRole")
    ET.SubElement(gr2, "deviceId").text = slave_id
    ET.SubElement(gr2, "role").text = "RIGHT"
    ET.SubElement(gr2, "ipAddress").text = slave_ip

    ET.SubElement(group, "senderIPAddress").text = master_ip
    return f'<?xml version="1.0" encoding="UTF-8" ?>{ET.tostring(group, encoding="unicode")}'


def _group_xml_by_id(datastore, account: str, groupid: str) -> str:
    devices_dir = datastore.account_devices_dir(account)
    fn = f"{devices_dir}/Group_{groupid}.xml"
    with open(fn, "r", encoding="utf-8") as f:
        return f.read()


def _group_id_by_name(datastore, account: str, name: str) -> Optional[str]:
    for gid in datastore.list_groups(account):
        try:
            xml = _group_xml_by_id(datastore, account, gid)
            root = ET.fromstring(xml.strip())
            nm = (root.findtext("name") or "").strip()
            if nm == name:
                return gid
        except Exception:
            continue
    return None


def _extract_group_ips(group_xml: str) -> list[str]:
    root = ET.fromstring(group_xml.strip())
    ips = []
    for gr in root.findall("./roles/groupRole"):
        ip = (gr.findtext("ipAddress") or "").strip()
        if ip:
            ips.append(ip)
    return list(dict.fromkeys(ips))


def _extract_master_device_id(group_xml: str) -> str:
    root = ET.fromstring(group_xml.strip())
    return (root.findtext("masterDeviceId") or "").strip()


def _extract_master_ip(group_xml: str) -> str:
    root = ET.fromstring(group_xml.strip())
    sender = (root.findtext("senderIPAddress") or "").strip()
    if sender:
        return sender
    ips = _extract_group_ips(group_xml)
    return ips[0] if ips else ""


# ----------------------------------------------------------------------
# Factory: creates router with access to datastore (Dependency Injection)
# ----------------------------------------------------------------------
def get_groups_service_router(datastore: DataStore):
    service = APIRouter(tags=["service"])
    from soundcork.main import bose_xml_str

    ################# service endpoints ##################################
    # ---------------- listgroups ----------------------------------------
    # list all groups and their devices
    # call as GET /service/account/{account}/listgroups
    # returns <groups>...</groups>
    @service.get("/service/account/{account}/listgroups", tags=["service"])
    async def service_listgroups(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
    ):
        # -- get group ids
        try:
            groups = datastore.list_groups(account)
        except Exception as e:
            return Response(
                f"<error>{e}</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # import os
        # import xml.etree.ElementTree as ET
        # from xml.sax.saxutils import escape as _x

        parts: list[str] = []
        parts.append('<?xml version="1.0" encoding="UTF-8"?>')
        parts.append("<groups>")

        # devices_dir = datastore.account_devices_dir(account)

        # -- iterate groups
        for group in groups:
            # group_file = os.path.join(devices_dir, f"Group_{gid}.xml")
            # try:
            #    tree = ET.parse(group_file)
            #    root = tree.getroot()
            # except Exception:
            #    continue

            gname = group.name or ""
            parts.append(f'  <group id="{group.id}">')
            if gname:
                parts.append(f"    <name>{gname}</name>")
            parts.append("    <devices>")

            # -- extract devices from groupRole elements
            # for role in root.findall(".//groupRole"):
            #     dev_id = role.findtext("deviceId") or ""
            #    dev_ip = role.findtext("ipAddress") or ""
            #    dev_role = role.findtext("role") or ""
            #    dev_name = ""

            # resolve device name via datastore
            #    if dev_id:
            #        try:
            #            info = datastore.get_device_info(account, dev_id)
            #            dev_name = info.name
            #            if not dev_ip:
            #                dev_ip = info.ip_address
            #        except Exception:
            #            pass

            #    parts.append(
            #        f'      <device id="{_x(dev_id)}" ip="{_x(dev_ip)}" role="{_x(dev_role)}">{_x(dev_name)}</device>'
            #    )
            parts.append(
                f'      <device id="{group.left_id}" ip="{group.left_ip}" role="LEFT"></device>'
            )
            parts.append(
                f'      <device id="{group.right_id}" ip="{group.right_ip}" role="RIGHT"></device>'
            )
            parts.append("    </devices>")
            parts.append("  </group>")
        parts.append("</groups>")
        xml = "\n".join(parts) + "\n"
        return Response(xml, media_type="application/xml", status_code=200)

    # ---------------- creategroup ----------------------------------------
    # create a stereo pair (=group)
    # call as GET /service/account/{account}/creategroup?master={device1}&slave={device2}
    # returns GROUP_OK or GROUP_ERROR
    @service.get("/service/account/{account}/creategroup", tags=["service"])
    async def service_creategroup(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        master: Annotated[str | None, Query()] = None,
        slave: Annotated[str | None, Query()] = None,
    ):
        # -- parameters
        master_id = (master or "").strip()
        slave_id = (slave or "").strip()
        if not master_id or not slave_id:
            return Response(
                "<error>Use ?master=...&slave=...</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # -- acquire IPs
        try:
            master_info = datastore.get_device_info(account, master_id)
            slave_info = datastore.get_device_info(account, slave_id)
        except Exception as e:
            return Response(
                f"<error>{e}</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        # -- build XML payload
        xml_no_id = _build_group_payload_no_id(
            name=f"{master_info.name} + {slave_info.name}",
            master_id=master_id,
            master_ip=master_info.ip_address,
            slave_id=slave_id,
            slave_ip=slave_info.ip_address,
        )
        # shim = _BodyRequestShim(xml_no_id.encode("utf-8"))
        from soundcork.main import bose_xml_str

        # -- create in datastore
        xml_with_id = bose_xml_str(
            add_group(datastore, account=account, group_info_xml=xml_no_id)
        )  # reuse
        # xml_with_id = _extract_resp_text(resp).strip()
        if "<error" in xml_with_id and "<group" not in xml_with_id:
            return Response(xml_with_id, media_type="application/xml", status_code=409)

        # -- submit to both boxes
        results = await asyncio.gather(
            _box_call(master_info.ip_address, "POST", BOSE_ADDGROUP, xml_with_id),
            _box_call(slave_info.ip_address, "POST", BOSE_ADDGROUP, xml_with_id),
            return_exceptions=True,
        )
        ok = True
        for r0 in results:
            if isinstance(r0, BaseException):
                ok = False
            else:
                status, text = r0
                if status != 200 or "GROUP_OK" not in text:
                    ok = False
        return _xml_status(ok)

    # ---------------- modgroup ----------------------------------------
    # rename a stereo pair (=group)
    # call as GET /service/account/{account}/modgroup?groupid={groupid}&newname={newname}
    #   or as PUT /service/account/{account}/modgroup?name={name}&newname={newname}
    # returns GROUP_OK or GROUP_ERROR
    @service.get("/service/account/{account}/modgroup", tags=["service"])
    async def service_modgroup(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        newname: Annotated[str | None, Query()] = None,
        groupid: Annotated[str | None, Query()] = None,
        name: Annotated[str | None, Query()] = None,
    ):
        # -- parameters
        newname = (newname or "").strip()
        groupid = (groupid or "").strip() or None
        name = (name or "").strip() or None
        # -- missing newname
        if not newname:
            return Response(
                "<error>Missing newname</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        # -- exactly one must be set
        if (groupid is None and name is None) or (
            groupid is not None and name is not None
        ):
            return Response(
                "<error>Use exactly one of groupid=... or name=...</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # -- acquire GroupService.xml
        if not groupid:
            groupid = _group_id_by_name(datastore, account, name or "")
            if not groupid:
                return Response(
                    "<error>Group name not found</error>",
                    media_type="application/xml",
                    status_code=404,
                )
        try:
            stored_xml = _group_xml_by_id(datastore, account, groupid)
            master_dev = _extract_master_device_id(stored_xml)
            ips = _extract_group_ips(stored_xml)
            if not master_dev:
                return Response(
                    "<error>Stored group has no masterDeviceId</error>",
                    media_type="application/xml",
                    status_code=500,
                )
            if len(ips) != 2:
                return Response(
                    "<error>Stored group must contain exactly two ipAddress entries</error>",
                    media_type="application/xml",
                    status_code=500,
                )
        except Exception as e:
            return Response(
                f"<error>{e}</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # -- build new XML payload
        g = ET.Element("group")
        ET.SubElement(g, "name").text = newname
        ET.SubElement(g, "masterDeviceId").text = master_dev
        mod_payload = f'<?xml version="1.0" encoding="UTF-8" ?>{ET.tostring(g, encoding="unicode")}'
        # shim = _BodyRequestShim(mod_payload.encode("utf-8"))
        updated_xml = bose_xml_str(
            modify_group(
                datastore=datastore,
                account=account,
                group_id=groupid,
                group_info_xml=mod_payload,
            )
        )  # reuse
        # updated_xml = _extract_resp_text(resp).strip()
        if "<error" in updated_xml and "<group" not in updated_xml:
            return Response(updated_xml, media_type="application/xml", status_code=409)

        # -- update both boxes
        results = await asyncio.gather(
            *(_box_call(ip, "POST", BOSE_UPDATEGROUP, updated_xml) for ip in ips),
            return_exceptions=True,
        )
        ok = True
        for r0 in results:
            if isinstance(r0, BaseException):
                ok = False
            else:
                status, _text = r0
                if status != 200:
                    ok = False
        return _xml_status(ok)

    # ---------------- removegroup ----------------------------------------
    # remove a stereo pair (=group)
    # call as GET /service/account/{account}/removegroup?groupid={groupid}
    #   or as GET /service/account/{account}/removegroup?name={name}
    # returns GROUP_OK or GROUP_ERROR
    @service.get("/service/account/{account}/removegroup", tags=["service"])
    async def service_removegroup(
        account: Annotated[str, Path(pattern=ACCOUNT_RE)],
        groupid: Annotated[str | None, Query()] = None,
        name: Annotated[str | None, Query()] = None,
    ):
        # -- parameters
        groupid = (groupid or "").strip() or None
        name = (name or "").strip() or None
        # -- exactly one must be set
        if (groupid is None and name is None) or (
            groupid is not None and name is not None
        ):
            return Response(
                "<error>Use exactly one of groupid=... or name=...</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        # -- resolve groupid from name if needed
        if groupid is None:
            groupid = _group_id_by_name(datastore, account, name or "")
            if not groupid:
                return Response(
                    "<error>Group name not found</error>",
                    media_type="application/xml",
                    status_code=404,
                )

        # -- acquire GroupService.xml
        try:
            stored_xml = _group_xml_by_id(datastore, account, groupid)
            master_ip = _extract_master_ip(stored_xml)
            if not master_ip:
                return Response(
                    "<error>Cannot determine master ip</error>",
                    media_type="application/xml",
                    status_code=500,
                )
        except Exception as e:
            return Response(
                f"<error>{e}</error>",
                media_type="application/xml",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # -- delete group at the box first
        try:
            status, text = await _box_call(master_ip, "GET", BOSE_REMOVEGROUP)
        except Exception as e:
            return Response(
                f"<error>removeGroup request failed: {e}</error>",
                media_type="application/xml",
                status_code=500,
            )

        if status != 200 or not _is_group_empty_xml(text):
            return Response(
                f"<error>removeGroup failed on {master_ip}: HTTP {status} {text}</error>",
                media_type="application/xml",
                status_code=500,
            )
        # -- only if successful delete also in datastore
        try:
            datastore.delete_group(account, groupid)
        except Exception as e:
            return Response(
                f"<error>Removed on box, but datastore delete failed: {e}</error>",
                media_type="application/xml",
                status_code=500,
            )
        return _xml_status(True)

    return service
