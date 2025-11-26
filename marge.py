import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from os import path, walk

from config import Settings
from model import (
    ConfiguredSource,
    ContentItem,
    DeviceInfo,
    Preset,
    Recent,
    SourceProvider,
)

# We'll move these into a constants file eventually.
PROVIDERS = [
    "PANDORA",
    "INTERNET_RADIO",
    "OFF",
    "LOCAL",
    "AIRPLAY",
    "CURRATED_RADIO",
    "STORED_MUSIC",
    "SLAVE_SOURCE",
    "AUX",
    "RECOMMENDED_INTERNET_RADIO",
    "LOCAL_INTERNET_RADIO",
    "GLOBAL_INTERNET_RADIO",
    "HELLO",
    "DEEZER",
    "SPOTIFY",
    "IHEART",
    "SIRIUSXM",
    "GOOGLE_PLAY_MUSIC",
    "QQMUSIC",
    "AMAZON",
    "LOCAL_MUSIC",
    "WBMX",
    "SOUNDCLOUD",
    "TIDAL",
    "TUNEIN",
    "QPLAY",
    "JUKE",
    "BBC",
    "DARFM",
    "7DIGITAL",
    "SAAVN",
    "RDIO",
    "PHONE_MUSIC",
    "ALEXA",
    "RADIOPLAYER",
    "RADIO.COM",
    "RADIO_COM",
    "SIRIUSXM_EVEREST",
]


def account_device_dir(settings: Settings, account: str, device: str) -> str:
    return path.join(settings.data_dir, account, device)


def source_providers() -> list[SourceProvider]:
    datestr = "2012-09-19T12:43:00.000+00:00"
    return [
        SourceProvider(id=i[0], created_on=datestr, name=i[1], updated_on=datestr)
        for i in enumerate(PROVIDERS, start=1)
    ]


# This will probably be refactored into a datastore class for reading and writing the datastore,
# but it's too early to do that refactor for now during POC.
def configured_sources(
    settings: Settings, account: str, device: str
) -> list[ConfiguredSource]:
    sources_tree = ET.parse(
        path.join(account_device_dir(settings, account, device), "Sources.xml")
    )
    root = sources_tree.getroot()
    sources_list = []
    for source_elem in root.findall("source"):
        display_name = source_elem.attrib.get("displayName", "")
        # the id had to be hand-added to the xml; once we get it working we'll
        # see if we can use an artificially-generated value
        id = source_elem.attrib.get("id", "")
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


def presets(settings: Settings, account: str, device: str) -> list[Preset]:
    storedTree = ET.parse(
        path.join(account_device_dir(settings, account, device), "Presets.xml")
    )
    root = storedTree.getroot()

    presets = []

    for preset in root.findall("preset"):
        id = preset.attrib["id"]
        content_item = preset.find("ContentItem")
        name = content_item.find("itemName").text
        source = content_item.attrib["source"]
        type = content_item.attrib.get("type", "")
        location = content_item.attrib["location"]
        source_account = content_item.attrib["sourceAccount"]
        is_presetable = content_item.attrib["isPresetable"]
        container_art_elem = content_item.find("containerArt")
        # have to 'is not None' because bool(Element) returns false
        # if the element has no children
        if container_art_elem is not None and container_art_elem.text:
            container_art = container_art_elem.text
        else:
            container_art = ""

        presets.append(
            Preset(
                name=name,
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


def presets_xml(settings: Settings, account: str, device: str) -> ET.Element:
    conf_sources_list = configured_sources(settings, account, device)

    presets_list = presets(settings, account, device)

    # We hardcode a date here because we'll never use it, so there's no need for a real date object.
    datestr = "2012-09-19T12:43:00.000+00:00"

    presets_element = ET.Element("presets")
    for preset in presets_list:
        preset_element = ET.SubElement(presets_element, "preset")
        preset_element.attrib["buttonNumber"] = preset.id
        ET.SubElement(preset_element, "containerArt").text = preset.container_art
        ET.SubElement(preset_element, "contentItemType").text = preset.type
        ET.SubElement(preset_element, "createdOn").text = datestr
        ET.SubElement(preset_element, "location").text = preset.location
        ET.SubElement(preset_element, "name").text = preset.name
        preset_element.append(
            content_item_source_xml(conf_sources_list, preset, datestr)
        )
        ET.SubElement(preset_element, "updatedOn").text = datestr

    return presets_element


def content_item_source_xml(
    configured_sources: list[ConfiguredSource],
    content_item: ContentItem,
    datestr: str,
) -> ET.Element:
    idx = str(PROVIDERS.index(content_item.source) + 1)

    matching_src = next(
        i
        for i in configured_sources
        if i.source_key_type == content_item.source
        and i.source_key_account == content_item.source_account
    )

    source = ET.Element("source")
    source.attrib["id"] = matching_src.id
    source.attrib["type"] = "Audio"
    ET.SubElement(source, "createdOn").text = datestr
    credential = ET.SubElement(source, "credential")
    credential.text = matching_src.secret
    credential.attrib["type"] = "token"
    ET.SubElement(source, "name").text = content_item.name
    ET.SubElement(source, "sourceproviderid").text = idx
    ET.SubElement(source, "sourcename").text = matching_src.display_name
    ET.SubElement(source, "sourcesettings")
    ET.SubElement(source, "updatedOn").text = datestr
    ET.SubElement(source, "username").text = content_item.name

    return source


def all_sources_xml(
    configured_sources: list[ConfiguredSource],
    datestr: str,
) -> ET.Element:

    sources_elem = ET.Element("sources")

    for conf_source in configured_sources:
        source = ET.SubElement(sources_elem, "source")
        source.attrib["id"] = conf_source.id
        source.attrib["type"] = "Audio"
        ET.SubElement(source, "createdOn").text = datestr
        credential = ET.SubElement(source, "credential")
        credential.text = conf_source.secret
        credential.attrib["type"] = "token"
        ET.SubElement(source, "name").text = conf_source.display_name
        ET.SubElement(source, "sourceproviderid").text = str(
            PROVIDERS.index(conf_source.source_key_type) + 1
        )
        ET.SubElement(source, "sourcename").text = conf_source.display_name
        ET.SubElement(source, "sourcesettings")
        ET.SubElement(source, "updatedOn").text = datestr
        ET.SubElement(source, "username").text = conf_source.display_name

    return sources_elem


def recents(settings: Settings, account: str, device: str) -> list[Recent]:
    stored_tree = ET.parse(
        path.join(account_device_dir(settings, account, device), "Recents.xml")
    )
    root = stored_tree.getroot()

    recents = []

    for recent in root.findall("recent"):
        id = recent.attrib.get("id", "")
        device_id = recent.attrib.get("deviceID", "")
        utc_time = recent.attrib.get("utcTime", "")
        content_item = recent.find("contentItem")
        name = content_item.find("itemName").text or "test"
        source = content_item.get("source", "")
        type = content_item.attrib.get("type", "")
        location = content_item.attrib["location"]
        source_account = content_item.attrib["sourceAccount"]
        is_presetable = content_item.attrib["isPresetable"]

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
            )
        )

    return recents


def recents_xml(settings: Settings, account: str, device: str) -> ET.Element:
    conf_sources_list = configured_sources(settings, account, device)

    recents_list = recents(settings, account, device)

    # We hardcode a date here because we'll never use it, so there's no need for a real date object.
    datestr = "2012-09-19T12:43:00.000+00:00"

    recents_element = ET.Element("recents")
    for recent in recents_list:
        lastplayed = datetime.fromtimestamp(
            int(recent.utc_time), timezone.utc
        ).isoformat()

        recent_element = ET.SubElement(recents_element, "recent")
        recent_element.attrib["id"] = recent.id
        ET.SubElement(recent_element, "contentItemType").text = recent.type
        ET.SubElement(recent_element, "createdOn").text = datestr
        ET.SubElement(recent_element, "lastplayedat").text = lastplayed
        ET.SubElement(recent_element, "location").text = recent.location
        ET.SubElement(recent_element, "name").text = recent.name
        recent_element.append(
            content_item_source_xml(conf_sources_list, recent, datestr)
        )
        ET.SubElement(recent_element, "updatedOn").text = datestr

    return recents_element


def provider_settings_xml(settings: Settings, account: str) -> ET.Element:
    # this seems to report information like if you're eligible for a free
    # trial, which shouldn't be all that important.
    # let's try just returning an empty element for this
    return ET.Element("providerSettings")


def get_device_info(settings: Settings, account: str, device: str) -> DeviceInfo:
    stored_tree = ET.parse(
        path.join(account_device_dir(settings, account, device), "PowerOn.xml")
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
        root.find("diagnostic-data").find("device-landscape").find("ip-address").text
    )
    system_stored_tree = ET.parse(
        path.join(
            account_device_dir(settings, account, device), "SystemConfigurationDB.xml"
        )
    )
    name = system_stored_tree.find("DeviceName").text

    return DeviceInfo(
        device_id=device_id,
        product_code=product_code,
        device_serial_number=device_serial_number,
        product_serial_number=product_serial_number,
        firmware_version=firmware_version,
        ip_address=ip_address,
        name=name,
    )


def account_full_xml(settings: Settings, account: str) -> ET.Element:
    datestr = "2012-09-19T12:43:00.000+00:00"

    account_dir = path.join(settings.data_dir, account)

    account_elem = ET.Element("account")
    account_elem.attrib["id"] = account
    ET.SubElement(account_elem, "accountStatus").text = "OK"
    devices_elem = ET.SubElement(account_elem, "devices")
    last_device_id = ""
    for device_id in next(walk(account_dir))[1]:
        last_device_id = device_id
        device_info = get_device_info(settings, account, device_id)

        device_elem = ET.SubElement(devices_elem, "device")
        device_elem.attrib["deviceid"] = device_id
        attached_product_elem = ET.SubElement(device_elem, "attachedProduct")
        attached_product_elem.attrib["product_code"] = device_info.product_code
        # some devices seem to have components but i don't know they're important
        ET.SubElement(device_elem, "components")
        ET.SubElement(attached_product_elem, "productlabel").text = (
            device_info.product_code
        )
        ET.SubElement(attached_product_elem, "serialnumber").text = (
            device_info.product_serial_number
        )
        ET.SubElement(device_elem, "createdOn").text = datestr

        ET.SubElement(device_elem, "firmwareVersion").text = (
            device_info.firmware_version
        )
        ET.SubElement(device_elem, "ipaddress").text = device_info.ip_address
        ET.SubElement(device_elem, "name").text = device_info.name
        device_elem.append(presets_xml(settings, account, device_id))
        device_elem.append(recents_xml(settings, account, device_id))
        ET.SubElement(device_elem, "serialnumber").text = (
            device_info.device_serial_number
        )
        ET.SubElement(device_elem, "updatedOn").text = datestr

    ET.SubElement(account_elem, "mode").text = "global"

    ET.SubElement(account_elem, "preferrendLanguage").text = "en"
    account_elem.append(provider_settings_xml(settings, account))
    account_elem.append(
        all_sources_xml(configured_sources(settings, account, last_device_id), datestr)
    )

    return account_elem
