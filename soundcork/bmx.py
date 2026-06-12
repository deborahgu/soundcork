import base64
import json
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from soundcork.config import Settings
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
# the top-level browse categories return well using the opml/ashx endpoints
TUNEIN_NAVIGATE_ASHX = "http://opml.radiotime.com/?render=json"
# search seems to work better using the api.radiotime.com endpoints.
# bose servers seem to use api.radiotime.com for all requests, so if we want
# to merge the two together we should try api.radiotime.com first.
#
# also for future reference: the bose servers include &serial={guid}, where the
# guid is defined in the Source definition token for the tunein service. however,
# in actual use including the token doesn't seem to make a different; maybe
# this is used for tracking?
TUNEIN_SEARCH = (
    "https://api.radiotime.com/profiles?fulltextsearch=true&version=1.3&query="
)


def bmx_services_json(settings: Settings) -> str:
    with open("resources/bmx_services.json", "r") as file:
        bmx_response_json = file.read()
        bmx_response_json = bmx_response_json.replace(
            "{MEDIA_SERVER}", f"{settings.base_url}/media"
        ).replace("{BMX_SERVER}", settings.base_url)
        return bmx_response_json


def tunein_is_opml_uri(tunein_uri: str) -> bool:
    parsed_uri = urllib.parse.urlsplit(tunein_uri)
    return parsed_uri.netloc.lower() == "opml.radiotime.com"


def tunein_search_uri(query: str) -> str:
    return f"{TUNEIN_SEARCH}{urllib.parse.quote_plus(query)}"


def tunein_render_json_uri(tunein_uri: str) -> str:
    if not tunein_uri:
        return ""

    parsed_uri = urllib.parse.urlsplit(tunein_uri)
    query_params = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(
            parsed_uri.query, keep_blank_values=True
        )
        if key.lower() != "render"
    ]
    query_params.append(("render", "json"))

    return urllib.parse.urlunsplit(
        parsed_uri._replace(query=urllib.parse.urlencode(query_params))
    )


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

    if tunein_is_opml_uri(tunein_uri):
        # this builds all of the sections for ashx
        sections = tunein_sections_ashx(tunein_uri, subsection)
    else:
        # build subsections for api.radiotime.com
        sections = tunein_sections_jsonapi(tunein_uri, subsection)

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
    tunein_uri: str, subsection: int | None = None
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
            if type == "link":
                items.append(tunein_navigate_link(item))
            elif type == "audio":
                items.append(tunein_navigate_playitem(item))
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


def tunein_item_guide_id(item: dict) -> str:
    guide_id = item.get("guide_id", "")
    if guide_id:
        return guide_id

    tune_url = item.get("URL", "")
    if not tune_url:
        return ""

    tune_query = urllib.parse.parse_qs(urllib.parse.urlsplit(tune_url).query)
    return tune_query.get("id", [""])[0]


def tunein_navigate_playitem(item: dict) -> BmxNavItem:
    guide_id = tunein_item_guide_id(item)
    return BmxNavItem(
        links={
            "bmx_playback": {
                "href": f"/v1/playback/station/{guide_id}",
                "type": "stationurl",
            },
            "bmx_preset": {
                "container_art": item.get("image", ""),
                "href": guide_id,
                "name": item.get("text", ""),
                "type": "stationurl",
            },
        },
        image_url=item.get("image", ""),
        name=item.get("text", ""),
        subtitle=item.get("subtext", ""),
    )


def tunein_navigate_link(item: dict) -> BmxNavItem:
    url = tunein_render_json_uri(item.get("URL", ""))
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


def tunein_sections_jsonapi(
    tunein_uri: str, subsection: int | None = None
) -> list[BmxNavSection]:
    """
    this uses the api.radiotime.com api because it worked better for
    search, and worked just fine for results returned by search.
    """
    contents = urllib.request.urlopen(tunein_uri).read()
    content_str = contents.decode("utf-8")
    content_json = json.loads(content_str)
    # by default just show all of our items as a simple list
    layout = "list"
    sections = []
    items = content_json["Items"]

    for idx, item in enumerate(items):
        logger.debug(
            f"Type={item.get('Type', '')}, ContainerType={item.get('ContainerType', '')}"
        )
        if subsection is not None and subsection != idx:
            continue

        if item.get("Type", "") == "Container":
            logger.debug(f"creating section, Title = {item.get('Title', '')}")
            if item.get("ContainerType", "") != "NotPlayableStations":
                sections.append(tunein_search_section(item, idx, ""))
        else:
            logger.info(f"top-level nav not a container: {item.get('Type', '')}")

    if subsection is not None:
        subsection_part = f"sub/{subsection}/"
    else:
        subsection_part = ""  # if add_subsection:

    return sections


def tunein_navigate_profile_v1(encoded_uri: str = "") -> BmxNavResponse:
    tunein_uri = base64.urlsafe_b64decode(encoded_uri).decode()
    logger.debug(f"profile_nav tunein_uri={tunein_uri}")
    profile_resp = urllib.request.urlopen(tunein_uri).read()
    profile_resp_str = profile_resp.decode("utf-8")
    profile_json = json.loads(profile_resp_str)
    # for profile we expect a single result
    profile_json_item = profile_json.get("Item", {})

    sections = []

    # make the hero header
    sections.append(
        BmxNavSection(
            items=[
                BmxNavItem(
                    name=profile_json_item.get("Title", ""),
                    image_url=profile_json_item.get("Image", ""),
                    subtitle=profile_json_item.get("Subtitle", ""),
                )
            ],
            layout="hero",
            name="",
        ),
    )

    contents_uri = (
        profile_json.get("Item", {})
        .get("Pivots", {})
        .get("Contents", {})
        .get("Url", "")
    )
    logger.debug(f"profile_nav contents_uri={contents_uri}")

    contents = urllib.request.urlopen(contents_uri).read()
    content_str = contents.decode("utf-8")
    content_json = json.loads(content_str)
    # by default just show all of our items as a simple list
    items = content_json["Items"]

    for idx, item in enumerate(items):
        logger.debug(
            f"Type={item.get('Type', '')}, ContainerType={item.get('ContainerType', '')}"
        )
        if item.get("Type", "") == "Container":
            logger.debug(f"creating section, Title = {item.get('Title', '')}")
            if item.get("ContainerType", "") != "NotPlayableStations":
                sections.append(tunein_search_section(item, idx, "", "list"))
        else:
            logger.info(f"top-level search not a container: {item.type}")

    links = {
        "self": {"href": f"/v1/navigate/FIXME{encoded_uri}"},
    }
    return BmxNavResponse(
        links=links,
        bmx_sections=sections,
        layout="classic",
    )


def tunein_search_v1(query: str, subsection: str | None = None) -> BmxNavResponse:

    tunein_uri = tunein_search_uri(query)
    bmx_search_link = {
        "filters": [],
        "href": "/v1/search?q={query}",
        "templated": True,
    }
    contents = urllib.request.urlopen(tunein_uri).read()
    content_str = contents.decode("utf-8")
    content_json = json.loads(content_str)
    # by default just show all of our items as a simple list
    sections = []
    items = content_json["Items"]

    for idx, item in enumerate(items):
        logger.debug(
            f"Type={item.get('Type', '')}, ContainerType={item.get('ContainerType', '')}"
        )
        if item.get("Type", "") == "Container":
            logger.debug(f"creating section, Title = {item.get('Title', '')}")
            if item.get("ContainerType", "") != "NotPlayableStations":
                sections.append(tunein_search_section(item, idx, query))
        else:
            logger.info(f"top-level search not a container: {item.get('Type', '')}")

    links = {
        "self": {"href": f"/v1/search?{urllib.parse.urlencode({'q': query})}"},
    }
    return BmxNavResponse(
        links=links,
        bmx_sections=sections,
        layout="classic",
    )


def tunein_search_section(
    item: dict, idx: int, query: str, layout: str = "shortList"
) -> BmxNavSection:
    pivot_url = item.get("Pivots", {}).get("More", {}).get("Url", "")
    encoded_query = base64.urlsafe_b64encode(tunein_search_uri(query).encode()).decode()
    if pivot_url:
        href = f"/v1/navigate/{base64.urlsafe_b64encode(pivot_url.encode()).decode()}"
    else:
        href = f"/v1/navigate/sub/{idx}/{encoded_query}"
    section_items = []

    for child in item.get("Children", []):
        child_type = child.get("Type", "")
        if child_type == "Station":
            section_items.append(tunein_search_playitem(child))
        elif child_type == "Topic":
            section_items.append(tunein_search_topic(child))
        elif child_type == "Program":
            section_items.append(tunein_search_profile(child, "Program"))
        elif child_type == "Artist":
            section_items.append(tunein_search_profile(child, "Artist"))
        elif child_type == "Category":
            category_href = child.get("Actions", {}).get("Browse", {}).get("Url", "")
            category_href_encoded = base64.urlsafe_b64encode(
                category_href.encode()
            ).decode()
            section_items.append(
                BmxNavItem(
                    links={
                        "bmx_navigate": {
                            "href": f"/v1/navigate/{category_href_encoded}"
                        },
                    },
                    image_url=child.get("Image", ""),
                    name=child.get("Title", ""),
                    subtitle=child.get("Subtitle", ""),
                )
            )
        else:
            logger.info(f"child is type {child.get('Type', '')}")

    return BmxNavSection(
        links={"self": {"href": href}},
        items=section_items,
        layout=layout,
        name=item.get("Title", ""),
    )


def tunein_search_playitem(item: dict) -> BmxNavItem:
    href = f'/v1/playback/station/{item.get("GuideId", "")}'
    return BmxNavItem(
        links={
            "bmx_playback": {
                "href": href,
                "type": "stationurl",
            },
            "bmx_preset": {
                "container_art": item.get("Image", ""),
                "href": href,
                "name": item.get("Title", ""),
                "type": "stationurl",
            },
        },
        image_url=item.get("Image", ""),
        name=item.get("Title", ""),
        subtitle=item.get("Subtitle", ""),
    )


def tunein_search_topic(item: dict) -> BmxNavItem:
    title = item.get("Title", "")
    encoded_name = base64.urlsafe_b64encode(title.encode()).decode()
    href = (
        f'/v1/playback/episodes/{item.get("GuideId", "")}?encoded_name={encoded_name}'
    )
    return BmxNavItem(
        links={
            "bmx_playback": {
                "href": href,
                "type": "tracklisturl",
            },
            "bmx_preset": {
                "container_art": item.get("Image", ""),
                "href": href,
                "name": title,
                "type": "tracklisturl",
            },
        },
        image_url=item.get("Image", ""),
        name=title,
        subtitle=item.get("Subtitle", ""),
    )


def tunein_search_profile(item: dict, name: str) -> BmxNavItem:
    guide_id = item.get("GuideId", "")
    api_url = item.get("Actions", {}).get("Profile", {}).get("Url", "")
    api_url_encoded = base64.urlsafe_b64encode(api_url.encode()).decode()
    return BmxNavItem(
        links={
            "bmx_navigate": {
                "href": f"/v1/navigate/profiles/{name}/{guide_id}/{api_url_encoded}",
            },
            "bmx_preset": {
                "container_art": item.get("Image", ""),
                "href": f"/v1/preset/program/{guide_id}",
                "name": item.get("Title", ""),
                "type": "tracklisturl",
            },
        },
        image_url=item.get("Image", ""),
        name=item.get("Title", ""),
        subtitle=item.get("Subtitle", ""),
    )


def tunein_search_link(item: dict) -> BmxNavItem:
    url = tunein_render_json_uri(item.get("URL", ""))
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
