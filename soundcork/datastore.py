import logging
import xml.etree.ElementTree as ET
from os import path, walk

import upnpclient

from soundcork.config import Settings
from soundcork.constants import (
    DEVICE_INFO_FILE,
    DEVICES_DIR,
    PRESETS_FILE,
    RECENTS_FILE,
    SOURCES_FILE,
)
from soundcork.model import ConfiguredSource, DeviceInfo, Preset, Recent

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

    def account_dir(self, account: str) -> str:
        return path.join(settings.data_dir, account)

    def account_devices_dir(self, account: str) -> str:
        return path.join(settings.data_dir, account, DEVICES_DIR)

    def account_device_dir(self, account: str, device: str) -> str:
        return path.join(self.account_devices_dir(account), device)

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
            path.join(self.account_device_dir(account, device), DEVICE_INFO_FILE)
        )
        info_elem = stored_tree.getroot()
        # info_elem = root.find("info")
        device_id = info_elem.attrib.get("deviceID", "")
        name = info_elem.find("name").text
        type = info_elem.find("type").text
        module_type = info_elem.find("moduleType").text
        components = info_elem.find("components").findall("component")
        for component in components:
            component_category = component.find("componentCategory").text
            if component_category == "SCM":
                firmware_version = component.find("softwareVersion").text
                device_serial_number = component.find("serialNumber").text
            elif component_category == "PackagedProduct":
                product_serial_number = component.find("serialNumber").text
        for network_info in info_elem.findall("networkInfo"):
            if network_info.attrib.get("type", "") == "SCM":
                ip_address = network_info.find("ipAddress").text

        return DeviceInfo(
            device_id=device_id,
            product_code=f"{type} {module_type}",
            device_serial_number=str(device_serial_number),
            product_serial_number=str(product_serial_number),
            firmware_version=str(firmware_version),
            ip_address=str(ip_address),
            name=str(name),
        )

    def save_presets(self, account: str, device: str, presets_list: list[Preset]):
        save_file = path.join(self.account_dir(account), PRESETS_FILE)
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

    def get_presets(self, account: str, device: str) -> list[Preset]:
        storedTree = ET.parse(path.join(self.account_dir(account), PRESETS_FILE))
        root = storedTree.getroot()

        presets = []

        for preset in root.findall("preset"):
            id = preset.attrib["id"]
            created_on = preset.attrib.get("createdOn", "")
            updated_on = preset.attrib.get("updatedOn", "")
            content_item = preset.find("ContentItem")
            # If name is not present, the .text will correctly raise an error here
            name = content_item.find("itemName").text
            source = content_item.attrib["source"]
            type = content_item.attrib.get("type", "")
            location = content_item.attrib.get("location", "")
            source_account = content_item.attrib.get("sourceAccount", "")
            is_presetable = content_item.attrib.get("isPresetable", "")
            container_art_elem = content_item.find("containerArt")
            # have to 'is not None' because bool(Element) returns false
            # if the element has no children
            if container_art_elem is not None and container_art_elem.text:
                container_art = container_art_elem.text
            else:
                container_art = ""

            presets.append(
                Preset(
                    name=name,  # type: ignore
                    created_on=created_on,
                    updated_on=updated_on,
                    id=id,
                    source=source,
                    type=type,
                    location=location,
                    source_account=source_account,
                    is_presetable=is_presetable,
                    container_art=container_art,
                )
            )

        return presets

    def get_recents(self, account: str, device: str) -> list[Recent]:
        stored_tree = ET.parse(path.join(self.account_dir(account), RECENTS_FILE))
        root = stored_tree.getroot()

        recents = []

        for recent in root.findall("recent"):
            id = recent.attrib.get("id", "1")
            device_id = recent.attrib.get("deviceID", "")
            utc_time = recent.attrib.get("utcTime", "")
            content_item = recent.find("contentItem")
            name = content_item.find("itemName").text or "test"
            source = content_item.attrib.get("source", "")
            type = content_item.attrib.get("type", "")
            location = content_item.attrib.get("location", "")
            source_account = content_item.attrib.get("sourceAccount")
            is_presetable = content_item.attrib.get("isPresetable")
            container_art_elem = content_item.find("containerArt")
            if container_art_elem is not None:
                container_art = container_art_elem.text
            else:
                container_art = None

            recents.append(
                Recent(
                    name=name,
                    utc_time=utc_time,
                    id=id,
                    device_id=device_id,
                    source=source,
                    type=type,
                    location=location,
                    source_account=source_account,
                    is_presetable=is_presetable,
                    container_art=container_art,
                )
            )

        return recents

    def save_recents(
        self, account: str, device: str, recents_list: list[Recent]
    ) -> ET.Element:
        save_file = path.join(self.account_dir(account), RECENTS_FILE)
        recents_elem = ET.Element("recents")
        for recent in recents_list:
            recent_elem = ET.SubElement(recents_elem, "recent")
            recent_elem.attrib["deviceID"] = recent.device_id
            recent_elem.attrib["utcTime"] = recent.utc_time
            recent_elem.attrib["id"] = recent.id
            content_item_elem = ET.SubElement(recent_elem, "contentItem")
            if recent.source:
                content_item_elem.attrib["source"] = recent.source
            content_item_elem.attrib["type"] = recent.type
            content_item_elem.attrib["location"] = recent.location
            if recent.source_account:
                content_item_elem.attrib["sourceAccount"] = recent.source_account
            content_item_elem.attrib["isPresetable"] = recent.is_presetable or "true"
            ET.SubElement(content_item_elem, "itemName").text = recent.name
            ET.SubElement(content_item_elem, "containerArt").text = recent.container_art

        recents_tree = ET.ElementTree(recents_elem)
        ET.indent(recents_tree, space="    ", level=0)
        recents_tree.write(save_file, xml_declaration=True, encoding="UTF-8")
        return recents_elem

    def get_configured_sources(
        self, account: str, device: str
    ) -> list[ConfiguredSource]:
        sources_tree = ET.parse(path.join(self.account_dir(account), SOURCES_FILE))
        root = sources_tree.getroot()
        sources_list = []
        # TODO we should put ids in the Sources.xml file but if we don't then
        # this workaround is better than nothing
        last_id = 100001
        for source_elem in root.findall("source"):
            display_name = source_elem.attrib.get("displayName", "")
            # the id had to be hand-added to the xml; once we get it working we'll
            # see if we can use an artificially-generated value
            id = source_elem.attrib.get("id", "")
            if id == "":
                id = str(last_id)
                last_id += 1
            secret = source_elem.attrib.get("secret", "")
            secret_type = source_elem.attrib.get("secretType", "")
            source_key_elem = source_elem.find("sourceKey")
            source_key_account = source_key_elem.attrib.get("account", "")
            source_key_type = source_key_elem.attrib.get("type", "")
            sources_list.append(
                ConfiguredSource(
                    display_name=display_name,
                    id=id,
                    secret=secret,
                    secret_type=secret_type,
                    source_key_type=source_key_type,
                    source_key_account=source_key_account,
                )
            )

        return sources_list
