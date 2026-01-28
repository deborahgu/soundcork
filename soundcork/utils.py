import logging
import os
from urllib.parse import urlparse

import upnpclient
from telnetlib3 import Telnet

from soundcork.config import Settings
from soundcork.datastore import DataStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


datastore = DataStore()
settings = Settings()


def get_ssh_config() -> dict:
    return {
        "StrictHostKeyChecking": "accept-new",
        "HostkeyAlgorithms": "ssh-rsa,ssh-dss",
        "PreferredAuthentications": "password",
        "disabled_algorithms": {"pubkeys": []},
        "allow_agent": False,
    }


def send_file_to_speaker(filename: str, host: str, remote_path: str) -> None:
    """Place a file on the remote speaker."""
    raise NotImplementedError


def read_file_from_speaker_ssh(filename: str, host: str, remote_path: str) -> None:
    """Read a file from the remote speaker, using ssh."""
    raise NotImplementedError


def read_file_from_speaker_http(filename: str, host: str, remote_path: str) -> None:
    """Read a file from the remote speaker, using their HTTP API."""
    raise NotImplementedError


def get_bose_devices() -> list[upnpclient.upnp.Device]:
    """Return a list of all Bose SoundTouch UPnP devices on the network"""
    devices = upnpclient.discover()
    bose_devices = [d for d in devices if "Bose SoundTouch" in d.model_description]
    logger.info("Discovering upnp devices on the network")
    logger.info(
        f'Discovered Bose devices:\n- {"\n- ".join([b.friendly_name for b in bose_devices])}'
    )
    return bose_devices


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
