import logging
import xml.etree.ElementTree as ET
from os import path, walk

import upnpclient

from soundcork.config import Settings
from soundcork.marge import account_device_dir
from soundcork.model import DeviceInfo, Preset

# pyright: reportOptionalMemberAccess=false

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()


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

    def get_device_info(self, account: str, device: str) -> DeviceInfo:
        """Get the device info"""
        stored_tree = ET.parse(
            path.join(account_device_dir(account, device), "PowerOn.xml")
        )
        root = stored_tree.getroot()
        device_elem = root.find("device")
        device_id = device_elem.attrib.get("id", "")
        device_serial_number = device_elem.find("serialnumber").text
        firmware_version = device_elem.find("firmware-version").text
        product_elem = device_elem.find("product")
        product_code = product_elem.attrib.get("product_code", "")
        product_serial_number = product_elem.find("serialnumber").text
        ip_address = (
            root.find("diagnostic-data")
            .find("device-landscape")
            .find("ip-address")
            .text
        )
        system_stored_tree = ET.parse(
            path.join(
                account_device_dir(account, device),
                "SystemConfigurationDB.xml",
            )
        )
        name = system_stored_tree.find("DeviceName").text

        return DeviceInfo(
            device_id=device_id,
            product_code=product_code,
            device_serial_number=str(device_serial_number),
            product_serial_number=str(product_serial_number),
            firmware_version=str(firmware_version),
            ip_address=str(ip_address),
            name=str(name),
        )

    def save_presets(self, account: str, device: str, presets_list: list[Preset]):
        save_file = path.join(account_device_dir(account, device), "Presets.xml")
        presets_elem = ET.Element("presets")
        for preset in presets_list:
            preset_elem = ET.SubElement(presets_elem, "preset")
            preset_elem.attrib["id"] = preset.id
            preset_elem.attrib["createdOn"] = preset.created_on
            preset_elem.attrib["updatedOn"] = preset.updated_on
            content_item_elem = ET.SubElement(preset_elem, "ContentItem")
            if preset.source:
                content_item_elem.attrib["source"] = preset.source
            content_item_elem.attrib["type"] = preset.type
            content_item_elem.attrib["location"] = preset.location
            if preset.source_account:
                content_item_elem.attrib["sourceAccount"] = preset.source_account
            content_item_elem.attrib["isPresetable"] = "true"
            ET.SubElement(content_item_elem, "itemName").text = preset.name
            ET.SubElement(content_item_elem, "containerArt").text = preset.container_art

        presets_tree = ET.ElementTree(presets_elem)
        ET.indent(presets_tree, space="    ", level=0)
        presets_tree.write(save_file, xml_declaration=True, encoding="UTF-8")
        return presets_elem
