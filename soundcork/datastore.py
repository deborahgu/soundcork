import logging
import re
import random
import xml.etree.ElementTree as ET
from os import mkdir, rmdir, listdir, path, walk, remove

from typing import Optional
from io import BytesIO

from soundcork.config import Settings
from soundcork.constants import (
    DEVICE_INFO_FILE,
    DEVICES_DIR,
    PRESETS_FILE,
    RECENTS_FILE,
    SOURCES_FILE,
)
from soundcork.model import ConfiguredSource, DeviceInfo, Preset, Recent
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
        # def __init__(self, data_dir: str, settings: Settings) -> None:

    def initialize_data_directory(self) -> None:
        raise NotImplementedError

    def account_dir(self, account: str) -> str:
        return path.join(self.data_dir, account)

    def account_devices_dir(self, account: str) -> str:
        return path.join(self.data_dir, account, DEVICES_DIR)

    def account_device_dir(self, account: str, device: str) -> str:
        return path.join(self.account_devices_dir(account), device)

    def get_device_info(self, account: str, device: str) -> DeviceInfo:
        """Get the device info"""

        stored_tree = ET.parse(
            path.join(self.account_device_dir(account, device), DEVICE_INFO_FILE)
        )
        info_elem = stored_tree.getroot()
        # info_elem = root.find("info")
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

        try:
            return DeviceInfo(
                device_id=device_id,
                product_code=f"{type} {module_type}",
                device_serial_number=str(device_serial_number),
                product_serial_number=str(product_serial_number),
                firmware_version=str(firmware_version),
                ip_address=str(ip_address),
                name=str(name),
            )
        except NameError:
            raise RuntimeError(
                f"There are missing required fields in the device: {device_id}"
            )

    def save_presets(self, account: str, device: str, presets_list: list[Preset]):
        save_file = path.join(self.account_dir(account), PRESETS_FILE)
        presets_elem = ET.Element("presets")
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
        with open(
            path.join(self.account_dir(account), PRESETS_FILE), "w"
        ) as presets_file:
            presets_file.write(presets_xml)

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
        with open(
            path.join(self.account_dir(account), RECENTS_FILE), "w"
        ) as recents_file:
            recents_file.write(recents_xml)

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
                )
            )

        return sources_list

    # TODO: add error handling if you can't write the file
    def save_configured_sources_xml(self, account: str, sources_xml: str):
        with open(
            path.join(self.account_dir(account), SOURCES_FILE), "w"
        ) as sources_file:
            sources_file.write(sources_xml)

    def etag_for_presets(self, account: str) -> int:
        presets_file = path.join(self.account_dir(account), PRESETS_FILE)
        if path.exists(presets_file):
            return int(path.getmtime(presets_file) * 1000)
        else:
            return 0

    def etag_for_sources(self, account: str) -> int:
        sources_file = path.join(self.account_dir(account), SOURCES_FILE)
        if path.exists(sources_file):
            return int(path.getmtime(sources_file) * 1000)
        else:
            return 0

    def etag_for_recents(self, account: str) -> int:
        recents_file = path.join(self.account_dir(account), RECENTS_FILE)
        if path.exists(recents_file):
            return int(path.getmtime(recents_file) * 1000)
        else:
            return 0

    def etag_for_account(self, account: str) -> int:
        return max(
            self.etag_for_presets(account),
            self.etag_for_sources(account),
            self.etag_for_recents(account),
        )

    ######## create account

    def list_accounts(self) -> list[Optional[str]]:
        accounts: list[str | None] = []
        for account_id in next(walk(self.data_dir))[1]:
            accounts.append(account_id)

        return accounts

    def list_devices(self, account_id) -> list[Optional[str]]:
        devices: list[str | None] = []
        for device_id in next(walk(self.account_devices_dir(account_id)))[1]:
            devices.append(device_id)

        return devices

    def account_exists(self, account: str) -> bool:
        return account in self.list_accounts()

    def device_exists(self, account: str, device_id: str) -> bool:
        return device_id in self.list_devices(account)

    def create_account(self, account: str) -> bool:
        logger.info(f"creating account {account}")
        if self.account_exists(account):
            return False

        # TODO: add error handling if you can't make the directory
        mkdir(self.account_dir(account))
        mkdir(self.account_devices_dir(account))
        # create devices subdirectory
        return True

    def add_device(self, account: str, device_id: str, device_info_xml: str) -> bool:
        if self.device_exists(account, device_id):
            return False

        # TODO: add error handling if you can't make the directory
        mkdir(path.join(self.account_devices_dir(account), device_id))

        # TODO: add error handling if you can't write the file
        with open(
            path.join(self.account_device_dir(account, device_id), DEVICE_INFO_FILE),
            "w",
        ) as device_info_file:
            device_info_file.write(device_info_xml)
        return True

    def remove_device(self, account: str, device_id: str) -> bool:
        logger.debug(f"removing device {device_id} from account {account}")
        if not self.device_exists(account, device_id):
            return False

        # TODO: add error handling if you can't delete the files
        remove(path.join(self.account_device_dir(account, device_id), DEVICE_INFO_FILE))
        rmdir(path.join(self.account_devices_dir(account), device_id))
        return True
           
######## groups #################
    #-- Helper function to prettyprint XML
    def _pretty_xml(self, root: ET.Element) -> str:
        #-- add indentations
        ET.indent(root, space="  ", level=0)
        buf = BytesIO()
        ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
        return buf.getvalue().decode("utf-8")
        
    #-- Helper function to create a unique group_id
    def _generate_group_id(self, account: str) -> str:
        while True:
            group_id = f"{random.randint(0, 9999999):07d}"
            filepath = path.join(
                self.account_devices_dir(account),
                f"Group_{group_id}.xml"
            )
            if not path.exists(filepath):
                return group_id

    #-- list all existing groups
    def list_groups(self, account: str) -> list[str]:
        devices_dir = self.account_devices_dir(account)
        groups = []
        for fn in listdir(devices_dir):
            if fn.startswith("Group_") and fn.endswith(".xml"):
                groups.append(fn[len("Group_"):-len(".xml")])
        return groups

    #-- check if a group with given id exist
    def group_exists(self, account: str, group_id: str) -> bool:
        return path.exists(path.join(self.account_devices_dir(account), f"Group_{group_id}.xml"))
    
    #-- check if a given device is already grouped    
    def check_device_grouped(self, account: str, device_id: str) -> Optional[str]:
        devices_dir = self.account_devices_dir(account)
        for filename in listdir(devices_dir):
            if not filename.startswith("Group_") or not filename.endswith(".xml"):
                continue
            filepath = path.join(devices_dir, filename)
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()
            except ET.ParseError:
                continue  # kaputte Gruppe ignorieren
            for dev in root.findall(".//deviceId"):
                if dev.text == device_id:
                    # get group_id from filename
                    # Group_<id>.xml
                    return filename[len("Group_") : -len(".xml")]
        return None

    #-- check if a device with given id is of type ST10    
    def check_device_type(self, account: str, device_id: str) -> bool:
        info_path = path.join(
            self.account_devices_dir(account),
            device_id,
            DEVICE_INFO_FILE,
        )

        if not path.exists(info_path):
            return False
        try:
            tree = ET.parse(info_path)
            root = tree.getroot()
        except ET.ParseError:
            return False
        dev_type = root.find("type")
        return dev_type is not None and dev_type.text == "SoundTouch 10"

    #-- validate group xml        
    def validate_group_xml(self, xml_content: str) -> ET.Element:
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")

        #-- <name>
        name = root.find("name")
        if name is None or not name.text or not name.text.strip():
            raise ValueError("Missing or empty <name> element")

        #-- <masterDeviceId>
        master = root.find("masterDeviceId")
        if master is None or not master.text:
            raise ValueError("Missing <masterDeviceId> element")

        # <roles>/<groupRole>/<deviceId>
        device_ids = [d.text for d in root.findall("./roles/groupRole/deviceId") if d.text]
        if not device_ids:
            raise ValueError("No <groupRole>/<deviceId> entries found")

        if master.text not in device_ids:
            raise ValueError("masterDeviceId must appear in group roles")

        return root


    #-- add a group, if a.) both devices are ungrouped and 
    #                   b.) of type ST10 and       
    def add_group(self, account: str, group_info_xml: str) -> str:
        """
        adds a group if it a.) both devices exist, b.) both are ST10 
        return value:
        - XML string of created group on success
        - error message on failure
        """
        group_id = self._generate_group_id(account)
        filename = f"Group_{group_id}.xml"
        filepath = path.join(self.account_devices_dir(account), filename)

        if path.exists(filepath):
            return "Group already exists"
        try:
            root = self.validate_group_xml(group_info_xml)
        except ValueError as e:
            return str(e)

        #-- extract two deviceIds
        device_ids = [d.text for d in root.findall("./roles/groupRole/deviceId") if d.text]
        if len(device_ids) != 2:
            return "Group must contain exactly two deviceId entries"

        #-- are these already grouped?
        for dev_id in device_ids:
            grouped_in = self.check_device_grouped(account, dev_id)
            if grouped_in:
                return f"Device {dev_id} is already part of group {grouped_in}"

        #-- are these ST10 devices?
        for dev_id in device_ids:
            if not self.check_device_type(account, dev_id):
                return f"Device {dev_id} is not of type 'SoundTouch 10'"
        
        #-- done with tests
        root.set("id", group_id)
        xml_out = self._pretty_xml(root)
        #-- write to file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(xml_out)
        #-- return complete prettyprinted XML
        return xml_out

    #-- change the name of a group
    def modify_group(
        self,
        account: str,
        group_id: str,
        new_name: str,
        master_device_id: str,
        ) -> str:
        """
        modifies name of a group
        return value:
        - XML string of created group on success
        - error message on failure
        """
        group_file = path.join(
            self.account_devices_dir(account),
            f"Group_{group_id}.xml"
        )

        if not path.exists(group_file):
            return f"Group does not exist in account {account}"

        #-- get xml file
        try:
            tree = ET.parse(group_file)
            root = tree.getroot()
        except ET.ParseError:
            return "Stored group XML is invalid"

        #-- check master device
        stored_master = root.findtext("masterDeviceId")
        if not stored_master:
            return "Group has no masterDeviceId"

        if stored_master != master_device_id:
            return "masterDeviceId does not match group master"

        #-- <name> replacement
        name_elem = root.find("name")
        if name_elem is None:
            name_elem = ET.SubElement(root, "name")
        name_elem.text = new_name

        #-- stringify with prettyprint
        xml_out = self._pretty_xml(root)
        #xml_out = ET.tostring(
        #    root,
        #    encoding="utf-8",
        #    xml_declaration=True,
        #).decode("utf-8")

        #-- write to file 
        with open(group_file, "w", encoding="utf-8") as f:
            f.write(xml_out)

        return xml_out

    #-- delete a group if it exists
    def delete_group(self, account: str, group_id: str) -> str:
        """
        deletes a group if it exists.
        return value:
        ""    → in case of success
        "..." → error message
        """
        filename = f"Group_{group_id}.xml"
        filepath = path.join(self.account_devices_dir(account), filename)

        if not path.exists(filepath):
            return f"Group {group_id} does not exist in account {account}"

        try:
            remove(filepath)
        except Exception as e:
            return f"Failed to delete group {group_id}: {e}"

        return ""

    #-- check group status of a device
    def get_device_group_xml(self, account: str, device_id: str) -> str:
        """
        check group status of a device      
        return value::
        - XML <group/> if ungrouped
        - XML file of group if grouped
        - error if device does not exist or is no ST10
        """
        #-- device existent (may be obsolete, is already checked in main.py)
        device_dir = path.join(self.account_devices_dir(account), device_id)
        info_path = path.join(device_dir, DEVICE_INFO_FILE)
        if not path.exists(info_path):
            return f"Device {device_id} does not exist"

        #-- type=ST10 ? 
        if not self.check_device_type(account, device_id):
            return f"Device {device_id} is not of type 'SoundTouch 10'"

        #-- check status
        grouped_in = self.check_device_grouped(account, device_id)
        if not grouped_in:
            return "<group/>"

        #-- get xml file of group
        group_file = path.join(self.account_devices_dir(account), f"Group_{grouped_in}.xml")
        try:
            with open(group_file, "r", encoding="utf-8") as f:
                xml_content = f.read()
            return xml_content
        except Exception as e:
            return f"Failed to read group {grouped_in}: {e}"
