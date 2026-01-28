import base64
import datetime
import json
import random
import threading
import time
from typing import Any, Dict, List, Optional, Union

import requests


class SiriusXM:
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    REST_FORMAT = "https://api.edge-gateway.siriusxm.com/{}"
    CDN_URL = "https://imgsrv-sxm-prod-device.streaming.siriusxm.com/{}"

    def __init__(self, username: str, password: str):
        self.api_base = "https://api.edge-gateway.siriusxm.com"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
        self.username = username
        self.password = password
        self.playlists: Dict = {}
        self.channels: Optional[List[Dict]] = None
        self.m3u8dat: Optional[str] = None
        self.channel_urls: Dict[str, Dict] = {}
        self.metadata_cache: Dict[str, Any] = {}

        # For xtra streams: session_id -> streaminfo dict with expiry
        self.xtra_streams: Dict[str, Dict] = {}
        # Cleanup thread for expired xtra sessions
        threading.Thread(target=self._cleanup_xtra_sessions, daemon=True).start()

    @staticmethod
    def log(message: str):
        print(
            f"{datetime.datetime.now().strftime('%d.%b %Y %H:%M:%S')} <SiriusXM>: {message}"
        )

    def is_logged_in(self) -> bool:
        auth = self.session.headers.get("Authorization", "")
        self.log(f"headers={self.session.headers}")
        return auth.startswith("Bearer ")

    def sfetch(self, url: str) -> Optional[bytes]:
        res = self.session.get(url)
        if res.status_code != 200:
            self.log(f"Failed to receive stream data. Error code {res.status_code}")
            return None
        return res.content

    def get(
        self,
        method: str,
        params: dict = {},
        authenticate: bool = True,
        retries: int = 0,
    ) -> Optional[dict]:
        if retries >= 3:
            self.log(f"Max retries hit on GET {method}")
            return None

        if authenticate and not self.is_logged_in():
            if not self.authenticate():
                self.log("Unable to authenticate before GET request")
                return None

        res = self.session.get(self.REST_FORMAT.format(method), params=params)
        if res.status_code == 401 and retries < 3:
            if not self.login():
                return None
            return self.get(method, params, authenticate, retries + 1)

        if res.status_code != 200:
            self.log(f"GET {method} returned status {res.status_code}")
            return None

        try:
            return res.json()
        except ValueError:
            self.log(f"Error decoding JSON for GET {method}")
            return None

    def post(
        self,
        method: str,
        postdata: dict,
        authenticate: bool = True,
        headers: dict = {},
        retries: int = 0,
    ) -> Optional[dict]:
        if retries >= 3:
            self.log(f"Max retries hit on POST {method}")
            return None

        if authenticate and not self.is_logged_in():
            if not self.authenticate():
                self.log("Unable to authenticate before POST request")
                return None

        res = self.session.post(
            self.REST_FORMAT.format(method), data=json.dumps(postdata), headers=headers
        )
        if res.status_code == 401 and retries < 3:
            if not self.login():
                return None
            return self.post(method, postdata, authenticate, headers, retries + 1)

        if res.status_code not in (200, 201):
            self.log(f"POST {method} returned status {res.status_code}")
            return None

        try:
            resjson = res.json()
        except ValueError:
            self.log(f"Error decoding JSON for POST {method}")
            return None

        bearer_token = resjson.get("grant") or resjson.get("accessToken")
        if bearer_token:
            self.session.headers.update({"Authorization": f"Bearer {bearer_token}"})
            self.log("Authorization token updated")

        return resjson

    def login(self) -> bool:
        postdata = {
            "devicePlatform": "web-desktop",
            "deviceAttributes": {
                "browser": {
                    "browserVersion": "7.74.0",
                    "userAgent": self.USER_AGENT,
                    "sdk": "web",
                    "app": "web",
                    "sdkVersion": "7.74.0",
                    "appVersion": "7.74.0",
                }
            },
            "grantVersion": "v2",
        }
        sxmheaders = {"x-sxm-tenant": "sxm"}

        data = self.post(
            "device/v1/devices", postdata, authenticate=False, headers=sxmheaders
        )
        if not data:
            self.log("Error creating device session")
            return False

        data = self.post(
            "session/v1/sessions/anonymous", {}, authenticate=False, headers=sxmheaders
        )
        if not data:
            self.log("Error validating anonymous session")
            return False

        return "accessToken" in data and self.is_logged_in()

    def authenticate(self) -> bool:
        if not self.is_logged_in():
            if not self.login():
                self.log("Login failed during authenticate")
                return False

        postdata = {"handle": self.username, "password": self.password}
        data = self.post(
            "identity/v1/identities/authenticate/password", postdata, authenticate=False
        )
        if not data:
            return False

        autheddata = self.post(
            "session/v1/sessions/authenticated", {}, authenticate=False
        )
        self.log(f"authed - {autheddata}")
        try:
            return autheddata["sessionType"] == "authenticated" and self.is_logged_in()
        except KeyError:
            self.log("Error parsing authentication response")
            return False

    def get_channels(self) -> Optional[List[Dict]]:
        if self.channels is not None:
            return self.channels

        self.channels = []
        initData = {
            "containerConfiguration": {
                "3JoBfOCIwo6FmTpzM1S2H7": {
                    "filter": {"one": {"filterId": "all"}},
                    "sets": {
                        "5mqCLZ21qAwnufKT8puUiM": {
                            "sort": {"sortId": "CHANNEL_NUMBER_ASC"}
                        }
                    },
                }
            },
            "pagination": {"offset": {"containerLimit": 3, "setItemsLimit": 50}},
            "deviceCapabilities": {"supportsDownloads": False},
        }
        data = self.post(
            "browse/v1/pages/curated-grouping/403ab6a5-d3c9-4c2a-a722-a94a6a5fd056/view",
            initData,
        )
        if not data:
            self.log("Unable to get init channel list")
            return None

        try:
            first_container = data["page"]["containers"][0]
            for channel in first_container["sets"][0]["items"]:
                self.channels.append(self._parse_channel(channel))

            channellen = first_container["sets"][0]["pagination"]["offset"]["size"]
            # Fetch remaining channels in chunks of 50
            for offset in range(50, channellen, 50):
                postdata = {
                    "filter": {"one": {"filterId": "all"}},
                    "sets": {
                        "5mqCLZ21qAwnufKT8puUiM": {
                            "sort": {"sortId": "CHANNEL_NUMBER_ASC"},
                            "pagination": {
                                "offset": {
                                    "setItemsOffset": offset,
                                    "setItemsLimit": 50,
                                }
                            },
                        }
                    },
                    "pagination": {"offset": {"setItemsLimit": 50}},
                }
                chunk_data = self.post(
                    "browse/v1/pages/curated-grouping/403ab6a5-d3c9-4c2a-a722-a94a6a5fd056/containers/3JoBfOCIwo6FmTpzM1S2H7/view",
                    postdata,
                    initData,
                )
                if not chunk_data:
                    self.log("Unable to fetch channel list chunk")
                    return None
                for channel in chunk_data["container"]["sets"][0]["items"]:
                    self.channels.append(self._parse_channel(channel))

        except (KeyError, IndexError) as e:
            self.log(f"Error parsing channel data: {e}")
            return None

        return self.channels

    def _parse_channel(self, channel: dict) -> Dict:
        title = channel["entity"]["texts"]["title"]["default"]
        description = channel["entity"]["texts"]["description"]["default"]
        genre = channel["decorations"].get("genre", "")
        channel_type = channel["actions"]["play"][0]["entity"]["type"]
        logo = channel["entity"]["images"]["tile"]["aspect_1x1"]["preferred"]["url"]
        logo_width = channel["entity"]["images"]["tile"]["aspect_1x1"]["preferred"][
            "width"
        ]
        logo_height = channel["entity"]["images"]["tile"]["aspect_1x1"]["preferred"][
            "height"
        ]
        id = channel["entity"]["id"]
        channel_number = channel["decorations"].get("channelNumber", "")

        jsonlogo = json.dumps(
            {
                "key": logo,
                "edits": [
                    {"format": {"type": "jpeg"}},
                    {"resize": {"width": logo_width, "height": logo_height}},
                ],
            },
            separators=(",", ":"),
        )
        b64logo = base64.b64encode(jsonlogo.encode("ascii")).decode("utf-8")

        return {
            "title": title,
            "description": description,
            "genre": genre,
            "channel_type": channel_type,
            "logo": self.CDN_URL.format(b64logo),
            "url": f"/listen/{id}",
            "id": id,
            "channel_number": channel_number,  # TVG-ID
        }

    def get_channel_info(self, channel_id: str) -> Optional[Dict]:
        if not self.channels:
            self.get_channels()
        for ch in self.channels or []:
            if ch["id"] == channel_id:
                return ch
        return None

    def get_channel_info_by_number(self, channel_number: int) -> Optional[Dict]:
        if not self.channels:
            self.get_channels()
        for ch in self.channels or []:
            if int(ch["channel_number"]) == int(channel_number):
                return ch
        return None

    def get_metadata(self, channel_id: str):
        postdata = {
            "id": channel_id,
            "type": "channel-linear",
            "hlsVersion": "V3",
            "manifestVariant": "WEB",
            "mtcVersion": "V2",
        }
        data = self.post("playback/play/v1/tuneSource", postdata, authenticate=True)
        if not data:
            self.log(f"Couldn't get metadata for channel {channel_id}")
            return None
        return data

    def get_now_playing(self, channel_id: str) -> Optional[dict]:
        data = self.get_metadata(channel_id)
        if not data:
            self.log(f"No metadata found for now playing on channel {channel_id}")
            return None
        try:
            live_metadata = data["streams"][0]["metadata"]["live"]["items"][0]
            return {
                "songTitle": live_metadata.get("name", ""),
                "artist": live_metadata.get("artistName", ""),
                "album": live_metadata.get("albumName", ""),
                "image": live_metadata.get("images", {})
                .get("tile", {})
                .get("aspect_1x1", {})
                .get("preferredImage", {})
                .get("url", ""),
            }
        except (KeyError, IndexError) as e:
            self.log(f"Error parsing now playing data for {channel_id}: {e}")
            return None

    def get_tuner(
        self, channel_id: str, session_id: Optional[str] = None
    ) -> Union[Dict, bool]:
        channel_info = self.get_channel_info(channel_id)
        if not channel_info:
            self.log(f"Channel info not found for id {channel_id}")
            return False

        channel_type = channel_info.get("channel_type", "channel-linear")
        is_xtra = channel_type == "channel-xtra"

        # If Xtra with existing sessionId, attempt to peek
        if is_xtra and session_id and session_id in self.xtra_streams:
            streaminfo = self.xtra_streams[session_id]
            postdata = {
                "id": channel_id,
                "type": channel_type,
                "hlsVersion": "V3",
                "mtcVersion": "V2",
                "sourceContextId": streaminfo.get("sourceContextId"),
            }
            data = self.post("playback/play/v1/peek", postdata, authenticate=True)
        else:
            postdata = {
                "id": channel_id,
                "type": channel_type,
                "hlsVersion": "V3",
                "manifestVariant": (
                    "WEB" if channel_type == "channel-linear" else "FULL"
                ),
                "mtcVersion": "V2",
            }
            data = self.post("playback/play/v1/tuneSource", postdata, authenticate=True)

        if not data:
            self.log(f"Couldn't tune channel {channel_id}")
            return False

        streaminfo = {}
        primarystreamurl = data["streams"][0]["urls"][0]["url"]
        base_url, m3u8_loc = primarystreamurl.rsplit("/", 1)
        streaminfo["base_url"] = base_url
        streaminfo["sources"] = m3u8_loc
        streaminfo["chid"] = base_url.split("/")[-2]

        # Xtra session info
        if is_xtra:
            session_id = str(random.randint(10**37, 10**38))
            streaminfo["sessionId"] = session_id
            streaminfo["expires"] = time.time() + 600  # expires in 10 minutes
            streaminfo["sourceContextId"] = data["streams"][0]["metadata"]["xtra"][
                "sourceContextId"
            ]
            self.xtra_streams[session_id] = streaminfo

        streamdata = self.sfetch(primarystreamurl)
        if not streamdata:
            self.log("Failed to fetch m3u8 stream details")
            return False

        streamdata = streamdata.decode("utf-8")
        for line in streamdata.splitlines():
            if "256k" in line and line.endswith("m3u8"):
                streaminfo["quality"] = line
                streaminfo["HLS"] = line.split("/")[0]

        self.channel_urls[channel_id] = streaminfo
        return streaminfo

    def get_tuner_cached(self, session_id: str) -> Optional[Dict]:
        streaminfo = self.xtra_streams.get(session_id)
        if streaminfo and streaminfo.get("expires", 0) > time.time():
            return streaminfo
        if session_id in self.xtra_streams:
            del self.xtra_streams[session_id]
        return None

    def get_channel(
        self, channel_id: str, session_id: Optional[str] = None
    ) -> Union[bytes, bool]:
        if session_id:
            streaminfo = self.get_tuner_cached(session_id)
            if not streaminfo:
                # Session expired, retune
                streaminfo = self.get_tuner(channel_id)
        else:
            streaminfo = self.channel_urls.get(channel_id)
            if not streaminfo:
                streaminfo = self.get_tuner(channel_id)

        if not streaminfo:
            self.log(f"No stream info for channel id {channel_id}")
            return False

        aacurl = f"{streaminfo['base_url']}/{streaminfo['quality']}"
        data = self.sfetch(aacurl)
        if not data:
            self.log("Failed to fetch AAC stream list")
            return False

        data_str = data.decode("utf-8").replace(
            "https://api.edge-gateway.siriusxm.com/playback/key/v1/", "/key/", 1
        )
        lines = data_str.splitlines()
        for i, line in enumerate(lines):
            if line.rstrip().endswith(".aac"):
                if session_id:
                    lines[i] = f"{channel_id}/{line}?session_id={session_id}"
                else:
                    lines[i] = f"{channel_id}/{line}"
        return "\n".join(lines).encode("utf-8")

    def get_segment(
        self, channel_id: str, segment: str, session_id: Optional[str] = None
    ) -> Optional[bytes]:
        if session_id:
            streaminfo = self.get_tuner_cached(session_id)
            if not streaminfo:
                streaminfo = self.get_tuner(channel_id)
        else:
            streaminfo = self.channel_urls.get(channel_id)
            if not streaminfo:
                streaminfo = self.get_tuner(channel_id)

        if not streaminfo:
            self.log(f"No stream info for channel id {channel_id}")
            return None

        baseurl = streaminfo["base_url"]
        HLStag = streaminfo["HLS"]
        segmenturl = f"{baseurl}/{HLStag}/{segment}"
        if session_id:
            segmenturl += f"?session_id={session_id}"

        self.log(f"Fetching segment URL: {segmenturl}")
        data = self.sfetch(segmenturl)
        if not data:
            self.log(f"Failed to fetch segment {segment} for channel {channel_id}")
        return data

    def getAESkey(self, uuid: str) -> Union[str, bool]:
        data = self.get(f"playback/key/v1/{uuid}")
        if not data:
            self.log("AES Key fetch error.")
            return False
        return data.get("key", False)

    def get_playlist(self) -> Optional[str]:
        if not self.channels:
            self.get_channels()
        if not self.m3u8dat:
            data = ["#EXTM3U"]
            m3umetadata = '#EXTINF:-1 tvg-id="{}" tvg-logo="{}" group-title="{}",{}\n{}'
            for channel in self.channels or []:
                title = channel["title"]
                genre = channel["genre"]
                logo = channel["logo"]
                url = f"/listen/{channel['id']}"
                tvg_id = channel.get("channel_number", "")
                data.append(m3umetadata.format(tvg_id, logo, genre, title, url))
            self.m3u8dat = "\n".join(data)
        return self.m3u8dat

    def _cleanup_xtra_sessions(self):
        while True:
            now = time.time()
            expired = [
                k for k, v in self.xtra_streams.items() if v.get("expires", 0) < now
            ]
            for k in expired:
                self.log(f"Cleaning up expired Xtra session {k}")
                del self.xtra_streams[k]
            time.sleep(60)
