import base64
import json
import logging
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from http import HTTPStatus

from fastapi import HTTPException

from soundcork.config import Settings
from soundcork.model import (
    Audio,
    BmxNowPlaying,
    BmxOauthToken,
    BmxPlaybackResponse,
    BmxPodcastInfoResponse,
    BmxReporting,
    Stream,
    Track,
)
from soundcork.sxm import SiriusXM
from soundcork.utils import strip_element_text

logger = logging.getLogger(__name__)

# TODO: move into constants file eventually.
TUNEIN_DESCRIBE = "https://opml.radiotime.com/describe.ashx?id=%s"
TUNEIN_STREAM = "http://opml.radiotime.com/Tune.ashx?id=%s&formats=mp3,aac,ogg"


# TODO:  determine how listen_id is used, if at all
# TODO:  determine how stream_id is used, if at all
# TODO:  see if there is a value to varying the timeout values
def tunein_playback(station_id: str) -> BmxPlaybackResponse:
    describe_url = TUNEIN_DESCRIBE % station_id
    contents = urllib.request.urlopen(describe_url).read()
    content_str = contents.decode("utf-8")

    root = ET.fromstring(content_str)

    try:
        body = root.find("body")
        outline = body.find("outline")  # type: ignore
        station_elem = outline.find("station")  # type: ignore
    except Exception as e:
        # TODO narrow this exception
        outline = None
        station_elem = None

    name = strip_element_text(station_elem.find("name")) if station_elem else ""
    logo = strip_element_text(station_elem.find("logo")) if station_elem else ""

    # not using these now but leaving the code in for use later
    # current_song_elem = station_elem.find("current_song")
    # current_song = current_song_elem.text if current_song_elem != None else ""
    # current_artist_elem = station_elem.find("current_artist")
    # current_artist = current_artist_elem.text if current_artist_elem != None else ""

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


def tunein_podcast_info(podcast_id: str, encoded_name: str) -> BmxPodcastInfoResponse:

    name = str(base64.urlsafe_b64decode(encoded_name), "utf-8")
    track = Track(
        links={"bmx_track": {"href": f"/v1/playback/episode/{podcast_id}"}},
        is_selected=False,
        name=name,
    )
    resp = BmxPodcastInfoResponse(
        links={
            "self": {
                "href": f"/v1/playback/episodes/{podcast_id}?encoded_name={encoded_name}"
            },
        },
        name=name,
        shuffle_disabled=True,
        repeat_disabled=True,
        stream_type="onDemand",
        tracks=[track],
    )
    return resp


# TODO:  determine how listen_id is used, if at all
# TODO:  determine how stream_id is used, if at all
# TODO:  see if there is a value to varying the timeout values
def tunein_playback_podcast(podcast_id: str) -> BmxPlaybackResponse:

    describe_url = TUNEIN_DESCRIBE % podcast_id
    contents = urllib.request.urlopen(describe_url).read()
    content_str = contents.decode("utf-8")

    root = ET.fromstring(content_str)

    try:
        body = root.find("body")
        outline = body.find("outline")  # type: ignore
        topic = outline.find("topic")  # type: ignore
    except Exception as e:
        # TODO narrow this exception
        outline = None
        topic = None
    title = strip_element_text(topic.find("title")) if topic else ""
    show_title = strip_element_text(topic.find("show_title")) if topic else ""
    duration = strip_element_text(topic.find("duration")) if topic else ""
    show_id = strip_element_text(topic.find("show_id")) if topic else ""
    logo = strip_element_text(topic.find("logo")) if topic else ""

    streamreq = TUNEIN_STREAM % podcast_id
    stream_url_resp = urllib.request.urlopen(streamreq).read().decode("utf-8")

    # these might be used by later calls to bmx_reporting and/or now-playing,
    # so we might need to give them actual values
    stream_id = "e3342"
    listen_id = str(3432432423)
    bmx_reporting_qs = urllib.parse.urlencode(
        {
            "stream_id": stream_id,
            "guide_id": podcast_id,
            "listen_id": listen_id,
            "stream_type": "onDemand",
        }
    )
    bmx_reporting = "/v1/report?" + bmx_reporting_qs

    stream_url_list = stream_url_resp.splitlines()
    stream_list = [
        Stream(
            links={"bmx_reporting": {"href": bmx_reporting}},
            hasPlaylist=True,
            isRealtime=False,
            maxTimeout=60,
            bufferingTimeout=20,
            connectingTimeout=10,
            streamUrl=stream_url,
        )
        for stream_url in stream_url_list
    ]

    audio = Audio(
        hasPlaylist=True,
        isRealtime=False,
        maxTimeout=60,
        streamUrl=stream_url_list[0],
        streams=stream_list,
    )
    resp = BmxPlaybackResponse(
        links={
            "bmx_favorite": {"href": f"/v1/favorite/{show_id}"},
            "bmx_reporting": {"href": bmx_reporting},
        },
        artist={"name": show_title},
        audio=audio,
        duration=int(duration),
        imageUrl=logo,
        isFavorite=False,
        name=title,
        shuffle_disabled=True,
        repeat_disabled=True,
        streamType="onDemand",
    )
    return resp


def play_custom_stream(data: str) -> BmxPlaybackResponse:
    # data comes in as base64-encoded json with fields
    # streamUrl, imageUrl, and name
    json_str = base64.urlsafe_b64decode(data)
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


def siriusxm_access_token(refresh_payload: str) -> BmxOauthToken:
    #  refresh_payloard in {"grant_type":"refresh_token","refresh_token": "{token}"
    try:
        grant_request = json.loads(refresh_payload)
        if grant_request.get("grant_type", "") == "refresh_token":
            logger.info("grant request")
            links = {"self": {"href": "/token"}}
            refresh_token = grant_request.get("refresh_token", "")
            refresh_token_obj = json.loads(base64.b64decode(refresh_token))
            rt_payload = refresh_token_obj.get("payload", "")
            payload_obj = json.loads(base64.b64decode(rt_payload))
            player_id = payload_obj.get("playerId", "")
            at_payload_obj = {
                "playerId": player_id,
                "routingUrl": "https://streamingapi2-east.mountain.siriusxm.com",
                "template": "HLSP",
                "lineupId": "400",
            }
            at_payload = base64.b64encode(
                bytes(json.dumps(at_payload_obj), "utf-8")
            ).decode()
            access_token_obj = {"payload": at_payload, "code": "12345"}
            access_token = base64.b64encode(
                bytes(json.dumps(access_token_obj), "utf-8")
            ).decode()
            # test to make sure generated value is correct
            if siriusxm_player_from_token(access_token):
                return BmxOauthToken(
                    links=links, access_token=access_token, refresh_token=refresh_token
                )
    except Exception as e:
        logger.info(f"exception handing refresh token {e}")
        pass

    raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid refresh request")


def siriusxm_player_from_token(access_token: str) -> str:
    logger.info(f"getting player from access_token {access_token}")
    # access_token should be a BmxOauthToken where the payload has an embedded playerId
    try:
        payload = json.loads(base64.b64decode(access_token)).get("payload", "")
        logger.info(f"payload={payload}")
        player_id = json.loads(base64.b64decode(payload)).get("playerId", "")
        logger.info(f"player_id={player_id}")
        if player_id:
            return player_id
    except Exception as e:
        logger.info(f"exception {e}")
        pass

    raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid token")


def play_siriusxm_station(
    sxm: SiriusXM, station: str, player_id: str
) -> BmxPlaybackResponse:
    logger.info(f"playing sxm {station}")
    guid, channel_id = sxm.get_channel(station)
    logger.info(f"playlist={sxm.get_playlist_url(guid, channel_id)}")
    # channel_by_number = sxm.get_channel_info_by_number(station)
    # tuner = sxm.get_tuner(channel_by_number["id"])
    # stream_url = f"{tuner['base_url']}{tuner['sources']}"
    stream_url = sxm.get_bmx_playback(guid, channel_id, player_id, station)
    channel_info = sxm.get_channel_info(station)
    # logger.info(f"channelinfo={channel_info}")
    image_url = ""
    for image in channel_info.get("images", {}).get("images", {}):
        if image.get("name", "") == "list view channel logo":
            image_url = image.get("url", "")
            break

    # image_url = "http://pri.art.prod.streaming.siriusxm.com/images/chan/84/79e99c-eff4-c36e-b1a5-dde0aa457787.png"
    name = channel_info.get("name", "")

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
        imageUrl=image_url,
        isFavorite=False,
        name=name,
        restrictions={"inactivityTimeout": 28800},
        streamType="liveRadio",
    )
    return resp


def now_playing_siriusxm(sxm: SiriusXM, station_name: str, date: str) -> BmxNowPlaying:

    channel = sxm.get_channel_info(station_name)

    if channel:
        # now_playing = sxm.get_now_playing(channel["id"])
        now_playing = sxm.get_now_playing(station_name, date)
        if not now_playing:
            now_playing = {"artist": "test artist", "songTitle": "song title"}

    else:
        now_playing = {"artist": "test artist", "songTitle": "song title"}

    resp = BmxNowPlaying(
        links={
            "self": {
                "href": f"/now-playing/{station_name}?a={{absolutePlayPoint}}",
                "templated": True,
            },
        },
        artist=now_playing.get("artist", ""),
        album=now_playing.get("album", ""),
        image_url=now_playing.get("image_url", ""),
        track=now_playing.get("track"),
        ask_again_after=10,
    )
    return resp


def reporting_siriusxm(payload: str, station: str) -> BmxReporting:
    report = json.loads(payload)

    default_timestamp = datetime.now().isoformat()
    stream_timestamp = report.get("absolutePlayPoint", default_timestamp)
    event_timestamp = report.get("timeStamp", default_timestamp)

    last_report = {
        "marker": str(uuid.uuid4()),
        "stream_timestamp": stream_timestamp,
        "event_timestamp": event_timestamp,
    }
    last_report_json = json.dumps(last_report)
    last_report_encoded = urllib.parse.quote_plus(
        str(base64.b64encode(bytes(last_report_json, "utf-8")), "utf-8")
    )
    return BmxReporting(
        links={
            "self": {
                "href": f"/reporting/live/{station}?lastReport={last_report_encoded}"
            }
        },
        next_report_in=0,
    )
