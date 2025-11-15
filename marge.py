import xml.etree.ElementTree as ET
from datetime import datetime

from config import Settings
from model import ConfiguredSource, Preset, SourceProvider

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
    return settings.data_dir + "/" + account + "/" + device + "/"


def source_providers() -> list[SourceProvider]:
    datestr = "2012-09-19T12:43:00.000+00:00"
    return [
        SourceProvider(id=i[0], created_on=datestr, name=i[1], updated_on=datestr)
        for i in enumerate(PROVIDERS, start=1)
    ]


def configured_sources(
    settings: Settings, account: str, device: str
) -> list[ConfiguredSource]:
    sources_tree = ET.parse(
        account_device_dir(settings, account, device) + "Sources.xml"
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
    storedTree = ET.parse(account_device_dir(settings, account, device) + "Presets.xml")
    root = storedTree.getroot()

    presets = []

    for preset in root.findall("preset"):
        id = preset.attrib["id"]
        content_item = preset.find("ContentItem")
        name = content_item.find("itemName").text
        source = content_item.attrib["source"]
        type = content_item.attrib["type"] if "type" in content_item.attrib else ""
        location = content_item.attrib["location"]
        source_account = content_item.attrib["sourceAccount"]
        is_presetable = content_item.attrib["isPresetable"]
        container_art_elem = content_item.find("containerArt")
        if container_art_elem != None and container_art_elem.text != None:
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
