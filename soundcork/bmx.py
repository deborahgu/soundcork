import base64
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

<<<<<<< Updated upstream
from soundcork.model import Audio, BmxPlaybackResponse, Stream
=======
from soundcork.model import (
    Audio,
    BmxNowPlaying,
    BmxPlaybackResponse,
    BmxPodcastInfoResponse,
    Stream,
    Track,
)
from soundcork.siriusxm_fastapi import SiriusXM
>>>>>>> Stashed changes

# TODO: move into constants file eventually.
TUNEIN_DESCRIBE = "https://opml.radiotime.com/describe.ashx?id=%s"
TUNEIN_STREAM = "http://opml.radiotime.com/Tune.ashx?id=%s"


# TODO:  determine how listen_id is used, if at all
# TODO:  determine how stream_id is used, if at all
# TODO:  see if there is a value to varying the timeout values
def tunein_playback(station_id: str) -> BmxPlaybackResponse:
    describe_url = TUNEIN_DESCRIBE % station_id
    contents = urllib.request.urlopen(describe_url).read()
    content_str = contents.decode("utf-8")

    root = ET.fromstring(content_str)

    body = root.find("body")

    outline = body.find("outline")
    station_elem = outline.find("station")
    name = station_elem.find("name").text
    logo = station_elem.find("logo").text

    # not using these now but leaving the code in for use later
    current_song_elem = station_elem.find("current_song")
    current_song = current_song_elem.text if current_song_elem != None else ""
    current_artist_elem = station_elem.find("current_artist")
    current_artist = current_artist_elem.text if current_artist_elem != None else ""

    streamreq = TUNEIN_STREAM % station_id
    stream_url_resp = urllib.request.urlopen(streamreq).read().decode("utf-8")

    # these might be used by later calls to bmx_reporting and/or now-playing,
    # so we might need to give them actual values
    stream_id = "e3342"
    listen_id = str(3432432423)
    bmx_reporting_qs = urllib.parse.urlencode(
        {
            "stream_id": stream_id,
            "guide_id": station_id,
            "listen_id": listen_id,
            "stream_type": "liveRadio",
        }
    )
    bmx_reporting = "/v1/report?" + bmx_reporting_qs

    stream_url_list = stream_url_resp.splitlines()
    stream_list = [
        Stream(
            links={"bmx_reporting": {"href": bmx_reporting}},
            hasPlaylist=True,
            isRealtime=True,
            maxTimeout=60,
            bufferingTimeout=20,
            connectingTimeout=10,
            streamUrl=stream_url,
        )
        for stream_url in stream_url_list
    ]

    audio = Audio(
        hasPlaylist=True,
        isRealtime=True,
        maxTimeout=60,
        streamUrl=stream_url_list[0],
        streams=stream_list,
    )
    resp = BmxPlaybackResponse(
        links={
            "bmx_favorite": {"href": "/v1/favorite/" + station_id},
            "bmx_nowplaying": {
                "href": "/v1/now-playing/station/" + station_id,
                "useInternalClient": "ALWAYS",
            },
            "bmx_reporting": {"href": bmx_reporting},
        },
        audio=audio,
        imageUrl=logo,
        isFavorite=False,
        name=name,
        streamType="liveRadio",
    )
    return resp


def play_custom_stream(data: str) -> BmxPlaybackResponse:
    # data comes in as base64-encoded json with fields
    # streamUrl, imageUrl, and name
    json_str = base64.b64decode(data)
    json_obj = json.loads(json_str)
    stream_list = [
        Stream(
            hasPlaylist=True,
            isRealtime=True,
            streamUrl=json_obj["streamUrl"],
        )
    ]

    audio = Audio(
        hasPlaylist=True,
        isRealtime=True,
        streamUrl=json_obj["streamUrl"],
        streams=stream_list,
    )
    resp = BmxPlaybackResponse(
        audio=audio,
        imageUrl=json_obj["imageUrl"],
        name=json_obj["name"],
        streamType="liveRadio",
    )
    return resp


def play_siriusxm_station(sxm: SiriusXM, station: int) -> BmxPlaybackResponse:
    # channel_by_number = sxm.get_channel_info_by_number(station)
    # tuner = sxm.get_tuner(channel_by_number["id"])
    # stream_url = f"{tuner['base_url']}{tuner['sources']}"
    stream_url = f"http://10.0.0.186:8000/listen/{station}.m3u8"
    stream_id = "s3342"
    listen_id = str(3432432423)

    stream_list = [
        Stream(
            hasPlaylist=True,
            isRealtime=True,
            maxTimeout=60,
            bufferingTimeout=12,
            connectingTimeout=10,
            streamUrl=stream_url,
            start_at_live_point=False,
        )
    ]

    audio = Audio(
        hasPlaylist=True,
        isRealtime=True,
        streamUrl=stream_url,
        streams=stream_list,
    )
    resp = BmxPlaybackResponse(
        links={
            "bmx_favorite": {"href": f"/favorite/station/{station}"},
            "bmx_nowplaying": {
                "href": f"/now-playing/{station}?a={{absolutePlayPoint}}",
                "templated": True,
            },
            "bmx_reporting": {"href": f"/reporting/live/{station}"},
        },
        audio=audio,
        imageUrl="http://pri.art.prod.streaming.siriusxm.com/images/chan/84/79e99c-eff4-c36e-b1a5-dde0aa457787.png",
        isFavorite=False,
        name="First Wave",
        restrictions={"inactivityTimeout": 28800},
        streamType="liveRadio",
    )
    return resp


def now_playing_siriusxm(sxm: SiriusXM, station: int) -> BmxNowPlaying:
    channels = sxm.get_channels()
    # print(f"channels = {channels}")
    # channel_info = sxm.get_channel_info(station)
    # print(f"channel_info = {channel_info}")
    # channel = sxm.get_channel(station)
    # print(f"channel = {channel}")

    channel_by_number = sxm.get_channel_info_by_number(station)
    if not channel_by_number:
        channel_by_number = channels[0]
    # print(f"channel by number {station} = {channel_by_number}")
    if channel_by_number:
        now_playing = sxm.get_now_playing(channel_by_number["id"])
        # print(f"now_playing = {now_playing}")
    else:
        now_playing = {"artist": "test artist", "songTitle": "song title"}

    resp = BmxNowPlaying(
        links={
            "self": {
                "href": f"/now-playing/{station}?a={{absolutePlayPoint}}",
                "templated": True,
            },
        },
        artist=now_playing.get("artist", ""),
        track=now_playing.get("songTitle"),
        ask_again_after=10,
    )
    return resp
