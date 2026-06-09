"""Device management

Code to interact with Bose SoundTouch UPnP devices. In almost all cases,
these will be the physical SoundTouch speakers, running the SoundTouch
software on a BusyBox system.
"""

import asyncio
import logging
import socket
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO
from os import unlink
from subprocess import run
from typing import Optional
from urllib.parse import urlparse

import paramiko
import upnpclient  # type: ignore
from scp import SCPClient  # type: ignore
from telnetlib3 import TelnetReaderUnicode, TelnetWriterUnicode, open_connection

from soundcork.config import Settings
from soundcork.constants import (
    SPEAKER_DEVICE_INFO_PATH,
    SPEAKER_HTTP_PORT,
    SPEAKER_OVERRIDE_SDK_LOCATION,
    SPEAKER_PRESETS_PATH,
    SPEAKER_RECENTS_PATH,
    SPEAKER_SOURCES_FILE_LOCATION,
)
from soundcork.datastore import DataStore
from soundcork.model import ConfiguredSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


datastore = DataStore()
settings = Settings()


def hostname_for_device(device: upnpclient.upnp.Device) -> str:
    """Given a UPnP device, return hostname/IP

    Raises AttributeError if there's something wrong with the Device object and
    it has no location.
    """
    return urlparse(device.location).hostname  # type: ignore


def read_recents(hostname: str) -> str:
    return read_file_from_speaker_http(hostname, SPEAKER_RECENTS_PATH)


def read_device_info(hostname: str) -> str:
    return read_file_from_speaker_http(hostname, SPEAKER_DEVICE_INFO_PATH)


def read_presets(hostname: str) -> str:
    return read_file_from_speaker_http(hostname, SPEAKER_PRESETS_PATH)


def read_sources(hostname: str) -> str:
    sources_tmp_file = tempfile.NamedTemporaryFile(delete=False)
    read_file_from_speaker_ssh(
        host=hostname,
        remote_path=SPEAKER_SOURCES_FILE_LOCATION,
        local_path=sources_tmp_file.name,
    )
    sources = sources_tmp_file.read()
    sources_tmp_file.close()
    unlink(sources_tmp_file.name)
    return sources.decode()


def override_speaker_config(host: str) -> bool:
    bytesio = BytesIO()
    with open("resources/OverrideSdkPrivateCfg.xml.template", "r") as file:
        override_xml = file.read()
        override_xml = override_xml.replace("{SC_BASE_URL}", f"{settings.base_url}")
        bytesio.write(override_xml.encode())
        bytesio.seek(0)
    return write_file_to_speaker(bytesio, host, SPEAKER_OVERRIDE_SDK_LOCATION)


async def override_speaker_config_non_rooted(host: str) -> bool:
    logger.info("override speaker without root")
    reader, writer = await open_connection(host, 17000, encoding="utf-8")
    if isinstance(reader, TelnetReaderUnicode) and isinstance(
        writer, TelnetWriterUnicode
    ):
        # the telnet reader can read up to a certain number of characters
        # or until EOF, but in order to say "fill this buffer or return after
        # a timeout" you have to wrap it with asyncio.wait_for
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.write(
            f"sys configuration bmxRegistryUrl {settings.base_url}/bmx/registry/v1/services\r\n"
        )
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.write(f"sys configuration statsServerUrl {settings.base_url}\r\n")
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.write(f"sys configuration margeServerUrl {settings.base_url}/marge\r\n")
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.write(
            f"sys configuration swUpdateUrl {settings.base_url}/updates/soundtouch\r\n"
        )
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.write(
            f"envswitch boseurls set {settings.base_url}/marge {settings.base_url}/updates/soundtouch\r\n"
        )
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        # this isn't actually necessary but good to have in the logs
        writer.write("getpdo CurrentSystemConfiguration\r\n")
        reply = await asyncio.wait_for(reader.read(4096), timeout=2)
        logger.info(f"pdo for device: {reply}")
        writer.write("sys reboot\r\n")
        return True
    else:
        logger.warning("Error: telnet could not get UTF reader/writer")
        return False


def write_file_to_speaker(payload: BytesIO, host: str, remote_path: str) -> bool:

    # TODO add timeout handling
    logger.debug(f"copying {remote_path} to {host}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname=host, port=22, username="root", password="")

        with SCPClient(ssh.get_transport()) as scp:
            scp.putfo(payload, remote_path)
    except Exception as e:
        logger.info(f"Error: {e}")
        return False
    return True


def reboot_speaker(host: str) -> bool:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname=host, port=22, username="root", password="")
        ssh.exec_command("reboot")
        ssh.close()
        logger.debug(f"sent reboot to {host}")
        return True
    except:
        logger.info(f"error rebooting {host}")
        return False


def read_file_from_speaker_ssh(host: str, remote_path: str, local_path: str) -> None:
    """Read a file from the remote speaker, using ssh."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname=host, port=22, username="root", password="")

        with SCPClient(ssh.get_transport()) as scp:
            scp.get(remote_path, local_path)
    except Exception as e:
        logger.info(f"Error: {e}")


def read_file_from_speaker_http(host: str, path: str) -> str:
    """Read a file from the remote speaker, using their HTTP API."""
    url = f"http://{host}:{SPEAKER_HTTP_PORT}{path}"
    logger.info(f"checking {url}")
    try:
        return str(urllib.request.urlopen(url).read(), "utf-8")
    except Exception:
        logger.info(f"no result for {url}")
        return ""


def get_bose_devices() -> list[upnpclient.upnp.Device]:
    """Return a list of all Bose SoundTouch UPnP devices on the network"""
    devices = upnpclient.discover()
    bose_devices = [d for d in devices if "Bose SoundTouch" in d.model_description]
    logger.info("Discovering upnp devices on the network")
    logger.info(
        f'Discovered Bose devices:\n- {"\n- ".join([b.friendly_name for b in bose_devices])}'
    )
    return bose_devices


def get_device_by_id(device_id: str) -> Optional[upnpclient.upnp.Device]:
    devices = get_bose_devices()
    for device in devices:
        try:
            info_str = read_device_info(hostname_for_device(device))
            if info_str:
                info_elem = ET.fromstring(info_str)
                if info_elem.attrib.get("deviceID", "") == device_id:
                    return device
        except:
            pass
    return None


def show_upnp_devices() -> None:
    """Print a list of devices, specifying reachable ones."""
    devices = get_bose_devices()
    print(
        "Bose SoundTouch devices on your network. Devices currently "
        "configured to allow file copying (eg. that have been setup "
        "with a USB drive) are prefaced with `*`."
    )
    for d in devices:
        reachable = ""
        if is_reachable(d):
            reachable = "* "
        print(f"{reachable}{d.friendly_name}")


def is_reachable(device: upnpclient.upnp.Device) -> bool:
    """Returns true if device is reachable via telnet, ssh, etc."""
    device_address = urlparse(device.location).hostname
    return bool(device_address and addr_is_reachable(device_address))


def addr_port_is_reachable(device_address: str, port: int, timeout: int = 2) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((device_address, port))
        return True
    except:
        return False
    finally:
        s.close()


def addr_is_reachable(device_address: str) -> bool:
    return addr_port_is_reachable(device_address, 22)


def add_device(device: upnpclient.upnp.Device) -> bool:
    hostname = hostname_for_device(device)
    return add_device_by_ip(hostname)


def add_device_by_ip(hostname: str, reachable: bool = True) -> bool:
    logger.info(f"loading by ip, reachable={reachable}")
    info_elem = ET.fromstring(read_device_info(hostname))
    device_id = info_elem.attrib.get("deviceID", "")
    # If margeAccountUUID is not present, the .text will correctly raise an error here
    account_id = info_elem.find("margeAccountUUID").text  # type: ignore
    if account_id:
        if not datastore.account_exists(account_id):  # type: ignore
            recents = read_recents(hostname)
            presets = read_presets(hostname)
            if reachable:
                sources = read_sources(hostname)
            else:
                sources = default_sources_string()
            logger.info(f"sources={sources}")
            # FIXME get the account email address for this
            account_name = None
            add_account(account_id, recents, presets, sources, account_name)

        datastore.add_device(
            account_id,
            device_id,
            datastore.device_info_from_device_info_xml(
                ET.fromstring(read_device_info(hostname))
            ),
        )  # type: ignore
        return True
    return False


def add_account(
    account_id: str,
    recents: str,
    presets: str,
    sources: str,
    account_name: str | None = None,
) -> bool:
    if not datastore.create_account(account_id, label=account_name):
        return False
    datastore.save_presets_xml(account_id, presets)
    datastore.save_recents_xml(account_id, recents)
    datastore.save_configured_sources_xml(account_id, sources)

    return True


def default_sources() -> list[ConfiguredSource]:
    # this is a basic set of sources that all can be
    # used without a configured account
    now = datetime.fromtimestamp(datetime.now().timestamp(), timezone.utc).isoformat(
        timespec="milliseconds"
    )
    return [
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
            display_name="LOCAL_INTERNET RADIO",
            id="112347",
            secret="",
            secret_type="token",
            source_key_type="LOCAL_INTERNET_RADIO",
            source_key_account="",
            created_on=now,
            updated_on=now,
        ),
        ConfiguredSource(
            display_name="",
            id="112348",
            secret="",
            secret_type="token",
            source_key_type="TUNEIN",
            source_key_account="",
            created_on=now,
            updated_on=now,
        ),
    ]


def default_sources_string() -> str:
    sources_root = datastore.sources_to_xml(default_sources())
    ET.indent(sources_root, space="    ", level=0)
    return ET.tostring(sources_root, xml_declaration=True, encoding="UTF-8").decode()
