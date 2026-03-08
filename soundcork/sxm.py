import argparse
import base64
import datetime
import json
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


class SiriusXM:
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/604.5.6 (KHTML, like Gecko) Version/11.0.3 Safari/604.5.6"
    REST_FORMAT = "https://player.siriusxm.com/rest/v2/experience/modules/{}"
    LIVE_PRIMARY_HLS = "https://siriusxm-priprodlive.akamaized.net"
    LIVE_BMX_PLAYBACK = "https://hlspproduction2e-primary.mountain.siriusxm.com/r/sessionid/{session_id}{player_id}{station_id}"

    def __init__(self, username, password):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
        self.username = username
        self.password = password
        self.playlists = {}
        self.channels = None

    @staticmethod
    def log(x):
        print(
            "{} <SiriusXM>: {}".format(
                datetime.datetime.now().strftime("%d.%b %Y %H:%M:%S"), x
            )
        )

    def is_logged_in(self):
        #        self.log(f"checking cookies {self.session.cookies}")
        return "SXMAUTHNEW" in self.session.cookies

    def is_session_authenticated(self):
        return (
            "AUTH_NEW_ATLAS" in self.session.cookies
            and "SXMDATA" in self.session.cookies
        )

    def get(self, method, params, authenticate=True):
        if (
            authenticate
            and not self.is_session_authenticated()
            and not self.authenticate()
        ):
            self.log("Unable to authenticate")
            return None

        res = self.session.get(self.REST_FORMAT.format(method), params=params)
        if res.status_code != 200:
            self.log(
                "Received status code {} for method '{}'".format(
                    res.status_code, method
                )
            )
            return None

        try:
            return res.json()
        except ValueError:
            self.log("Error decoding json for method '{}'".format(method))
            return None

    def post(self, method, postdata, authenticate=True):
        if (
            authenticate
            and not self.is_session_authenticated()
            and not self.authenticate()
        ):
            self.log("Unable to authenticate")
            return None

        res = self.session.post(
            self.REST_FORMAT.format(method), data=json.dumps(postdata)
        )
        if res.status_code != 200:
            self.log(
                "Received status code {} for method '{}'".format(
                    res.status_code, method
                )
            )
            return None

        try:
            return res.json()
        except ValueError:
            self.log("Error decoding json for method '{}'".format(method))
            return None

    def login(self):
        postdata = {
            "moduleList": {
                "modules": [
                    {
                        "moduleRequest": {
                            "resultTemplate": "web",
                            "deviceInfo": {
                                "osVersion": "Mac",
                                "platform": "Web",
                                "sxmAppVersion": "3.1802.10011.0",
                                "browser": "Safari",
                                "browserVersion": "11.0.3",
                                "appRegion": "US",
                                "deviceModel": "K2WebClient",
                                "clientDeviceId": "null",
                                "player": "html5",
                                "clientDeviceType": "web",
                            },
                            "standardAuth": {
                                "username": self.username,
                                "password": self.password,
                            },
                        },
                    }
                ],
            },
        }
        # self.log(f"logging in; postdata={postdata}")
        data = self.post("modify/authentication", postdata, authenticate=False)
        if not data:
            self.log("no data")
            return False

        try:
            return data["ModuleListResponse"]["status"] == 1 and self.is_logged_in()
        except KeyError:
            self.log("Error decoding json response for login")
            return False

    def authenticate(self):
        if not self.is_logged_in() and not self.login():
            self.log("Unable to authenticate because login failed")
            return False

        postdata = {
            "moduleList": {
                "modules": [
                    {
                        "moduleRequest": {
                            "resultTemplate": "web",
                            "deviceInfo": {
                                "osVersion": "Mac",
                                "platform": "Web",
                                "clientDeviceType": "web",
                                "sxmAppVersion": "3.1802.10011.0",
                                "browser": "Safari",
                                "browserVersion": "11.0.3",
                                "appRegion": "US",
                                "deviceModel": "K2WebClient",
                                "player": "html5",
                                "clientDeviceId": "null",
                            },
                        }
                    }
                ]
            }
        }
        data = self.post("resume?OAtrial=false", postdata, authenticate=False)
        if not data:
            return False

        try:
            return (
                data["ModuleListResponse"]["status"] == 1
                and self.is_session_authenticated()
            )
        except KeyError:
            self.log("Error parsing json response for authentication")
            return False

    def get_sxmak_token(self):
        try:
            return self.session.cookies["SXMAKTOKEN"].split("=", 1)[1].split(",", 1)[0]
        except (KeyError, IndexError):
            return None

    def get_gup_id(self):
        try:
            return json.loads(urllib.parse.unquote(self.session.cookies["SXMDATA"]))[
                "gupId"
            ]
        except (KeyError, ValueError):
            return None

    def get_playlist_url(self, guid, channel_id, use_cache=True, max_attempts=5):
        # self.log(f"get_playlist_url {channel_id}")
        if use_cache and channel_id in self.playlists:
            # self.log("cached?")
            return self.playlists[channel_id]

        # self.log("gpurl: calling with params")
        params = {
            "assetGUID": guid,
            "ccRequestType": "AUDIO_VIDEO",
            "channelId": channel_id,
            "hls_output_mode": "custom",
            "marker_mode": "all_separate_cue_points",
            "result-template": "web",
            "time": int(round(time.time() * 1000.0)),
            "timestamp": datetime.datetime.utcnow().isoformat("T") + "Z",
        }
        # self.log(f"calling now-playing-live with params {params}")
        data = self.get("tune/now-playing-live", params)
        if not data:
            return None

        # get status
        try:
            status = data["ModuleListResponse"]["status"]
            message = data["ModuleListResponse"]["messages"][0]["message"]
            message_code = data["ModuleListResponse"]["messages"][0]["code"]
        except (KeyError, IndexError):
            self.log("Error parsing json response for playlist")
            return None

        # login if session expired
        if message_code == 201 or message_code == 208:
            if max_attempts > 0:
                self.log("Session expired, logging in and authenticating")
                if self.authenticate():
                    self.log("Successfully authenticated")
                    return self.get_playlist_url(
                        guid, channel_id, use_cache, max_attempts - 1
                    )
                else:
                    self.log("Failed to authenticate")
                    return None
            else:
                self.log("Reached max attempts for playlist")
                return None
        elif message_code != 100:
            self.log("Received error {} {}".format(message_code, message))
            return None

        # get m3u8 url
        try:
            # data_json = json.dumps(data)
            # with open(
            #    "/home/allen/working/bose/siriusxm/fulldata.json", "w"
            # ) as json_file:
            #    json_file.write(data_json)

            playlists = data["ModuleListResponse"]["moduleList"]["modules"][0][
                "moduleResponse"
            ]["liveChannelData"]["hlsAudioInfos"]
        except (KeyError, IndexError):
            self.log("Error parsing json response for playlist")
            return None
        # for playlist_info in playlists:
        #    self.log(f"playlisturl={playlist_info['url']}")
        for playlist_info in playlists:
            if playlist_info["size"] == "LARGE":
                playlist_url = playlist_info["url"].replace(
                    "%Live_Primary_HLS%", self.LIVE_PRIMARY_HLS
                )
                self.playlists[channel_id] = self.get_playlist_variant_url(playlist_url)
                return self.playlists[channel_id]

        return None

    def get_playlist_variant_url(self, url):
        params = {
            "token": self.get_sxmak_token(),
            "consumer": "k2",
            "gupId": self.get_gup_id(),
        }
        res = self.session.get(url, params=params)

        if res.status_code != 200:
            self.log(
                "Received status code {} on playlist variant retrieval".format(
                    res.status_code
                )
            )
            return None

        for x in res.text.split("\n"):
            if x.rstrip().endswith(".m3u8"):
                # first variant should be 256k one
                return "{}/{}".format(url.rsplit("/", 1)[0], x.rstrip())

        return None

    def get_playlist(self, name, use_cache=True):
        guid, channel_id = self.get_channel(name)
        if not guid or not channel_id:
            self.log("No channel for {}".format(name))
            return None

        url = self.get_playlist_url(guid, channel_id, use_cache)
        # self.log(f"got url {url}")
        params = {
            "token": self.get_sxmak_token(),
            "consumer": "k2",
            "gupId": self.get_gup_id(),
        }
        res = self.session.get(url, params=params)

        if res.status_code == 403:
            self.log("Received status code 403 on playlist, renewing session")
            return self.get_playlist(name, False)

        if res.status_code != 200:
            self.log(
                "Received status code {} on playlist variant".format(res.status_code)
            )
            return None

        # add base path to segments
        base_url = url.rsplit("/", 1)[0]
        base_path = base_url[8:].split("/", 1)[1]
        lines = res.text.split("\n")
        for x in range(len(lines)):
            if lines[x].rstrip().endswith(".aac"):
                lines[x] = "{}/{}".format(base_path, lines[x])
        return "\n".join(lines)

    def get_channels(self):
        # download channel list if necessary
        if not self.channels:
            postdata = {
                "moduleList": {
                    "modules": [
                        {
                            "moduleArea": "Discovery",
                            "moduleType": "ChannelListing",
                            "moduleRequest": {
                                "consumeRequests": [],
                                "resultTemplate": "responsive",
                                "alerts": [],
                                "profileInfos": [],
                            },
                        }
                    ]
                }
            }
            data = self.post("get", postdata)
            if not data:
                self.log("Unable to get channel list")
                return (None, None)

            try:
                self.channels = data["ModuleListResponse"]["moduleList"]["modules"][0][
                    "moduleResponse"
                ]["contentData"]["channelListing"]["channels"]
            except (KeyError, IndexError):
                self.log("Error parsing json response for channels")
                return []
        return self.channels

    def get_channel(self, name):
        name = name.lower()
        for x in self.get_channels():
            if (
                x.get("name", "").lower() == name
                or x.get("channelId", "").lower() == name
                or x.get("siriusChannelNumber") == name
            ):
                return (x["channelGuid"], x["channelId"])
        return (None, None)

    def get_channel_info(self, name):
        name = name.lower()
        for x in self.get_channels():
            if (
                x.get("name", "").lower() == name
                or x.get("channelId", "").lower() == name
                or x.get("siriusChannelNumber") == name
            ):
                return x
        return None

    def get_channel_data(
        self, guid, channel_id, use_cache=False, max_attempts=5
    ) -> dict:
        # self.log(f"get_playlist_url {channel_id}")
        if use_cache and channel_id in self.playlists:
            self.log("cached?")
            return self.playlists[channel_id]

        # self.log("gpurl: calling with params")
        params = {
            "assetGUID": guid,
            "ccRequestType": "AUDIO_VIDEO",
            "channelId": channel_id,
            "hls_output_mode": "custom",
            "marker_mode": "all_separate_cue_points",
            "result-template": "web",
            "time": int(round(time.time() * 1000.0)),
            "timestamp": datetime.datetime.utcnow().isoformat("T") + "Z",
        }
        # self.log(f"calling now-playing-live with params {params}")
        data = self.get("tune/now-playing-live", params)
        if not data:
            return {}

        # get status
        try:
            status = data["ModuleListResponse"]["status"]
            message = data["ModuleListResponse"]["messages"][0]["message"]
            message_code = data["ModuleListResponse"]["messages"][0]["code"]
        except (KeyError, IndexError):
            self.log("Error parsing json response for playlist")
            return {}

        # login if session expired
        if message_code == 201 or message_code == 208:
            if max_attempts > 0:
                self.log("Session expired, logging in and authenticating")
                if self.authenticate():
                    self.log("Successfully authenticated")
                    return self.get_playlist_url(
                        guid, channel_id, use_cache, max_attempts - 1
                    )
                else:
                    self.log("Failed to authenticate")
                    return {}
            else:
                self.log("Reached max attempts for playlist")
                return {}
        elif message_code != 100:
            self.log("Received error {} {}".format(message_code, message))
            return {}

        return data

    def get_bmx_playback(
        self, guid, channel_id, player_id, station_id, use_cache=False, max_attempts=5
    ) -> str:
        data = self.get_channel_data(guid, channel_id)
        # get m3u8 url
        try:
            # data_json = json.dumps(data)
            # with open(
            #    "/home/allen/working/bose/siriusxm/fulldata.json", "w"
            # ) as json_file:
            #    json_file.write(data_json)

            playlists = data["ModuleListResponse"]["moduleList"]["modules"][0][
                "moduleResponse"
            ]["liveChannelData"]["hlsAudioInfos"]
        except (KeyError, IndexError):
            self.log("Error parsing json response for playlist")
            return ""

        session_id = self.get_gup_id()
        playback_format = self.LIVE_BMX_PLAYBACK.format(
            station_id=station_id, player_id=player_id, session_id=session_id
        )
        playlist_url = ""

        for playlist_info in playlists:
            if playlist_info["size"] == "SMALL":

                playlist_url = playlist_info["url"].replace(
                    "%Live_Primary_HLS%", playback_format
                )
                self.playlists[channel_id] = self.get_playlist_variant_url(playlist_url)
                break

        return playlist_url

    def get_now_playing(self, channel_name: str, date: str) -> dict | None:
        guid, channel_id = self.get_channel(channel_name)
        data = self.get_channel_data(guid, channel_id)
        if not data:
            self.log(f"No metadata found for now playing on channel {channel_id}")
            return None
        try:
            markers = data["ModuleListResponse"]["moduleList"]["modules"][0][
                "moduleResponse"
            ]["liveChannelData"]["markerLists"]
            for marker in markers:
                if marker["layer"] == "cut":
                    # testing
                    cut = marker["markers"][-1]["cut"]
                    track = cut.get("title", "")
                    try:
                        artist = cut["artists"][0]["name"]
                    except:
                        artist = ""
                    try:
                        album = cut["album"]["title"]
                    except:
                        album = ""
                    try:
                        image_url = cut["album"]["creativeArts"][0]["url"]
                    except:
                        image_url = ""
                    return {
                        "track": track,
                        "artist": artist,
                        "album": album,
                        "image_url": image_url,
                    }
        except (KeyError, IndexError) as e:
            self.log(f"Error parsing now playing data for {channel_id}: {e}")
            return None
        self.log("failed to find song info")
        return None
