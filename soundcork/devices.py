"""Device management

Code to interact with Bose SoundTouch UPnP devices. In almost all cases,
these will be the physical SoundTouch speakers, running the SoundTouch
software on a BusyBox system.
"""

import logging
import urllib.request
import xml.etree.ElementTree as ET
from subprocess import run
from urllib.parse import urlparse

import upnpclient
from telnetlib3 import Telnet

from soundcork.config import Settings
from soundcork.constants import (
    SPEAKER_DEVICE_INFO_PATH,
    SPEAKER_HTTP_PORT,
    SPEAKER_PRESETS_PATH,
    SPEAKER_RECENTS_PATH,
    SPEAKER_SOURCES_FILE_LOCATION,
)
from soundcork.datastore import DataStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


datastore = DataStore()
settings = Settings()


SSH_ARGS = [
    "scp",
    "-O",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "HostkeyAlgorithms=+ssh-rsa,ssh-dss",
    "-o",
    "PreferredAuthentications=password",
]


def hostname_for_device(device: upnpclient.upnp.Device) -> str:
    """Given a UPnP device, return hostname/IP

    Raises AttributeError if there's something wrong with the Device object and
    it has no location.
    """
    return urlparse(device.location).hostname  # type: ignore


def read_recents(device: upnpclient.upnp.Device) -> str:
    return read_file_from_speaker_http(
        hostname_for_device(device), SPEAKER_RECENTS_PATH
    )


def read_device_info(device: upnpclient.upnp.Device) -> str:
    return read_file_from_speaker_http(
        hostname_for_device(device), SPEAKER_DEVICE_INFO_PATH
    )


def read_presets(device: upnpclient.upnp.Device) -> str:
    return read_file_from_speaker_http(
        hostname_for_device(device), SPEAKER_PRESETS_PATH
    )


def write_file_to_speaker(filename: str, host: str, remote_path: str) -> None:
    """Place a file on the remote speaker.

    Unfortunately, the speakers' shell (BusyBox) supports scp but not sftp, while
    all the Paramiko-based ssh libraries for Python (such as Fabric) only emulate scp over
    sftp. As a result, we need to subprocess call out to scp, which hopefully is present
    on the host system and hopefully uses a version with these arguments.
    """
    # TODO add timeout handling
    logger.debug(f"copying {filename} to {host}")
    result = run(
        SSH_ARGS + [filename, f"root@{host}:{remote_path}"], capture_output=True
    )
    if result.returncode:
        raise RuntimeError(
            f"something went wrong copying {filename} to {host}: {result.stderr}"
        )


def read_file_from_speaker_ssh(
    filename: str, host: str, remote_path: str, local_path: str
) -> None:
    """Read a file from the remote speaker, using ssh.

    Unfortunately, the speakers' shell (BusyBox) supports scp but not sftp, while
    all the Paramiko-based ssh libraries for Python (such as Fabric) only emulate scp over
    sftp. As a result, we need to subprocess call out to scp, which hopefully is present
    on the host system and hopefully uses a version with these arguments.
    """
    # TODO add timeout handling
    logger.debug(f"copying {filename} from {host}")
    result = run(
        SSH_ARGS + [f"root@{host}:{remote_path}", local_path], capture_output=True
    )
    if result.returncode:
        raise RuntimeError(
            f"something went wrong copying {filename} from {host}: {result.stderr}"
        )


def read_file_from_speaker_http(host: str, path: str) -> str:
    """Read a file from the remote speaker, using their HTTP API."""
    url = f"http://{host}:{SPEAKER_HTTP_PORT}{path}"
    logger.info(f"checking {url}")
    try:
        return str(urllib.request.urlopen(url).read(), "utf-8")
    except Exception:
        logger.info(f"no result for {url}")
        return "none"


def get_bose_devices() -> list[upnpclient.upnp.Device]:
    """Return a list of all Bose SoundTouch UPnP devices on the network"""
    devices = upnpclient.discover()
    bose_devices = [d for d in devices if "Bose SoundTouch" in d.model_description]
    logger.info("Discovering upnp devices on the network")
    logger.info(
        f'Discovered Bose devices:\n- {"\n- ".join([b.friendly_name for b in bose_devices])}'
    )
    return bose_devices


def get_device_by_id(device_id: str) -> upnpclient.upnp.Device:
    devices = get_bose_devices()
    for device in devices:
        try:
            info_elem = ET.fromstring(read_device_info(device))
            if info_elem.attrib.get("deviceID", "") == device_id:
                return device
        except:
            pass


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
    try:
        conn = Telnet(device_address)
    except ConnectionRefusedError:
        return False
    conn.close()
    return True


def add_device(device: upnpclient.upnp.Device) -> bool:
    info_elem = ET.fromstring(read_device_info(device))
    device_id = info_elem.attrib.get("deviceID", "")
    # If margeAccountUUID is not present, the .text will correctly raise an error here
    account_id = info_elem.find("margeAccountUUID").text  # type: ignore
    if not datastore.account_exists(account_id):  # type: ignore
        recents = read_recents(device)
        presets = read_presets(device)
        # TBD
        # sources = read_sources(device)
        sources = ""
        add_account(account_id, recents, presets, sources)  # type: ignore

    datastore.add_device(account_id, device_id, read_device_info(device))  # type: ignore
    return True


def add_account(account_id: str, recents: str, presets: str, sources: str) -> bool:
    if not datastore.create_account(account_id):
        return False
    datastore.save_presets_xml(account_id, presets)
    datastore.save_recents_xml(account_id, recents)
    datastore.save_configured_sources_xml(account_id, sources)

    return True
