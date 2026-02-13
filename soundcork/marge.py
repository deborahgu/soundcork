import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from os import path, walk
from typing import TYPE_CHECKING

from fastapi import HTTPException

from soundcork.config import Settings
from soundcork.constants import PROVIDERS
from soundcork.model import (
    ConfiguredSource,
    ContentItem,
    Preset,
    Recent,
    SourceProvider,
)

if TYPE_CHECKING:
    from soundcork.datastore import DataStore

# pyright: reportOptionalMemberAccess=false

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

logger = logging.getLogger(__name__)

settings = Settings()

# used for when a timestamp is missing
default_datestr = "2012-09-19T12:43:00.000+00:00"


def source_providers() -> list[SourceProvider]:
    return [
        SourceProvider(
            id=i[0], created_on=default_datestr, name=i[1], updated_on=default_datestr
        )
        for i in enumerate(PROVIDERS, start=1)
    ]


def preset_xml(preset: Preset, conf_sources_list: list[ConfiguredSource]) -> ET.Element:
    preset_element = ET.Element("preset")
    preset_element.attrib["buttonNumber"] = preset.id

    try:
        created_on = datetime.fromtimestamp(
            int(preset.created_on), timezone.utc
        ).isoformat()
    except:
        created_on = default_datestr

    try:
        updated_on = datetime.fromtimestamp(
            int(preset.updated_on), timezone.utc
        ).isoformat()
    except:
        updated_on = default_datestr

    ET.SubElement(preset_element, "containerArt").text = preset.container_art
    ET.SubElement(preset_element, "contentItemType").text = preset.type
    ET.SubElement(preset_element, "createdOn").text = created_on
    ET.SubElement(preset_element, "location").text = preset.location
    ET.SubElement(preset_element, "name").text = preset.name
    preset_element.append(content_item_source_xml(conf_sources_list, preset))
    ET.SubElement(preset_element, "updatedOn").text = updated_on
    return preset_element


def presets_xml(datastore: "DataStore", account: str, device: str) -> ET.Element:
    conf_sources_list = datastore.get_configured_sources(account, device)

    presets_list = datastore.get_presets(account, device)

    presets_element = ET.Element("presets")
    for preset in presets_list:
        preset_element = preset_xml(preset, conf_sources_list)
        presets_element.append(preset_element)

    return presets_element


def update_preset(
    datastore: "DataStore",
    account: str,
    device: str,
    preset_number: int,
    source_xml: bytes,
) -> ET.Element:
    conf_sources_list = datastore.get_configured_sources(account, device)
    presets_list = datastore.get_presets(account, device)

    new_preset_elem = ET.fromstring(source_xml)

    # load the preset to add

    name = strip_element_text(new_preset_elem.find("name"))
    source_id = strip_element_text(new_preset_elem.find("sourceid"))
    # we could use username to match source maybe?
    # username = new_preset_elem.find("username").text
    location = strip_element_text(new_preset_elem.find("location"))
    content_item_type = strip_element_text(new_preset_elem.find("contentItemType"))

    container_art = strip_element_text(new_preset_elem.find("containerArt"))

    try:
        matching_src = next(src for src in conf_sources_list if src.id == source_id)
    except StopIteration:
        raise HTTPException(status_code=400, detail=f"Invalid source {source_id}")
    source = matching_src.source_key_type
    source_account = matching_src.source_key_account

    now_str = str(int(datetime.now().timestamp()))

    preset_obj = Preset(
        id=str(preset_number),
        type=content_item_type,
        created_on=now_str,
        updated_on=now_str,
        name=name,
        source=source,
        location=location,
        source_id=source_id,
        source_account=source_account,
        container_art=container_art,
    )

    presets_list[preset_number - 1] = preset_obj

    datastore.save_presets(account, device, presets_list)

    preset_element = preset_xml(preset_obj, conf_sources_list)
    return preset_element


def content_item_source_xml(
    configured_sources: list[ConfiguredSource],
    content_item: ContentItem,
) -> ET.Element:
    if content_item.source_id:
        try:
            matching_src = next(
                cs for cs in configured_sources if cs.id == content_item.source_id
            )
        except StopIteration:
            print(f"invalid source for content_item.source_id {content_item.source_id}")
            raise HTTPException(status_code=400, detail="Invalid source")
        return configured_source_xml(matching_src)

    try:
        matching_src = next(
            cs
            for cs in configured_sources
            if cs.source_key_type == content_item.source
            and (
                cs.source_key_account == content_item.source_account
                or (not cs.source_key_account and not content_item.source_account)
            )
        )
    except StopIteration:
        print(
            f"invalid source for source key {content_item.source} account {content_item.source_account}"
        )
        raise HTTPException(status_code=400, detail="Invalid source")
    return configured_source_xml(matching_src)


def all_sources_xml(
    configured_sources: list[ConfiguredSource],
) -> ET.Element:

    sources_elem = ET.Element("sources")

    for conf_source in configured_sources:
        sources_elem.append(configured_source_xml(conf_source))

    return sources_elem


def configured_source_xml(conf_source: ConfiguredSource) -> ET.Element:
    source = ET.Element("source")
    source.attrib["id"] = conf_source.id
    source.attrib["type"] = "Audio"
    ET.SubElement(source, "createdOn").text = default_datestr
    credential = ET.SubElement(source, "credential")
    credential.text = conf_source.secret
    credential.attrib["type"] = "token"
    ET.SubElement(source, "name").text = conf_source.source_key_account
    ET.SubElement(source, "sourceproviderid").text = str(
        PROVIDERS.index(conf_source.source_key_type) + 1
    )
    ET.SubElement(source, "sourcename").text = conf_source.display_name
    ET.SubElement(source, "sourcesettings")
    ET.SubElement(source, "updatedOn").text = default_datestr
    ET.SubElement(source, "username").text = conf_source.source_key_account

    return source


def recents_xml(datastore: "DataStore", account: str, device: str) -> ET.Element:
    conf_sources_list = datastore.get_configured_sources(account, device)

    recents_list = datastore.get_recents(account, device)

    recents_element = ET.Element("recents")
    for recent in recents_list:
        lastplayed = datetime.fromtimestamp(
            int(recent.utc_time), timezone.utc
        ).isoformat()

        try:
            created_on = datetime.fromtimestamp(
                int(recent.created_on), timezone.utc
            ).isoformat()
        except:
            created_on = default_datestr

        recent_element = ET.SubElement(recents_element, "recent")
        recent_element.attrib["id"] = recent.id
        ET.SubElement(recent_element, "contentItemType").text = recent.type
        ET.SubElement(recent_element, "createdOn").text = created_on
        ET.SubElement(recent_element, "lastplayedat").text = lastplayed
        ET.SubElement(recent_element, "location").text = recent.location
        ET.SubElement(recent_element, "name").text = recent.name
        recent_element.append(content_item_source_xml(conf_sources_list, recent))
        ET.SubElement(recent_element, "updatedOn").text = lastplayed

    return recents_element


def add_recent(
    datastore: "DataStore", account: str, device: str, source_xml: bytes
) -> ET.Element:
    conf_sources_list = datastore.get_configured_sources(account, device)
    recents_list = datastore.get_recents(account, device)

    new_recent_elem = ET.fromstring(source_xml)

    # load the recent to add
    device_id = device
    last_played_at = new_recent_elem.find("lastplayedat")
    if last_played_at is not None and last_played_at.text:
        utc_time = int(datetime.fromisoformat(last_played_at.text).timestamp())
    else:
        utc_time = int(datetime.now().timestamp())

    # these values are all assumed to be required for this to be
    # a valid Recent XML source; if any of these are not present
    # they should produce an exception
    name = new_recent_elem.find("name").text
    source_id = new_recent_elem.find("sourceid").text
    location = new_recent_elem.find("location").text
    is_presetable = "true"

    type = strip_element_text(new_recent_elem.find("contentItemType"))

    try:
        matching_src = next(src for src in conf_sources_list if src.id == source_id)
    except StopIteration:
        raise HTTPException(status_code=400, detail=f"Invalid source {source_id}")
    source = matching_src.source_key_type
    source_account = matching_src.source_key_account

    # see if this item is already in the recents list
    matching_recent = next(
        (
            i
            for i in recents_list
            if i.source == source
            and i.location == location
            and i.source_account == source_account
        ),
        None,
    )
    recent_obj = None
    if matching_recent:
        # just update the time and move it to the front of the list
        matching_recent.utc_time = str(utc_time)
        created_on = default_datestr
        recent_obj = matching_recent
    else:
        # need a new id
        # TODO handle race conditions -- right now two recent requests
        # would probably have the second clobber the first
        next_id = max(int(recent.id) for recent in recents_list) + 1
        recent_obj = Recent(
            name=name,  # type:ignore
            utc_time=str(utc_time),
            id=str(next_id),
            source_id=source_id,
            source=source,
            device_id=device_id,
            type=type,  # type:ignore
            location=location,  # type:ignore
            source_account=source_account,
            is_presetable=is_presetable,
        )
        created_on = datetime.fromtimestamp(
            datetime.now().timestamp(), timezone.utc
        ).isoformat()

        recents_list.insert(0, recent_obj)
        # probably shouldn't just let this grow unbounded
        recents_list = recents_list[:10]

    datastore.save_recents(account, device, recents_list)

    lastplayed = datetime.fromtimestamp(
        int(recent_obj.utc_time), timezone.utc
    ).isoformat()

    # return newly created or updated element in return-value xml format
    # TODO reuse code from recents_xml()
    recent_element = ET.Element("recent")
    recent_element.attrib["id"] = recent_obj.id
    ET.SubElement(recent_element, "contentItemType").text = recent_obj.type
    ET.SubElement(recent_element, "createdOn").text = created_on
    ET.SubElement(recent_element, "lastplayedat").text = lastplayed
    ET.SubElement(recent_element, "location").text = recent_obj.location
    ET.SubElement(recent_element, "name").text = recent_obj.name
    recent_element.append(content_item_source_xml(conf_sources_list, recent_obj))
    ET.SubElement(recent_element, "updatedOn").text = lastplayed

    return recent_element


def provider_settings_xml(account: str) -> ET.Element:
    # this seems to report information like if you're eligible for a free
    # trial
    provider_settings = ET.Element("providerSettings")
    p_setting = ET.SubElement(provider_settings, "providerSetting")
    ET.SubElement(p_setting, "boseId").text = account
    ET.SubElement(p_setting, "keyName").text = "ELIGIBLE_FOR_TRIAL"
    ET.SubElement(p_setting, "value").text = "true"
    ET.SubElement(p_setting, "providerId").text = "14"
    return provider_settings


def account_full_xml(account: str, datastore: "DataStore") -> ET.Element:
    account_elem = ET.Element("account")
    account_elem.attrib["id"] = account
    ET.SubElement(account_elem, "accountStatus").text = "OK"
    devices_elem = ET.SubElement(account_elem, "devices")
    last_device_id = ""
    for device_id in datastore.list_devices(account):
        last_device_id = device_id
        device_info = datastore.get_device_info(account, device_id)

        device_elem = ET.SubElement(devices_elem, "device")
        device_elem.attrib["deviceid"] = device_id
        attached_product_elem = ET.SubElement(device_elem, "attachedProduct")
        attached_product_elem.attrib["product_code"] = device_info.product_code
        # some devices seem to have components but i don't know they're important
        ET.SubElement(attached_product_elem, "components")
        ET.SubElement(attached_product_elem, "productlabel").text = (
            device_info.product_code
        )
        ET.SubElement(attached_product_elem, "serialnumber").text = (
            device_info.product_serial_number
        )
        ET.SubElement(device_elem, "createdOn").text = default_datestr

        ET.SubElement(device_elem, "firmwareVersion").text = (
            device_info.firmware_version
        )
        ET.SubElement(device_elem, "ipaddress").text = device_info.ip_address
        ET.SubElement(device_elem, "name").text = device_info.name
        device_elem.append(presets_xml(datastore, account, device_id))
        device_elem.append(recents_xml(datastore, account, device_id))
        ET.SubElement(device_elem, "serialnumber").text = (
            device_info.device_serial_number
        )
        ET.SubElement(device_elem, "updatedOn").text = default_datestr

    ET.SubElement(account_elem, "mode").text = "global"

    # FIXME we can get this from the language endpoint but it returns a
    # number rather than a language code
    ET.SubElement(account_elem, "preferredLanguage").text = "en"
    account_elem.append(provider_settings_xml(account))
    account_elem.append(
        all_sources_xml(datastore.get_configured_sources(account, last_device_id))
    )

    return account_elem


def software_update_xml() -> ET.Element:
    # <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    # <software_update><softwareUpdateLocation></softwareUpdateLocation></software_update>
    su = ET.Element("software_update")
    ET.SubElement(su, "softwareUpdateLocation")
    return su


def add_device_to_account(
    datastore: "DataStore", account: str, source_xml: str
) -> ET.Element:

    new_device_elem = ET.fromstring(source_xml)
    device_id = new_device_elem.attrib.get("deviceid", "")
    name = new_device_elem.find("name").text

    # TODO implement
    # datastore.add_device(account, device_id, name)

    created_on = datetime.fromtimestamp(
        datetime.now().timestamp(), timezone.utc
    ).isoformat()

    return_elem = ET.Element("device")
    return_elem.attrib["deviceid"] = device_id
    ET.SubElement(return_elem, "createdOn").text = created_on
    ET.SubElement(return_elem, "ipaddress")
    ET.SubElement(return_elem, "name").text = name
    ET.SubElement(return_elem, "updatedOn").text = created_on

    return return_elem


def remove_device_from_account(datastore: "DataStore", account: str, device: str):
    # TODO implement
    # datastore.remove_device(account, device)
    return {"ok"}


def strip_element_text(elem: ET.Element) -> str:
    if elem == None:
        return ""
    else:
        text = elem.text
        if not text:
            return ""
        else:
            return text.strip()
