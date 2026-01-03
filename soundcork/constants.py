# Hard-coded providers the Bose servers know how to serve
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

# where we store associated devices.
DEVICES_DIR = "devices"

# retrieved per-device via {deviceip}:8090/info
DEVICE_INFO_FILE = "DeviceInfo.xml"
# retrieved per account via {deviceip}:8090/presets
PRESETS_FILE = "Presets.xml"
# retrieved per account via {deviceip}:8090/recents
RECENTS_FILE = "Recents.xml"
# retrieved per account via file retrieval from /mnt/nv/BoseApp-Persistence/1/Sources.xml
# a limited version is available via {deviceip}:8090/sources but this doesn't include
# necessary secrets.
#
# also each source should have an id but they don't seem to; should probably add these
# values on initial copy of the Sources.xml file from the device.
SOURCES_FILE = "Sources.xml"
