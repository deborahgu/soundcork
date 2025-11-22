import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from os import path

from config import Settings
from model import ConfiguredSource, Preset, Recent, SourceProvider

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
        secret = source_elem.attrib.get("secret", "")
        secret_type = source_elem.attrib.get("secretType", "")
        source_key_elem = source_elem.find("sourceKey")
        source_key_account = source_key_elem.attrib.get("account", "")
        source_key_type = source_key_elem.attrib.get("type", "")
        sources_list.append(
            ConfiguredSource(
                display_name=display_name,
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
        if container_art_elem and container_art_elem.text:
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
        preset_element.append(source_xml(conf_sources_list, preset, datestr))
        ET.SubElement(preset_element, "updatedOn").text = datestr

    return presets_element


def source_xml(
    configured_sources: list[ConfiguredSource],
    preset: Preset,
    datestr: str,
) -> ET.Element:
    idx = str(PROVIDERS.index(preset.source) + 1)

    matching_src = next(
        i
        for i in configured_sources
        if i.source_key_type == preset.source
        and i.source_key_account == preset.source_account
    )

    source = ET.Element("source")
    source.attrib["id"] = idx
    source.attrib["type"] = "Audio"
    ET.SubElement(source, "createdOn").text = datestr
    credential = ET.SubElement(source, "credential")
    credential.text = matching_src.secret
    credential.attrib["type"] = "token"
    ET.SubElement(source, "name").text = preset.name
    ET.SubElement(source, "sourceproviderid").text = idx
    ET.SubElement(source, "sourcename").text = matching_src.display_name
    ET.SubElement(source, "sourcesettings")
    ET.SubElement(source, "updatedOn").text = datestr
    ET.SubElement(source, "username").text = preset.name

    return source


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
        recent_element.append(source_xml(conf_sources_list, recent, datestr))
        ET.SubElement(recent_element, "updatedOn").text = datestr

    return recents_element
