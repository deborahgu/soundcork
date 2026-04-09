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
    "RADIO_BROWSER",  # https://www.radio-browser.info
]

# where we store associated devices.
DEVICES_DIR = "devices"

# retrieved per-device via {deviceip}:8090/info
DEVICE_INFO_FILE = "DeviceInfo.xml"
# sent to power_on endpoint
POWERON_FILE = "PowerOn.xml"
# Marge API knows this mapping and it's exposed at login, but not returned
ACCOUNTS_FILE = "Accounts.json"
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

# for device initialization via http
SPEAKER_HTTP_PORT = 8090
SPEAKER_DEVICE_INFO_PATH = "/info"
SPEAKER_RECENTS_PATH = "/recents"
SPEAKER_PRESETS_PATH = "/presets"
# this one needs to be pulled from a device
SPEAKER_SOURCES_FILE_LOCATION = "/mnt/nv/BoseApp-Persistence/1/Sources.xml"
SPEAKER_OVERRIDE_SDK_LOCATION = "/mnt/nv/OverrideSdkPrivateCfg.xml"

# validation
ACCOUNT_RE = "^\\d{1,20}$"
DEVICE_RE = "^[0-9a-fA-F]{12}$"
GROUP_RE = "^\\d{7}$"


# used for when a timestamp is missing
DEFAULT_DATESTR = "2012-09-19T12:43:00.000+00:00"

# used when an account label is missing
DEFAULT_ACCOUNT_LABEL = "Unnamed account"

# Device image mappings
DEVICE_IMAGE_MAP = {
    "taigan": "d0.png",
    "soundtouch portable": "d0.png",
    "soundtouch portable scm": "d0.png",
    "spotty": "d1.png",
    "soundtouch 20": "d1.png",
    "soundtouch 20 sm2": "d1.png",
    "mojo": "d2.png",
    "soundtouch 30": "d2.png",
    "soundtouch 30 sm2": "d2.png",
    "nelson": "d3.png",
    "wave soundtouch": "d3.png",
    "wave soundtouch music system iv": "d3.png",
    "colin": "d4.png",
    "soundtouch sa-4": "d4.png",
    "luke": "d5.png",
    "soundtouch stereo jc": "d5.png",
    "soundtouch wireless link adapter": "d5.png",
    "soundtouch sa-5 amplifier": "d5.png",
    "otto": "d6.png",
    "marconi": "d6.png",
    "videowave": "d6.png",
    "corey": "d7.png",
    "135": "d7.png",
    "235": "d7.png",
    "525": "d7.png",
    "535": "d7.png",
    "lifestyle": "d7.png",
    "lifestyle 135": "d7.png",
    "lifestyle 235": "d7.png",
    "lifestyle 525": "d7.png",
    "lifestyle 535": "d7.png",
    "triode": "d8.png",
    "cinemate": "d8.png",
    "rhino": "d9.png",
    "soundtouch 10": "d9.png",
    "soundtouch 10 sm2": "d9.png",
    "burns": "d10.png",
    "soundtouch sa-5": "d10.png",
    "binky": "d11.png",
    "soundtouch wireless link adapter": "d11.png",
    "soundtouch 10 grouped": "d12.png",
    "soundtouch 300": "d13.png",
    "soundtouch 300 scm": "d13.png",
    "soundtouch 300 sm2": "d13.png",
    "lifestyle 600/650": "d14.png",
}
DEFAULT_DEVICE_IMAGE = "soundtouch-30.png"
