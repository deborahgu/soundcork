import logging
import urllib.request

import yt_dlp

logger = logging.getLogger(__name__)


def resolve_track(url: str) -> dict:
    """Resolve a SoundCloud URL to track metadata and HLS playlist info."""
    ydl_opts = {
        "format": "hls_aac_96k/hls_mp3_1_0/best",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    m3u8_url = info["url"]

    raw_m3u8 = urllib.request.urlopen(m3u8_url, timeout=10).read().decode()
    segment_urls = []
    for line in raw_m3u8.splitlines():
        if line.startswith("https://"):
            segment_urls.append(line)

    return {
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail", ""),
        "m3u8_url": m3u8_url,
        "raw_m3u8": raw_m3u8,
        "segments": segment_urls,
    }


def rewrite_m3u8(track_id: str, base_url: str, raw_m3u8: str, segments: list[str]) -> str:
    """Replace long CDN URLs in the original m3u8 with short proxy URLs."""
    result = raw_m3u8
    for i, long_url in enumerate(segments):
        result = result.replace(long_url, f"{base_url}/soundcloud/seg/{track_id}/{i}")
    return result


def fetch_segment(url: str) -> bytes:
    """Fetch a single audio segment from the CDN."""
    return urllib.request.urlopen(url, timeout=30).read()
