import base64
import json
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from soundcork.model import (
    Audio,
    BmxNavItem,
    BmxNavResponse,
    BmxNavSection,
    BmxPlaybackResponse,
    BmxPodcastInfoResponse,
    Stream,
    Track,
)
from soundcork.utils import strip_element_text

logger = logging.getLogger(__name__)

# TODO: move into constants file eventually.
TUNEIN_DESCRIBE = "https://opml.radiotime.com/describe.ashx?id=%s"
TUNEIN_STREAM = "http://opml.radiotime.com/Tune.ashx?id=%s&formats=mp3,aac,ogg"
TUNEIN_NAVIGATE_ASHX = "http://opml.radiotime.com/?render=json"


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


def tunein_navigate_v1(
    encoded_uri: str = "", subsection: int | None = None
) -> BmxNavResponse:
    """
    tunein navigation has a base level /v1/navigate plus an optional /sub/{n}
    to indicate a particular subsection, plus an optional base64-encoded uri
    to show the source url used to populate the navigation. if no encoded uri
    is included, use the top level TUNEIN_NAVIGATE_ASHX instead.

    the tunein browse pages get a bit large for a single page, for instance where
    you request local radio and it returns every single FM station, every single
    AM station, and every local internet-only station from a single request. so
    bose by default would collapse each category into a 'ribbon' menu where it
    would show the first 5 entries and then a 'more' link. the 'more' link would
    then call the /v1/navigate/sub/{subsection number}/{encoded uri} endpoint,
    which in turn would show all the entries in the particular subsection. so with
    the above example, /v1/navigate/{local-radio-uri} would display three 'ribbon'
    menus with 5 FM, 5 AM, and 5 internet-only stations. if you clicked on the
    'more' button for internet-only, it would call /v1/navigate/sub/2/(local-radio-uri},
    which in turn would display all of the entries in the 'internet-only' subsection
    (and only those, not the AM or FM stations) as a single grid.

    The actual bose implementation seems to have some customized behavior where they
    display lists that don't match any tunein endpoints that I was able to find. In
    theory we could build such a custom menu, too, but that's a bit much for a first pass.

    Also for context: the bose bmx navigate endpoint is clearly designed specifically
    for the stockholm application, which uses the responses from the server to
    determine what information to show on which pages as well as what layout to use.
    This first implementation for soundcork follows that pattern as closely as possible.
    Future interactions for other clients could be implemented in different ways, perhaps
    as v2.
    """
    bmx_search_link = None
    if encoded_uri:
        tunein_uri = base64.urlsafe_b64decode(encoded_uri).decode()
    else:
        tunein_uri = TUNEIN_NAVIGATE_ASHX
        # search only shows at the top level
        bmx_search_link = {
            "filters": [],
            "href": "/v1/search?q={query}",
            "templated": True,
        }

    # this builds all of the sections
    sections = tunein_sections_ashx(tunein_uri, not subsection, subsection)

    # for the self link
    if subsection is not None:
        subsection_part = f"/sub/{subsection}"
    else:
        subsection_part = ""
    if encoded_uri:
        uri_part = f"/{encoded_uri}"
    else:
        uri_part = ""
    links = {
        "self": {"href": f"/v1/navigate{subsection_part}{uri_part}"},
        "bmx_search": bmx_search_link,
        "filters": None,
    }
    return BmxNavResponse(
        links=links,
        bmx_sections=sections,
        layout="classic",
    )


def tunein_sections_ashx(
    tunein_uri: str, add_subsection: bool = False, subsection: int | None = None
) -> list[BmxNavSection]:
    contents = urllib.request.urlopen(tunein_uri).read()
    content_str = contents.decode("utf-8")
    content_json = json.loads(content_str)
    # by default just show all of our items as a simple list
    layout = "list"
    sections = []
    items = []
    body = content_json["body"]

    for idx, item in enumerate(body):
        type = item.get("type", "")
        if type:
            # i only saw top-level items that were of type "link"; "audio" items seemed
            # only to be included as chlidren of subsections.
            if type == "link":
                items.append(tunein_navigate_link(item))
            else:
                logger.info(f"top-level item has type {type}: {item}")
        else:
            logger.debug(f"subsection {subsection} idx {idx}")
            # if we've requested a single subsection then only show items
            # in that subsection
            if subsection is not None and not subsection == idx:
                continue

            # if there is only one subsection or we've requested a
            # specific subsection, then show all entries as a grid.
            # otherwise show just a ribbon of the first 5 entries.
            if len(body) == 1 or subsection is not None:
                layout = "responsiveGrid"
                max_count = 500
            else:
                layout = "ribbon"
                max_count = 5

            section_title = item["text"]
            section_items = []
            count = 0
            for nav_item in item["children"]:
                type = nav_item.get("type", "")
                if type == "audio":
                    section_items.append(tunein_navigate_playitem(nav_item))
                elif type == "link":
                    section_items.append(tunein_navigate_link(nav_item))
                else:
                    logger.info(f"unknown type {type} for {nav_item}")

                count += 1
                if count > max_count:
                    break

            section_self_link = f"/v1/navigate/sub/{idx}/{base64.urlsafe_b64encode(tunein_uri.encode()).decode()}"
            sections.append(
                BmxNavSection(
                    links={"self": {"href": section_self_link}},
                    items=section_items,
                    layout=layout,
                    name=section_title,
                )
            )
    if subsection is not None:
        subsection_part = f"sub/{subsection}/"
    else:
        subsection_part = ""  # if add_subsection:

    section_self_link = f"/v1/navigate/{subsection_part}{base64.urlsafe_b64encode(tunein_uri.encode()).decode()}"
    sections.append(
        BmxNavSection(
            links={"self": {"href": section_self_link}},
            items=items,
            layout=layout,
            name=content_json["head"].get("title", ""),
        )
    )
    return sections


def tunein_navigate_playitem(item: dict) -> BmxNavItem:
    return BmxNavItem(
        links={
            "bmx_playback": {
                "href": f'/v1/playback/station/{item.get("guide_id", "")}',
                "type": "stationurl",
            },
            "bmx_preset": {
                "container_art": item.get("image", ""),
                "href": f'{item.get("guide_id", "")}',
                "name": item.get("text", ""),
                "type": "stationurl",
            },
        },
        image_url=item.get("image", ""),
        name=item.get("text", ""),
        subtitle=item.get("subtext", ""),
    )


def tunein_navigate_link(item: dict) -> BmxNavItem:
    url = f'{item.get("URL", "")}&render=json'
    enc_url = base64.urlsafe_b64encode(url.encode()).decode()
    return BmxNavItem(
        links={
            "bmx_navigate": {
                "href": f"/v1/navigate/{enc_url}",
            }
        },
        image_url=item.get("image", ""),
        name=item.get("text", ""),
        subtitle=item.get("subtext", ""),
    )


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
