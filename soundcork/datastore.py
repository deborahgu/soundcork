import logging
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http import HTTPStatus
from os import listdir, mkdir, path, remove, rmdir, walk
from random import randint
from typing import Optional

from fastapi import HTTPException

from soundcork.config import Settings
from soundcork.constants import (
    DEFAULT_DATESTR,
    DEVICE_INFO_FILE,
    DEVICES_DIR,
    POWERON_FILE,
    PRESETS_FILE,
    RECENTS_FILE,
    SOURCES_FILE,
)
from soundcork.model import ConfiguredSource, DeviceInfo, Group, Preset, Recent
from soundcork.utils import strip_element_text

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
        logger.info("Initiating Datastore")
        self.data_dir = settings.data_dir

    def poweron_devices_dir(self) -> str:
        """returns the top-level directory that stores poweron info for all devices"""
        pdd = path.join(self.data_dir, DEVICES_DIR)
        if not path.exists(pdd):
            mkdir(pdd)
        return pdd

    def poweron_device_dir(self, device_id: str) -> str:
        """returns the directory that stores the poweron file for the given device"""
        return path.join(self.poweron_devices_dir(), device_id)

    def account_dir(self, account: str, create: bool = False) -> str:
        dir = path.join(self.data_dir, account)
        if not path.exists(dir) and not create:
            raise HTTPException(HTTPStatus.NOT_FOUND, f"Account {account} not found")
        return dir

    def account_devices_dir(self, account: str) -> str:
        """Returns the directory holding an account's devices.

        Unlike the top-level (generic) devices directory, this is for devices
        associated with an account.
        """
        return path.join(self.data_dir, account, DEVICES_DIR)

    def account_device_dir(self, account: str, device: str) -> str:
        """Returns the directory holding an account's files for a given device."""
        dir = path.join(self.account_devices_dir(account), device)
        if not path.exists(dir):
            raise HTTPException(
                HTTPStatus.NOT_FOUND,
                f"Device {device} does not belong to account {account}",
            )
        return dir

    def get_device_info(self, account: str, device: str) -> DeviceInfo:
        """Gets definition of a Device associated with an Account"""

        stored_tree = ET.parse(
            path.join(self.account_device_dir(account, device), DEVICE_INFO_FILE)
        )
        info_elem = stored_tree.getroot()
        return self.device_info_from_device_info_xml(info_elem)

    def save_device_info(self, device: DeviceInfo, account: str) -> DeviceInfo:
        """Saves definition of a Device associated with an Account"""
        device.updated_on = datetime.fromtimestamp(
            int(datetime.now().timestamp()), timezone.utc
        ).isoformat(timespec="milliseconds")
        if not device.created_on:
            device.created_on = device.updated_on

        save_file = path.join(
            self.account_device_dir(account, device.device_id), DEVICE_INFO_FILE
        )
        info_elem = ET.Element("info")
        info_elem.attrib["deviceID"] = device.device_id
        ET.SubElement(info_elem, "name").text = device.name
        ET.SubElement(info_elem, "type").text = device.product_code
        components_elem = ET.SubElement(info_elem, "components")
        scm_elem = ET.SubElement(components_elem, "component")
        ET.SubElement(scm_elem, "componentCategory").text = "SCM"
        ET.SubElement(scm_elem, "softwareVersion").text = device.firmware_version
        ET.SubElement(scm_elem, "serialNumber").text = device.device_serial_number
        product_elem = ET.SubElement(components_elem, "component")
        ET.SubElement(product_elem, "componentCategory").text = "PackagedProduct"
        ET.SubElement(product_elem, "serialNumber").text = device.product_serial_number
        network_elem = ET.SubElement(info_elem, "networkInfo")
        network_elem.attrib["type"] = "SCM"
        ET.SubElement(network_elem, "macAddress").text = device.device_id
        ET.SubElement(network_elem, "ipAddress").text = device.ip_address
        ET.SubElement(info_elem, "createdOn").text = device.created_on
        ET.SubElement(info_elem, "updatedOn").text = device.updated_on

        info_tree = ET.ElementTree(info_elem)
        ET.indent(info_tree, space="    ", level=0)
        info_tree.write(save_file, xml_declaration=True, encoding="UTF-8")

        return self.get_device_info(account, device.device_id)

    def save_presets(self, account: str, device: str, presets_list: list[Preset]):
        """Saves Presets for a Device associated with an Account"""
        save_file = path.join(self.account_dir(account), PRESETS_FILE)
        presets_elem = ET.Element("presets")
        presets_list.sort(key=lambda preset: int(preset.id))
        for preset in presets_list:
            preset_elem = ET.SubElement(presets_elem, "preset")
            preset_elem.attrib["id"] = preset.id
            preset_elem.attrib["createdOn"] = preset.created_on or ""
            preset_elem.attrib["updatedOn"] = preset.updated_on or ""
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

    # TODO: add error handling if you can't write the file
    def save_presets_xml(self, account: str, presets_xml: str):
        """Write Presets.xml for an Account"""
        with open(
            path.join(self.account_dir(account), PRESETS_FILE), "w"
        ) as presets_file:
            presets_file.write(presets_xml)

    def get_presets(self, account: str, device: str) -> list[Preset]:
        """Gets Presets for a Device associated with an Account"""
        storedTree = ET.parse(path.join(self.account_dir(account), PRESETS_FILE))
        root = storedTree.getroot()

        presets = []

        for preset in root.findall("preset"):
            id = preset.attrib["id"]
            created_on = preset.attrib.get("createdOn", "")
            updated_on = preset.attrib.get("updatedOn", "")
            content_item = preset.find("ContentItem")
            # If name is not present, the .text will correctly raise an error here
            name = content_item.find("itemName").text  # type: ignore
            source = content_item.attrib["source"]  # type: ignore
            type = content_item.attrib.get("type", "")  # type: ignore
            location = content_item.attrib.get("location", "")  # type: ignore
            source_account = content_item.attrib.get("sourceAccount", "")  # type: ignore
            is_presetable = content_item.attrib.get("isPresetable", "")  # type: ignore
            container_art_elem = content_item.find("containerArt")  # type: ignore
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
        """Gets Recents for a Device associated with an Account"""
        stored_tree = ET.parse(path.join(self.account_dir(account), RECENTS_FILE))
        root = stored_tree.getroot()

        recents = []

        for recent in root.findall("recent"):
            id = recent.attrib.get("id", "1")
            device_id = recent.attrib.get("deviceID", "")
            utc_time = recent.attrib.get("utcTime", "")
            # if contentItem is not present, the .find will correctly raise an error here
            content_item = recent.find("contentItem")
            name = content_item.find("itemName").text or "test"  # type: ignore
            source = content_item.attrib.get("source", "")  # type: ignore
            type = content_item.attrib.get("type", "")  # type: ignore
            location = content_item.attrib.get("location", "")  # type: ignore
            source_account = content_item.attrib.get("sourceAccount")  # type: ignore
            is_presetable = content_item.attrib.get("isPresetable")  # type: ignore
            container_art_elem = content_item.find("containerArt")  # type: ignore
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

    # TODO: add error handling if you can't write the file
    def save_recents_xml(self, account: str, recents_xml: str):
        """Write Recents.xml for an Account"""
        with open(
            path.join(self.account_dir(account), RECENTS_FILE), "w"
        ) as recents_file:
            recents_file.write(recents_xml)

    def get_configured_sources(
        self, account: str, device: str = ""
    ) -> list[ConfiguredSource]:
        """Get known Sources for a Device associated with an Account"""
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
            created_on = strip_element_text(source_elem.find("createdOn"))
            updated_on = strip_element_text(source_elem.find("updatedOn"))

            # if sourceKey is not present, the .find will correctly raise an error here
            source_key_elem = source_elem.find("sourceKey")
            source_key_account = source_key_elem.attrib.get("account", "")  # type: ignore
            source_key_type = source_key_elem.attrib.get("type", "")  # type: ignore
            sources_list.append(
                ConfiguredSource(
                    display_name=display_name,
                    id=id,
                    secret=secret,
                    secret_type=secret_type,
                    source_key_type=source_key_type,
                    source_key_account=source_key_account,
                    created_on=created_on,
                    updated_on=updated_on,
                )
            )

        return sources_list

    def add_source(
        self, account: str, new_source: ConfiguredSource
    ) -> ConfiguredSource:
        """Adds a source to the source list.

        Returns:
        - the newly created ConfiguredSource, including fields like id and updated
        """
        now = datetime.fromtimestamp(
            datetime.now().timestamp(), timezone.utc
        ).isoformat(timespec="milliseconds")
        all_sources = self.get_configured_sources(account)
        max_source = max(all_sources, key=lambda x: int(x.id))
        new_source.id = str(int(max_source.id) + randint(1, 100))
        new_source.updated_on = now
        new_source.created_on = now

        all_sources.append(new_source)
        self.save_configured_sources(account, all_sources)

        return new_source

    def save_configured_sources(
        self, account: str, sources_list: list[ConfiguredSource]
    ) -> ET.Element:
        save_file = path.join(self.account_dir(account), SOURCES_FILE)
        sources_root = ET.Element("sources")
        for source in sources_list:
            source_elem = ET.SubElement(sources_root, "source")
            source_elem.attrib["id"] = source.id
            source_elem.attrib["displayName"] = source.display_name
            source_elem.attrib["secret"] = source.secret
            source_elem.attrib["secretType"] = source.secret_type
            key_elem = ET.SubElement(source_elem, "sourceKey")
            key_elem.attrib["type"] = source.source_key_type
            key_elem.attrib["account"] = source.source_key_account
            ET.SubElement(source_elem, "createdOn").text = source.created_on
            ET.SubElement(source_elem, "updatedOn").text = source.updated_on
        sources_tree = ET.ElementTree(sources_root)
        ET.indent(sources_tree, space="    ", level=0)
        sources_tree.write(save_file, xml_declaration=True, encoding="UTF-8")
        return sources_root

    def remove_source(self, account: str, source_id: str) -> bool:
        all_sources = self.get_configured_sources(account)
        match = None
        for source in all_sources:
            if source.id == source_id:
                logger.info("found source")
                match = source
                break
        if match:
            all_sources.remove(match)
            self.save_configured_sources(account, all_sources)
            return True
        return False

    # TODO: add error handling if you can't write the file
    def save_configured_sources_xml(self, account: str, sources_xml: str):
        """Write Sources.xml for an Account"""
        with open(
            path.join(self.account_dir(account), SOURCES_FILE), "w"
        ) as sources_file:
            sources_file.write(sources_xml)

    def find_device(self, device_id: str) -> tuple[DeviceInfo | None, str | None]:
        """Looks for Device in datastore.

        Given a device_id, looks for it
        1. first, if associated with an account
        2. if not, then as a device that's ever been powered on

        Returns:
            A tuple of the DeviceInfo object, if found, with the Account ID,
            if it exists.
        """
        for account_id in self.list_accounts():
            if account_id:
                for id in self.list_devices(account_id):
                    if id == device_id:
                        return self.get_device_info(account_id, id), account_id
        for id in self.list_poweron_devices():
            if id == device_id:
                return self.get_poweron_device_info(id), None

        return None, None

    def get_poweron_device_info(self, device: str) -> DeviceInfo:
        """Return info about a Device that's been powered on at least once."""
        poweron_elem = ET.parse(
            path.join(self.poweron_device_dir(device), POWERON_FILE)
        ).getroot()
        return self.device_info_from_poweron_xml(poweron_elem)

    def save_poweron(self, device_id: str, poweron_xml: str):
        """Writes Device information for a newly discovered device

        Records Device infomation for a Device that's been powered on, if it
        doesn't already exist in the directory.
        """
        device_dir = self.poweron_device_dir(device_id)
        if not path.exists(device_dir):
            mkdir(device_dir)

        with open(
            path.join(device_dir, POWERON_FILE),
            "w",
        ) as poweron_file:
            poweron_file.write(poweron_xml)

    def device_info_from_poweron_xml(self, poweron_elem: ET.Element) -> DeviceInfo:
        """Creates a DeviceInfo object

        Args:
        - poweron_elem (ET.Element): deserialized XML element from the poweron device XML

        Returns:
        - DeviceInfo:  DeviceInfo built from the poweron XML
        """
        device_elem = poweron_elem.find("device")
        if device_elem != None:
            device_id = device_elem.attrib.get("id", "")
            device_serial_number = strip_element_text(device_elem.find("serialnumber"))
            firmware_version = strip_element_text(device_elem.find("firmware-version"))
            product_elem = device_elem.find("product")
            if product_elem != None:
                product_code = product_elem.attrib.get("product_code", "")
                product_type = product_elem.attrib.get("type", "")
                product_serial_number = strip_element_text(
                    product_elem.find("serialnumber")
                )
        diagnostic_elem = poweron_elem.find("diagnostic-data")
        if diagnostic_elem != None:
            landscape_elem = diagnostic_elem.find("device-landscape")
            if landscape_elem != None:
                ip_address = strip_element_text(landscape_elem.find("ip-address"))

        return DeviceInfo(
            device_id=device_id,
            product_code=product_code,
            device_serial_number=device_serial_number,
            product_serial_number=str(product_serial_number),
            firmware_version=str(firmware_version),
            ip_address=str(ip_address),
            name="",
            created_on="",
            updated_on="",
        )

    def device_info_from_device_info_xml(self, info_elem: ET.Element) -> DeviceInfo:
        """
        converts a DeviceInfo.xml formatted element into a DeviceInfo object.
        usually sourced either from {account}/devices/{deviceid}/DeviceInfo.xml
        or from http://{deviceip}:8090/info
        """
        device_id = info_elem.attrib.get("deviceID", "")
        name = strip_element_text(info_elem.find("name"))
        type = strip_element_text(info_elem.find("type"))
        module_type = strip_element_text(info_elem.find("moduleType"))

        try:
            components = info_elem.find("components").findall("component")  # type: ignore
        except Exception:
            # TODO narrow exception class
            components = []

        for component in components:
            component_category = strip_element_text(component.find("componentCategory"))
            if component_category == "SCM":
                firmware_version = strip_element_text(component.find("softwareVersion"))
                device_serial_number = strip_element_text(
                    component.find("serialNumber")
                )
            elif component_category == "PackagedProduct":
                product_serial_number = strip_element_text(
                    component.find("serialNumber")
                )

        try:
            for network_info in info_elem.findall("networkInfo"):
                if network_info.attrib.get("type", "") == "SCM":
                    ip_address = strip_element_text(network_info.find("ipAddress"))
        except Exception:
            # TODO narrow exception class
            ip_address = ""

        created_on = strip_element_text(info_elem.find("createdOn"))
        if not created_on:
            created_on = DEFAULT_DATESTR
        updated_on = strip_element_text(info_elem.find("updatedOn"))
        if not updated_on:
            updated_on = created_on

        try:
            return DeviceInfo(
                device_id=device_id,
                product_code=f"{type} {module_type}",
                device_serial_number=str(device_serial_number),
                product_serial_number=str(product_serial_number),
                firmware_version=str(firmware_version),
                ip_address=str(ip_address),
                name=str(name),
                created_on=created_on,
                updated_on=updated_on,
            )
        except NameError:
            raise RuntimeError(
                f"There are missing required fields in the device: {device_id}"
            )

    #########
    # ETags #
    #########

    def etag_for_presets(self, account: str) -> int:
        """Returns an etag for the Presets.xml file for a given account"""
        presets_file = path.join(self.account_dir(account), PRESETS_FILE)
        if path.exists(presets_file):
            return int(path.getmtime(presets_file) * 1000)
        else:
            return 0

    def etag_for_sources(self, account: str) -> int:
        """Returns an etag for the Sources.xml file for a given account"""
        sources_file = path.join(self.account_dir(account), SOURCES_FILE)
        if path.exists(sources_file):
            return int(path.getmtime(sources_file) * 1000)
        else:
            return 0

    def etag_for_recents(self, account: str) -> int:
        """Returns an etag for the Recents.xml file for a given account"""
        recents_file = path.join(self.account_dir(account), RECENTS_FILE)
        if path.exists(recents_file):
            return int(path.getmtime(recents_file) * 1000)
        else:
            return 0

    def etag_for_account(self, account: str) -> int:
        """Returns an etag for a given account"""
        return max(
            self.etag_for_presets(account),
            self.etag_for_sources(account),
            self.etag_for_recents(account),
        )

    ##################
    # create account #
    ##################

    def list_accounts(self) -> list[Optional[str]]:
        """Returns a list of accounts that have been created in the datastore.

        If no accounts have been created, returns an empty list.
        """
        accounts: list[str | None] = []
        for account_id in next(walk(self.data_dir))[1]:
            # Check if the ID is digits to distinguish between accounts and power_on devices.
            if account_id.isdigit():
                accounts.append(account_id)

        return accounts

    def list_devices(self, account_id) -> list[Optional[str]]:
        """Returns a list of devices associated with an account.

        If the account has no devices, returns an empty list.
        """
        devices: list[str | None] = []
        for device_id in next(walk(self.account_devices_dir(account_id)))[1]:
            devices.append(device_id)

        return devices

    def list_poweron_devices(self) -> list[str]:
        """List all devices Soundcork has seen power on

        Returns:
        - List[device_ids: str]: IDs for every device Soundcork has seen
        """
        devices: list[str] = []
        for device_id in next(walk(self.poweron_devices_dir()))[1]:
            devices.append(device_id)

        return devices

    def account_exists(self, account: str) -> bool:
        """Returns true if account exists in the datastore."""
        return account in self.list_accounts()

    def device_exists(self, account: str, device_id: str) -> bool:
        """Returns true if device exists for a given account in the datastore."""
        return device_id in self.list_devices(account)

    def create_account(self, account: str) -> bool:
        """Creates an account folder in the datastore.

        Returns:
        - True if account was successfully created
        - False if account already exists
        """
        logger.info(f"creating account {account}")
        if self.account_exists(account):
            return False

        # TODO: add error handling if you can't make the directory
        mkdir(self.account_dir(account, True))
        mkdir(self.account_devices_dir(account))
        # create devices subdirectory
        return True

    def add_device(
        self, account: str, device_id: str, device: DeviceInfo
    ) -> DeviceInfo | None:
        """Adds a device to a given account in the datastore.

        Returns:
        - True if device was successfully added
        - False if device already exists for the account
        """
        if self.device_exists(account, device_id):
            return None

        # TODO: add error handling if you can't make the directory
        mkdir(path.join(self.account_devices_dir(account), device_id))

        return self.save_device_info(device, account)

    def remove_device(self, account: str, device_id: str) -> bool:
        """Removes a device from a given account in the datastore.

        Returns:
        - True if device was successfully removed
        - False if device does not exist for the account
        """
        logger.debug(f"removing device {device_id} from account {account}")
        if not self.device_exists(account, device_id):
            return False

        # TODO: add error handling if you can't delete the files
        remove(path.join(self.account_device_dir(account, device_id), DEVICE_INFO_FILE))
        rmdir(path.join(self.account_devices_dir(account), device_id))
        return True

    ############################################################################
    # groups                                                                   #
    #                                                                          #
    # A Group is two devices that have been paired together to play in stereo. #
    ############################################################################

    def _generate_group_id(self, account: str) -> str:
        """Helper function to create a unique group_id"""
        while True:
            group_id = f"{random.randint(0, 9999999):07d}"
            filepath = path.join(
                self.account_devices_dir(account), f"Group_{group_id}.xml"
            )
            if not path.exists(filepath):
                return group_id

    def list_groups(self, account: str) -> list[Group]:
        """list all existing groups"""
        devices_dir = self.account_devices_dir(account)
        groups = []
        for fn in listdir(devices_dir):
            if fn.startswith("Group_") and fn.endswith(".xml"):
                group = self.get_group(account, fn)
                if group:
                    groups.append(group)
        return groups

    def group_exists(self, account: str, group_id: str) -> bool:
        """check if a group with given id exist"""
        return path.exists(
            path.join(self.account_devices_dir(account), f"Group_{group_id}.xml")
        )

    def device_is_groupable(self, device_info: DeviceInfo) -> bool:
        return device_info.product_code == "SoundTouch 10"

    def add_group(self, account: str, group: Group) -> ET.Element:
        """adds a group

        Adds group if a.) both devices exist, b.) both are ST10
        Returns:
        - XML string of created group on success
        - raises exception on failure
        """

        group_id = self._generate_group_id(account)
        group.id = group_id
        device_ids = [group.left_id, group.right_id]
        # -- are these already grouped?
        for dev_id in device_ids:
            existing_group = self.group_for_device(account, dev_id)
            if existing_group:
                raise HTTPException(
                    HTTPStatus.BAD_REQUEST,
                    f"Device {dev_id} is already part of group {existing_group.id}",
                )

        # Only ST10 devices can be grouped
        for dev_id in device_ids:
            device_info = self.get_device_info(account, dev_id)
            if not device_info:
                raise HTTPException(
                    HTTPStatus.BAD_REQUEST, f"Device {dev_id} does not exist"
                )
            if not self.device_is_groupable(device_info):
                raise HTTPException(
                    HTTPStatus.BAD_REQUEST,
                    f"Device {dev_id} is not of type 'SoundTouch 10'",
                )

        return self.save_group(account, group_id, group)

    def save_group(self, account: str, group_id: str, group: Group) -> ET.Element:
        """Saves a group to the account in the datastore

        Overwrite if it already exists.
        """

        filename = f"Group_{group_id}.xml"
        filepath = path.join(self.account_devices_dir(account), filename)
        group_xml = self.group_to_xml(group)

        ET.indent(group_xml, space="    ", level=0)
        ET.ElementTree(group_xml).write(
            filepath, xml_declaration=True, encoding="UTF-8"
        )
        return group_xml

    def get_group(self, account: str, group_id: str) -> Group | None:
        """Gets a group from the account files in the datastore"""
        filename = f"Group_{group_id}.xml"
        filepath = path.join(self.account_devices_dir(account), filename)
        if path.exists(filepath):
            stored_tree = ET.parse(filepath)
            info_elem = stored_tree.getroot()
            return self.group_from_xml(group_id, info_elem)
        else:
            return None

    def delete_group(self, account: str, group_id: str) -> str:
        """
        deletes a group if it exists.

        Returns:
        - Empty string on success
        - raises exception if group doesn't exist or if there's an error deleting the file
        """
        filename = f"Group_{group_id}.xml"
        filepath = path.join(self.account_devices_dir(account), filename)

        if not path.exists(filepath):
            raise HTTPException(
                HTTPStatus.NOT_FOUND,
                f"Group {group_id} does not exist in account {account}",
            )

        try:
            remove(filepath)
        except Exception as e:
            raise HTTPException(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"Failed to delete group {group_id}: {e}",
            )

        return ""

    def group_for_device(self, account: str, device_id: str) -> Group | None:
        """
        check group status of a device

        Returns:
        - XML <group/> if ungrouped
        - XML file of group if grouped
        - error if device does not exist or is not ST10
        """
        device_info = self.get_device_info(account, device_id)
        if not device_info:
            return None

        if not self.device_is_groupable(device_info):
            return None

        all_groups = self.list_groups(account)
        for g in all_groups:
            if g.left_id == device_id or g.right_id == device_id:
                return g
        return None

    def group_to_xml(self, group: Group) -> ET.Element:
        """Converts a Group object to an XML element for storage."""
        group_elem = ET.Element("group")
        ET.SubElement(group_elem, "name").text = group.name
        ET.SubElement(group_elem, "masterDeviceId").text = group.master_id
        roles = ET.SubElement(group_elem, "roles")

        gr1 = ET.SubElement(roles, "groupRole")
        ET.SubElement(gr1, "deviceId").text = group.left_id
        ET.SubElement(gr1, "role").text = "LEFT"
        ET.SubElement(gr1, "ipAddress").text = group.left_ip

        gr2 = ET.SubElement(roles, "groupRole")
        ET.SubElement(gr2, "deviceId").text = group.right_id
        ET.SubElement(gr2, "role").text = "RIGHT"
        ET.SubElement(gr2, "ipAddress").text = group.right_ip
        return group_elem

    def group_from_xml(self, group_id: str, group_elem: ET.Element) -> Group:
        """Converts an XML element into a Group object."""
        name = strip_element_text(group_elem.find("name"))
        master_id = strip_element_text(group_elem.find("masterDeviceId"))
        roles_elem = group_elem.find("roles")
        if not roles_elem == None:
            for role_elem in roles_elem.findall("groupRole"):
                role = strip_element_text(role_elem.find("role"))
                if role == "LEFT":
                    left_id = strip_element_text(role_elem.find("deviceId"))
                    left_ip = strip_element_text(role_elem.find("ipAddress"))
                elif role == "RIGHT":
                    right_id = strip_element_text(role_elem.find("deviceId"))
                    right_ip = strip_element_text(role_elem.find("ipAddress"))

        return Group(
            id=group_id,
            name=name,
            master_id=master_id,
            left_id=left_id,
            left_ip=left_ip,
            right_id=right_id,
            right_ip=right_ip,
        )
