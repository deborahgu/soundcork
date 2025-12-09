import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from os import path, walk

import upnpclient

from soundcork.config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class DataStore:
    """The Soundcork datastore.

    - Creates the filesystem structure used for the server datastore
    - Creates, reads, and writes the XML files stored on device
    """

    def __init__(self) -> None:
        # def __init__(self, data_dir: str, settings: Settings) -> None:

        # self.data_dir = data_dir
        self.bose_devices: list[upnpclient.upnp.Device]
        logger.info("Initiating Datastore")

    def discover_devices(self) -> None:
        """Discovered upnp devices on the network

        Righ now this doesn't do anything except put discovered devices on self.bose_devices
        (see main.py for instantiation) to show how we'll put info on this datastore class.

        Discovered devices may well NOT end up as class properties, since this method
        will theoretically run very rarely and only on demand."""
        upnp_devices = upnpclient.discover()
        self.bose_devices = [
            d for d in upnp_devices if "Bose SoundTouch" in d.model_description
        ]
        logger.info("Discovering upnp devices on the network")
        logger.info(
            f'Discovered Bose devices:\n- {"\n- ".join([b.friendly_name for b in self.bose_devices])}'
        )
